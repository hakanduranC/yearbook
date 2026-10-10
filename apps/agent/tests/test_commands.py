import json

import pytest
from pydantic import ValidationError

from yearbook_agent.commands import SavedCommandDraft, draft_command, draft_messages
from yearbook_agent.testing.fake_model import FakeProvider

FINAL = {"name": "search_media", "args": {"me": True, "day_part": "evening", "limit": 60}}


async def test_draft_parses_structured_output_and_coerces_kind():
    draft = SavedCommandDraft(
        name="Evening Me",
        description="Fotos von mir am Abend",
        params={"type": "object", "properties": {"day_part": {"type": "string"}}},
        kind="sql",
        sql_template="select 1",
        search_args={"me": True, "day_part": ":day_part"},
    )
    structured = FakeProvider(structured=draft).structured(SavedCommandDraft)
    out = await draft_command(structured, "Fotos von mir am Abend", "Abend", FINAL, "de")
    assert out.name == "evening_me"
    assert out.kind == "search"  # the final call decides
    assert out.search_args == {"me": True, "day_part": ":day_part"}


async def test_draft_rejects_bad_sql_template():
    draft = SavedCommandDraft(
        name="x_y", description="d", params={}, kind="sql", sql_template="delete from v_media"
    )
    structured = FakeProvider(structured=draft).structured(SavedCommandDraft)
    with pytest.raises(ValueError, match="SELECT"):
        await draft_command(
            structured, "q", "l", {"name": "run_query", "args": {"sql": "select 1"}}, "en"
        )


def test_name_validation():
    with pytest.raises(ValidationError):
        SavedCommandDraft(name="1bad", description="d", params={}, kind="search", search_args={})
    assert (
        SavedCommandDraft(
            name="With Space", description="d", params={}, kind="search", search_args={}
        ).name
        == "with_space"
    )


def test_messages_carry_turn_and_locale():
    msgs = draft_messages("photos of me", "Me", FINAL, "tr")
    assert "(tr)" in msgs[0].content
    assert json.loads(msgs[1].content)["expected_kind"] == "search"
