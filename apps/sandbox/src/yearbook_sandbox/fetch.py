"""Fetch input files for a run. Only hosts the API or storage would issue URLs for are allowed."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from yearbook_sandbox.config import FETCH_TIMEOUT_S, MAX_FILE_BYTES
from yearbook_sandbox.models import InputFile


class FetchError(Exception):
    """A file could not be fetched; `code` is stable for clients, `message` is for humans."""

    def __init__(self, code: str, message: str, name: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.name = name


def check_url_allowed(url: str, allowed_hosts: frozenset[str]) -> str | None:
    """Return a reason the URL is refused, or None if it may be fetched."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme or '<none>'!r} is not http(s)"
    host = parsed.netloc.lower()
    if "@" in host:
        return "credentials in URL are not allowed"
    if not host:
        return "URL has no host"
    if host not in allowed_hosts:
        return f"host {host!r} is not one of the configured storage hosts"
    return None


def fetch_files(files: list[InputFile], into: Path, allowed_hosts: frozenset[str]) -> None:
    """Download every file into `into/<name>`. Raises FetchError on the first problem."""
    for f in files:
        reason = check_url_allowed(f.url, allowed_hosts)
        if reason:
            raise FetchError("url_not_allowed", reason, f.name)
    # No redirects: a redirect could point at a host outside the allowlist.
    with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
        for f in files:
            _fetch_one(client, f, into / f.name)


def _fetch_one(client: httpx.Client, f: InputFile, dest: Path) -> None:
    try:
        with client.stream("GET", f.url) as resp:
            if resp.status_code != 200:
                raise FetchError("fetch_failed", f"GET returned {resp.status_code}", f.name)
            declared = resp.headers.get("content-length")
            if declared and int(declared) > MAX_FILE_BYTES:
                raise FetchError("file_too_large", f"{declared} bytes > {MAX_FILE_BYTES}", f.name)
            written = 0
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as out:
                for chunk in resp.iter_bytes(64 * 1024):
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise FetchError(
                            "file_too_large", f"body exceeds {MAX_FILE_BYTES} bytes", f.name
                        )
                    out.write(chunk)
    except httpx.HTTPError as e:
        raise FetchError("fetch_failed", f"{type(e).__name__}: {e}", f.name) from e
