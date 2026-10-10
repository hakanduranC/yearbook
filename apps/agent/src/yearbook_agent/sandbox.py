"""Client for apps/sandbox (`POST /run`), the only component that starts containers."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class SandboxFile:
    name: str
    data: bytes


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    files: list[SandboxFile] = field(default_factory=list)
    duration_ms: int = 0


class SandboxError(Exception):
    pass


class SandboxClient:
    def __init__(self, url: str, timeout_s: int = 20) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    @staticmethod
    def sha256(code: str) -> bytes:
        return hashlib.sha256(code.encode("utf-8")).digest()

    async def run(
        self,
        code: str,
        inputs: dict[str, Any] | list[Any] | None,
        files: list[dict[str, str]] | None = None,
        timeout_s: int | None = None,
    ) -> SandboxResult:
        body = {
            "code": code,
            "inputs": inputs if inputs is not None else {},
            "files": files or [],
            "timeout_s": min(timeout_s or self.timeout_s, 20),
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(body["timeout_s"] + 10)) as client:
                resp = await client.post(f"{self.url}/run", json=body)
        except httpx.HTTPError as exc:
            raise SandboxError(f"sandbox unreachable: {exc}") from exc
        if resp.status_code >= 400:
            raise SandboxError(f"sandbox returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        files_out = []
        for f in data.get("files") or []:
            if f.get("bytes_b64"):
                files_out.append(SandboxFile(name=f["name"], data=base64.b64decode(f["bytes_b64"])))
        return SandboxResult(
            exit_code=int(data.get("exit_code", -1)),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
            files=files_out,
            duration_ms=int(data.get("duration_ms", 0)),
        )
