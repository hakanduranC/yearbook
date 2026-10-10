"""Save-as-chip eligibility: the turn's final tool call was `run_query`, or a `search_media`
with at least two structured arguments (free text, limit and order do not count)."""

from __future__ import annotations

from typing import Any

UNSTRUCTURED = {"text", "limit", "order_by"}


def structured_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in args.items()
        if k not in UNSTRUCTURED and v is not None and v != "" and v != [] and v is not False
    }


def is_saveable(final_call: dict[str, Any] | None) -> bool:
    if not final_call:
        return False
    name = final_call.get("name")
    args = final_call.get("args") or {}
    if name == "run_query":
        return bool(args.get("sql"))
    if name == "search_media":
        return len(structured_args(args)) >= 2
    return False
