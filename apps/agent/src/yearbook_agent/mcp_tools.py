"""Tools from the Go API's MCP server, loaded per request with the viewer's own session token.

The tool *schemas* are cached per process for 60 s (keyed by token so saved commands exposed to
one viewer never show up for another); the tool *objects* are rebuilt per request because each
one carries the request's headers. The Go side enforces visibility: we only pass the token on.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.sessions import StreamableHttpConnection, create_session
from langchain_mcp_adapters.tools import _list_all_tools, convert_mcp_tool_to_langchain_tool
from mcp.types import Tool as MCPTool

# Local tools shadow anything an MCP server offers under the same name.
LOCAL_TOOL_NAMES = frozenset({"present", "run_python", "create_tool", "run_tool"})


def connection_for(url: str, token: str, event_slug: str | None) -> StreamableHttpConnection:
    headers: dict[str, Any] = {"Authorization": f"Bearer {token}"}
    if event_slug:
        headers["X-Event-Slug"] = event_slug
    return {"transport": "streamable_http", "url": url, "headers": headers, "timeout": 15}


class ToolCatalog:
    def __init__(self, url: str, ttl_s: float = 60.0) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self._cache: dict[str, tuple[float, list[MCPTool]]] = {}

    def _key(self, token: str, event_slug: str | None) -> str:
        return hashlib.sha256(f"{token}\0{event_slug or ''}".encode()).hexdigest()

    async def specs(self, token: str, event_slug: str | None) -> list[MCPTool]:
        key = self._key(token, event_slug)
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < self.ttl_s:
            return hit[1]
        conn = connection_for(self.url, token, event_slug)
        async with create_session(conn) as session:
            await session.initialize()
            specs = await _list_all_tools(session)
        specs = [t for t in specs if t.name not in LOCAL_TOOL_NAMES]
        self._cache[key] = (now, specs)
        return specs

    async def tools(self, token: str, event_slug: str | None) -> list[BaseTool]:
        specs = await self.specs(token, event_slug)
        conn = connection_for(self.url, token, event_slug)
        return [convert_mcp_tool_to_langchain_tool(None, t, connection=conn) for t in specs]

    def invalidate(self) -> None:
        self._cache.clear()
