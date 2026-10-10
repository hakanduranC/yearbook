from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from yearbook_worker import capture_time

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG_20240614_211400.jpg", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("20240614_211400.jpg", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("VID_20240614_211400.mp4", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("2024-06-14 21.14.00.jpg", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("2024-06-14_21-14-00.heic", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("Screenshot_2024-06-14-21-14-00-123.png", datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)),
        ("PXL_20240614_191400123.jpg", datetime(2024, 6, 14, 19, 14, 0, tzinfo=UTC)),
        ("photos/PXL_20240614_191400123.MP.jpg", datetime(2024, 6, 14, 19, 14, 0, tzinfo=UTC)),
    ],
)
def test_filename_patterns(name: str, expected: datetime) -> None:
    got = capture_time.parse_filename_datetime(name, BERLIN)
    assert got == expected
    assert got is not None and got.utcoffset() == expected.utcoffset()


def test_pixel_filename_is_utc_and_equals_berlin_evening() -> None:
    got = capture_time.parse_filename_datetime("PXL_20240614_191400123.jpg", BERLIN)
    assert got == datetime(2024, 6, 14, 21, 14, 0, tzinfo=BERLIN)


@pytest.mark.parametrize(
    "name",
    ["IMG_7421.jpg", "DSC_0042.JPG", "IMG-20240614-WA0012.jpg", "20241399_251400.jpg", None, ""],
)
def test_filename_without_time(name: str | None) -> None:
    assert capture_time.parse_filename_datetime(name, BERLIN) is None


def test_exif_with_offset() -> None:
    got = capture_time.parse_exif_datetime("2024:06:14 21:14:00", "+02:00", BERLIN)
    assert got == datetime(2024, 6, 14, 21, 14, tzinfo=timezone(timedelta(hours=2)))
    assert got is not None and got.astimezone(UTC) == datetime(2024, 6, 14, 19, 14, tzinfo=UTC)


def test_exif_without_offset_uses_event_zone() -> None:
    got = capture_time.parse_exif_datetime("2024:01:14 21:14:00", None, BERLIN)
    assert got is not None and got.utcoffset() == timedelta(hours=1)  # CET in January


@pytest.mark.parametrize(
    "text", [None, "", "0000:00:00 00:00:00", "garbage", "2024:13:40 99:00:00"]
)
def test_exif_invalid(text: str | None) -> None:
    assert capture_time.parse_exif_datetime(text, None, BERLIN) is None


def test_iso() -> None:
    assert capture_time.parse_iso_datetime("2024-06-14T19:30:00.000000Z", BERLIN) == datetime(
        2024, 6, 14, 19, 30, tzinfo=UTC
    )
    assert capture_time.parse_iso_datetime("2024-06-14T21:30:00+0200", BERLIN) == datetime(
        2024, 6, 14, 19, 30, tzinfo=UTC
    )
    assert capture_time.parse_iso_datetime("1904-01-01T00:00:00Z", BERLIN) is None
    assert capture_time.parse_iso_datetime(None, BERLIN) is None


def test_zone_fallbacks() -> None:
    assert capture_time.zone("Europe/Berlin") == BERLIN
    assert capture_time.zone("Not/AZone") == BERLIN
    assert capture_time.zone(None, fallback="Nope/Nope") == UTC
