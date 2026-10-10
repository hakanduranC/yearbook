"""fetch: stream the original from the private bucket to the work dir, hashing on the fly."""

from __future__ import annotations

from pathlib import PurePosixPath

import psycopg

from yearbook_worker.context import StageContext


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    suffix = PurePosixPath(ctx.media.original_key).suffix.lower() or ""
    dest = ctx.workdir / f"original{suffix}"
    result = ctx.storage.download(ctx.storage.private_bucket, ctx.media.original_key, dest)
    if result.size == 0:
        raise RuntimeError(f"original {ctx.media.original_key} is empty")
    ctx.original_path = result.path
    ctx.sha256 = result.sha256
    if ctx.media.original_bytes is None:
        ctx.media.original_bytes = result.size
