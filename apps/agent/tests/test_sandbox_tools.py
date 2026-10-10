"""run_python -> attachment, create_tool -> row, run_tool permissions, and sandbox_runs logging."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage

from conftest import caller_for, make_service, text_of
from fake_mcp import MEDIA
from yearbook_agent import ids
from yearbook_agent.testing.fake_model import ScriptedChatModel, present

pytestmark = pytest.mark.integration

PNG_CODE = """
import json, struct, zlib
def png(w, h):
    raw = b''.join(b'\\x00' + b'\\xff\\x00\\x00' * w for _ in range(h))
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
inp = json.load(open('/work/inputs.json'))
open('/work/out/chart.png', 'wb').write(png(40, 20))
print(json.dumps({'total': sum(inp['values'])}))
"""


async def test_run_python_produces_attachment_and_logs_run(settings, db, rows, sandbox):
    planner = ScriptedChatModel(
        script=[
            [
                (
                    "run_python",
                    {"code": PNG_CODE, "inputs": {"values": [1, 2, 3]}, "media_ids": [MEDIA[0]]},
                )
            ],
            [present("Chart", kind="stat", title="Total", value="6")],
        ]
    )
    svc = make_service(settings, db, planner)
    resp = await svc.message("chart it", None, None, caller_for(rows))
    assert resp.result.kind == "stat"
    assert len(resp.attachments) == 1
    att = resp.attachments[0]
    assert (
        att.name == "chart.png" and att.mime == "image/png" and (att.width, att.height) == (40, 20)
    )
    assert att.url.startswith(f"memory://memory/agent/{resp.turn_id}/chart.png")
    assert f"agent/{resp.turn_id}/chart.png" in svc.storage.objects
    # the model saw stdout
    out = json.loads(text_of(next(m for m in planner.calls[1] if isinstance(m, ToolMessage))))
    assert json.loads(out["stdout"]) == {"total": 6} and out["files"] == ["chart.png"]
    # media ids were resolved to files through describe_media (not in entities yet)
    assert sandbox.runs[-1]["files"][0]["name"].startswith(MEDIA[0])
    assert sandbox.runs[-1]["files"][0]["url"].startswith("http://public.test/v/")
    async with db.pool.connection() as conn:
        run = await (
            await conn.execute(
                "select * from sandbox_runs where turn_id = %s", (ids.decode(resp.turn_id),)
            )
        ).fetchone()
        turn = await (
            await conn.execute(
                "select attachments from agent_turns where id = %s", (ids.decode(resp.turn_id),)
            )
        ).fetchone()
    assert run["exit_code"] == 0 and run["actor"] == rows.user_id and len(run["code_sha256"]) == 32
    assert run["duration_ms"] >= 0 and run["stdout_bytes"] > 0
    assert turn["attachments"][0]["name"] == "chart.png"


async def test_run_python_failure_is_reported_to_model(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [("run_python", {"code": "raise SystemExit(3)"})],
            [present("x", kind="empty", title="Could not compute")],
        ]
    )
    resp = await make_service(settings, db, planner).message("x", None, None, caller_for(rows))
    out = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert '"exit_code": 3' in text_of(out) and resp.attachments == []


async def test_create_tool_inserts_unapproved_row(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [
                (
                    "create_tool",
                    {
                        "name": "count_values",
                        "description": "Sums values",
                        "params_schema": {
                            "type": "object",
                            "properties": {"values": {"type": "array"}},
                        },
                        "code": "import json; print(sum(json.load(open('/work/inputs.json'))['values']))",
                    },
                )
            ],
            [present("Saved", kind="stat", title="Tool saved", value="count_values")],
        ]
    )
    await make_service(settings, db, planner).message("save a tool", None, None, caller_for(rows))
    out = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert '"command_id"' in text_of(out)
    async with db.pool.connection() as conn:
        row = await (
            await conn.execute(
                "select * from saved_commands where owner = %s and name = 'count_values'",
                (rows.user_id,),
            )
        ).fetchone()
    assert (
        row["kind"] == "python" and row["created_by_agent"] is True and row["approved_at"] is None
    )
    assert (
        row["scope"] == "event"
        and row["event_id"] == rows.event_id
        and row["code"].startswith("import json")
    )
    assert row["params"]["properties"]["values"]["type"] == "array"


async def test_create_tool_rejects_bad_name(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [
                (
                    "create_tool",
                    {
                        "name": "Bad Name!",
                        "description": "d",
                        "params_schema": {},
                        "code": "print(1)",
                    },
                )
            ],
        ]
    )
    await make_service(settings, db, planner).message("x", None, None, caller_for(rows))
    out = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert "snake_case" in text_of(out)


async def _insert_tool(
    db, owner: bytes, event_id: bytes | None, *, shared: bool, approved: bool, code="print(42)"
):
    return await db.insert_saved_command(
        owner=owner,
        scope="event" if event_id else "global",
        event_id=event_id,
        name="answer",
        label="Answer",
        description="prints 42",
        params={},
        kind="python",
        code=code,
        created_by_agent=True,
        approved=approved,
    )


@pytest.mark.parametrize(
    ("shared", "approved", "same_event", "allowed"),
    [
        (False, False, True, False),  # someone else's private, unapproved tool
        (True, False, True, False),  # shared but not approved yet
        (True, True, False, False),  # approved and shared, but another event
        (True, True, True, True),  # approved and shared in this event
    ],
)
async def test_run_tool_permissions_for_other_actor(
    settings, db, rows, shared, approved, same_event, allowed
):
    other = ids.new_id()
    row = await _insert_tool(
        db, other, rows.event_id if same_event else None, shared=shared, approved=approved
    )
    try:
        if shared:
            async with db.pool.connection() as conn:
                await conn.execute(
                    "update saved_commands set shared = true where id = %s", (row.id,)
                )
        planner = ScriptedChatModel(
            script=[[("run_tool", {"command_id": ids.encode(row.id), "params": {}})]]
        )
        await make_service(settings, db, planner).message("run it", None, None, caller_for(rows))
        out = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
        fresh = await db.get_saved_command(row.id)
        if allowed:
            assert '"stdout": "42' in text_of(out) and fresh.run_count == 1
        else:
            assert "not allowed" in text_of(out) and fresh.run_count == 0
    finally:
        async with db.pool.connection() as conn:
            await conn.execute("delete from saved_commands where id = %s", (row.id,))
            await conn.execute("delete from sandbox_runs where actor = %s", (other,))


async def test_owner_runs_own_unapproved_tool_with_params(settings, db, rows):
    row = await _insert_tool(
        db,
        rows.user_id,
        rows.event_id,
        shared=False,
        approved=False,
        code="import json; print(json.load(open('/work/inputs.json'))['n'] * 2)",
    )
    planner = ScriptedChatModel(
        script=[
            [("run_tool", {"command_id": ids.encode(row.id), "params": {"n": 21}})],
            [present("Ran", kind="stat", title="Answer", value="42")],
        ]
    )
    await make_service(settings, db, planner).message("run", None, None, caller_for(rows))
    out = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert '"stdout": "42' in text_of(out)
    fresh = await db.get_saved_command(row.id)
    assert fresh.run_count == 1
    async with db.pool.connection() as conn:
        n = await (
            await conn.execute(
                "select count(*) n from sandbox_runs where command_id = %s", (row.id,)
            )
        ).fetchone()
    assert n["n"] == 1
