"""In-memory stand-in for `storage.Storage` so tests can assert on uploaded attachments."""

from __future__ import annotations


class MemoryStorage:
    bucket = "memory"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, mime: str) -> None:
        self.objects[key] = (data, mime)

    async def presigned_get(self, key: str, expires_s: int = 3600) -> str:
        return f"memory://{self.bucket}/{key}?expires={expires_s}"
