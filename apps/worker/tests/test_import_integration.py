"""The import job on the Takeout-shaped fixture archive and on a folder."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from tests.conftest import FIXTURES, MediaSeeder, Seeded, drain, fetch_media
from yearbook_worker import ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.importer import run_import
from yearbook_worker.storage import Storage

pytestmark = pytest.mark.integration

ARCHIVE = FIXTURES / "takeout.zip"


def _create_import(
    pool: ConnectionPool, owner_id: bytes, kind: str, *, event_id: bytes | None = None,
    source_key: str | None = None,
) -> bytes:  # fmt: skip
    import_id = ids.new_id()
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "insert into imports (id, owner_id, kind, state, event_id, source_key) "
            "values (%s, %s, %s, 'queued', %s, %s)",
            (import_id, owner_id, kind, event_id, source_key),
        )
    return import_id


def _import_row(pool: ConnectionPool, import_id: bytes) -> dict:
    with pool.connection() as conn:
        return conn.execute("select * from imports where id = %s", (import_id,)).fetchone()


def test_takeout_archive(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    owner = seeder.seeded.user_id
    # fixture 05 already lives in the owner's library: the archive's copy is a duplicate
    seeder.add("05_IMG_7425.jpg", event=False)
    drain(clean_db, storage, settings, ("ingest",))
    import_id = _create_import(clean_db, owner, "takeout")
    key = f"imports/{ids.encode(import_id)}.zip"
    storage.upload_bytes(storage.private_bucket, key, ARCHIVE.read_bytes(), "application/zip")

    listener = psycopg.connect(settings.database_url, autocommit=True)
    try:
        listener.execute("listen media_events")
        with clean_db.connection() as conn:
            job_id = queue.enqueue(conn, "import", {"import_id": ids.encode(import_id)})
        jobs = drain(clean_db, storage, settings, ("import",))
        assert [j.id for j in jobs] == [job_id]
        payloads = [json.loads(n.payload) for n in listener.notifies(timeout=1, stop_after=1)]
    finally:
        listener.close()
    progress = [p for p in payloads if p["type"] == "import.progress"]
    assert progress and progress[0]["state"] == "running" and progress[-1]["state"] == "done"
    assert progress[-1]["import_id"] == ids.encode(import_id)

    row = _import_row(clean_db, import_id)
    assert row["state"] == "done" and row["error"] is None and row["finished_at"]
    assert row["stats"] == {
        "found": 6, "imported": 5, "duplicates": 1, "failed": 0, "matched": 4, "people_seeded": 5,
    }  # fmt: skip

    with clean_db.connection() as conn:
        media = conn.execute(
            "select * from media where import_id = %s order by original_filename", (import_id,)
        ).fetchall()
        hints = conn.execute(
            "select m.original_filename, h.name from media_person_hints h "
            "join media m on m.id = h.media_id order by 1, 2"
        ).fetchall()
        pending = conn.execute(
            "select count(*) from jobs where kind = 'ingest' and done_at is null"
        ).fetchone()["count"]
    by_name = {m["original_filename"]: m for m in media}
    assert set(by_name) == {
        "IMG_7421.jpg", "IMG_7422.jpg", "IMG_7424_sehr_langer_dateiname_vom_telefon.jpg",
        "VID_20240614_223000.mp4", "IMG_20231224_180000.jpg",
    }  # fmt: skip
    event_id = seeder.seeded.event_id
    for name in ("IMG_7421.jpg", "IMG_7422.jpg", "IMG_7424_sehr_langer_dateiname_vom_telefon.jpg",
                 "VID_20240614_223000.mp4"):  # fmt: skip
        m = by_name[name]
        assert bytes(m["event_id"]) == event_id
        assert m["original_key"].startswith(f"o/{ids.encode(event_id)}/")
        assert m["captured_src"] == "sidecar" and m["state"] == "queued"
        assert m["source"] == "takeout" and bytes(m["owner_id"]) == owner
        assert storage.head(storage.private_bucket, m["original_key"]) is not None
    winter = by_name["IMG_20231224_180000.jpg"]
    assert winter["event_id"] is None and winter["original_key"].startswith("o/lib/")
    assert winter["captured_at"] == datetime(2023, 12, 24, 17, 0, tzinfo=UTC)
    assert by_name["IMG_7421.jpg"]["captured_at"] == datetime(2024, 6, 14, 16, 5, 11, tzinfo=UTC)
    assert by_name["VID_20240614_223000.mp4"]["kind"] == "video"
    assert [(h["original_filename"], h["name"]) for h in hints] == [
        ("IMG_20231224_180000.jpg", "Anna Beispiel"),
        ("IMG_7421.jpg", "Anna Beispiel"),
        ("IMG_7421.jpg", "Ben Muster"),
        ("IMG_7422.jpg", "Anna Beispiel"),
        ("IMG_7424_sehr_langer_dateiname_vom_telefon.jpg", "Ben Muster"),
    ]
    assert pending == 5

    # the light worker finishes the job: probe keeps the sidecar time, GPS from the sidecar stays
    drain(clean_db, storage, settings, ("ingest",))
    r = fetch_media(clean_db, bytes(by_name["IMG_7421.jpg"]["id"]))
    assert r["state"] == "ready" and r["captured_src"] == "sidecar"
    assert r["captured_at"] == datetime(2024, 6, 14, 16, 5, 11, tzinfo=UTC)
    assert abs(r["gps_lat"] - 52.52) < 1e-3 and abs(r["gps_lon"] - 13.405) < 1e-3
    r = fetch_media(clean_db, bytes(winter["id"]))
    assert r["state"] == "ready" and r["dup_group_id"] is None
    with clean_db.connection() as conn:
        analyze = conn.execute(
            "select count(*) from jobs where kind = 'analyze'"
        ).fetchone()["count"]
    assert analyze == 6  # 5 imported + the pre-seeded library item


def test_folder_import_with_fixed_event(
    seeded: Seeded, clean_db: ConnectionPool, storage: Storage, settings: Settings, tmp_path
) -> None:
    with zipfile.ZipFile(ARCHIVE) as zf:
        zf.extractall(tmp_path)
    import_id = _create_import(
        clean_db, seeded.user_id, "folder", event_id=seeded.event_id, source_key=str(tmp_path)
    )
    stats = run_import(clean_db, storage, settings, import_id)
    assert stats == {
        "found": 6, "imported": 6, "duplicates": 0, "failed": 0, "matched": 6, "people_seeded": 5,
    }  # fmt: skip
    with clean_db.connection() as conn:
        rows = conn.execute(
            "select event_id, source, captured_src from media where import_id = %s", (import_id,)
        ).fetchall()
    assert all(bytes(r["event_id"]) == seeded.event_id and r["source"] == "folder" for r in rows)
    assert sum(1 for r in rows if r["captured_src"] == "sidecar") == 5


def test_missing_archive_fails_the_import(
    seeded: Seeded, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    import_id = _create_import(clean_db, seeded.user_id, "zip", source_key="imports/nothing.zip")
    with pytest.raises(Exception):  # noqa: B017 - boto3 raises its own ClientError subclass
        run_import(clean_db, storage, settings, import_id)
    row = _import_row(clean_db, import_id)
    assert row["state"] == "failed" and row["error"]
