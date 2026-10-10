"""`NOTIFY media_events` with the payloads shared with the API (see docs/CONVENTIONS.md)."""

from __future__ import annotations

import json
from typing import Any, Literal

import psycopg

from yearbook_worker import ids

MediaEventType = Literal["media.ready", "media.failed", "media.analyzed"]


def notify_media(
    conn: psycopg.Connection, type_: MediaEventType, event_id: bytes | None, media_id: bytes
) -> None:
    """Emit `{"type", "event_id", "media_id"}` on channel `media_events` (delivered on commit)."""
    payload = {
        "type": type_,
        "event_id": ids.encode(event_id) if event_id else None,
        "media_id": ids.encode(media_id),
    }
    conn.execute("select pg_notify('media_events', %s)", (json.dumps(payload),))


def notify_people_updated(conn: psycopg.Connection, event_id: bytes) -> None:
    """`{"type": "people.updated", "event_id"}` after a clustering run."""
    payload = {"type": "people.updated", "event_id": ids.encode(event_id), "media_id": None}
    conn.execute("select pg_notify('media_events', %s)", (json.dumps(payload),))


def notify_import_progress(
    conn: psycopg.Connection,
    import_id: bytes,
    event_id: bytes | None,
    stats: dict[str, Any],
    state: str,
) -> None:
    """`{"type": "import.progress", "import_id", "stats", "state"}` while an import runs."""
    payload = {
        "type": "import.progress",
        "import_id": ids.encode(import_id),
        "event_id": ids.encode(event_id) if event_id else None,
        "media_id": None,
        "stats": stats,
        "state": state,
    }
    conn.execute("select pg_notify('media_events', %s)", (json.dumps(payload),))
