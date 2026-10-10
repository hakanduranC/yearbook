"""hashes: content sha256 (from fetch) and a 64-bit perceptual hash of the `small` image."""

from __future__ import annotations

import imagehash
import psycopg
from PIL import Image

from yearbook_worker.context import StageContext
from yearbook_worker.stages.variants import resize_long_edge

UPDATE_SQL = """
update media set content_sha256 = %(sha)s, phash = %(phash)s::bit(64) where id = %(id)s
"""


def phash_bits(im: Image.Image) -> str:
    """64-char '0'/'1' string of the DCT pHash (ImageHash, hash_size 8)."""
    h = imagehash.phash(im, hash_size=8)
    return "".join("1" if bit else "0" for bit in h.hash.flatten())


def hamming(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b, strict=True))


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    if ctx.sha256 is None:
        raise RuntimeError("fetch did not produce a sha256")
    small = ctx.small_image or resize_long_edge(ctx.image, 640)
    ctx.phash = phash_bits(small)
    conn.execute(UPDATE_SQL, {"id": ctx.media.id, "sha": ctx.sha256, "phash": ctx.phash})
