"""`import {import_id}`: zip / Takeout archive or server folder → originals, media, ingest jobs.

Archives are streamed from the private bucket (`imports/{id}.zip`) to a temp file and read with
`zipfile` entry by entry; nothing is held in RAM. Takeout sidecars (`<file>.json`,
`<file>.supplemental-metadata.json` and Google's truncated / numbered variants) provide the
capture time (`captured_src = sidecar`), GPS and people names (`media_person_hints`). Exact
SHA-256 duplicates against the owner's existing media (and within the import) are skipped and
counted. Items match an event by the CONVENTIONS window unless the import has a fixed event.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import traceback
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path, PurePosixPath
from typing import IO, Any

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from yearbook_worker import capture_time, ids, queue
from yearbook_worker.config import Settings
from yearbook_worker.log import get_logger
from yearbook_worker.notify import notify_import_progress
from yearbook_worker.storage import Storage

log = get_logger(__name__)

# Upload MIME allowlist (apps/api/internal/media/rules.go), by file extension.
EXT_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}
MIME_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/webp": "webp",
    "image/avif": "avif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}
SIDECAR_SUFFIXES = (".json", ".supplemental-metadata.json", ".supplemental-meta.json")
SIDECAR_TRUNCATED_MIN = 40  # a truncated sidecar stem must keep at least this many characters
STATS_EVERY = 20
EVENT_PADDING = timedelta(hours=2)
EVENT_DEFAULT_LENGTH = timedelta(hours=12)
CHUNK = 1 << 20

STATS_KEYS = ("found", "imported", "duplicates", "failed", "matched", "people_seeded")
# `media.source` only knows upload|takeout|folder|picker|share; plain zips count as uploads.
SOURCE_BY_KIND = {"takeout": "takeout", "folder": "folder", "zip": "upload"}

LOAD_IMPORT_SQL = """
select id, owner_id, kind, state, event_id, source_key, source_bytes, stats
from imports where id = %(id)s
"""
LOAD_EVENTS_SQL = """
select id, starts_at, ends_at, timezone from events
where owner_id = %(owner_id)s and archived_at is null
order by starts_at
"""
DUP_SQL = """
select 1 from media
where owner_id = %(owner_id)s and content_sha256 = %(sha)s and state <> 'removed' limit 1
"""
INSERT_MEDIA_SQL = """
insert into media (id, event_id, owner_id, uploader_user, source, kind, state, original_key,
                   original_mime, original_filename, original_bytes, variant_prefix,
                   captured_at, captured_src, gps, content_sha256, import_id)
values (%(id)s, %(event_id)s, %(owner_id)s, %(owner_id)s, %(source)s, %(kind)s, 'queued',
        %(original_key)s, %(mime)s, %(filename)s, %(bytes)s, %(variant_prefix)s,
        %(captured_at)s, %(captured_src)s,
        case when %(lon)s::float8 is null then null else point(%(lon)s, %(lat)s) end,
        %(sha)s, %(import_id)s)
