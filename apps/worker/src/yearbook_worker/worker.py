"""The claim → run → complete/fail loop of one worker process.

Light kinds (`ingest`, `import`, `recompute_scores`) and ML kinds (`analyze`, `cluster_event`)
share this loop; which kinds a process claims is decided by `--kinds`. ML models load lazily on
the first `analyze` job and stay resident in that process (see `models.ModelHub`).
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import signal
import threading
import time
from collections.abc import Sequence
from typing import Any

from psycopg_pool import ConnectionPool

from yearbook_worker import db, ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.heartbeat import Heartbeat
from yearbook_worker.log import configure, get_logger
from yearbook_worker.pipeline import run_ingest
from yearbook_worker.queue import Job
from yearbook_worker.storage import Storage

log = get_logger(__name__)


class UnknownJobKind(Exception):
    pass


def dispatch(job: Job, pool: ConnectionPool, storage: Storage, settings: Settings) -> None:
    """Route a claimed job to its handler."""
    if job.kind == "ingest":
        media_id = ids.decode(str(job.payload["media_id"]))
        run_ingest(pool, storage, settings, media_id, final_attempt=job.last_attempt)
    elif job.kind == "analyze":
        from yearbook_worker.analysis import run_analyze

        run_analyze(pool, storage, settings, ids.decode(str(job.payload["media_id"])))
    elif job.kind == "cluster_event":
        from yearbook_worker.clustering import run_cluster_event

        run_cluster_event(pool, settings, ids.decode(str(job.payload["event_id"])))
    elif job.kind == "import":
        from yearbook_worker.importer import run_import

        run_import(pool, storage, settings, ids.decode(str(job.payload["import_id"])))
    elif job.kind == "recompute_scores":
        from yearbook_worker import scoring

        with pool.connection() as conn, conn.transaction():
            scoring.recompute_event(conn, ids.decode(str(job.payload["event_id"])))
    elif job.kind == "noop":
        return
    else:
        raise UnknownJobKind(job.kind)


def process_one(
    pool: ConnectionPool,
    storage: Storage,
    settings: Settings,
    kinds: Sequence[str],
    locked_by: str,
) -> Job | None:
    """Claim and run one job. Returns the job (done or failed) or None when the queue is idle."""
    with pool.connection() as conn:
        job = queue.claim(conn, kinds, locked_by)
    if job is None:
        return None
    log.info("job.start", job_id=job.id, kind=job.kind, attempt=job.attempts)
    try:
        with Heartbeat(pool, job.id, locked_by, settings.worker_heartbeat_seconds):
            dispatch(job, pool, storage, settings)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        with pool.connection() as conn:
            dead = queue.fail(conn, job.id, locked_by, error)
        log.error("job.fail", job_id=job.id, kind=job.kind, error=error, dead=dead)
        return job
    with pool.connection() as conn:
        ok = queue.complete(conn, job.id, locked_by)
    log.info("job.done", job_id=job.id, kind=job.kind, lock_kept=ok)
    return job


def run_loop(settings: Settings, kinds: Sequence[str], stop: threading.Event) -> None:
    """Claim jobs until `stop` is set; sleeps on LISTEN jobs_new with a poll fallback."""
    pool = db.make_pool(settings.database_url, min_size=1, max_size=3)
    storage = Storage(settings)
    locked_by = queue.locked_by_token()
    listen = db.listen_connection(settings.database_url, "jobs_new")
    log.info("worker.start", locked_by=locked_by, kinds=list(kinds))
    try:
        while not stop.is_set():
            job = process_one(pool, storage, settings, kinds, locked_by)
            if job is None:
                _idle_wait(listen, settings.worker_poll_seconds, stop)
    finally:
        listen.close()
        pool.close()
        log.info("worker.stop", locked_by=locked_by)


def _idle_wait(listen: Any, poll_seconds: float, stop: threading.Event) -> None:
    """Sleep until `NOTIFY jobs_new`, the poll interval, or a stop request, in 1 s slices."""
    deadline = time.monotonic() + poll_seconds
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0 or queue.wait_for_notification(listen, min(1.0, remaining)):
            return


def _child_main(settings: Settings, kinds: list[str], log_level: str) -> None:
    configure(log_level)
    stop = threading.Event()

    def handle(signum: int, _frame: Any) -> None:
        log.info("worker.signal", signal=signum)
        stop.set()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    run_loop(settings, kinds, stop)


def run_processes(settings: Settings, concurrency: int, kinds: Sequence[str]) -> None:
    """Spawn `concurrency` worker processes, each with its own pool, and wait for them."""
    ctx = mp.get_context("spawn")
    procs = [
        ctx.Process(
            target=_child_main,
            args=(settings, list(kinds), settings.worker_log_level),
            name=f"worker-{i}",
        )
        for i in range(concurrency)
    ]
    for p in procs:
        p.start()
    log.info("supervisor.start", processes=concurrency, kinds=list(kinds))

    def forward(signum: int, _frame: Any) -> None:
        for p in procs:
            if p.is_alive() and p.pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(p.pid, signal.SIGTERM)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    for p in procs:
        p.join()
    log.info("supervisor.stop")
