"""`run_ingest`: fetch → probe → decode | video → variants → hashes → dedupe, resumable."""

from __future__ import annotations

import tempfile
import time
import traceback
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

from yearbook_worker import ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.context import MediaRow, StageContext
from yearbook_worker.log import get_logger
from yearbook_worker.notify import notify_media
from yearbook_worker.stages import STAGES, Stage
from yearbook_worker.storage import Storage

log = get_logger(__name__)

LOAD_SQL = """
select m.id, m.event_id, m.owner_id, m.kind, m.state, m.original_key, m.original_mime,
       m.original_filename, m.original_bytes, m.variant_prefix, m.width, m.height,
       m.duration_ms, m.captured_at, m.captured_src, m.processed_stages, m.created_at, e.timezone
from media m left join events e on e.id = m.event_id
where m.id = %(id)s
"""

RECORD_STAGE_SQL = """
update media
set processed_stages = processed_stages || jsonb_build_object(%(name)s::text, now())
where id = %(id)s
"""


class MediaNotFound(Exception):
    """The media row disappeared (deleted before the job ran)."""


def load_media(conn: psycopg.Connection, media_id: bytes, settings: Settings) -> MediaRow:
    row = conn.execute(LOAD_SQL, {"id": media_id}).fetchone()
    if row is None:
        raise MediaNotFound(ids.encode(media_id))
    return MediaRow.from_record(row, settings.default_timezone)


def run_ingest(
    pool: ConnectionPool,
    storage: Storage,
    settings: Settings,
    media_id: bytes,
    *,
    final_attempt: bool = True,
    stages: tuple[Stage, ...] = STAGES,
) -> None:
    """Process one media row end to end.

    Raises on failure so the caller's job fails with backoff. When `final_attempt` is set the
    row is marked `failed` and `media.failed` is emitted before re-raising.
    """
    media_str = ids.encode(media_id)
    with pool.connection() as conn:
        media = load_media(conn, media_id, settings)
        if media.state == "removed":
            log.info("ingest.skip_removed", media_id=media_str)
            return
        with conn.transaction():
            conn.execute(
                "update media set state = 'processing', error = null where id = %s", (media_id,)
            )
        started = time.perf_counter()
        try:
            _run_stages(conn, media, storage, settings, stages)
            with conn.transaction():
                conn.execute(
                    "update media set state = 'ready', processed_at = now(), error = null "
                    "where id = %s",
                    (media_id,),
                )
                notify_media(conn, "media.ready", media.event_id, media_id)
                # Hand over to the ML worker (`yearbook-worker run --kinds analyze`).
                queue.enqueue_media_job(conn, "analyze", media_id)
        except Exception as exc:
            _mark_failure(conn, media, exc, final_attempt)
            raise
        log.info(
            "ingest.done",
            media_id=media_str,
            kind=media.kind,
            duration_ms=_ms(started),
        )


def _run_stages(
    conn: psycopg.Connection,
    media: MediaRow,
    storage: Storage,
    settings: Settings,
    stages: tuple[Stage, ...],
) -> None:
    tmp_root = settings.worker_tmp_dir
    if tmp_root is not None:
        tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yb-", dir=tmp_root) as tmp:
        ctx = StageContext(media=media, settings=settings, storage=storage, workdir=Path(tmp))
        for stage in stages:
            if media.kind not in stage.kinds:
                continue
            if stage.record and stage.name in media.processed_stages:
                if stage.restore is not None:
                    stage.restore(ctx)
                log.info("stage.skip", media_id=media.id_str, stage=stage.name)
                continue
            started = time.perf_counter()
            with conn.transaction():
                stage.run(ctx, conn)
                if stage.record:
                    conn.execute(RECORD_STAGE_SQL, {"id": media.id, "name": stage.name})
            media.processed_stages[stage.name] = time.time()
            log.info(
                "stage.done", media_id=media.id_str, stage=stage.name, duration_ms=_ms(started)
            )


def _mark_failure(
    conn: psycopg.Connection, media: MediaRow, exc: Exception, final_attempt: bool
) -> None:
    error = f"{type(exc).__name__}: {exc}"[:2000]
    log.error(
        "ingest.error",
        media_id=media.id_str,
        error=error,
        final=final_attempt,
        tb=traceback.format_exc(limit=8),
    )
    try:
        conn.rollback()
        with conn.transaction():
            if final_attempt:
                conn.execute(
                    "update media set state = 'failed', error = %s where id = %s",
                    (error, media.id),
                )
                notify_media(conn, "media.failed", media.event_id, media.id)
            else:
                # Back to `queued` while the job waits for its retry; the grid keeps the cell.
                conn.execute(
                    "update media set state = 'queued', error = %s where id = %s",
                    (error, media.id),
                )
    except Exception as inner:
        log.error("ingest.mark_failure_error", media_id=media.id_str, error=str(inner))


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
