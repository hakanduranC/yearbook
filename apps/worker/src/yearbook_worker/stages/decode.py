"""decode: open the original (HEIC included), apply EXIF orientation, flatten to RGB."""

from __future__ import annotations

import pillow_heif
import psycopg
from PIL import Image, ImageOps

from yearbook_worker.context import StageContext

pillow_heif.register_heif_opener()


def load_rgb(path: str) -> Image.Image:
    """Oriented RGB image with any alpha composited onto white."""
    with Image.open(path) as im:
        im.load()
        oriented = ImageOps.exif_transpose(im) or im
        return flatten_to_rgb(oriented)


def flatten_to_rgb(im: Image.Image) -> Image.Image:
    has_alpha = im.mode in {"RGBA", "LA", "PA"} or (im.mode == "P" and "transparency" in im.info)
    if has_alpha:
        rgba = im.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return im if im.mode == "RGB" else im.convert("RGB")


def restore(ctx: StageContext) -> None:
    """Pure stage: re-run on resume so later stages have the working image."""
    ctx.image = load_rgb(str(ctx.require_original()))


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    restore(ctx)
