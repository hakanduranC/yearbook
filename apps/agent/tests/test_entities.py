from fake_mcp import ALBUM, MEDIA, P_ANNA, PERSONS
from yearbook_agent.entities import collect, merge_entities, parse_tool_output


def test_collect_persons_albums_and_media_urls():
    data = {
        "matches": [{"query": "Anna", "persons": [PERSONS[P_ANNA]]}],
        "items": [{"id": MEDIA[0], "variants": {"thumb": "t", "medium": "http://x/m.webp"}}],
        "album": {"id": ALBUM, "title": "A", "kind": "agent", "count": 1},
    }
    found = collect(data)
    assert found["persons"][P_ANNA]["display_name"] == "Anna"
    assert found["media_urls"][MEDIA[0]] == "http://x/m.webp"
    assert found["albums"][ALBUM]["title"] == "A"


def test_merge_and_parse():
    merged = merge_entities(
        {"persons": {"a": {"id": "a"}}}, {"persons": {"b": {"id": "b"}}, "albums": {}}
    )
    assert set(merged["persons"]) == {"a", "b"}
    assert parse_tool_output('{"x": 1}') == {"x": 1}
    assert parse_tool_output("plain") == "plain"
    assert parse_tool_output([{"type": "text", "text": '{"y": 2}'}]) == {"y": 2}
    assert parse_tool_output("ignored", {"structured_content": {"z": 3}}) == {"z": 3}
