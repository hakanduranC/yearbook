"""`run_analyze`: faces → embed → quality → age → tags on a ready media row, resumable.

Mirrors `pipeline.run_ingest` but works from the public `large` variant (never the original),
uses the per-process `ModelHub`, and records each stage in `media.processed_stages` under its own
key so `ingest` and `analyze` never collide. The end sets `media.analyzed_at`, emits
`media.analyzed` and, when faces ran for an event item, debounces a `cluster_event` job.
"""

from __future__ import annotations

import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from PIL import Image
from psycopg_pool import ConnectionPool

from yearbook_worker import ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.context import MediaRow
from yearbook_worker.log import get_logger
from yearbook_worker.models import ModelHub, get_hub
from yearbook_worker.notify import notify_media
from yearbook_worker.pipeline import RECORD_STAGE_SQL, MediaNotFound
from yearbook_worker.storage import Storage, variant_key

log = get_logger(__name__)

LOAD_SQL = """
select m.id, m.event_id, m.owner_id, m.kind, m.state, m.original_key, m.original_mime,
       m.original_filename, m.original_bytes, m.variant_prefix, m.width, m.height,
       m.duration_ms, m.captured_at, m.captured_src, m.processed_stages, m.created_at,
       e.timezone, coalesce(e.faces_enabled, true) as faces_enabled
from media m left join events e on e.id = m.event_id
where m.id = %(id)s
"""

LOAD_FACES_SQL = """
select id, bbox, landmarks, det_score, quality, eyes_open, smile, age_est
from faces where media_id = %(id)s order by created_at, id
"""


@dataclass(slots=True)
class FaceRecord:
    """A `faces` row as later stages need it (bbox in original pixels)."""

    id: bytes
    bbox: tuple[int, int, int, int]
    kps: np.ndarray | None  # 5x2 original pixels, from `landmarks`
    det_score: float
    quality: float
    eyes_open: float | None
    smile: float | None
    age_est: float | None = None


@dataclass(slots=True)
class AnalysisContext:
    media: MediaRow
    faces_enabled: bool
    settings: Settings
    storage: Storage
    hub: ModelHub
    workdir: Path
    _image: Image.Image | None = field(default=None, repr=False)
    faces: list[FaceRecord] = field(default_factory=list)
    faces_ran: bool = False  # detection actually executed (not disabled) in this run
    embedding: np.ndarray | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)

    @property
    def image(self) -> Image.Image:
        """The `large` variant (poster for videos) as RGB, downloaded on first access."""
        if self._image is None:
            self._image = load_large_variant(self)
        return self._image

    @property
    def scale(self) -> float:
        """Original pixels per image pixel (the large variant is at most 2048 px)."""
        width = self.media.width or self.image.width
        return width / self.image.width

    def load_faces(self, conn: psycopg.Connection) -> None:
        rows = conn.execute(LOAD_FACES_SQL, {"id": self.media.id}).fetchall()
        self.faces = [
            FaceRecord(
                id=bytes(r["id"]),
                bbox=tuple(int(v) for v in r["bbox"]),  # type: ignore[arg-type]
                kps=_kps_from_landmarks(r["landmarks"]),
                det_score=float(r["det_score"]),
                quality=float(r["quality"] or 0.0),
                eyes_open=r["eyes_open"],
                smile=r["smile"],
                age_est=r["age_est"],
            )
            for r in rows
        ]


StageFn = Callable[[AnalysisContext, psycopg.Connection], None]
RestoreFn = Callable[[AnalysisContext, psycopg.Connection], None]


@dataclass(frozen=True, slots=True)
class AnalysisStage:
    name: str
    run: StageFn
    restore: RestoreFn | None = None
    enabled: Callable[[Settings], bool] = lambda _s: True


def load_large_variant(ctx: AnalysisContext) -> Image.Image:
    key = variant_key(ctx.media.variant_prefix, "large.webp")
    dest = ctx.workdir / "large.webp"
    result = ctx.storage.download(ctx.storage.public_bucket, key, dest)
    if result.size == 0:
        raise RuntimeError(f"variant {key} is empty")
    with Image.open(dest) as im:
        im.load()
        return im.convert("RGB")


