from datetime import UTC, datetime

import pytest

from yearbook_agent.prompts import EventInfo, Scope, fewshots, render_system_prompt

EVENT = EventInfo(
    slug="sommerfest-ab12",
    title="Sommerfest",
    timezone="Europe/Berlin",
    starts_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    ends_at=None,
)
NOW = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("locale", "language", "claimed_word"),
    [
        ("de", "Deutsch", "zugeordnet"),
        ("en", "English", "claimed"),
        ("tr", "Türkçe", "sahiplendi"),
    ],
)
def test_scope_renders_in_each_locale(locale, language, claimed_word):
    scope = Scope(
        actor_kind="user",
        viewer_name="Hakan Duran",
        has_claimed_person=True,
        locale=locale,
        event=EVENT,
        now=NOW,
    )
    text = render_system_prompt(scope)
    assert f"Answer language: {language} ({locale})" in text
    assert (
        'Event "Sommerfest" (slug sommerfest-ab12), Saturday 2026-07-18 14:00' in text
    )  # event tz
    assert "Viewer: Hakan (user)" in text  # first name only
    assert claimed_word in text
    assert "Today: 2026-07-18" in text
    assert "Always finish by calling `present`" in text


def test_global_scope_and_unclaimed_guest():
    scope = Scope(
        actor_kind="guest",
        viewer_name=None,
        has_claimed_person=False,
        locale="en",
        event=None,
        now=NOW,
    )
    text = render_system_prompt(scope)
    assert "All of the viewer's events and their personal library" in text
    assert "Viewer: Guest (guest)" in text
    assert "has not claimed a person yet" in text


def test_fewshots_cover_three_locales():
    shots = fewshots()
    assert 6 <= len(shots) <= 10
    assert {s["locale"] for s in shots} == {"de", "en", "tr"}
    for s in shots:
        assert s["steps"][-1]["tool"] == "present"
    text = render_system_prompt(Scope("user", "A", True, "en", EVENT, NOW))
    assert "resolve_people" in text and "User (tr, event scope)" in text
