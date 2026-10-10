"""Public ids: 16 random bytes, base64url without padding (22 chars), see docs/CONVENTIONS.md."""

import base64
import os


def new_id() -> bytes:
    return os.urandom(16)


def encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def decode(s: str) -> bytes:
    if len(s) != 22:
        raise ValueError("id must be 22 characters")
    return base64.urlsafe_b64decode(s + "==")


def is_id(s: object) -> bool:
    if not isinstance(s, str) or len(s) != 22:
        return False
    try:
        decode(s)
    except (ValueError, TypeError):
        return False
    return True
