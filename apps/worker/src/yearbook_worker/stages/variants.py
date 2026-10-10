"""variants: thumb (256 square), small 640, medium 1280, large 2048 as WebP in the public bucket."""

from __future__ import annotations

import io
from dataclasses import dataclass

import psycopg
from PIL import Image, ImageOps

from yearbook_worker.context import StageContext, VariantInfo
from yearbook_worker.storage import variant_key

WEBP_QUALITY = 82
WEBP_METHOD = 4
THUMB_SIZE = 256


@dataclass(frozen=True, slots=True)
class VariantSpec:
    name: str
    long_edge: int


LONG_EDGE_VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec("large", 2048),
    VariantSpec("medium", 1280),
    VariantSpec("small", 640),
)

UPSERT_SQL = """
insert into media_variants (media_id, name, key, width, height, bytes)
values (%(media_id)s, %(name)s, %(key)s, %(width)s, %(height)s, %(bytes)s)
on conflict (media_id, name) do update
set key = excluded.key, width = excluded.width, height = excluded.height, bytes = excluded.bytes
"""


def resize_long_edge(im: Image.Image, long_edge: int) -> Image.Image:
    """Scale so the longer side equals `long_edge`; never upscale."""
    w, h = im.size
    scale = long_edge / max(w, h)
    if scale >= 1:
        return im
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return im.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)


def square_thumb(im: Image.Image, size: int = THUMB_SIZE) -> Image.Image:
    """Center crop to a square of `size` (smaller when the source is smaller)."""
    side = min(size, *im.size)
    return ImageOps.fit(im, (side, side), Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def encode_webp(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
    return buf.getvalue()


def upsert_variant(conn: psycopg.Connection, media_id: bytes, info: VariantInfo) -> None:
    conn.execute(
        UPSERT_SQL,
        {
            "media_id": media_id,
            "name": info.name,
            "key": info.key,
            "width": info.width,
            "height": info.height,
            "bytes": info.bytes,
        },
    )


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    source = ctx.image
    prefix = ctx.media.variant_prefix
    produced: list[tuple[str, Image.Image]] = []

    current = source
    for spec in LONG_EDGE_VARIANTS:  # progressive downscale: each from the previous, larger one
        current = resize_long_edge(current, spec.long_edge)
        produced.append((spec.name, current))
    small = current
    ctx.small_image = small
    produced.append(("thumb", square_thumb(small)))

    for name, im in produced:
        data = encode_webp(im)
        key = variant_key(prefix, f"{name}.webp")
        ctx.storage.upload_bytes(ctx.storage.public_bucket, key, data, "image/webp")
        info = VariantInfo(name=name, key=key, width=im.width, height=im.height, bytes=len(data))
        upsert_variant(conn, ctx.media.id, info)
        ctx.variants.append(info)
