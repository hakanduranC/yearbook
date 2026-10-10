"""Private-bucket uploads of sandbox output files and 1-hour presigned GET URLs (boto3)."""

from __future__ import annotations

import asyncio
import mimetypes
import struct
from typing import Any

from .config import Settings


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height for PNG and JPEG without decoding the image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(w), int(h)
            seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + seg_len
    return None


def mime_for(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class Storage:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        cfg = Config(
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            signature_version="s3v4",
        )
        kwargs: dict[str, Any] = {
            "region_name": settings.s3_region,
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key,
            "config": cfg,
        }
        self.bucket = settings.s3_bucket_private
        self._client = boto3.client("s3", endpoint_url=settings.s3_endpoint, **kwargs)
        presign_endpoint = settings.s3_presign_endpoint or settings.s3_endpoint
        self._presign = boto3.client("s3", endpoint_url=presign_endpoint, **kwargs)

    async def put(self, key: str, data: bytes, mime: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=mime
        )

    async def presigned_get(self, key: str, expires_s: int = 3600) -> str:
        return await asyncio.to_thread(
            self._presign.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s,
        )


class NullStorage:
    """Used when S3 is not configured: attachments are dropped with a log line."""

    bucket = ""

    async def put(self, key: str, data: bytes, mime: str) -> None:
        return None

    async def presigned_get(self, key: str, expires_s: int = 3600) -> str:
        return ""
