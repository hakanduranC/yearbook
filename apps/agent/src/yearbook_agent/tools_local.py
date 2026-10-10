"""Tools that live in this service rather than behind MCP: `present` (intercepted by the graph,
never executed), and the sandbox trio `run_python`, `create_tool`, `run_tool`."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from . import ids
from .entities import parse_tool_output
from .result import PresentDraft
from .sandbox import SandboxClient, SandboxError, SandboxResult
from .storage import image_size, mime_for
from .turn import TurnContext

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
MAX_CODE_LINES = 200


class PresentArgs(BaseModel):
    """Deliver the answer. This is the only thing the user sees; call it exactly once, last."""

    model_config = ConfigDict(extra="forbid")
    understood: str = Field(
        description="One short line in the answer language restating the request"
    )
    result: PresentDraft = Field(
        description="The structured result the UI renders, discriminated on kind"
    )


class RunPythonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(
        description="Python 3.12 program (numpy, pandas, pillow, matplotlib). Reads "
        "/work/inputs.json, writes files to /work/out, prints a JSON result."
    )
    inputs: dict[str, Any] | None = Field(default=None, description="Written to /work/inputs.json")
    media_ids: list[str] | None = Field(
        default=None, description="Media to make available under /work/in/"
    )


class CreateToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="snake_case, 3-40 characters")
    description: str = Field(max_length=300)
    params_schema: dict[str, Any] = Field(description="JSON schema of the inputs the tool expects")
    code: str = Field(description="The program; inputs arrive in /work/inputs.json")


class RunToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    params: dict[str, Any] | None = None


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def can_run_saved_tool(row: Any, actor: bytes, event_id: bytes | None) -> bool:
    """Owner always (also unapproved); otherwise only approved + shared tools of the same event."""
    if row.owner == actor:
        return True
    return bool(
        row.shared
        and row.approved_at is not None
        and event_id is not None
        and row.event_id == event_id
    )


async def _media_files(ctx: TurnContext, media_ids: list[str]) -> list[dict[str, str]]:
    urls = dict(ctx.entities.get("media_urls", {}))
    missing = [m for m in media_ids if m not in urls]
    describe = ctx.tools.get("describe_media")
    for mid in missing[:20]:
        if describe is None or not ids.is_id(mid):
            continue
        try:
            msg = await describe.ainvoke(
                {
                    "name": "describe_media",
                    "args": {"media_id": mid},
                    "id": f"hydrate_{mid}",
                    "type": "tool_call",
                }
            )
        except Exception:
            continue
        data = parse_tool_output(getattr(msg, "content", msg), getattr(msg, "artifact", None))
        if isinstance(data, dict):
            v = data.get("variants") or {}
            url = v.get("large") or v.get("medium") or v.get("small")
            if url:
                urls[mid] = url
    return [{"name": f"{m}{_ext(urls[m])}", "url": urls[m]} for m in media_ids if m in urls]


def _ext(url: str) -> str:
    path = url.split("?", 1)[0]
    return path[path.rfind(".") :] if "." in path.rsplit("/", 1)[-1] else ""


async def _execute(
    ctx: TurnContext, code: str, inputs: Any, files: list[dict[str, str]], command_id: bytes | None
) -> str:
    sandbox: SandboxClient = ctx.sandbox
    if len(code.splitlines()) > MAX_CODE_LINES:
        return json.dumps({"error": f"program longer than {MAX_CODE_LINES} lines"})
    t0 = time.monotonic()
    error: str | None = None
    result: SandboxResult | None = None
    try:
        result = await sandbox.run(code, inputs, files, timeout_s=ctx.settings.sandbox_timeout_s)
    except SandboxError as exc:
        error = str(exc)
    duration_ms = int((time.monotonic() - t0) * 1000)
    if ctx.db is not None:
        await ctx.db.insert_sandbox_run(
            turn_id=ctx.turn_id,
            command_id=command_id,
            actor=ctx.actor,
            code_sha256=SandboxClient.sha256(code),
            exit_code=result.exit_code if result else None,
            duration_ms=result.duration_ms or duration_ms if result else duration_ms,
            stdout_bytes=len(result.stdout.encode()) if result else 0,
            error=error
            if error
            else (_truncate(result.stderr, 500) if result and result.exit_code else None),
        )
    if error or result is None:
        return json.dumps({"error": error or "sandbox failed"})
    names = []
    for f in result.files:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)[:80]
        key = f"agent/{ids.encode(ctx.turn_id)}/{name}"
        mime = mime_for(name)
        try:
            await ctx.storage.put(key, f.data, mime)
            url = await ctx.storage.presigned_get(key, 3600)
        except Exception as exc:
            return json.dumps({"error": f"could not store {name}: {exc}"})
        if not url:
            continue
        att: dict[str, Any] = {"name": name, "url": url, "mime": mime, "key": key}
        size = image_size(f.data)
        if size:
            att["width"], att["height"] = size
        ctx.attachments.append(att)
        names.append(name)
    return json.dumps(
        {
            "exit_code": result.exit_code,
            "stdout": _truncate(result.stdout, 4000),
            "stderr": _truncate(result.stderr, 1000),
            "files": names,
            "note": "files are attached to the answer automatically" if names else None,
        }
    )


def build_local_tools(ctx: TurnContext) -> list[BaseTool]:
    async def present(understood: str, result: Any) -> str:  # never executed; the graph intercepts
        return "ok"

    async def run_python(
        code: str, inputs: dict[str, Any] | None = None, media_ids: list[str] | None = None
    ) -> str:
        files = await _media_files(ctx, media_ids or [])
        return await _execute(ctx, code, inputs, files, None)

    async def create_tool(
        name: str, description: str, params_schema: dict[str, Any], code: str
    ) -> str:
        if not NAME_RE.match(name):
            return json.dumps({"error": "name must be snake_case, 3-40 characters"})
        if len(code.splitlines()) > MAX_CODE_LINES:
            return json.dumps({"error": f"program longer than {MAX_CODE_LINES} lines"})
        if ctx.db is None:
            return json.dumps({"error": "no database; cannot save tools"})
        row = await ctx.db.insert_saved_command(
            owner=ctx.actor,
            scope="event" if ctx.event_id else "global",
            event_id=ctx.event_id,
            name=name,
            label=name.replace("_", " ").capitalize()[:30],
            description=description,
            params=params_schema,
            kind="python",
            code=code,
            created_by_agent=True,
            approved=False,
        )
        return json.dumps(
            {
                "command_id": ids.encode(row.id),
                "name": row.name,
                "note": "saved; the owner can approve it in the UI, you can run it now",
            }
        )

    async def run_tool(command_id: str, params: dict[str, Any] | None = None) -> str:
        if ctx.db is None or not ids.is_id(command_id):
            return json.dumps({"error": "unknown command"})
        row = await ctx.db.get_saved_command(ids.decode(command_id))
        if row is None or row.kind != "python" or not row.code:
            return json.dumps({"error": "unknown command"})
        if not can_run_saved_tool(row, ctx.actor, ctx.event_id):
            return json.dumps({"error": "not allowed to run this tool"})
        out = await _execute(ctx, row.code, params or {}, [], row.id)
        await ctx.db.bump_saved_command(row.id)
        return out

    return [
        StructuredTool.from_function(
            coroutine=present,
            name="present",
            args_schema=PresentArgs,
            description=PresentArgs.__doc__ or "",
        ),
        StructuredTool.from_function(
            coroutine=run_python,
            name="run_python",
            args_schema=RunPythonArgs,
            description="Run a short Python program in the sandbox for computation "
            "or image work the other tools cannot do. Output files are attached.",
        ),
        StructuredTool.from_function(
            coroutine=create_tool,
            name="create_tool",
            args_schema=CreateToolArgs,
            description="Save a reusable Python program as a tool of the viewer.",
        ),
        StructuredTool.from_function(
            coroutine=run_tool,
            name="run_tool",
            args_schema=RunToolArgs,
            description="Run a saved Python tool by command id with params.",
        ),
    ]
