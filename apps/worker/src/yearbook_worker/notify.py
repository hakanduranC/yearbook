"""`NOTIFY media_events` with the payload shared with the API."""

from __future__ import annotations

import json
from typing import Literal

import psycopg

from yearbook_worker import ids

MediaEventType = Literal["media.ready", "media.failed"]


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
