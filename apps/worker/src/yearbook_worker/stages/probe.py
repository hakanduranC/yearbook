"""probe: dimensions, orientation, capture time (+ source) and GPS from the original's metadata."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, tzinfo
from fractions import Fraction
from typing import Any

import pillow_heif
import psycopg
from PIL import ExifTags, Image

from yearbook_worker import capture_time
from yearbook_worker.context import CapturedSrc, ProbeResult, StageContext

pillow_heif.register_heif_opener()

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_ORIENTATION = 0x0112
TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011
TAG_OFFSET_TIME = 0x9010

UPDATE_SQL = """
update media
set width = %(width)s, height = %(height)s, duration_ms = %(duration_ms)s,
    captured_at = %(captured_at)s, captured_src = %(captured_src)s,
    gps = case when %(lon)s::float8 is null then null else point(%(lon)s, %(lat)s) end
where id = %(id)s
"""


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    tz = capture_time.zone(ctx.media.timezone, ctx.settings.default_timezone)
    ctx.require_original()
    result = probe_video(ctx, tz) if ctx.media.kind == "video" else probe_photo(ctx, tz)
    ctx.probe = result
    conn.execute(
        UPDATE_SQL,
        {
            "id": ctx.media.id,
            "width": result.width,
            "height": result.height,
            "duration_ms": result.duration_ms,
            "captured_at": result.captured_at,
            "captured_src": result.captured_src,
            "lat": result.gps[0] if result.gps else None,
            "lon": result.gps[1] if result.gps else None,
        },
    )
    ctx.media.width, ctx.media.height = result.width, result.height
    ctx.media.duration_ms = result.duration_ms
    ctx.media.captured_at = result.captured_at


def _fallback_capture(ctx: StageContext, tz: tzinfo) -> tuple[datetime, CapturedSrc]:
    """Filename pattern, else the upload time."""
    from_name = capture_time.parse_filename_datetime(ctx.media.original_filename, tz)
    if from_name is not None:
        return from_name, "filename"
    return ctx.media.created_at, "upload"


# --- photos ---------------------------------------------------------------------------


def probe_photo(ctx: StageContext, tz: tzinfo) -> ProbeResult:
    with Image.open(ctx.require_original()) as im:
        width, height = im.size
        exif = im.getexif()
    orientation = int(exif.get(TAG_ORIENTATION) or 1)
    if orientation not in range(1, 9):
        orientation = 1
    if orientation >= 5:  # transposed orientations swap the axes
        width, height = height, width

    ifd = exif.get_ifd(EXIF_IFD)
    captured = capture_time.parse_exif_datetime(
        _text(ifd.get(TAG_DATETIME_ORIGINAL)), _text(ifd.get(TAG_OFFSET_TIME_ORIGINAL)), tz
    ) or capture_time.parse_exif_datetime(
        _text(exif.get(TAG_DATETIME)), _text(ifd.get(TAG_OFFSET_TIME)), tz
    )
    src: CapturedSrc = "exif"
    if captured is None:
        captured, src = _fallback_capture(ctx, tz)

    return ProbeResult(
        width=width,
        height=height,
        captured_at=captured,
        captured_src=src,
        orientation=orientation,
        gps=_gps(exif.get_ifd(GPS_IFD)),
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    return str(value).strip("\x00 ") or None


def _gps(gps: dict[int, Any]) -> tuple[float, float] | None:
    """Decimal (lat, lon) from the GPS IFD, or None when absent or implausible."""
    if not gps:
        return None
    try:
        lat = _dms(gps[ExifTags.GPS.GPSLatitude], gps.get(ExifTags.GPS.GPSLatitudeRef, "N"))
        lon = _dms(gps[ExifTags.GPS.GPSLongitude], gps.get(ExifTags.GPS.GPSLongitudeRef, "E"))
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180 or (lat == 0 and lon == 0):
        return None
    return (lat, lon)


def _dms(values: Any, ref: Any) -> float | None:
    deg, minutes, seconds = (float(Fraction(v)) for v in values)
    decimal = deg + minutes / 60 + seconds / 3600
    ref_text = ref.decode() if isinstance(ref, bytes) else str(ref)
    return -decimal if ref_text.upper() in {"S", "W"} else decimal


# --- videos ---------------------------------------------------------------------------


def ffprobe(path: str) -> dict[str, Any]:
    """`ffprobe -print_format json -show_format -show_streams` as a dict."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )  # fmt: skip
    return json.loads(out.stdout or b"{}")


def video_rotation(stream: dict[str, Any]) -> int:
    """Rotation in degrees from side data (ffmpeg ≥ 5) or the legacy `rotate` tag."""
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return round(float(side["rotation"])) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    return int(float(tag)) % 360 if tag else 0


def probe_video(ctx: StageContext, tz: tzinfo) -> ProbeResult:
    info = ffprobe(str(ctx.require_original()))
    streams = info.get("streams") or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise RuntimeError("no video stream found")
    width, height = int(vstream.get("width") or 0), int(vstream.get("height") or 0)
    rotation = video_rotation(vstream)
    if rotation in (90, 270):
        width, height = height, width
    fmt = info.get("format") or {}
    duration_s = float(fmt.get("duration") or vstream.get("duration") or 0)
    tags = {**(vstream.get("tags") or {}), **(fmt.get("tags") or {})}
    captured = capture_time.parse_iso_datetime(
        tags.get("com.apple.quicktime.creationdate"), tz
    ) or capture_time.parse_iso_datetime(tags.get("creation_time"), tz)
    src: CapturedSrc = "exif"
    if captured is None:
        captured, src = _fallback_capture(ctx, tz)
    gps = _quicktime_location(
        tags.get("com.apple.quicktime.location.ISO6709") or tags.get("location")
    )
    return ProbeResult(
        width=width,
        height=height,
        captured_at=captured,
        captured_src=src,
        orientation=1,
        gps=gps,
        duration_ms=round(duration_s * 1000),
    )


def _quicktime_location(text: str | None) -> tuple[float, float] | None:
    """ISO 6709 `+52.5200+013.4050+034.000/` → (lat, lon)."""
    if not text:
        return None
    m = re.match(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", text.strip())
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return (lat, lon)
