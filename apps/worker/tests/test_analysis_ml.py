"""Real models on the portrait fixtures: faces, embeddings, quality, age, tags, clustering.

Marked `ml` (slow; downloads models on first run into WORKER_MODELS_DIR) and `integration`.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from psycopg_pool import ConnectionPool

from tests.conftest import FACES, MediaSeeder, drain, fetch_media
from yearbook_worker import ids
from yearbook_worker.analysis import run_analyze
from yearbook_worker.clustering import evaluate, run_cluster_event
from yearbook_worker.config import Settings
from yearbook_worker.storage import Storage
from yearbook_worker.vectors import as_array

pytestmark = [pytest.mark.integration, pytest.mark.ml]

SINGLES = [
    "whitson_1.jpg", "whitson_2.jpg", "williams_1.jpg", "williams_2.jpg",
    "jemison_1.jpg", "jemison_2.jpg", "kelly_1.jpg", "kelly_2.jpg",
]  # fmt: skip
GROUPS = {"group_williams_wilmore.jpg": 2, "group_sts47_jemison.jpg": 5}


@pytest.fixture(scope="module")
def portraits_ready(
    settings: Settings, pool: ConnectionPool, storage: Storage, hub
) -> dict:
    """Ingest + analyse every portrait once per module; later tests read the results."""
    from datetime import UTC, datetime

    from tests.conftest import TRUNCATE, Seeded

    with pool.connection() as conn, conn.transaction():
        conn.execute(TRUNCATE)
    user_id, event_id = ids.new_id(), ids.new_id()
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "insert into users (id, email, display_name) values (%s, %s, %s)",
            (user_id, f"{ids.encode(user_id)}@example.test", "Test host"),
        )
        conn.execute(
            "insert into events (id, slug, title, starts_at, timezone, owner_id) "
            "values (%s, %s, %s, %s, %s, %s)",
            (event_id, f"faces-{ids.encode(event_id)[:8]}", "Portraits",
             datetime(2024, 6, 14, 16, 0, tzinfo=UTC), "Europe/Berlin", user_id),
        )  # fmt: skip
    seeder = MediaSeeder(pool, storage, Seeded(user_id=user_id, event_id=event_id))
    media = {name: seeder.add(FACES / name) for name in [*SINGLES, *GROUPS]}
    library = seeder.add(FACES / "kelly_1.jpg", event=False)
    ingest_jobs = drain(pool, storage, settings, ("ingest",))
    assert len(ingest_jobs) == len(media) + 1
    for mid in [*media.values(), library]:
        assert fetch_media(pool, mid)["state"] == "ready"

    with pool.connection() as conn:
        pending = conn.execute(
            "select count(*) from jobs where kind = 'analyze' and done_at is null"
        ).fetchone()["count"]
    assert pending == len(media) + 1, "ingest must enqueue analyze for every item"

    started = time.perf_counter()
    analyze_jobs = drain(pool, storage, settings, ("analyze",))
    analyze_s = time.perf_counter() - started
    assert len(analyze_jobs) == len(media) + 1
    with pool.connection() as conn:
        failed = conn.execute(
            "select id, error from jobs where kind = 'analyze' and error is not null"
        ).fetchall()
    assert not failed, failed
    import resource

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    per_item = analyze_s / len(analyze_jobs)
    print(f"\nanalyze: {len(analyze_jobs)} items in {analyze_s:.1f}s ({per_item:.1f}s per item), "
          f"process max RSS {rss_mb} MB")  # fmt: skip
    return {"event_id": event_id, "user_id": user_id, "media": media, "library": library,
            "seconds": analyze_s}  # fmt: skip


def _faces(pool: ConnectionPool, media_id: bytes) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(
            "select * from faces where media_id = %s order by quality desc", (media_id,)
        ).fetchall()


def test_faces_found_on_portraits(portraits_ready: dict, pool: ConnectionPool, storage: Storage):
    media = portraits_ready["media"]
    for name in SINGLES:
        rows = _faces(pool, media[name])
        assert len(rows) >= 1, name
        best = rows[0]
        x1, y1, x2, y2 = best["bbox"]
        row = fetch_media(pool, media[name])
        assert 0 <= x1 < x2 <= row["width"] and 0 <= y1 < y2 <= row["height"]
        assert min(x2 - x1, y2 - y1) >= 32
        assert best["det_score"] >= 0.6
        emb = as_array(best["embedding"])
        assert emb.shape == (512,) and abs(float(np.linalg.norm(emb)) - 1) < 1e-3
        assert 0 <= best["quality"] <= 1 and 0 <= best["eyes_open"] <= 1 and 0 <= best["smile"] <= 1
        assert len(best["landmarks"]) == 10
        assert best["crop_key"] == f"f/{ids.encode(bytes(best['id']))}.jpg"
        head = storage.head(storage.private_bucket, best["crop_key"])
        assert head is not None and head["ContentType"] == "image/jpeg"
        assert best["age_est"] is not None and 15 <= best["age_est"] <= 80
        assert best["age_est_sd"] >= 4.0
    for name, minimum in GROUPS.items():
        assert len(_faces(pool, media[name])) >= minimum, name


def test_portrait_eyes_open_and_smile_are_plausible(portraits_ready: dict, pool: ConnectionPool):
    media = portraits_ready["media"]
    whitson = _faces(pool, media["whitson_1.jpg"])[0]  # broad smile, eyes open
    assert whitson["eyes_open"] > 0.5
    assert whitson["smile"] > 0.5
    jemison_1987 = _faces(pool, media["jemison_2.jpg"])[0]
    assert 22 <= jemison_1987["age_est"] <= 42  # she was 31


def test_embeddings_quality_and_tags_written(portraits_ready: dict, pool: ConnectionPool, settings):
    media = portraits_ready["media"]
    with pool.connection() as conn:
        for mid in media.values():
            emb = conn.execute(
                "select model, embedding from media_embeddings where media_id = %s", (mid,)
            ).fetchone()
            assert emb is not None and emb["model"] == settings.worker_siglip_model
            vec = as_array(emb["embedding"])
            assert vec.shape == (1152,) and abs(float(np.linalg.norm(vec)) - 1) < 1e-3
            q = conn.execute("select * from media_quality where media_id = %s", (mid,)).fetchone()
            assert q is not None and 0 <= q["score"] <= 1 and 0 <= q["sharpness"] <= 1
            assert 1 <= q["aesthetic"] <= 10 and q["face_count"] >= 1
            row = fetch_media(pool, mid)
            assert row["analyzed_at"] is not None
            stages = set(row["processed_stages"])
            assert {"faces", "embed", "quality", "age"} <= stages
            if settings.worker_tags_enabled:
                assert "tags" in stages
        if settings.worker_tags_enabled:
            cap = fetch_media(pool, media["group_williams_wilmore.jpg"])["caption"]
            assert cap and len(cap) > 20
            tags = conn.execute(
                "select tag, source from media_tags where media_id = %s",
                (media["group_williams_wilmore.jpg"],),
            ).fetchall()
            by_source = {}
            for t in tags:
                by_source.setdefault(t["source"], set()).add(t["tag"])
            assert by_source.get("florence"), tags
            assert by_source["florence"] & {"astronauts", "flag", "woman", "man", "suits", "blue"}
            # OCR needs legible text; the 800 px fixtures carry none, so only the shape is checked
            assert all(len(t) >= 3 for t in by_source.get("ocr", set()))
        # the library item (no event) still got faces and an embedding
        assert len(_faces(pool, portraits_ready["library"])) >= 1


def test_clustering_finds_the_four_people(portraits_ready: dict, pool: ConnectionPool, settings):
    event_id = portraits_ready["event_id"]
    with pool.connection() as conn:
        job = conn.execute(
            "select * from jobs where kind = 'cluster_event' and payload->>'event_id' = %s",
            (ids.encode(event_id),),
        ).fetchall()
    assert len(job) == 1, "analyze must debounce exactly one cluster_event per event"
    stats = run_cluster_event(pool, settings, event_id)
    assert stats is not None and stats.mode == "full"
    with pool.connection() as conn:
        persons = conn.execute(
            "select * from persons where event_id = %s and face_count >= 2 "
            "order by face_count desc",
            (event_id,),
        ).fetchall()
        labels = json.loads((FACES / "labels.json").read_text())
        report = evaluate(conn, event_id, labels)
        ev = conn.execute("select clustered_at from events where id = %s", (event_id,)).fetchone()
    print("\ncluster report:", report, "persons:", [p["face_count"] for p in persons])
    assert ev["clustered_at"] is not None
    assert 3 <= len(persons) <= 5
    assert report["labeled_faces"] == 8
    assert report["purity"] >= 0.99
    assert report["completeness"] >= 0.75
    for p in persons:
        assert p["cover_face"] is not None and p["cover_face_quality"] > 0
        assert as_array(p["centroid"]).shape == (512,)

    # incremental run: nothing new, assignments stay
    before = {bytes(p["id"]): p["face_count"] for p in persons}
    again = run_cluster_event(pool, settings, event_id)
    assert again is not None and again.mode == "incremental"
    with pool.connection() as conn:
        after = {
            bytes(p["id"]): p["face_count"]
            for p in conn.execute(
                "select id, face_count from persons where event_id = %s", (event_id,)
            )
        }
    assert all(after.get(pid) == n for pid, n in before.items())


def test_faces_disabled_event_skips_faces_only(
    portraits_ready: dict, pool: ConnectionPool, storage: Storage, settings: Settings
):
    from datetime import UTC, datetime

    from tests.conftest import Seeded

    user_id = portraits_ready["user_id"]
    event_id = ids.new_id()
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "insert into events (id, slug, title, starts_at, timezone, owner_id, faces_enabled) "
            "values (%s, %s, %s, %s, %s, %s, false)",
            (event_id, f"nofaces-{ids.encode(event_id)[:8]}", "No faces",
             datetime(2024, 6, 14, 16, 0, tzinfo=UTC), "Europe/Berlin", user_id),
        )  # fmt: skip
    seeder = MediaSeeder(pool, storage, Seeded(user_id=user_id, event_id=event_id))
    mid = seeder.add(FACES / "whitson_2.jpg")
    drain(pool, storage, settings, ("ingest",))
    ctx = run_analyze(pool, storage, settings, mid)
    assert ctx is not None and ctx.faces == [] and ctx.faces_ran is False
    with pool.connection() as conn:
        n_faces = conn.execute(
            "select count(*) from faces where media_id = %s", (mid,)
        ).fetchone()["count"]
        assert n_faces == 0
        assert conn.execute("select 1 from media_embeddings where media_id = %s", (mid,)).fetchone()
        q = conn.execute(
            "select face_count from media_quality where media_id = %s", (mid,)
        ).fetchone()
        assert q["face_count"] == 0
        clusters = conn.execute(
            "select count(*) from jobs where kind = 'cluster_event' and payload->>'event_id' = %s",
            (ids.encode(event_id),),
        ).fetchone()["count"]
    assert clusters == 0


def test_analyze_resumes_recorded_stages(
    portraits_ready: dict, pool: ConnectionPool, storage: Storage, settings: Settings
):
    mid = portraits_ready["media"]["kelly_2.jpg"]
    first = fetch_media(pool, mid)["processed_stages"]
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "update media set processed_stages = processed_stages - 'quality' where id = %s", (mid,)
        )
    ctx = run_analyze(pool, storage, settings, mid)
    assert ctx is not None
    assert set(ctx.timings_ms) == {"quality"}  # only the forgotten stage re-ran
    assert len(ctx.faces) >= 1  # restored from the database for the quality terms
    after = fetch_media(pool, mid)["processed_stages"]
    assert after["faces"] == first["faces"] and after["embed"] == first["embed"]
