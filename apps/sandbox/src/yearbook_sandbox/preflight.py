"""Cheap first line: refuse code that obviously wants out.

This is NOT the security boundary; the container configuration is. It only saves a container
start for the model's most common mistakes and gives it a precise message to self-correct on.
"""

from __future__ import annotations

import re

FORBIDDEN_TOKENS = (
    "socket",
    "subprocess",
    "ctypes",
    "os.system",
    "importlib",
    "__import__",
)

_PATTERNS = [
    (tok, re.compile(rf"(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])"))
    for tok in FORBIDDEN_TOKENS
]


def find_forbidden_token(code: str) -> str | None:
    """Return the first forbidden token found as a whole word, or None."""
    for tok, pat in _PATTERNS:
        if pat.search(code):
            return tok
    return None