"""
INSERT_HINT_SQL = """
insert into media_person_hints (media_id, name, source) values (%(media_id)s, %(name)s, 'takeout')
on conflict do nothing
"""
UPDATE_STATS_SQL = "update imports set stats = %(stats)s where id = %(id)s"
START_SQL = """
update imports set state = 'running', started_at = coalesce(started_at, now()), error = null
where id = %(id)s
"""
FINISH_SQL = """
update imports set state = %(state)s, finished_at = now(), stats = %(stats)s, error = %(error)s
where id = %(id)s
"""


class ImportNotFound(Exception):
    pass


@dataclass(slots=True)
class Sidecar:
    taken_at: datetime | None = None
    gps: tuple[float, float] | None = None  # (lat, lon)
    people: list[str] = field(default_factory=list)
    description: str | None = None


@dataclass(slots=True)
class EventWindow:
    id: bytes
    starts_at: datetime
    ends_at: datetime | None
    timezone: str

    @property
    def window(self) -> tuple[datetime, datetime]:
        end = self.ends_at or (self.starts_at + EVENT_DEFAULT_LENGTH)
        return self.starts_at - EVENT_PADDING, end + EVENT_PADDING


@dataclass(slots=True)
class Entry:
    """One file of the source: relative posix path, size and a way to open it."""

    path: str
    size: int
    _opener: Any

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def directory(self) -> str:
        return str(PurePosixPath(self.path).parent)

    def open(self) -> IO[bytes]:
        return self._opener()


# --- sidecars -----------------------------------------------------------------------------------


_NUMBERED = re.compile(r"^(?P<stem>.+?)(?P<num>\(\d+\))(?P<ext>\.[^.]+)$")


def sidecar_candidates(filename: str) -> list[str]:
    """Sidecar file names Google Takeout may use for `filename`, most specific first.

    Covers `IMG.jpg.json`, `IMG.jpg.supplemental-metadata.json`, numbered copies
    (`IMG(1).jpg` → `IMG.jpg(1).json`) and `-edited` variants (which share the original's sidecar).
    Truncated names (Google cuts the sidecar stem at ~46-51 characters) are matched by prefix in
    `find_sidecar`.
    """
    names: list[str] = []
    bases = [filename]
    stem, ext = os.path.splitext(filename)
    if stem.endswith("-edited"):
        bases.append(stem[: -len("-edited")] + ext)
    for base in bases:
        m = _NUMBERED.match(base)
        if m:
            plain = m.group("stem") + m.group("ext")
            num = m.group("num")
            names.extend(f"{plain}{suffix[:-5]}{num}.json" for suffix in SIDECAR_SUFFIXES)
            names.extend(f"{plain}{suffix}" for suffix in SIDECAR_SUFFIXES)
        else:
            names.extend(f"{base}{suffix}" for suffix in SIDECAR_SUFFIXES)
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def find_sidecar(filename: str, json_names: set[str]) -> str | None:
    """The sidecar for `filename` among the `.json` names of the same directory, or None."""
    candidates = sidecar_candidates(filename)
    for name in candidates:
        if name in json_names:
            return name
    # Truncated variants: the stem of the json is a prefix of a candidate (minus `.json`).
    stems = [c[:-5] for c in candidates]
    best: str | None = None
    for name in json_names:
        if not name.endswith(".json"):
            continue
        js = name[:-5]
        if len(js) < SIDECAR_TRUNCATED_MIN:
            continue
        if any(s.startswith(js) for s in stems) and (best is None or len(name) > len(best)):
            best = name
    return best


def parse_sidecar(raw: bytes | str | dict[str, Any]) -> Sidecar:
    """Pull capture time, GPS and people names out of a Takeout sidecar."""
    data: Any = raw
    if isinstance(raw, bytes | str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return Sidecar()
    if not isinstance(data, dict):
        return Sidecar()
    out = Sidecar()
    taken = data.get("photoTakenTime") or data.get("creationTime") or {}
    ts = taken.get("timestamp") if isinstance(taken, dict) else None
    if ts is not None:
        try:
            out.taken_at = datetime.fromtimestamp(int(str(ts)), tz=UTC)
        except (ValueError, OverflowError, OSError):
            out.taken_at = None
    for key in ("geoDataExif", "geoData"):
        geo = data.get(key)
        if isinstance(geo, dict):
            try:
                lat, lon = float(geo.get("latitude", 0)), float(geo.get("longitude", 0))
            except (TypeError, ValueError):
                continue
            if (lat, lon) != (0.0, 0.0) and abs(lat) <= 90 and abs(lon) <= 180:
                out.gps = (lat, lon)
                break
    people = data.get("people")
    if isinstance(people, list):
        seen: set[str] = set()
        for person in people:
            name = person.get("name") if isinstance(person, dict) else None
            if isinstance(name, str):
                name = " ".join(name.split())[:120]
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    out.people.append(name)
    desc = data.get("description")
    if isinstance(desc, str) and desc.strip():
        out.description = desc.strip()[:2000]
    return out


# --- event matching ------------------------------------------------------------------------------


def match_event(captured_at: datetime | None, events: list[EventWindow]) -> bytes | None:
    """The owner's event whose padded window contains `captured_at` (closest start wins)."""
    if captured_at is None:
        return None
    best: tuple[float, bytes] | None = None
    for ev in events:
        start, end = ev.window
        if start <= captured_at <= end:
            distance = abs((captured_at - ev.starts_at).total_seconds())
            if best is None or distance < best[0]:
                best = (distance, ev.id)
    return best[1] if best else None


# --- sources -------------------------------------------------------------------------------------


class ZipSource:
    def __init__(self, path: Path) -> None:
        self.zf = zipfile.ZipFile(path)
        self.infos = [i for i in self.zf.infolist() if not i.is_dir()]
        self.json_by_dir: dict[str, set[str]] = {}
        self.info_by_path: dict[str, zipfile.ZipInfo] = {}
        for info in self.infos:
            p = PurePosixPath(info.filename)
            self.info_by_path[info.filename] = info
            if p.suffix.lower() == ".json":
                self.json_by_dir.setdefault(str(p.parent), set()).add(p.name)

    def close(self) -> None:
        self.zf.close()

    def entries(self) -> Iterator[Entry]:
        for info in self.infos:
            opener = lambda info=info: self.zf.open(info)  # noqa: E731
            yield Entry(info.filename, info.file_size, opener)

    def sidecar(self, entry: Entry) -> bytes | None:
        names = self.json_by_dir.get(entry.directory, set())
        found = find_sidecar(entry.name, names)
        if found is None:
            return None
        info = self.info_by_path.get(str(PurePosixPath(entry.directory) / found))
        if info is None or info.file_size > 1 << 20:
            return None
        with self.zf.open(info) as fh:
            return fh.read()


class FolderSource:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: list[Path] = sorted(p for p in root.rglob("*") if p.is_file())
        self.json_by_dir: dict[str, set[str]] = {}
        for p in self.files:
            if p.suffix.lower() == ".json":
                rel = p.relative_to(root).as_posix()
                self.json_by_dir.setdefault(str(PurePosixPath(rel).parent), set()).add(p.name)

    def close(self) -> None:
        return None

    def entries(self) -> Iterator[Entry]:
        for p in self.files:
            rel = p.relative_to(self.root).as_posix()
            yield Entry(rel, p.stat().st_size, lambda p=p: p.open("rb"))

    def sidecar(self, entry: Entry) -> bytes | None:
        names = self.json_by_dir.get(entry.directory, set())
        found = find_sidecar(entry.name, names)
        if found is None:
            return None
        path = self.root / entry.directory / found
        if not path.is_file() or path.stat().st_size > 1 << 20:
            return None
        return path.read_bytes()


# --- the job ---------------------------------------------------------------------------------


def run_import(
    pool: ConnectionPool, storage: Storage, settings: Settings, import_id: bytes
) -> dict[str, int]:
    """Process one `imports` row to completion. Per-item errors are counted, not raised."""
    started = time.perf_counter()
    with pool.connection() as conn:
        row = conn.execute(LOAD_IMPORT_SQL, {"id": import_id}).fetchone()
        if row is None:
            raise ImportNotFound(ids.encode(import_id))
        if row["state"] in {"done", "cancelled"}:
            log.info("import.skip_state", import_id=ids.encode(import_id), state=row["state"])
            return dict(row["stats"] or {})
        owner_id = bytes(row["owner_id"])
        fixed_event = bytes(row["event_id"]) if row["event_id"] is not None else None
        kind = row["kind"]
        stats = dict.fromkeys(STATS_KEYS, 0)  # a retried import starts its counters over
        with conn.transaction():
            conn.execute(START_SQL, {"id": import_id})
            notify_import_progress(conn, import_id, fixed_event, stats, "running")
        conn.commit()
        events = [
            EventWindow(bytes(e["id"]), e["starts_at"], e["ends_at"], e["timezone"])
            for e in conn.execute(LOAD_EVENTS_SQL, {"owner_id": owner_id}).fetchall()
        ]
        tz = capture_time.zone(None, settings.default_timezone)
        tmp_root = settings.worker_tmp_dir
        if tmp_root is not None:
            tmp_root.mkdir(parents=True, exist_ok=True)
        error: str | None = None
        with tempfile.TemporaryDirectory(prefix="yb-import-", dir=tmp_root) as tmp:
            workdir = Path(tmp)
            try:
                source = _open_source(kind, row["source_key"], storage, import_id, workdir)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:2000]
                log.error("import.open_error", import_id=ids.encode(import_id), error=error)
                conn.rollback()
                with conn.transaction():
                    conn.execute(
                        FINISH_SQL,
                        {"id": import_id, "state": "failed", "stats": Jsonb(stats), "error": error},
                    )
                    notify_import_progress(conn, import_id, fixed_event, stats, "failed")
                conn.commit()
                raise
            try:
                seen_hashes: set[bytes] = set()
                since_update = 0
                for entry in source.entries():
                    mime = EXT_MIME.get(PurePosixPath(entry.name).suffix.lower())
                    if mime is None or entry.name.startswith("._"):
                        continue
                    stats["found"] += 1
                    try:
                        outcome = _import_entry(
                            conn,
                            storage,
                            source,
                            entry,
                            mime,
                            workdir,
                            owner_id=owner_id,
                            import_id=import_id,
                            kind=kind,
                            fixed_event=fixed_event,
                            events=events,
                            tz=tz,
                            seen_hashes=seen_hashes,
                        )
                    except Exception as exc:
                        conn.rollback()
                        stats["failed"] += 1
                        log.warning(
                            "import.item_error",
                            import_id=ids.encode(import_id),
                            path=entry.path,
                            error=f"{type(exc).__name__}: {exc}"[:500],
                            tb=traceback.format_exc(limit=4),
                        )
                    else:
                        conn.commit()
                        for key, inc in outcome.items():
                            stats[key] += inc
                    since_update += 1
                    if since_update >= STATS_EVERY:
                        since_update = 0
                        with conn.transaction():
                            conn.execute(UPDATE_STATS_SQL, {"id": import_id, "stats": Jsonb(stats)})
                            notify_import_progress(conn, import_id, fixed_event, stats, "running")
                        conn.commit()
            finally:
                source.close()
        conn.rollback()
        with conn.transaction():
            conn.execute(
                FINISH_SQL, {"id": import_id, "state": "done", "stats": Jsonb(stats), "error": None}
            )
            notify_import_progress(conn, import_id, fixed_event, stats, "done")
        conn.commit()
    log.info(
        "import.done",
        import_id=ids.encode(import_id),
        duration_ms=int((time.perf_counter() - started) * 1000),
        **stats,
    )
    return stats


