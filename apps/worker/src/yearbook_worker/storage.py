"""S3 access for originals (private bucket) and variants (public bucket)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from yearbook_worker.config import Settings

CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Downloaded:
    """Result of streaming an object to disk."""

    path: Path
    size: int
    sha256: bytes


class Storage:
    """Thin boto3 wrapper configured for SeaweedFS / R2 / Hetzner (path style, lazy checksums)."""

    def __init__(self, settings: Settings) -> None:
        self.private_bucket = settings.s3_bucket_private
        self.public_bucket = settings.s3_bucket_public
        self.public_base_url = settings.public_base_url.rstrip("/")
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 4, "mode": "standard"},
            ),
        )

    def download(self, bucket: str, key: str, dest: Path) -> Downloaded:
        """Stream `bucket/key` to `dest`, hashing on the fly."""
        obj = self.client.get_object(Bucket=bucket, Key=key)
        digest = hashlib.sha256()
        size = 0
        with dest.open("wb") as fh:
            for chunk in obj["Body"].iter_chunks(CHUNK):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        return Downloaded(path=dest, size=size, sha256=digest.digest())

    def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        """Upload an in-memory object."""
        self.client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    def upload_file(self, bucket: str, key: str, path: Path, content_type: str) -> None:
        """Upload a file from disk (multipart for large videos is handled by boto3)."""
        self.client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )

    def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        """Metadata of an object or None when it does not exist."""
        try:
            return self.client.head_object(Bucket=bucket, Key=key)
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def delete(self, bucket: str, key: str) -> None:
        """Delete one object (missing keys are not an error)."""
        self.client.delete_object(Bucket=bucket, Key=key)

    def public_url(self, key: str) -> str:
        """`PUBLIC_BASE_URL + "/" + key` as pinned in CONVENTIONS."""
        return f"{self.public_base_url}/{key}"


def variant_key(variant_prefix: str, name: str) -> str:
    """Public key of a variant: `v/{variant_prefix}/{name}` (name carries its extension)."""
    return f"v/{variant_prefix}/{name}"
