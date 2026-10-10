"""Ingestion stages. Each exposes `run(ctx, conn)`; some also `restore(ctx)` for resumes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg

from yearbook_worker.context import Kind, StageContext
from yearbook_worker.stages import decode, dedupe, fetch, hashes, probe, variants, video

StageFn = Callable[[StageContext, psycopg.Connection], None]
RestoreFn = Callable[[StageContext], None]


@dataclass(frozen=True, slots=True)
class Stage:
    """A pipeline step.

    `record`: write the stage name into `media.processed_stages` after success and skip it
    on later runs. `restore`: cheap, DB-free rebuild of the stage's in-memory output, called
    when the stage is skipped so later stages still find what they need.
    """

    name: str
    run: StageFn
    kinds: frozenset[Kind] = frozenset({"photo", "video"})
    record: bool = True
    restore: RestoreFn | None = None
    dependencies: tuple[str, ...] = field(default_factory=tuple)


PHOTO = frozenset({"photo"})
VIDEO = frozenset({"video"})

STAGES: tuple[Stage, ...] = (
    Stage("fetch", fetch.run, record=False),
    Stage("probe", probe.run),
    Stage("decode", decode.run, kinds=PHOTO, restore=decode.restore),
    Stage("video", video.run, kinds=VIDEO, restore=video.restore),
    Stage("variants", variants.run),
    Stage("hashes", hashes.run),
    Stage("dedupe", dedupe.run),
)

__all__ = ["STAGES", "Stage"]
