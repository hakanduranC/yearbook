"""Public ids: 16 random bytes, base64url without padding (22 characters) on the wire."""

from __future__ import annotations

import base64
import binascii
import secrets

ID_LEN = 16
ENCODED_LEN = 22


def new_id() -> bytes:
    """Return 16 cryptographically random bytes."""
    return secrets.token_bytes(ID_LEN)


def encode(raw: bytes) -> str:
    """Encode 16 bytes as a 22-char base64url string without padding."""
    if len(raw) != ID_LEN:
        raise ValueError(f"id must be {ID_LEN} bytes, got {len(raw)}")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode(text: str) -> bytes:
    """Decode a 22-char base64url id back to 16 bytes; raises ValueError on bad input."""
    if len(text) != ENCODED_LEN:
        raise ValueError(f"id must be {ENCODED_LEN} characters, got {len(text)}")
    try:
        raw = base64.urlsafe_b64decode(text + "==")
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid id {text!r}") from exc
    if len(raw) != ID_LEN or encode(raw) != text:
        raise ValueError(f"invalid id {text!r}")
    return raw


def new_encoded() -> str:
    """Convenience: a fresh id already in wire format."""
    return encode(new_id())