def _open_source(
    kind: str, source_key: str | None, storage: Storage, import_id: bytes, workdir: Path
) -> ZipSource | FolderSource:
    if kind == "folder":
        if not source_key:
            raise RuntimeError("folder import without source_key")
        root = Path(source_key)
        if not root.is_dir():
            raise RuntimeError(f"folder {root} does not exist")
        return FolderSource(root)
    key = source_key or f"imports/{ids.encode(import_id)}.zip"
    archive = workdir / "archive.zip"
    result = storage.download(storage.private_bucket, key, archive)
    if result.size == 0:
        raise RuntimeError(f"archive {key} is empty")
    if not zipfile.is_zipfile(archive):
        raise RuntimeError(f"archive {key} is not a zip file")
    return ZipSource(archive)


def _import_entry(
    conn: psycopg.Connection,
    storage: Storage,
    source: ZipSource | FolderSource,
    entry: Entry,
    mime: str,
    workdir: Path,
    *,
    owner_id: bytes,
    import_id: bytes,
    kind: str,
    fixed_event: bytes | None,
    events: list[EventWindow],
    tz: tzinfo,
    seen_hashes: set[bytes],
) -> dict[str, int]:
    ext = MIME_EXT[mime]
    local = workdir / f"item.{ext}"
    digest = hashlib.sha256()
    size = 0
    with entry.open() as src, local.open("wb") as dst:
        while chunk := src.read(CHUNK):
            dst.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    sha = digest.digest()
    if size == 0:
        return {"failed": 1}
    if sha in seen_hashes or conn.execute(DUP_SQL, {"owner_id": owner_id, "sha": sha}).fetchone():
        seen_hashes.add(sha)
        return {"duplicates": 1}
    seen_hashes.add(sha)

    sidecar = Sidecar()
    raw = source.sidecar(entry)
    if raw is not None:
        sidecar = parse_sidecar(raw)
    captured_at, captured_src = sidecar.taken_at, "sidecar" if sidecar.taken_at else None
    for_matching = captured_at or _probe_capture_time(local, mime, entry.name, tz)

    event_id = fixed_event if fixed_event is not None else match_event(for_matching, events)
    media_id = ids.new_id()
    segment = ids.encode(event_id) if event_id else "lib"
    key = f"o/{segment}/{ids.encode(media_id)}.{ext}"
    storage.upload_file(storage.private_bucket, key, local, mime)
    with conn.transaction():
        conn.execute(
            INSERT_MEDIA_SQL,
            {
                "id": media_id,
                "event_id": event_id,
                "owner_id": owner_id,
                "source": SOURCE_BY_KIND[kind],
                "kind": "video" if mime.startswith("video/") else "photo",
                "original_key": key,
                "mime": mime,
                "filename": entry.name,
                "bytes": size,
                "variant_prefix": ids.new_encoded(),
                "captured_at": captured_at,
                "captured_src": captured_src,
                "lat": sidecar.gps[0] if sidecar.gps else None,
                "lon": sidecar.gps[1] if sidecar.gps else None,
                "sha": sha,
                "import_id": import_id,
            },
        )
        for name in sidecar.people:
            conn.execute(INSERT_HINT_SQL, {"media_id": media_id, "name": name})
        queue.enqueue_media_job(conn, "ingest", media_id)
    local.unlink(missing_ok=True)
    return {
        "imported": 1,
        "matched": 1 if event_id is not None else 0,
        "people_seeded": len(sidecar.people),
    }


