"""Chat model construction and default-model resolution.

`OPENAI_MODEL` empty means: ask `GET /v1/models` at startup and pick the newest chat-capable
model of the gpt-6 family (non-mini unless nothing else exists; realtime, audio, transcribe,
tts, embedding, image, search and codex variants are skipped), falling back to the newest gpt-5
family model only when no gpt-6 model is listed. The chosen id is logged once at startup.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel

from .config import Settings

log = logging.getLogger("yearbook_agent.models")

_EXCLUDE = re.compile(
    r"realtime|audio|transcribe|tts|embedding|image|search|codex|moderation|instruct"
)
_VERSION = re.compile(r"^gpt-(\d+)(?:[.-](\d+))?")


@dataclass(frozen=True)
class ModelInfo:
    id: str
    created: int = 0


def _rank(m: ModelInfo) -> tuple[int, int, int, int]:
    """Higher is better: family, minor version, non-mini/nano, creation time."""
    match = _VERSION.match(m.id)
    major = int(match.group(1)) if match else 0
    minor = int(match.group(2)) if match and match.group(2) else 0
    small = 0 if re.search(r"-(mini|nano)", m.id) else 1
    return (major, minor, small, m.created)


def resolve_default_model(models: list[ModelInfo]) -> str | None:
    """Pick the default chat model from a `/v1/models` listing; None if nothing fits."""
    chat = [m for m in models if m.id.startswith("gpt-") and not _EXCLUDE.search(m.id)]
    for family in ("gpt-6", "gpt-5"):
        candidates = [
            m
            for m in chat
            if m.id == family or m.id.startswith(family + "-") or m.id.startswith(family + ".")
        ]
        if candidates:
            return max(candidates, key=_rank).id
    return None


async def list_openai_models(settings: Settings) -> list[ModelInfo]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    page = await client.models.list()
    return [ModelInfo(id=m.id, created=int(getattr(m, "created", 0) or 0)) for m in page.data]


async def resolve_model_id(settings: Settings) -> str | None:
    """The configured id, or the resolved default. None when the service has no key."""
    if not settings.configured:
        return None
    if settings.openai_model:
        log.info("openai model (configured): %s", settings.openai_model)
        return settings.openai_model
    try:
        chosen = resolve_default_model(await list_openai_models(settings))
    except Exception as exc:
        log.warning("could not list models (%s); falling back to gpt-5", exc)
        chosen = "gpt-5"
    if chosen is None:
        log.warning("no gpt-6 or gpt-5 model listed; falling back to gpt-5")
        chosen = "gpt-5"
    log.info("openai model (resolved from /v1/models): %s", chosen)
    return chosen


class ModelProvider:
    """Builds the chat models the service needs. Tests pass a fake provider instead."""

    def __init__(self, settings: Settings, model_id: str) -> None:
        self.settings = settings
        self.model_id = model_id

    def _make(self, model_id: str | None = None, **kwargs: Any) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_id or self.model_id,
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            use_responses_api=True,
            output_version="responses/v1",
            timeout=30,
            max_retries=1,
            **kwargs,
        )

    def planner(self) -> BaseChatModel:
        """The tool-calling model of the graph."""
        return self._make()

    def structured(self, schema: type) -> Any:
        """A runnable returning instances of `schema` (JSON-schema structured output)."""
        return self._make().with_structured_output(schema, method="json_schema")

    def vision(self) -> BaseChatModel:
        """Model for image descriptions: OPENAI_VISION_MODEL when set, else the planner model."""
        return self._make(self.settings.openai_vision_model or None)
