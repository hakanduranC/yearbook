"""Integration: the real graph with the real Postgres checkpointer, the fake MCP server over
streamable HTTP and a scripted model."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from conftest import caller_for, make_service, text_of
from fake_mcp import MEDIA, P_ANNA, P_ANNA2, P_BEN
from yearbook_agent import ids
from yearbook_agent.prompts import FORCED_TITLE
from yearbook_agent.testing.fake_model import ScriptedChatModel, present

pytestmark = pytest.mark.integration


async def test_resolve_search_present_media(settings, db, rows, mcp):
    mcp.recorder.reset()
    planner = ScriptedChatModel(
        script=[
            [("resolve_people", {"names": ["Anna"]})],
            [("search_media", {"me": True, "people_all": [P_ANNA], "limit": 60})],
            [
                present(
                    "Photos with you and Anna",
                    kind="media",
                    title="You and Anna",
                    media_ids=MEDIA[:2],
                    group_by="time",
                    refine=[{"label": "Only the best", "text": "the best of me and Anna"}],
                )
            ],
        ]
    )
    svc = make_service(settings, db, planner)
    resp = await svc.message(
        "photos of me and Anna", None, None, caller_for(rows, token="sess-abc")
    )

    assert resp.result.kind == "media" and resp.result.media_ids == MEDIA[:2]
    assert resp.understood == "Photos with you and Anna"
    assert resp.saveable is True
    assert [c.label for c in resp.suggestions] == ["Only the best"]
    assert ids.is_id(resp.conversation_id) and ids.is_id(resp.turn_id)
    # the user's token and the event slug were forwarded on every MCP call
    assert [c[0] for c in mcp.recorder.calls] == ["resolve_people", "search_media"]
    assert all(h["authorization"] == "Bearer sess-abc" for h in mcp.recorder.headers)
    assert all(h["x-event-slug"] == rows.slug for h in mcp.recorder.headers)
    # present and the local tools were offered next to the MCP tools
    assert {"present", "run_python", "create_tool", "run_tool", "search_media"} <= set(
        planner.bound_tools
    )
    # system prompt carries the scope
    system = planner.calls[0][0].content
    assert (
        'Event "Sommerfest"' in system
        and "Viewer: Hakan (user)" in system
        and "has claimed" in system
    )

    async with db.pool.connection() as conn:
        turn = await (
            await conn.execute(
                "select * from agent_turns where id = %s", (ids.decode(resp.turn_id),)
            )
        ).fetchone()
        conv = await (
            await conn.execute(
                "select * from agent_conversations where id = %s",
                (ids.decode(resp.conversation_id),),
            )
        ).fetchone()
    assert turn["tools_used"] == ["resolve_people", "search_media"]
    assert turn["result_kind"] == "media" and turn["understood"] == resp.understood
    assert turn["final_call"]["name"] == "search_media" and turn["user_id"] == rows.user_id
    assert turn["event_id"] == rows.event_id and turn["latency_ms"] >= 0
    assert conv["provider_ref"] == resp.conversation_id and conv["expires_at"] is not None


async def test_follow_up_resumes_thread_and_expired_conversation_is_replaced(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [present("Photos of you", kind="media", title="You", media_ids=[MEDIA[2]])],
            [present("Only videos of you", kind="empty", title="No videos of you")],
        ]
    )
    svc = make_service(settings, db, planner)
    first = await svc.message("photos of me", None, None, caller_for(rows))
    second = await svc.message("only videos", None, first.conversation_id, caller_for(rows))
    assert second.conversation_id == first.conversation_id
    history = [m.content for m in planner.calls[1] if isinstance(m, HumanMessage)]
    assert history == ["photos of me", "only videos"]  # checkpointed messages were restored

    async with db.pool.connection() as conn:
        await conn.execute(
            "update agent_conversations set expires_at = now() - interval '1 minute' where id = %s",
            (ids.decode(first.conversation_id),),
        )
    third = await svc.message("again", None, first.conversation_id, caller_for(rows))
    assert third.conversation_id != first.conversation_id
    assert [m.content for m in planner.calls[2] if isinstance(m, HumanMessage)] == ["again"]


async def test_run_query_path_people_result(settings, db, rows):
    sql = "select p.id, p.display_name, count(*) n from v_faces f join v_persons p on p.id = f.person_id group by 1, 2 order by n desc"
    planner = ScriptedChatModel(
        script=[
            [("run_query", {"sql": sql})],
            [
                present(
                    "Who you appear with most",
                    kind="people",
                    title="Most often with you",
                    person_ids=[P_ANNA, P_BEN],
                )
            ],
        ]
    )
    resp = await make_service(settings, db, planner).message(
        "who did I spend the most time with", None, None, caller_for(rows)
    )
    assert resp.result.kind == "people"
    assert [p.id for p in resp.result.persons] == [P_ANNA, P_BEN]
    assert resp.saveable is True
    tool_msg = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert "Anna" in text_of(tool_msg)  # rows came back from the fake


async def test_run_query_error_returns_to_model(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [("run_query", {"sql": "select * from v_nonexistent"})],
            [("run_query", {"sql": "select count(*) from v_media"})],
            [present("Count", kind="stat", title="Photos", value="37")],
        ]
    )
    resp = await make_service(settings, db, planner).message(
        "how many", None, None, caller_for(rows)
    )
    assert resp.result.kind == "stat"
    err = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert err.status == "error" and "v_nonexistent" in text_of(err)


async def test_clarify_path(settings, db, rows, mcp_ambiguous):
    planner = ScriptedChatModel(
        script=[
            [("resolve_people", {"names": ["Anna"]})],
            [
                present(
                    "Fotos mit Anna",
                    kind="clarify",
                    question="Welche Anna meinst du?",
                    options=["Anna M.", "Anna K."],
                )
            ],
        ]
    )
    svc = make_service(settings, db, planner, mcp_url=mcp_ambiguous.url)
    resp = await svc.message("Fotos mit Anna", None, None, caller_for(rows, locale="de"))
    assert resp.result.kind == "clarify" and resp.result.options == ["Anna M.", "Anna K."]
    assert resp.saveable is False
    assert resp.suggestions and resp.suggestions[0].label == "Fotos von mir"  # locale defaults
    tool_msg = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert P_ANNA2 in text_of(tool_msg)


async def test_six_round_guard_forces_empty(settings, db, rows):
    planner = ScriptedChatModel(script=[[("event_stats", {})] for _ in range(10)])
    resp = await make_service(settings, db, planner).message(
        "loop", None, None, caller_for(rows, locale="tr")
    )
    assert resp.result.kind == "empty" and resp.result.title == FORCED_TITLE["tr"]
    assert len(planner.calls) == 6  # the seventh model call never happens
    async with db.pool.connection() as conn:
        turn = await (
            await conn.execute(
                "select tools_used from agent_turns where id = %s", (ids.decode(resp.turn_id),)
            )
        ).fetchone()
    assert turn["tools_used"] == ["event_stats"] * 6


async def test_wall_clock_guard(settings, db, rows):
    settings.wall_clock_s = 0.0
    planner = ScriptedChatModel(script=[[("event_stats", {})]])
    resp = await make_service(settings, db, planner).message(
        "slow", None, None, caller_for(rows, locale="de")
    )
    assert resp.result.kind == "empty" and resp.result.title == FORCED_TITLE["de"]
    assert planner.calls == []


async def test_invalid_present_is_rejected_then_accepted(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [present("x", kind="media", title="Bad", media_ids=["not-an-id"])],
            [present("Photos", kind="media", title="Good", media_ids=[MEDIA[0]])],
        ]
    )
    resp = await make_service(settings, db, planner).message("photos", None, None, caller_for(rows))
    assert resp.result.title == "Good"
    rejected = next(m for m in planner.calls[1] if isinstance(m, ToolMessage))
    assert rejected.status == "error" and text_of(rejected).startswith("present rejected")


async def test_prose_answer_is_nudged_once(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            "I found twelve photos of you.",
            [present("Photos of you", kind="media", title="You", media_ids=[MEDIA[0]])],
        ]
    )
    resp = await make_service(settings, db, planner).message(
        "photos of me", None, None, caller_for(rows)
    )
    assert resp.result.kind == "media"
    assert any(
        "call `present`" in m.content for m in planner.calls[1] if isinstance(m, HumanMessage)
    )


async def test_prose_twice_becomes_empty_with_the_text(settings, db, rows):
    planner = ScriptedChatModel(script=["Nothing found.", "Still nothing."])
    resp = await make_service(settings, db, planner).message("x", None, None, caller_for(rows))
    assert resp.result.kind == "empty" and resp.result.title == "Still nothing."


async def test_album_result_hydrated_from_create_album(settings, db, rows):
    planner = ScriptedChatModel(
        script=[
            [("search_media", {"text": "cake", "age_max": 12})],
            [("create_album", {"title": "Kids at the cake", "media_ids": MEDIA[:3]})],
            [present("Album", kind="album", album_id=ids.encode(b"album-00000000-1"))],
        ]
    )
    resp = await make_service(settings, db, planner).message(
        "album of kids", None, None, caller_for(rows)
    )
    assert resp.result.kind == "album" and resp.result.album.title == "Kids at the cake"
    assert resp.result.album.count == 3 and resp.saveable is False


async def test_global_scope_without_event(settings, db, rows, mcp):
    mcp.recorder.reset()
    planner = ScriptedChatModel(
        script=[[("event_stats", {})], [present("Stats", kind="stat", title="Photos", value="412")]]
    )
    resp = await make_service(settings, db, planner).message(
        "how many photos", None, None, caller_for(rows, event=False)
    )
    assert resp.result.kind == "stat"
    assert "All of the viewer's events" in planner.calls[0][0].content
    assert mcp.recorder.headers[0]["x-event-slug"] == ""


async def test_unknown_event_slug(settings, db, rows):
    from yearbook_agent.service import ServiceError

    with pytest.raises(ServiceError) as err:
        await make_service(settings, db, ScriptedChatModel()).message(
            "x", "no-such-event", None, caller_for(rows)
        )
    assert err.value.status == 404