def _probe_capture_time(path: Path, mime: str, filename: str, tz: tzinfo) -> datetime | None:
    """Cheap capture time for event matching only: EXIF DateTimeOriginal, else the filename."""
    if mime.startswith("image/"):
        try:
            from PIL import Image

            from yearbook_worker.stages.probe import (
                EXIF_IFD,
                TAG_DATETIME,
                TAG_DATETIME_ORIGINAL,
                TAG_OFFSET_TIME,
                TAG_OFFSET_TIME_ORIGINAL,
                _text,
            )

            with Image.open(path) as im:
                exif = im.getexif()
            ifd = exif.get_ifd(EXIF_IFD)
            found = capture_time.parse_exif_datetime(
                _text(ifd.get(TAG_DATETIME_ORIGINAL)), _text(ifd.get(TAG_OFFSET_TIME_ORIGINAL)), tz
            ) or capture_time.parse_exif_datetime(
                _text(exif.get(TAG_DATETIME)), _text(ifd.get(TAG_OFFSET_TIME)), tz
            )
            if found is not None:
                return found
        except Exception:  # matching is best effort; the probe stage does the real work
            pass
    return capture_time.parse_filename_datetime(filename, tz)


__all__ = [
    "EXT_MIME",
    "Sidecar",
    "find_sidecar",
    "match_event",
    "parse_sidecar",
    "run_import",
    "sidecar_candidates",
]
