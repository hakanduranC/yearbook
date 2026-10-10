"""Per-turn context handed to the graph as LangGraph runtime context (never checkpointed)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from .config import Settings
from .prompts import Scope
from .result import Locale


@dataclass
class TurnContext:
    settings: Settings
    actor: bytes
    actor_kind: str
    event_id: bytes | None
    event_slug: str | None
    turn_id: bytes
    locale: Locale
    scope: Scope
    system_prompt: str
    model: BaseChatModel
    tools: dict[str, BaseTool] = field(default_factory=dict)
    db: Any = None  # Database | None (None in evals without Postgres)
    sandbox: Any = None  # SandboxClient
    storage: Any = None  # Storage | NullStorage
    attachments: list[dict[str, Any]] = field(default_factory=list)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    @property
    def deadline(self) -> float:
        return self.started + self.settings.wall_clock_s

    @property
    def max_rounds(self) -> int:
        return self.settings.max_tool_rounds
