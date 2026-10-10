from yearbook_agent.models import ModelInfo, resolve_default_model


def m(*names: str) -> list[ModelInfo]:
    return [ModelInfo(id=n, created=i) for i, n in enumerate(names)]


def test_prefers_gpt6_over_gpt5():
    assert resolve_default_model(m("gpt-5", "gpt-5-mini", "gpt-6", "gpt-4o")) == "gpt-6"


def test_falls_back_to_newest_gpt5_when_no_gpt6():
    assert resolve_default_model(m("gpt-4.1", "gpt-5-mini", "gpt-5", "gpt-5.1", "o3")) == "gpt-5.1"


def test_skips_variants_and_prefers_non_mini():
    listing = m(
        "gpt-6-realtime",
        "gpt-6-audio-preview",
        "gpt-6-mini",
        "gpt-6-nano",
        "gpt-6.1-mini",
        "gpt-6-transcribe",
        "gpt-6.1",
        "gpt-6-image",
        "gpt-6-codex",
        "text-embedding-3-large",
    )
    assert resolve_default_model(listing) == "gpt-6.1"


def test_mini_only_family_still_wins_over_older_family():
    assert resolve_default_model(m("gpt-5", "gpt-6-mini")) == "gpt-6-mini"


def test_none_when_nothing_fits():
    assert resolve_default_model(m("gpt-4o", "o3-mini", "gpt-5-realtime")) is None
