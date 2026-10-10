"""End-to-end: fixture → private bucket → ingest job → pipeline → variants, hashes, dedupe."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from psycopg_pool import ConnectionPool

from tests.conftest import FIXTURES, MediaSeeder, fetch_media, fetch_variants
from yearbook_worker import ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.pipeline import run_ingest
from yearbook_worker.stages import STAGES
from yearbook_worker.storage import Storage
from yearbook_worker.worker import process_one

pytestmark = pytest.mark.integration

PHOTO_STAGES = {"probe", "decode", "variants", "hashes", "dedupe"}
VIDEO_STAGES = {"probe", "video", "variants", "hashes", "dedupe"}


def drain(pool: ConnectionPool, storage: Storage, settings: Settings) -> list[queue.Job]:
    """Run jobs through the real claim → run → complete path until the queue is empty."""
    locked_by = queue.locked_by_token()
    done: list[queue.Job] = []
    while (job := process_one(pool, storage, settings, ["ingest"], locked_by)) is not None:
        done.append(job)
    return done


def test_photo_end_to_end(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    media_id = seeder.add("03_IMG_7423_portrait.jpg")
    jobs = drain(clean_db, storage, settings)
    assert len(jobs) == 1

    row = fetch_media(clean_db, media_id)
    assert row["state"] == "ready", row["error"]
    assert row["processed_at"] is not None
    assert set(row["processed_stages"]) == PHOTO_STAGES
    assert (row["width"], row["height"]) == (1200, 1600)  # orientation 6 applied
    assert row["captured_src"] == "exif"
    assert row["captured_at"] == datetime(2024, 6, 14, 17, 2, 5, tzinfo=UTC)
    assert row["content_sha256"] is not None and len(row["content_sha256"]) == 32
    assert len(row["phash_text"]) == 64
    assert row["dup_group_id"] is None and row["is_best_of_dup"] is True

    variants = fetch_variants(clean_db, media_id)
    assert set(variants) == {"thumb", "small", "medium", "large"}
    assert (variants["thumb"]["width"], variants["thumb"]["height"]) == (256, 256)
    assert (variants["small"]["width"], variants["small"]["height"]) == (480, 640)
    assert (variants["medium"]["width"], variants["medium"]["height"]) == (960, 1280)
    assert (variants["large"]["width"], variants["large"]["height"]) == (1200, 1600)  # no upscale
    prefix = row["variant_prefix"]
    for name, v in variants.items():
        assert v["key"] == f"v/{prefix}/{name}.webp"
        head = storage.head(storage.public_bucket, v["key"])
        assert head is not None and head["ContentLength"] == v["bytes"]
        assert head["ContentType"] == "image/webp"
    assert storage.public_url(variants["small"]["key"]).endswith(f"/v/{prefix}/small.webp")

    with clean_db.connection() as conn:
        job = conn.execute("select * from jobs where id = %s", (jobs[0].id,)).fetchone()
    assert job is not None and job["done_at"] is not None and job["error"] is None


def test_capture_time_sources(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    upload_time = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    no_offset = seeder.add("08_IMG_7428_nooffset.jpg")
    dated_name = seeder.add("13_IMG_20240614_211400.jpg")
    pixel_name = seeder.add("13_IMG_20240614_211400.jpg", filename="PXL_20240614_191400123.jpg")
    png = seeder.add("14_logo_alpha.png", created_at=upload_time)
    gps = seeder.add("06_IMG_7426_gps.jpg")
    drain(clean_db, storage, settings)

    row = fetch_media(clean_db, no_offset)
    assert (row["captured_src"], row["captured_at"]) == (
        "exif",
        datetime(2024, 6, 14, 19, 59, 33, tzinfo=UTC),  # 21:59:33 Berlin (CEST)
    )
    row = fetch_media(clean_db, dated_name)
    assert (row["captured_src"], row["captured_at"]) == (
        "filename",
        datetime(2024, 6, 14, 19, 14, tzinfo=UTC),
    )
    row = fetch_media(clean_db, pixel_name)
    assert (row["captured_src"], row["captured_at"]) == (
        "filename",
        datetime(2024, 6, 14, 19, 14, tzinfo=UTC),  # PXL names are UTC already
    )
    row = fetch_media(clean_db, png)
    assert (row["captured_src"], row["captured_at"], row["state"]) == (
        "upload",
        upload_time,
        "ready",
    )
    row = fetch_media(clean_db, gps)
    # stored as point(lon, lat): x = longitude, y = latitude
    assert abs(row["gps_lat"] - 52.52) < 1e-3 and abs(row["gps_lon"] - 13.405) < 1e-3
    assert fetch_media(clean_db, png)["gps_lat"] is None


def test_heic_decodes(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    media_id = seeder.add("15_IMG_0199.heic")
    drain(clean_db, storage, settings)
    row = fetch_media(clean_db, media_id)
    assert row["state"] == "ready", row["error"]
    assert (row["width"], row["height"]) == (1440, 1080)
    assert row["captured_at"] == datetime(2024, 6, 14, 17, 25, 47, tzinfo=UTC)
    variants = fetch_variants(clean_db, media_id)
    assert (variants["medium"]["width"], variants["medium"]["height"]) == (1280, 960)


def test_duplicates_are_grouped(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    a = seeder.add("02_IMG_7422.jpg")
    a_copy = seeder.add("16_IMG_7422_copy.jpg")
    b = seeder.add("05_IMG_7425.jpg")
    b_near = seeder.add("11_IMG_7425_copy_q50.jpg")
    other = seeder.add("04_IMG_7424.jpg")
    drain(clean_db, storage, settings)

    ra, rac = fetch_media(clean_db, a), fetch_media(clean_db, a_copy)
    assert ra["dup_group_id"] is not None and ra["dup_group_id"] == rac["dup_group_id"]
    assert ra["content_sha256"] == rac["content_sha256"]
    # equal size: the earlier upload stays best
    assert (ra["is_best_of_dup"], rac["is_best_of_dup"]) == (True, False)
    assert ra["state"] == rac["state"] == "ready"

    rb, rbn = fetch_media(clean_db, b), fetch_media(clean_db, b_near)
    assert rb["dup_group_id"] is not None and rb["dup_group_id"] == rbn["dup_group_id"]
    assert rb["dup_group_id"] != ra["dup_group_id"]
    assert (rb["is_best_of_dup"], rbn["is_best_of_dup"]) == (True, False)  # larger bytes wins

    assert fetch_media(clean_db, other)["dup_group_id"] is None

    with clean_db.connection() as conn:
        groups = conn.execute("select id, kind, event_id from duplicate_groups").fetchall()
    kinds = {bytes(g["id"]): g["kind"] for g in groups}
    assert kinds[bytes(ra["dup_group_id"])] == "exact"
    assert kinds[bytes(rb["dup_group_id"])] == "near"
    assert all(bytes(g["event_id"]) == seeder.seeded.event_id for g in groups)


def test_near_duplicate_outside_window_is_not_grouped(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    b = seeder.add("05_IMG_7425.jpg")
    # same pixels, but a filename time 3 hours later and no EXIF
    late = seeder.add("13_IMG_20240614_211400.jpg", filename="IMG_20240614_231400.jpg")
    drain(clean_db, storage, settings)
    assert fetch_media(clean_db, b)["dup_group_id"] is None
    assert fetch_media(clean_db, late)["dup_group_id"] is None


def test_library_items_dedupe_per_owner(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    lib = seeder.add("02_IMG_7422.jpg", event=False)
    lib_copy = seeder.add("16_IMG_7422_copy.jpg", event=False)
    in_event = seeder.add("02_IMG_7422.jpg")
    drain(clean_db, storage, settings)
    r1, r2, r3 = (fetch_media(clean_db, m) for m in (lib, lib_copy, in_event))
    assert r1["dup_group_id"] == r2["dup_group_id"] is not None
    assert r3["dup_group_id"] is None  # different scope: event vs library
    with clean_db.connection() as conn:
        g = conn.execute("select event_id from duplicate_groups").fetchone()
    assert g is not None and g["event_id"] is None


def test_video_gets_poster_and_mp4(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    media_id = seeder.add("17_clip.mp4")
    drain(clean_db, storage, settings)
    row = fetch_media(clean_db, media_id)
    assert row["state"] == "ready", row["error"]
    assert row["kind"] == "video"
    assert set(row["processed_stages"]) == VIDEO_STAGES
    assert (row["width"], row["height"]) == (640, 360)
    assert 2900 <= row["duration_ms"] <= 3100
    assert row["captured_at"] == datetime(2024, 6, 14, 20, 30, tzinfo=UTC)
    assert row["captured_src"] == "exif"
    variants = fetch_variants(clean_db, media_id)
    assert set(variants) == {"video", "poster", "thumb", "small", "medium", "large"}
    assert (variants["video"]["width"], variants["video"]["height"]) == (640, 360)
    assert (variants["poster"]["width"], variants["poster"]["height"]) == (640, 360)
    prefix = row["variant_prefix"]
    assert variants["video"]["key"] == f"v/{prefix}/video.mp4"
    head = storage.head(storage.public_bucket, variants["video"]["key"])
    assert head is not None and head["ContentType"] == "video/mp4"
    assert head["ContentLength"] == variants["video"]["bytes"] > 0
    assert storage.head(storage.public_bucket, f"v/{prefix}/poster.webp") is not None


def test_resume_skips_recorded_stages(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    media_id = seeder.add("07_IMG_7427.jpg")
    drain(clean_db, storage, settings)
    row = fetch_media(clean_db, media_id)
    first_stamp = row["processed_stages"]["variants"]
    with clean_db.connection() as conn, conn.transaction():
        conn.execute(
            "update media set processed_stages = processed_stages - 'dedupe' - 'hashes', "
            "state = 'queued', phash = null where id = %s",
            (media_id,),
        )
    run_ingest(clean_db, storage, settings, media_id)
    row = fetch_media(clean_db, media_id)
    assert row["state"] == "ready"
    assert row["processed_stages"]["variants"] == first_stamp  # not re-run
    assert len(row["phash_text"]) == 64  # hashes re-ran, using decode.restore for the image


def test_failure_marks_media_failed_on_last_attempt(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    media_id = seeder.add("07_IMG_7427.jpg")
    with clean_db.connection() as conn, conn.transaction():
        conn.execute("update jobs set max_attempts = 2")
        conn.execute(
            "update media set original_key = 'o/missing/nothing.jpg' where id = %s", (media_id,)
        )
    locked_by = queue.locked_by_token()

    job = process_one(clean_db, storage, settings, ["ingest"], locked_by)
    assert job is not None and job.attempts == 1
    row = fetch_media(clean_db, media_id)
    assert row["state"] == "queued" and row["error"]  # retry pending
    with clean_db.connection() as conn:
        j = conn.execute("select * from jobs where id = %s", (job.id,)).fetchone()
        assert j is not None and j["done_at"] is None and j["run_after"] > j["created_at"]
        conn.execute("update jobs set run_after = now()")
        conn.commit()

    job = process_one(clean_db, storage, settings, ["ingest"], locked_by)
    assert job is not None and job.attempts == 2
    row = fetch_media(clean_db, media_id)
    assert row["state"] == "failed" and row["error"]
    with clean_db.connection() as conn:
        j = conn.execute("select * from jobs where id = %s", (job.id,)).fetchone()
    assert j is not None and j["done_at"] is not None and j["error"]


def test_media_events_are_notified(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    import json

    import psycopg

    media_id = seeder.add("10_IMG_7430.jpg")
    listener = psycopg.connect(settings.database_url, autocommit=True)
    try:
        listener.execute("listen media_events")
        drain(clean_db, storage, settings)
        payloads = [json.loads(n.payload) for n in listener.notifies(timeout=2, stop_after=1)]
    finally:
        listener.close()
    assert payloads == [
        {
            "type": "media.ready",
            "event_id": ids.encode(seeder.seeded.event_id),
            "media_id": ids.encode(media_id),
        }
    ]


def test_stage_order() -> None:
    names = [s.name for s in STAGES]
    assert names == ["fetch", "probe", "decode", "video", "variants", "hashes", "dedupe"]
    assert not next(s for s in STAGES if s.name == "fetch").record


@pytest.mark.skipif(not any((FIXTURES / "private").glob("*")), reason="no private fixtures present")
def test_private_fixtures_ingest(
    seeder: MediaSeeder, clean_db: ConnectionPool, storage: Storage, settings: Settings
) -> None:
    """Real iPhone HEICs / MOVs the owner dropped into fixtures/private (gitignored)."""
    paths = sorted(
        p
        for p in (FIXTURES / "private").iterdir()
        if p.suffix.lower() in {".heic", ".heif", ".jpg", ".jpeg", ".mov", ".mp4", ".png"}
    )
    if os.environ.get("PRIVATE_FIXTURE_LIMIT"):
        paths = paths[: int(os.environ["PRIVATE_FIXTURE_LIMIT"])]
    media = {p.name: seeder.add(Path(p)) for p in paths}
    drain(clean_db, storage, settings)
    failures = {
        name: fetch_media(clean_db, mid)["error"]
        for name, mid in media.items()
        if fetch_media(clean_db, mid)["state"] != "ready"
    }
    assert not failures, failures
    for mid in media.values():
        assert fetch_media(clean_db, mid)["captured_at"] - datetime(
            2000, 1, 1, tzinfo=UTC
        ) > timedelta(0)
