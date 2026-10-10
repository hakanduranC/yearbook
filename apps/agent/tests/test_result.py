import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from fake_mcp import ALBUM, MEDIA, P_ANNA, PERSONS
from yearbook_agent.result import (
    AgentResponse,
    PresentCall,
    format_validation_error,
    to_wire,
    validate_present,
)


def test_media_result_validates():
    call = validate_present(
        {
            "understood": "x",
            "result": {
                "kind": "media",
                "title": "T",
                "media_ids": MEDIA[:2],
                "group_by": "time",
                "refine": [{"label": "a", "text": "b"}],
            },
        }
    )
    assert call.result.kind == "media"
    wire, chips = to_wire(call, {})
    assert wire.media_ids == MEDIA[:2] and chips[0].label == "a"


@pytest.mark.parametrize(
    "args",
    [
        {"kind": "media", "title": "T", "media_ids": ["short"]},
        {"kind": "media", "title": "", "media_ids": []},
        {"kind": "people", "title": "T"},
        {"kind": "stat", "title": "T"},
        {"kind": "album", "album_id": "nope"},
        {"kind": "clarify", "question": "Q", "options": ["one"]},
        {"kind": "empty"},
        {"kind": "unknown", "title": "T"},
        {"kind": "media", "title": "T", "media_ids": [], "extra": 1},
    ],
)
def test_invalid_results_are_rejected(args):
    with pytest.raises(ValidationError) as err:
        validate_present({"understood": "x", "result": args})
    assert format_validation_error(err.value).startswith("present rejected: ")


def test_understood_required():
    with pytest.raises(ValidationError):
        validate_present({"result": {"kind": "empty", "title": "T"}})


def test_people_hydrated_from_entities():
    call = validate_present(
        {
            "understood": "x",
            "result": {"kind": "people", "title": "P", "person_ids": [P_ANNA, MEDIA[0]]},
        }
    )
    wire, _ = to_wire(call, {"persons": {P_ANNA: PERSONS[P_ANNA]}})
    assert wire.persons[0].display_name == "Anna" and wire.persons[0].face_count == 22
    assert (
        wire.persons[1].id == MEDIA[0] and wire.persons[1].face_count == 0
    )  # unseen: minimal shape


def test_album_hydrated_and_stat_kept():
    call = validate_present({"understood": "x", "result": {"kind": "album", "album_id": ALBUM}})
    wire, _ = to_wire(
        call, {"albums": {ALBUM: {"id": ALBUM, "title": "Kids", "kind": "agent", "count": 3}}}
    )
    assert wire.album.title == "Kids" and wire.album.count == 3
    call = validate_present(
        {"understood": "x", "result": {"kind": "stat", "title": "N", "value": "37"}}
    )
    wire, _ = to_wire(call, {})
    assert wire.value == "37"


def test_agent_response_contract_shape():
    call = PresentCall.model_validate(
        {
            "understood": "x",
            "result": {
                "kind": "empty",
                "title": "Nothing",
                "suggestions": [{"label": "l", "text": "t"}],
            },
        }
    )
    wire, chips = to_wire(call, {})
    resp = AgentResponse(
        conversation_id="A" * 22,
        turn_id="B" * 22,
        understood=call.understood,
        result=wire,
        suggestions=chips,
        saveable=False,
    )
    data = resp.model_dump()
    assert set(data) == {
        "conversation_id",
        "turn_id",
        "understood",
        "result",
        "suggestions",
        "saveable",
        "attachments",
    }
    assert data["result"] == {"kind": "empty", "title": "Nothing"}


def test_present_tool_schema_is_openai_compatible():
    from yearbook_agent.tools_local import PresentArgs

    schema = convert_to_openai_tool(PresentArgs)
    params = schema["function"]["parameters"]
    assert "understood" in params["properties"] and "result" in params["properties"]
    assert "kind" in str(params)
