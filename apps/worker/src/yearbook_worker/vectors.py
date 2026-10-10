"""pgvector values as numpy arrays, whatever the driver handed back (Vector, list, text)."""

from __future__ import annotations

from typing import Any

import numpy as np


def as_array(value: Any) -> np.ndarray:
    """`vector` column value → float32 numpy array (pgvector.Vector, sequence or `[..]` text)."""
    if isinstance(value, np.ndarray):
        return value.astype(np.float32, copy=False)
    to_numpy = getattr(value, "to_numpy", None)
    if callable(to_numpy):
        return np.asarray(to_numpy(), dtype=np.float32)
    if isinstance(value, str):
        return np.asarray([float(v) for v in value.strip("[]").split(",") if v], dtype=np.float32)
    return np.asarray(value, dtype=np.float32)
