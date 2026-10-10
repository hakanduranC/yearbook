"""video: transcode to H.264 `video.mp4` (1080p max) and extract the poster frame at 1 s."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import psycopg
from PIL import Image

from yearbook_worker.context import StageContext, VariantInfo
from yearbook_worker.stages import variants as variants_stage
from yearbook_worker.stages.decode import flatten_to_rgb
from yearbook_worker.stages.probe import ffprobe
from yearbook_worker.storage import variant_key

POSTER_LONG_EDGE = 1280
TRANSCODE_TIMEOUT_S = 60 * 30


def poster_offset_s(duration_ms: int | None) -> float:
    """1 s into the clip, or the first frame for clips shorter than that."""
    return 1.0 if duration_ms is not None and duration_ms >= 1500 else 0.0


def extract_poster(src: Path, at_s: float) -> Image.Image:
    """Decode one frame at `at_s` seconds as an RGB image (ffmpeg applies rotation)."""
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-y",
        "-ss", f"{at_s:.3f}", "-i", str(src),
        "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1",
    ]  # fmt: skip
    out = subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    if not out.stdout:
        raise RuntimeError("ffmpeg produced no poster frame")
    with Image.open(io.BytesIO(out.stdout)) as im:
        im.load()
        return flatten_to_rgb(im)


def transcode(src: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src),
        "-vf", "scale='min(1920,iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        str(dest),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True, timeout=TRANSCODE_TIMEOUT_S)


def restore(ctx: StageContext) -> None:
    """On resume only the poster frame is needed in memory; the mp4 is already uploaded."""
    ctx.image = extract_poster(ctx.require_original(), poster_offset_s(ctx.duration_ms))


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    src = ctx.require_original()
    poster = extract_poster(src, poster_offset_s(ctx.duration_ms))
    ctx.image = poster

    out = ctx.workdir / "video.mp4"
    transcode(src, out)
    info = ffprobe(str(out))
    vstream = next(s for s in info["streams"] if s.get("codec_type") == "video")
    prefix = ctx.media.variant_prefix

    video_key = variant_key(prefix, "video.mp4")
    ctx.storage.upload_file(ctx.storage.public_bucket, video_key, out, "video/mp4")
    video_info = VariantInfo(
        name="video",
        key=video_key,
        width=int(vstream["width"]),
        height=int(vstream["height"]),
        bytes=out.stat().st_size,
    )

    poster_img = variants_stage.resize_long_edge(poster, POSTER_LONG_EDGE)
    poster_bytes = variants_stage.encode_webp(poster_img)
    poster_key = variant_key(prefix, "poster.webp")
    ctx.storage.upload_bytes(ctx.storage.public_bucket, poster_key, poster_bytes, "image/webp")
    poster_info = VariantInfo(
        name="poster",
        key=poster_key,
        width=poster_img.width,
        height=poster_img.height,
        bytes=len(poster_bytes),
    )

    for info_row in (video_info, poster_info):
        variants_stage.upsert_variant(conn, ctx.media.id, info_row)
        ctx.variants.append(info_row)
