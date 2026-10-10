"""Shared state passed through the ingestion stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from yearbook_worker import ids
from yearbook_worker.config import Settings
from yearbook_worker.storage import Storage

Kind = Literal["photo", "video"]
CapturedSrc = Literal["exif", "filename", "upload", "sidecar"]


@dataclass(slots=True)
class MediaRow:
    """The columns of `media` the pipeline reads, plus the event timezone."""

    id: bytes
    event_id: bytes | None
    owner_id: bytes | None
    kind: Kind
    state: str
    original_key: str
    original_mime: str
    original_filename: str | None
    original_bytes: int | None
    variant_prefix: str
    width: int | None
    height: int | None
    duration_ms: int | None
    captured_at: datetime | None
    processed_stages: dict[str, Any]
    created_at: datetime
    timezone: str
    captured_src: str | None = None

    @property
    def id_str(self) -> str:
        return ids.encode(self.id)

    @classmethod
    def from_record(cls, row: dict[str, Any], default_timezone: str) -> MediaRow:
        return cls(
            id=bytes(row["id"]),
            event_id=bytes(row["event_id"]) if row["event_id"] is not None else None,
            owner_id=bytes(row["owner_id"]) if row["owner_id"] is not None else None,
            kind=row["kind"],
            state=row["state"],
            original_key=row["original_key"],
            original_mime=row["original_mime"],
            original_filename=row["original_filename"],
            original_bytes=row["original_bytes"],
            variant_prefix=row["variant_prefix"],
            width=row["width"],
            height=row["height"],
            duration_ms=row["duration_ms"],
            captured_at=row["captured_at"],
            processed_stages=dict(row["processed_stages"] or {}),
            created_at=row["created_at"],
            timezone=row.get("timezone") or default_timezone,
            captured_src=row.get("captured_src"),
        )


@dataclass(slots=True)
class ProbeResult:
    """What `probe` learned from the original's metadata."""

    width: int
    height: int
    captured_at: datetime | None
    captured_src: CapturedSrc
    orientation: int = 1
    gps: tuple[float, float] | None = None  # (lat, lon)
    duration_ms: int | None = None


@dataclass(slots=True)
class VariantInfo:
    """One uploaded variant, mirrored into `media_variants`."""

    name: str
    key: str
    width: int
    height: int
    bytes: int


@dataclass(slots=True)
class StageContext:
    """Mutable bag handed to every stage. Stages read what earlier stages produced."""

    media: MediaRow
    settings: Settings
    storage: Storage
    workdir: Path
    original_path: Path | None = None
    sha256: bytes | None = None
    probe: ProbeResult | None = None
    _image: Image.Image | None = field(default=None, repr=False)
    small_image: Image.Image | None = field(default=None, repr=False)
    variants: list[VariantInfo] = field(default_factory=list)
    phash: str | None = None

    @property
    def image(self) -> Image.Image:
        """The oriented RGB working image; set by `decode` (photos) or `video` (poster)."""
        if self._image is None:
            raise RuntimeError("no working image: decode/video stage did not run")
        return self._image

    @image.setter
    def image(self, value: Image.Image) -> None:
        self._image = value

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def require_original(self) -> Path:
        if self.original_path is None:
            raise RuntimeError("original not fetched")
        return self.original_path

    @property
    def duration_ms(self) -> int | None:
        if self.probe is not None and self.probe.duration_ms is not None:
            return self.probe.duration_ms
        return self.media.duration_ms
