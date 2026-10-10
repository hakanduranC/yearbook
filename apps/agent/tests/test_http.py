"""HTTP surface: 503 without a key, the proxied endpoints with a scripted provider."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from conftest import headers_for, make_service
from fake_mcp import MEDIA
from yearbook_agent import ids
from yearbook_agent.app import create_app
from yearbook_agent.commands import SavedCommandDraft
from yearbook_agent.config import Settings
from yearbook_agent.testing.fake_model import ScriptedChatModel, present


def test_503_without_key_and_health():
    settings = Settings(OPENAI_API_KEY=None, DATABASE_URL=None, MCP_URL="http://127.0.0.1:1/mcp")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {
            "ok": True,
            "configured": False,
            "model": None,
            "db": False,
        }
        r = client.post(
            "/agent/messages",
            json={"text": "photos of me"},
            headers={"X-Actor": "A" * 22, "X-Actor-Kind": "user", "X-Session-Token": "t"},
        )
        assert r.status_code == 503
        assert r.json() == {"error": {"code": "internal", "message": "agent_not_configured"}}
        r = client.post(
            "/agent/commands",
            json={"turn_id": "A" * 22, "label": "x"},
            headers={"X-Actor": "A" * 22, "X-Session-Token": "t"},
        )
        assert r.status_code == 503 and r.json()["error"]["message"] == "agent_not_configured"
        r = client.post(
            "/describe", json={"media_id": "A" * 22, "image_url": "http://x/y.webp", "locale": "de"}
        )
        assert r.status_code == 503 and r.json()["error"]["message"] == "agent_not_configured"


@pytest.fixture
async def client(settings, db):
    draft = SavedCommandDraft(
        name="me_in_the_evening",
        description="Photos of you in the evening",
        kind="search",
        params={"type": "object", "properties": {"day_part": {"type": "string"}}},
        search_args={"me": True, "day_part": ":day_part"},
    )
    planner = ScriptedChatModel(
        script=[
            [("search_media", {"me": True, "day_part": "evening"})],
            [
                present(
                    "Photos of you in the evening",
                    kind="media",
                    title="Evening",
                    media_ids=MEDIA[:2],
                )
            ],
        ]
    )
    svc = make_service(settings, db, planner, structured=draft)
    app = create_app(settings, service=svc)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://agent") as c,
    ):
        yield c


@pytest.mark.integration
async def test_messages_then_save_command_then_describe(client, rows, db):
    r = await client.post(
        "/agent/messages",
        json={"text": "photos of me in the evening", "event_slug": rows.slug},
        headers=headers_for(rows, locale="en"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "conversation_id",
        "turn_id",
        "understood",
        "result",
        "suggestions",
        "saveable",
        "attachments",
    }
    assert body["result"]["kind"] == "media" and body["saveable"] is True

    r = await client.post(
        "/agent/commands",
        json={"turn_id": body["turn_id"], "label": "Evening me"},
        headers=headers_for(rows),
    )
    assert r.status_code == 201, r.text
    cmd = r.json()
    assert (
        cmd["name"] == "me_in_the_evening"
        and cmd["label"] == "Evening me"
        and cmd["kind"] == "search"
    )
    assert cmd["scope"] == "event" and cmd["event_slug"] == rows.slug and cmd["shared"] is False
    assert cmd["params"]["properties"]["day_part"]["type"] == "string"
    async with db.pool.connection() as conn:
        row = await (
            await conn.execute(
                "select * from saved_commands where id = %s", (ids.decode(cmd["id"]),)
            )
        ).fetchone()
    assert row["approved_at"] is not None and row["owner"] == rows.user_id
    assert row["search_args"] == {"me": True, "day_part": ":day_part"} and row["sql_template"] == ""

    # a turn that is not saveable
    r = await client.post(
        "/agent/commands",
        json={"turn_id": ids.encode(ids.new_id()), "label": "x"},
        headers=headers_for(rows),
    )
    assert r.status_code == 404

    r = await client.post(
        "/describe",
        json={
            "media_id": MEDIA[0],
            "image_url": "http://public.test/v/x/large.webp",
            "locale": "en",
        },
    )
    assert r.status_code == 200 and r.json() == {
        "text": "A table outdoors with cake and three people."
    }


@pytest.mark.integration
async def test_bad_headers(client, rows):
    r = await client.post(
        "/agent/messages", json={"text": "x"}, headers={"X-Actor": "nope", "X-Session-Token": "t"}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    r = await client.post("/agent/messages", json={"text": "x"}, headers={"X-Actor": rows.actor})
    assert r.status_code == 400 and "X-Session-Token" in r.json()["error"]["message"]


@pytest.mark.integration
async def test_run_python_command_endpoint(client, rows, db):
    row = await db.insert_saved_command(
        owner=rows.user_id,
        scope="event",
        event_id=rows.event_id,
        name="double",
        label="Double",
        description="doubles n",
        params={"type": "object"},
        kind="python",
        created_by_agent=True,
        approved=False,
        code="import json; print(json.dumps({'kind': 'stat', 'title': 'Double', 'value': str(json.load(open('/work/inputs.json'))['n'] * 2)}))",
    )
    cid = ids.encode(row.id)
    r = await client.post(
        f"/agent/commands/{cid}/run", json={"params": {"n": 4}}, headers=headers_for(rows)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == {
        "kind": "stat",
        "title": "Double",
        "value": "4" * 0 + "8",
        "detail": None,
        "media_ids": [],
    }
    assert body["saveable"] is False and ids.is_id(body["turn_id"])
    assert (await db.get_saved_command(row.id)).run_count == 1

    # another actor may not run a private tool
    other = {**headers_for(rows), "X-Actor": ids.encode(ids.new_id())}
    r = await client.post(f"/agent/commands/{cid}/run", json={}, headers=other)
    assert r.status_code == 403

    # sql kinds are not run here
    sql_row = await db.insert_saved_command(
        owner=rows.user_id,
        scope="global",
        event_id=None,
        name="q",
        label="Q",
        description="d",
        params={},
        kind="sql",
        sql_template="select 1",
    )
    r = await client.post(
        f"/agent/commands/{ids.encode(sql_row.id)}/run", json={}, headers=headers_for(rows)
    )
    assert r.status_code == 400
    r = await client.post(
        f"/agent/commands/{ids.encode(ids.new_id())}/run", json={}, headers=headers_for(rows)
    )
    assert r.status_code == 404
