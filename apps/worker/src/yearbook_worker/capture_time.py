"""Capture time from EXIF strings and from common camera / phone filename patterns."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# "2024:06:14 21:14:00" (EXIF) — tolerate '-' separators and fractional seconds
_EXIF_DT = re.compile(
    r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?\s*$"
)
_OFFSET = re.compile(r"^\s*([+-])(\d{2}):?(\d{2})\s*$")

# Filenames: IMG_20240614_211400, 20240614_211400, PXL_20240614_191400123 (UTC),
# 2024-06-14 21.14.00, 2024-06-14_21-14-00, VID_20240614_211400, Screenshot_2024-06-14-21-14-00
_FILENAME_DT = re.compile(
    r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})"  # date
    r"[ _T-]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})"  # time
    r"(?:\d{3})?(?!\d)"  # optional milliseconds (Pixel), then no more digits
)
_PIXEL_PREFIX = re.compile(r"(?:^|[/\\])PXL_", re.IGNORECASE)


def zone(name: str | None, fallback: str = "Europe/Berlin") -> tzinfo:
    """IANA zone by name, falling back to `fallback`, then UTC."""
    for candidate in (name, fallback):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return UTC


def parse_offset(text: str | None) -> tzinfo | None:
    """`+02:00` → fixed offset tzinfo; None when absent or malformed."""
    if not text:
        return None
    m = _OFFSET.match(text)
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours, minutes = int(m.group(2)), int(m.group(3))
    if hours > 14 or minutes > 59:
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_exif_datetime(
    text: str | None, offset: str | None, default_tz: tzinfo
) -> datetime | None:
    """EXIF `DateTimeOriginal` (+ `OffsetTimeOriginal`) → aware datetime, or None."""
    if not text:
        return None
    m = _EXIF_DT.match(text)
    if not m:
        return None
    parts = [int(g) for g in m.groups()]
    if parts[0] < 1900 or parts[1] == 0 or parts[2] == 0:  # "0000:00:00 00:00:00" placeholders
        return None
    try:
        naive = datetime(*parts)
    except ValueError:
        return None
    return naive.replace(tzinfo=parse_offset(offset) or default_tz)


def parse_filename_datetime(filename: str | None, default_tz: tzinfo) -> datetime | None:
    """Capture time from a dated filename, interpreted in `default_tz` (Pixel `PXL_` is UTC)."""
    if not filename:
        return None
    m = _FILENAME_DT.search(filename)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    try:
        naive = datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    tz = UTC if _PIXEL_PREFIX.search("/" + filename) else default_tz
    return naive.replace(tzinfo=tz)


def parse_iso_datetime(text: str | None, default_tz: tzinfo) -> datetime | None:
    """ISO 8601 as written by ffprobe (`2024-06-14T19:30:00.000000Z`) or QuickTime tags."""
    if not text:
        return None
    cleaned = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.year < 1980:  # QuickTime epoch placeholders such as 1904-01-01
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=default_tz)
