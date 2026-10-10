"""Claim / heartbeat / complete / fail against the test database."""

from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from yearbook_worker import queue

pytestmark = pytest.mark.integration


def _job(pool: ConnectionPool, job_id: int) -> dict:
    with pool.connection() as conn:
        row = conn.execute("select * from jobs where id = %s", (job_id,)).fetchone()
    assert row is not None
    return row


def test_claim_complete(clean_db: ConnectionPool) -> None:
    with clean_db.connection() as conn:
        job_id = queue.enqueue(conn, "noop", {"x": 1})
        me = queue.locked_by_token()
        job = queue.claim(conn, ["noop"], me)
        assert job is not None and job.id == job_id and job.attempts == 1
        assert job.payload == {"x": 1}
        assert queue.claim(conn, ["noop"], "someone-else") is None  # locked
        assert queue.heartbeat(conn, job.id, me) is True
        assert queue.heartbeat(conn, job.id, "someone-else") is False
        assert queue.complete(conn, job.id, me) is True
    row = _job(clean_db, job_id)
    assert row["done_at"] is not None and row["locked_by"] is None and row["error"] is None


def test_claim_respects_kinds_and_order(clean_db: ConnectionPool) -> None:
    with clean_db.connection() as conn:
        low = queue.enqueue(conn, "noop", priority=0)
        high = queue.enqueue(conn, "noop", priority=5)
        queue.enqueue(conn, "other")
        me = queue.locked_by_token()
        first = queue.claim(conn, ["noop"], me)
        second = queue.claim(conn, ["noop"], me)
        assert first is not None and first.id == high
        assert second is not None and second.id == low
        assert queue.claim(conn, ["noop"], me) is None


def test_fail_backs_off_then_dies(clean_db: ConnectionPool) -> None:
    with clean_db.connection() as conn:
        job_id = queue.enqueue(conn, "noop", max_attempts=2)
        me = queue.locked_by_token()
        job = queue.claim(conn, ["noop"], me)
        assert job is not None and not job.last_attempt
        assert queue.fail(conn, job.id, me, "boom") is False
        row = _job(clean_db, job_id)
        assert row["done_at"] is None and row["locked_by"] is None and row["error"] == "boom"
        assert row["run_after"] > row["created_at"]  # backoff: now + 20 s after attempt 1
        assert queue.claim(conn, ["noop"], me) is None  # not runnable yet
        conn.execute("update jobs set run_after = now() where id = %s", (job_id,))
        conn.commit()
        job = queue.claim(conn, ["noop"], me)
        assert job is not None and job.attempts == 2 and job.last_attempt
        assert queue.fail(conn, job.id, me, "boom again") is True
    row = _job(clean_db, job_id)
    assert row["done_at"] is not None and row["error"] == "boom again"


def test_stale_lock_is_reclaimable(clean_db: ConnectionPool) -> None:
    with clean_db.connection() as conn:
        job_id = queue.enqueue(conn, "noop")
        job = queue.claim(conn, ["noop"], "dead-worker")
        assert job is not None
        conn.execute(
            "update jobs set locked_at = now() - interval '3 minutes' where id = %s", (job_id,)
        )
        conn.commit()
        again = queue.claim(conn, ["noop"], "fresh-worker")
        assert again is not None and again.id == job_id and again.attempts == 2
