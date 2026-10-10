"""`yearbook-worker` command line.

run            claim jobs (light: --kinds ingest,import; ML: --kinds analyze,cluster_event)
serve          the ML server (GET /health, POST /embed/text)
once           run one job by id in this process
ingest         run the ingest pipeline for one media id, no job row
analyze        run the analysis pipeline for one media id, no job row
recluster      full recluster of one event (slug or id)
eval-cluster   purity / completeness of an event's persons against a labels JSON
import         run one import by id, no job row
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

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

    serve = sub.add_parser("serve", help="ML server: GET /health, POST /embed/text")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--no-warm", action="store_true", help="load the text tower lazily")

    once = sub.add_parser("once", help="run one job by id in this process (ignores locks)")
    once.add_argument("job_id", type=int)

    ingest = sub.add_parser("ingest", help="run the pipeline for one media id, no job row")
    ingest.add_argument("media_id", help="22-char id")
    ingest.add_argument(
        "--reset", action="store_true", help="clear processed_stages first and rerun everything"
    )

    analyze = sub.add_parser("analyze", help="run the ML analysis for one media id, no job row")
    analyze.add_argument("media_id", help="22-char id")
    analyze.add_argument(
        "--reset", action="store_true", help="forget recorded analysis stages first"
    )
    analyze.add_argument("--only", default=None, help="comma separated stages, e.g. faces,age")

    recluster = sub.add_parser("recluster", help="full recluster of one event")
    recluster.add_argument("event", help="event slug or 22-char id")

    ev = sub.add_parser("eval-cluster", help="purity / completeness against hand labels")
    ev.add_argument("--event", required=True, help="event slug or 22-char id")
    ev.add_argument(
        "--labels",
        required=True,
        help="JSON file {face_id_or_filename: label} or an inline JSON object",
    )
    ev.add_argument("--recluster", action="store_true", help="full recluster first")

    imp = sub.add_parser("import", help="run one import by id, no job row")
    imp.add_argument("import_id", help="22-char id")
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
    if args.command == "serve":
        from yearbook_worker.mlserver import serve as serve_ml

        serve_ml(settings, args.port or settings.ml_port, host=args.host, warm=not args.no_warm)
        return 0

    pool = db.make_pool(settings.database_url, min_size=1, max_size=3)
    storage = Storage(settings)
    try:
        if args.command == "once":
            return _once(args.job_id, pool, storage, settings)
        if args.command == "ingest":
            media_id = ids.decode(args.media_id)
            if args.reset:
                _reset_stages(pool, media_id, None)
            run_ingest(pool, storage, settings, media_id, final_attempt=True)
            return 0
        if args.command == "analyze":
            from yearbook_worker.analysis import run_analyze
            from yearbook_worker.analysis import stages as analysis_stages

            media_id = ids.decode(args.media_id)
            only = tuple(s.strip() for s in args.only.split(",")) if args.only else None
            if args.reset:
                _reset_stages(pool, media_id, only or tuple(s.name for s in analysis_stages()))
            ctx = run_analyze(pool, storage, settings, media_id, only=only)
            print(json.dumps(ctx.timings_ms if ctx else {}))
            return 0
        if args.command == "recluster":
            from yearbook_worker.clustering import run_cluster_event

            event_id = _resolve_event(pool, args.event)
            stats = run_cluster_event(pool, settings, event_id, force_full=True)
            print(json.dumps(stats.as_dict() if stats else {}))
            return 0
        if args.command == "eval-cluster":
            from yearbook_worker.clustering import evaluate, run_cluster_event

            event_id = _resolve_event(pool, args.event)
            if args.recluster:
                run_cluster_event(pool, settings, event_id, force_full=True)
            labels = _load_labels(args.labels)
            with pool.connection() as conn:
                report = evaluate(conn, event_id, labels)
            print(json.dumps(report))
            return 0
        if args.command == "import":
            from yearbook_worker.importer import run_import

            stats = run_import(pool, storage, settings, ids.decode(args.import_id))
            print(json.dumps(stats))
            return 0
    finally:
        pool.close()
    return 2


def _reset_stages(pool: db.ConnectionPool, media_id: bytes, names: tuple[str, ...] | None) -> None:
    with pool.connection() as conn, conn.transaction():
        if names is None:
            conn.execute(
                "update media set processed_stages = '{}'::jsonb where id = %s", (media_id,)
            )
        else:
            conn.execute(
                "update media set processed_stages = processed_stages - %s::text[] where id = %s",
                (list(names), media_id),
            )


def _resolve_event(pool: db.ConnectionPool, text: str) -> bytes:
    with pool.connection() as conn:
        row = conn.execute("select id from events where slug = %s", (text,)).fetchone()
    if row is not None:
        return bytes(row["id"])
    try:
        return ids.decode(text)
    except ValueError:
        raise SystemExit(f"no event with slug or id {text!r}") from None


def _load_labels(text: str) -> dict[str, str]:
    path = Path(text)
    raw = path.read_text() if path.is_file() else text
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("labels must be a JSON object {face_id_or_filename: label}")
    return {str(k): str(v) for k, v in data.items()}


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


__all__ = ["build_parser", "main", "psycopg"]
