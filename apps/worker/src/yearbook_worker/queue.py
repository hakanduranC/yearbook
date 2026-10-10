"""Jobs table protocol, byte for byte as pinned in docs/CONVENTIONS.md."""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

CLAIM_SQL = """
with next as (
  select id from jobs
  where done_at is null and run_after <= now() and kind = any(%(kinds)s)
    and (locked_at is null or locked_at < now() - interval '2 minutes')
  order by priority desc, run_after, id
  for update skip locked
  limit 1
)
update jobs j
set locked_by = %(locked_by)s, locked_at = now(), attempts = attempts + 1
from next where j.id = next.id
returning j.id, j.kind, j.payload, j.attempts, j.max_attempts
"""

HEARTBEAT_SQL = "update jobs set locked_at = now() where id = %(id)s and locked_by = %(locked_by)s"

COMPLETE_SQL = """
update jobs set done_at = now(), locked_by = null, error = null
where id = %(id)s and locked_by = %(locked_by)s
"""

FAIL_SQL = """
update jobs
set locked_by = null, locked_at = null, error = %(error)s,
    run_after = now() + make_interval(secs => least(600, 10 * power(2, attempts))),
    done_at = case when attempts >= max_attempts then now() end
where id = %(id)s and locked_by = %(locked_by)s
returning done_at is not null as dead
"""

ENQUEUE_SQL = """
insert into jobs (kind, payload, priority, max_attempts)
values (%(kind)s, %(payload)s, %(priority)s, %(max_attempts)s)
returning id
"""

# One open job per (kind, media_id): `jobs_one_per_media_idx` is a partial unique index, so the
# conflict target must repeat its predicate.
ENQUEUE_MEDIA_SQL = """
insert into jobs (kind, payload, priority, max_attempts)
values (%(kind)s, %(payload)s, %(priority)s, %(max_attempts)s)
on conflict (kind, (payload->>'media_id')) where done_at is null and payload ? 'media_id'
do nothing
returning id
"""

# Debounced per-event jobs (cluster_event, recompute_scores), byte for byte from CONVENTIONS.
ENQUEUE_DEBOUNCED_SQL = """
insert into jobs (kind, payload, run_after)
select %(kind)s, %(payload)s, now() + make_interval(secs => %(delay)s)
where not exists (
  select 1 from jobs
  where kind = %(kind)s and payload->>'event_id' = %(event_id)s and done_at is null
)
returning id
"""


@dataclass(frozen=True, slots=True)
class Job:
    """A claimed row of `jobs`. `attempts` already includes this attempt."""

    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int

    @property
    def last_attempt(self) -> bool:
        """True when a failure now would mark the job dead."""
        return self.attempts >= self.max_attempts


def locked_by_token() -> str:
    """`{host}:{pid}:{uuid}` identifying one worker process."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


def claim(conn: psycopg.Connection, kinds: Sequence[str], locked_by: str) -> Job | None:
    """Claim the next runnable job of the given kinds, or None. Commits."""
    with conn.transaction():
        row = conn.execute(CLAIM_SQL, {"kinds": list(kinds), "locked_by": locked_by}).fetchone()
    if row is None:
        return None
    return Job(
        id=row["id"],
        kind=row["kind"],
        payload=row["payload"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
    )


def heartbeat(conn: psycopg.Connection, job_id: int, locked_by: str) -> bool:
    """Refresh `locked_at`. Returns False when the lock no longer belongs to us."""
    with conn.transaction():
        cur = conn.execute(HEARTBEAT_SQL, {"id": job_id, "locked_by": locked_by})
    return cur.rowcount == 1


def complete(conn: psycopg.Connection, job_id: int, locked_by: str) -> bool:
    """Mark the job done. Returns False when the lock was lost meanwhile."""
    with conn.transaction():
        cur = conn.execute(COMPLETE_SQL, {"id": job_id, "locked_by": locked_by})
    return cur.rowcount == 1


def fail(conn: psycopg.Connection, job_id: int, locked_by: str, error: str) -> bool:
    """Release the job with backoff; returns True when it is now dead (attempts exhausted)."""
    with conn.transaction():
        row = conn.execute(
            FAIL_SQL, {"id": job_id, "locked_by": locked_by, "error": error[:2000]}
        ).fetchone()
    return bool(row and row["dead"])


def enqueue(
    conn: psycopg.Connection,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 0,
    max_attempts: int = 5,
) -> int:
    """Insert a job (used by tests and the debugging CLI; the API enqueues in production)."""
    with conn.transaction():
        row = conn.execute(
            ENQUEUE_SQL,
            {
                "kind": kind,
                "payload": Jsonb(payload or {}),
                "priority": priority,
                "max_attempts": max_attempts,
            },
        ).fetchone()
    assert row is not None
    return int(row["id"])


def enqueue_media_job(
    conn: psycopg.Connection, kind: str, media_id: bytes, *, priority: int = 0
) -> int | None:
    """Insert `{kind, {"media_id"}}` unless an open job for that media and kind exists.

    Runs inside the caller's transaction. Returns the new job id or None when debounced.
    """
    from yearbook_worker import ids

    row = conn.execute(
        ENQUEUE_MEDIA_SQL,
        {
            "kind": kind,
            "payload": Jsonb({"media_id": ids.encode(media_id)}),
            "priority": priority,
            "max_attempts": 5,
        },
    ).fetchone()
    return int(row["id"]) if row else None


def enqueue_event_job(
    conn: psycopg.Connection, kind: str, event_id: bytes, *, delay_seconds: float = 60.0
) -> int | None:
    """Debounced `{kind, {"event_id"}}`: no insert while an open job for the event exists."""
    from yearbook_worker import ids

    encoded = ids.encode(event_id)
    row = conn.execute(
        ENQUEUE_DEBOUNCED_SQL,
        {
            "kind": kind,
            "payload": Jsonb({"event_id": encoded}),
            "event_id": encoded,
            "delay": delay_seconds,
        },
    ).fetchone()
    return int(row["id"]) if row else None


def wait_for_notification(listen_conn: psycopg.Connection, timeout: float) -> bool:
    """Block until a NOTIFY arrives on the listening connection or `timeout` seconds pass.

    Drains every pending notification so a burst wakes the loop once. Returns True
    when at least one notification arrived.
    """
    got = False
    for _ in listen_conn.notifies(timeout=timeout, stop_after=1):
        got = True
    return got
