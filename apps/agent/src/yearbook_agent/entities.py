"""Collect persons, albums and media URLs from tool results so `present` can be hydrated and
`run_python` can hand media files to the sandbox without a second lookup."""

from __future__ import annotations

import json
from typing import Any

from . import ids

ALBUM_KINDS = {"highlights", "manual", "agent"}


def parse_tool_output(content: Any, artifact: Any = None) -> Any:
    if isinstance(artifact, dict) and artifact.get("structured_content") is not None:
        return artifact["structured_content"]
    if isinstance(content, list):
        texts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in content]
        content = "\n".join(texts)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


def merge_entities(
    a: dict[str, dict[str, Any]] | None, b: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (a or {}).items()}
    for k, v in (b or {}).items():
        out.setdefault(k, {}).update(v)
    return out


def collect(data: Any) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {"persons": {}, "albums": {}, "media_urls": {}}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            nid = node.get("id")
            if ids.is_id(nid):
                variants = node.get("variants")
                if isinstance(variants, dict):
                    url = variants.get("large") or variants.get("medium") or variants.get("small")
                    if url:
                        found["media_urls"][nid] = url
                elif "face_count" in node or "is_me" in node:
                    found["persons"][nid] = node
                elif node.get("kind") in ALBUM_KINDS and "title" in node:
                    found["albums"][nid] = node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return {k: v for k, v in found.items() if v}
