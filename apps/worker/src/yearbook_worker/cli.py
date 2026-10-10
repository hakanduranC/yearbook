"""`yearbook-worker` command line: run (the daemon), once <job_id>, ingest <media_id>."""

from __future__ import annotations

import argparse
import sys

from yearbook_worker import db, ids, queue
from yearbook_worker.config import Settings, load_settings
from yearbook_worker.log import configure, get_logger
from yearbook_worker.pipeline import run_ingest
from yearbook_worker.storage import Storage
from yearbook_worker.worker import dispatch, run_processes

log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yearbook-worker", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="claim and process jobs until stopped")
    run.add_argument("--concurrency", type=int, default=None, help="worker processes")
    run.add_argument("--kinds", default=None, help="comma separated job kinds (default: ingest)")

    once = sub.add_parser("once", help="run one job by id in this process (ignores locks)")
    once.add_argument("job_id", type=int)

    ingest = sub.add_parser("ingest", help="run the pipeline for one media id, no job row")
    ingest.add_argument("media_id", help="22-char id")
    ingest.add_argument(
        "--reset", action="store_true", help="clear processed_stages first and rerun everything"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    configure(settings.worker_log_level)

    if args.command == "run":
        concurrency = args.concurrency or settings.worker_concurrency
        kinds = [k.strip() for k in args.kinds.split(",")] if args.kinds else settings.kinds
        run_processes(settings, concurrency, kinds)
        return 0

    pool = db.make_pool(settings.database_url, min_size=1, max_size=3)
    storage = Storage(settings)
    try:
        if args.command == "once":
            return _once(args.job_id, pool, storage, settings)
        if args.command == "ingest":
            media_id = ids.decode(args.media_id)
            if args.reset:
                with pool.connection() as conn, conn.transaction():
                    conn.execute(
                        "update media set processed_stages = '{}'::jsonb where id = %s",
                        (media_id,),
                    )
            run_ingest(pool, storage, settings, media_id, final_attempt=True)
            return 0
    finally:
        pool.close()
    return 2


def _once(job_id: int, pool: db.ConnectionPool, storage: Storage, settings: Settings) -> int:
    """Debug helper: take over a specific job regardless of its lock state."""
    locked_by = queue.locked_by_token()
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            "update jobs set locked_by = %s, locked_at = now(), attempts = attempts + 1 "
            "where id = %s and done_at is null "
            "returning id, kind, payload, attempts, max_attempts",
            (locked_by, job_id),
        ).fetchone()
    if row is None:
        log.error("once.not_found", job_id=job_id)
        return 1
    job = queue.Job(**row)
    try:
        dispatch(job, pool, storage, settings)
    except Exception as exc:
        with pool.connection() as conn:
            dead = queue.fail(conn, job.id, locked_by, f"{type(exc).__name__}: {exc}")
        log.error("once.fail", job_id=job.id, error=str(exc), dead=dead)
        return 1
    with pool.connection() as conn:
        queue.complete(conn, job.id, locked_by)
    log.info("once.done", job_id=job.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
