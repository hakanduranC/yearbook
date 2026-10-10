"""Sidecar discovery (incl. truncated and numbered names), sidecar parsing, event matching."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from yearbook_worker import ids
from yearbook_worker.importer import (
    EventWindow,
    find_sidecar,
    match_event,
    parse_sidecar,
    sidecar_candidates,
)


def test_sidecar_candidates_cover_google_variants() -> None:
    c = sidecar_candidates("IMG_1234.jpg")
    assert c[0] == "IMG_1234.jpg.json"
    assert "IMG_1234.jpg.supplemental-metadata.json" in c
    numbered = sidecar_candidates("IMG_1234(1).jpg")
    assert "IMG_1234.jpg(1).json" in numbered
    assert "IMG_1234.jpg.supplemental-metadata(1).json" in numbered
    edited = sidecar_candidates("IMG_1234-edited.jpg")
    assert "IMG_1234.jpg.json" in edited  # edited copies share the original's sidecar


def test_find_sidecar_exact_numbered_truncated() -> None:
    names = {
        "IMG_1234.jpg.json",
        "IMG_1234.jpg(1).json",
        "IMG_7424_sehr_langer_dateiname_vom_telefon.jpg"[:44] + ".json",
        "Screenshot_20231017-073508_Instagram.jpg.suppleme.json",
        "metadata.json",
    }
    assert find_sidecar("IMG_1234.jpg", names) == "IMG_1234.jpg.json"
    assert find_sidecar("IMG_1234(1).jpg", names) == "IMG_1234.jpg(1).json"
    assert (
        find_sidecar("IMG_7424_sehr_langer_dateiname_vom_telefon.jpg", names)
        == "IMG_7424_sehr_langer_dateiname_vom_telefon.j.json"
    )
    assert (
        find_sidecar("Screenshot_20231017-073508_Instagram.jpg", names)
        == "Screenshot_20231017-073508_Instagram.jpg.suppleme.json"
    )
    assert find_sidecar("other.jpg", names) is None
    assert find_sidecar("meta.jpg", names) is None  # `metadata.json` is album metadata


def test_parse_sidecar() -> None:
    raw = json.dumps(
        {
            "title": "x.jpg",
            "photoTakenTime": {"timestamp": "1718381111"},
            "geoData": {"latitude": 52.52, "longitude": 13.405},
            "people": [{"name": "Anna  Beispiel"}, {"name": "anna beispiel"}, {"name": "Ben"}],
            "description": " Sommerfest ",
        }
    )
    sc = parse_sidecar(raw)
    assert sc.taken_at == datetime(2024, 6, 14, 16, 5, 11, tzinfo=UTC)
    assert sc.gps == (52.52, 13.405)
    assert sc.people == ["Anna Beispiel", "Ben"]
    assert sc.description == "Sommerfest"
    assert parse_sidecar(b"not json").taken_at is None
    assert parse_sidecar({"geoData": {"latitude": 0, "longitude": 0}}).gps is None


def test_match_event_window() -> None:
    start = datetime(2024, 6, 14, 16, 0, tzinfo=UTC)
    a = EventWindow(ids.new_id(), start, None, "Europe/Berlin")  # 14:00 .. next day 06:00
    week = timedelta(days=7)
    b = EventWindow(ids.new_id(), start + week, start + week + timedelta(hours=3), "UTC")
    events = [a, b]
    assert match_event(start - timedelta(hours=1), events) == a.id
    assert match_event(start + timedelta(hours=13, minutes=59), events) == a.id
    assert match_event(start + timedelta(hours=14, minutes=1), events) is None
    assert match_event(start + timedelta(days=7, hours=4, minutes=59), events) == b.id
    assert match_event(start + timedelta(days=7, hours=5, minutes=1), events) is None
    assert match_event(None, events) is None
    # overlapping windows: the closer start wins
    c = EventWindow(ids.new_id(), start + timedelta(hours=10), None, "UTC")
    assert match_event(start + timedelta(hours=11), [a, c]) == c.id
