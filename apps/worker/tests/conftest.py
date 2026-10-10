"""Shared fixtures: settings, a truncated test database, S3 and a helper to seed media + jobs."""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from yearbook_worker import db, ids, queue
from yearbook_worker.config import Settings, load_settings
from yearbook_worker.storage import Storage

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TRUNCATE = (
    "truncate jobs, media_variants, duplicate_groups, media, guests, guest_cookies, "
    "event_members, events, sessions, magic_links, users restart identity cascade"
)

mimetypes.add_type("image/heic", ".heic")


def _settings_or_skip() -> Settings:
    # Each app owns its test database so suites can run concurrently without
    # truncating each other's rows. WORKER_TEST_DATABASE_URL wins over the shared one.
    url = os.environ.get("WORKER_TEST_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("WORKER_TEST_DATABASE_URL / TEST_DATABASE_URL not set")
    settings = load_settings(worker_heartbeat_seconds=1.0, worker_poll_seconds=0.2)
    return settings.model_copy(update={"database_url": url})


@pytest.fixture(scope="session")
def settings() -> Settings:
    return _settings_or_skip()


@pytest.fixture(scope="session")
def pool(settings: Settings) -> Iterator[ConnectionPool]:
    try:
        p = db.make_pool(settings.database_url, min_size=1, max_size=4)
        with p.connection() as conn:
            conn.execute("select 1")
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable: {exc}")
    yield p
    p.close()


@pytest.fixture(scope="session")
def storage(settings: Settings) -> Storage:
    s = Storage(settings)
    try:
        s.client.head_bucket(Bucket=s.private_bucket)
        s.client.head_bucket(Bucket=s.public_bucket)
    except Exception as exc:
        pytest.skip(f"S3 unreachable: {exc}")
    return s


@pytest.fixture
def clean_db(pool: ConnectionPool) -> Iterator[ConnectionPool]:
    with pool.connection() as conn, conn.transaction():
        conn.execute(TRUNCATE)
    yield pool


@dataclass(frozen=True)
class Seeded:
    user_id: bytes
    event_id: bytes


@pytest.fixture
def seeded(clean_db: ConnectionPool) -> Seeded:
    """One user and one event in Europe/Berlin."""
    user_id, event_id = ids.new_id(), ids.new_id()
    with clean_db.connection() as conn, conn.transaction():
        conn.execute(
            "insert into users (id, email, display_name) values (%s, %s, %s)",
            (user_id, f"{ids.encode(user_id)}@example.test", "Test host"),
        )
        conn.execute(
            "insert into events (id, slug, title, starts_at, timezone, owner_id) "
            "values (%s, %s, %s, %s, %s, %s)",
            (
                event_id,
                f"test-{ids.encode(event_id)[:8]}",
                "Fixture evening",
                datetime(2024, 6, 14, 16, 0, tzinfo=UTC),
                "Europe/Berlin",
                user_id,
            ),
        )
    return Seeded(user_id=user_id, event_id=event_id)


class MediaSeeder:
    """Uploads a fixture as an original, inserts the media row and its ingest job."""

    def __init__(self, pool: ConnectionPool, storage: Storage, seeded: Seeded) -> None:
        self.pool = pool
        self.storage = storage
        self.seeded = seeded
        self.media_ids: list[bytes] = []

    def add(
        self,
        fixture: str | Path,
        *,
        event: bool = True,
        filename: str | None = None,
        created_at: datetime | None = None,
    ) -> bytes:
        path = Path(fixture) if isinstance(fixture, Path) else FIXTURES / fixture
        data = path.read_bytes()
        media_id = ids.new_id()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        kind = "video" if mime.startswith("video/") else "photo"
        event_id = self.seeded.event_id if event else None
        segment = ids.encode(event_id) if event_id else "lib"
        key = f"o/{segment}/{ids.encode(media_id)}{path.suffix.lower()}"
        self.storage.upload_bytes(self.storage.private_bucket, key, data, mime)
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                "insert into media (id, event_id, owner_id, uploader_user, kind, state, "
                "original_key, original_mime, original_filename, original_bytes, "
                "variant_prefix, created_at) "
                "values (%s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s, %s)",
                (
                    media_id,
                    event_id,
                    self.seeded.user_id,
                    self.seeded.user_id,
                    kind,
                    key,
                    mime,
                    filename or path.name,
                    len(data),
                    ids.new_encoded(),
                    created_at or datetime.now(UTC),
                ),
            )
            queue.enqueue(conn, "ingest", {"media_id": ids.encode(media_id)})
        self.media_ids.append(media_id)
        return media_id


@pytest.fixture
def seeder(clean_db: ConnectionPool, storage: Storage, seeded: Seeded) -> Iterator[MediaSeeder]:
    seeder = MediaSeeder(clean_db, storage, seeded)
    yield seeder
    # best effort: do not leave originals and variants behind in the dev buckets
    with clean_db.connection() as conn:
        originals = conn.execute("select original_key from media").fetchall()
        variants = conn.execute("select key from media_variants").fetchall()
    for row in originals:
        storage.delete(storage.private_bucket, row["original_key"])
    for row in variants:
        storage.delete(storage.public_bucket, row["key"])


def fetch_media(pool: ConnectionPool, media_id: bytes) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            "select *, phash::text as phash_text, gps[0] as gps_lon, gps[1] as gps_lat "
            "from media where id = %s",
            (media_id,),
        ).fetchone()
    assert row is not None
    return row


def fetch_variants(pool: ConnectionPool, media_id: bytes) -> dict[str, dict]:
    with pool.connection() as conn:
        rows = conn.execute(
            "select name, key, width, height, bytes from media_variants where media_id = %s",
            (media_id,),
        ).fetchall()
    return {r["name"]: r for r in rows}