def _kps_from_landmarks(values: Any) -> np.ndarray | None:
    if not values or len(values) < 10:
        return None
    return np.asarray(values[:10], dtype=np.float32).reshape(5, 2)


def stages() -> tuple[AnalysisStage, ...]:
    from yearbook_worker.stages import age, embed, faces, quality, tags

    return (
        AnalysisStage("faces", faces.run, restore=faces.restore),
        AnalysisStage("embed", embed.run),
        AnalysisStage("quality", quality.run),
        AnalysisStage("age", age.run),
        AnalysisStage("tags", tags.run, enabled=lambda s: s.worker_tags_enabled),
    )


def load_media(
    conn: psycopg.Connection, media_id: bytes, settings: Settings
) -> tuple[MediaRow, bool]:
    row = conn.execute(LOAD_SQL, {"id": media_id}).fetchone()
    if row is None:
        raise MediaNotFound(ids.encode(media_id))
    return MediaRow.from_record(row, settings.default_timezone), bool(row["faces_enabled"])


def run_analyze(
    pool: ConnectionPool,
    storage: Storage,
    settings: Settings,
    media_id: bytes,
    *,
    hub: ModelHub | None = None,
    only: tuple[str, ...] | None = None,
) -> AnalysisContext | None:
    """Analyse one ready media row. Raises on failure so the job backs off.

    Returns the context (with timings) or None when the row is gone, removed or not ready.
    """
    hub = hub or get_hub(settings)
    media_str = ids.encode(media_id)
    with pool.connection() as conn:
        media, faces_enabled = load_media(conn, media_id, settings)
        conn.commit()  # psycopg opened an implicit transaction for the SELECT
        if media.state != "ready":
            log.info("analyze.skip_state", media_id=media_str, state=media.state)
            return None
        started = time.perf_counter()
        tmp_root = settings.worker_tmp_dir
        if tmp_root is not None:
            tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="yb-an-", dir=tmp_root) as tmp:
            ctx = AnalysisContext(
                media=media,
                faces_enabled=faces_enabled,
                settings=settings,
                storage=storage,
                hub=hub,
                workdir=Path(tmp),
            )
            try:
                _run_stages(conn, ctx, only)
                with conn.transaction():
                    conn.execute(
                        "update media set analyzed_at = now() where id = %s", (media.id,)
                    )
                    notify_media(conn, "media.analyzed", media.event_id, media.id)
                    if ctx.faces_ran and media.event_id is not None:
                        queue.enqueue_event_job(
                            conn,
                            "cluster_event",
                            media.event_id,
                            delay_seconds=settings.worker_cluster_debounce_seconds,
                        )
            except Exception as exc:
                conn.rollback()
                log.error(
                    "analyze.error",
                    media_id=media_str,
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                    tb=traceback.format_exc(limit=8),
                )
                raise
        log.info(
            "analyze.done",
            media_id=media_str,
            kind=media.kind,
            faces=len(ctx.faces),
            duration_ms=_ms(started),
            stages_ms=ctx.timings_ms,
        )
        return ctx


def _run_stages(
    conn: psycopg.Connection, ctx: AnalysisContext, only: tuple[str, ...] | None
) -> None:
    media = ctx.media
    for stage in stages():
        if only is not None and stage.name not in only:
            continue
        if not stage.enabled(ctx.settings):
            log.info("stage.disabled", media_id=media.id_str, stage=stage.name)
            continue
        if stage.name in media.processed_stages:
            if stage.restore is not None:
                stage.restore(ctx, conn)
            log.info("stage.skip", media_id=media.id_str, stage=stage.name)
            continue
        started = time.perf_counter()
        with conn.transaction():
            stage.run(ctx, conn)
            conn.execute(RECORD_STAGE_SQL, {"id": media.id, "name": stage.name})
        conn.commit()  # a later stage may still fail; keep this one's rows
        media.processed_stages[stage.name] = time.time()
        ctx.timings_ms[stage.name] = _ms(started)
        log.info(
            "stage.done", media_id=media.id_str, stage=stage.name, duration_ms=_ms(started)
        )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
