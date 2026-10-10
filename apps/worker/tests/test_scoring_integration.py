"""`media_quality.score` SQL against the test database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from psycopg_pool import ConnectionPool

from tests.conftest import Seeded
from yearbook_worker import ids, queue, scoring
from yearbook_worker.config import Settings
from yearbook_worker.storage import Storage

pytestmark = pytest.mark.integration


def _media(conn, seeded: Seeded, event: bool = True) -> bytes:
    mid = ids.new_id()
    conn.execute(
        "insert into media (id, event_id, owner_id, kind, state, original_key, original_mime, "
        "variant_prefix, created_at) values (%s, %s, %s, 'photo', 'ready', 'o/x', 'image/jpeg', "
        "%s, %s)",
        (mid, seeded.event_id if event else None, seeded.user_id, ids.new_encoded(),
         datetime.now(UTC)),
    )  # fmt: skip
    return mid


def test_score_formula(seeded: Seeded, clean_db: ConnectionPool) -> None:
    with clean_db.connection() as conn, conn.transaction():
        a, b, c = _media(conn, seeded), _media(conn, seeded), _media(conn, seeded, event=False)
        conn.execute(
            "insert into media_quality (media_id, sharpness, exposure, aesthetic, face_count, "
            "eyes_open, smile) values (%s, 0.8, 1.0, 5.5, 2, 1.0, 0.5), (%s, 0.4, 0.5, 3.0, 0, "
            "null, null), (%s, 1.0, 1.0, 8.0, 7, 0.0, 0.0)",
            (a, b, c),
        )
        for _ in range(4):
            conn.execute(
                "insert into likes (media_id, actor) values (%s, %s)", (a, ids.new_id())
            )
        conn.execute("insert into likes (media_id, actor) values (%s, %s)", (b, ids.new_id()))
        n = scoring.update_scores(conn, event_id=seeded.event_id, owner_id=None)
        assert n == 2
        scoring.update_scores(conn, event_id=None, owner_id=seeded.user_id, media_id=c)
        rows = {
            bytes(r["media_id"]): r["score"]
            for r in conn.execute("select media_id, score from media_quality").fetchall()
        }
    # a: 0.35*0.5 + 0.25*0.8 + 0.15*1 + 0.15*0.75 + 0.10*1.0
    assert abs(rows[a] - (0.175 + 0.2 + 0.15 + 0.1125 + 0.1)) < 1e-4
    # b: 0.35*0 + 0.25*0.4 + 0.15*0.6 + 0.15*0.5 + 0.10*(1/4)
    assert abs(rows[b] - (0.0 + 0.1 + 0.09 + 0.075 + 0.025)) < 1e-4
    # c (library, no likes anywhere): 0.35*1 + 0.25*1 + 0.15*0.4 + 0.15*0 + 0
    assert abs(rows[c] - (0.35 + 0.25 + 0.06 + 0.0 + 0.0)) < 1e-4


def test_recompute_scores_job(
    seeded: Seeded, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    from tests.conftest import drain

    with clean_db.connection() as conn, conn.transaction():
        a = _media(conn, seeded)
        conn.execute(
            "insert into media_quality (media_id, sharpness, aesthetic, face_count) "
            "values (%s, 0.0, 3.0, 1)",
            (a,),
        )
        queue.enqueue_event_job(conn, "recompute_scores", seeded.event_id, delay_seconds=0)
        assert queue.enqueue_event_job(conn, "recompute_scores", seeded.event_id) is None
    jobs = drain(clean_db, storage, settings, ("recompute_scores",))
    assert len(jobs) == 1
    with clean_db.connection() as conn:
        score = conn.execute("select score from media_quality where media_id = %s", (a,)).fetchone()
    assert abs(score["score"] - (0.15 * 1.0 + 0.15 * 0.5)) < 1e-4
