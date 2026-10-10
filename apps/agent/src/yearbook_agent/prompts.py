"""System prompt rendering (SDD §9): scope, viewer, event, date, locale, rules, few-shots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path
from string import Template
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .result import Locale

PROMPTS_DIR = Path(__file__).parent / "prompts"

LANGUAGE = {"de": "Deutsch", "en": "English", "tr": "Türkçe"}


@dataclass(frozen=True)
class EventInfo:
    slug: str
    title: str
    starts_at: datetime
    ends_at: datetime | None
    timezone: str


@dataclass(frozen=True)
class Scope:
    actor_kind: str  # user | guest
    viewer_name: str | None
    has_claimed_person: bool
    locale: Locale
    event: EventInfo | None
    now: datetime | None = None

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.event.timezone if self.event else "Europe/Berlin")
        except Exception:
            return ZoneInfo("Europe/Berlin")

    @property
    def today(self) -> date:
        return (self.now or datetime.now(tz=self.tz)).astimezone(self.tz).date()


@cache
def _template() -> Template:
    return Template((PROMPTS_DIR / "system.md").read_text(encoding="utf-8"))


@cache
def fewshots() -> list[dict[str, Any]]:
    data = yaml.safe_load((PROMPTS_DIR / "fewshots.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, list) or not 6 <= len(data) <= 10:
        raise ValueError("fewshots.yaml must hold 6 to 10 examples")
    return data


def first_name(name: str | None) -> str | None:
    if not name:
        return None
    return name.strip().split()[0]


def _format_examples(examples: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for ex in examples:
        out.append(f'User ({ex["locale"]}, {ex["scope"]} scope): "{ex["user"]}"')
        for step in ex["steps"]:
            args = json.dumps(step["args"], ensure_ascii=False, separators=(",", ":"))
            note = f"  -> {step['note']}" if step.get("note") else ""
            out.append(f"  {step['tool']}({args}){note}")
        out.append("")
    return "\n".join(out).rstrip()


CLAIMED = {
    "de": (
        "Du bist im Event einer Person zugeordnet; `me: true` funktioniert.",
        "Du hast dich noch keiner Person zugeordnet; `me: true` liefert nichts.",
    ),
    "en": (
        "The viewer has claimed a person; `me: true` works.",
        "The viewer has not claimed a person yet; `me: true` returns nothing.",
    ),
    "tr": (
        "İzleyici bir kişiyi sahiplendi; `me: true` çalışır.",
        "İzleyici henüz bir kişiyi sahiplenmedi; `me: true` sonuç vermez.",
    ),
}


def render_system_prompt(scope: Scope, examples: list[dict[str, Any]] | None = None) -> str:
    ev = scope.event
    if ev:
        starts = ev.starts_at.astimezone(scope.tz)
        ends = ev.ends_at.astimezone(scope.tz).strftime("%Y-%m-%d %H:%M") if ev.ends_at else "open"
        scope_line = (
            f'Event "{ev.title}" (slug {ev.slug}), {starts.strftime("%A %Y-%m-%d %H:%M")} '
            f"to {ends}, timezone {ev.timezone}. Searches are limited to this event."
        )
    else:
        scope_line = (
            "All of the viewer's events and their personal library. Timezone Europe/Berlin "
            "unless an event says otherwise."
        )
    claimed = CLAIMED[scope.locale][0 if scope.has_claimed_person else 1]
    return _template().substitute(
        scope_line=scope_line,
        viewer_name=first_name(scope.viewer_name)
        or {"de": "Gast", "en": "Guest", "tr": "Misafir"}[scope.locale],
        actor_kind=scope.actor_kind,
        claimed_line=claimed,
        today=scope.today.isoformat(),
        language=LANGUAGE[scope.locale],
        locale=scope.locale,
        examples=_format_examples(examples if examples is not None else fewshots()),
    )


NUDGE = (
    "You answered in prose. Nothing reaches the user that way: call `present` now with the "
    "result (use kind `empty` with that text as the title if there is nothing to show)."
)

FORCED_TITLE = {
    "de": "Das hat zu lange gedauert. Versuch eine engere Frage, zum Beispiel eine Person "
    "oder eine Tageszeit.",
    "en": "That took too long. Try a narrower question, for example one person or one time of day.",
    "tr": "Bu çok uzun sürdü. Daha dar bir soru dene, örneğin bir kişi ya da günün bir saati.",
}

DEFAULT_SUGGESTIONS = {
    "de": [
        ("Fotos von mir", "Fotos von mir"),
        ("Die besten", "die besten Fotos"),
        ("Videos", "alle Videos"),
    ],
    "en": [
        ("Photos of me", "photos of me"),
        ("The best", "the best photos"),
        ("Videos", "all videos"),
    ],
    "tr": [
        ("Fotoğraflarım", "benim fotoğraflarım"),
        ("En iyiler", "en iyi fotoğraflar"),
        ("Videolar", "tüm videolar"),
    ],
}

NOT_CONFIGURED_UNDERSTOOD = {
    "de": "Der Assistent ist nicht eingerichtet.",
    "en": "The assistant is not set up.",
    "tr": "Asistan kurulmamış.",
}
