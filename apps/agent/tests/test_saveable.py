from yearbook_agent.saveable import is_saveable


def test_run_query_is_saveable():
    assert is_saveable({"name": "run_query", "args": {"sql": "select 1"}})
    assert not is_saveable({"name": "run_query", "args": {}})


def test_search_media_needs_two_structured_args():
    assert is_saveable({"name": "search_media", "args": {"me": True, "people_all": ["x"]}})
    assert is_saveable(
        {"name": "search_media", "args": {"kind": "video", "day_part": "night", "limit": 60}}
    )
    assert not is_saveable(
        {"name": "search_media", "args": {"me": True, "limit": 60, "order_by": "best"}}
    )
    assert not is_saveable({"name": "search_media", "args": {"text": "cake", "limit": 10}})
    assert not is_saveable({"name": "search_media", "args": {"text": "cake", "me": True}})
    assert not is_saveable(
        {"name": "search_media", "args": {"me": False, "people_all": [], "tags": None}}
    )


def test_other_tools_are_not_saveable():
    assert not is_saveable(None)
    assert not is_saveable({"name": "list_people", "args": {}})
    assert not is_saveable({"name": "present", "args": {"understood": "x"}})
