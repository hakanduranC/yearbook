"""AgentService: everything the HTTP layer calls. Holds the compiled graph, the tool catalog,
the model provider and the database; one instance per process."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from langchain_core.messages import HumanMessage

from . import ids
from .commands import SavedCommandDraft, draft_command
from .config import Settings
from .db import Database, SavedCommandRow, saved_command_to_wire
from .graph import build_graph, initial_state
from .mcp_tools import ToolCatalog
from .prompts import DEFAULT_SUGGESTIONS, Scope, render_system_prompt
from .result import (
    AgentResponse,
    Attachment,
    Chip,
    EmptyDraft,
    Locale,
    PresentCall,
    StatDraft,
    to_wire,
)
from .sandbox import SandboxClient
from .saveable import is_saveable
from .storage import NullStorage, Storage
from .tools_local import _execute, build_local_tools, can_run_saved_tool
from .turn import TurnContext

log = logging.getLogger("yearbook_agent.service")


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Caller:
    """What the Go API tells us about the authenticated viewer (proxy headers)."""

    actor: bytes
    actor_kind: str  # user | guest
    event_slug: str | None
    locale: Locale
    session_token: str

    @classmethod
    def from_headers(cls, h: Any) -> Caller:
        actor = h.get("x-actor") or ""
        if not ids.is_id(actor):
            raise ServiceError(400, "bad_request", "missing or invalid X-Actor")
        kind = (h.get("x-actor-kind") or "user").lower()
        if kind not in ("user", "guest"):
            raise ServiceError(400, "bad_request", "X-Actor-Kind must be user or guest")
        locale = (h.get("x-locale") or "en").lower()[:2]
        if locale not in ("de", "en", "tr"):
            locale = "en"
        token = h.get("x-session-token") or ""
        if not token:
            raise ServiceError(400, "bad_request", "missing X-Session-Token")
        return cls(
            actor=ids.decode(actor),
            actor_kind=kind,
            event_slug=h.get("x-event-slug") or None,
            locale=locale,
            session_token=token,
        )  # type: ignore[arg-type]


class AgentService:
    def __init__(
        self,
        settings: Settings,
        db: Database | None,
        provider: Any,
        catalog: ToolCatalog | None = None,
        sandbox: SandboxClient | None = None,
        storage: Storage | NullStorage | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.provider = provider  # ModelProvider | FakeProvider | None (not configured)
        self.catalog = catalog or ToolCatalog(settings.mcp_url, settings.tool_cache_s)
        self.sandbox = sandbox or SandboxClient(settings.sandbox_url, settings.sandbox_timeout_s)
        if storage is None:
            storage = Storage(settings) if settings.s3_configured else NullStorage()
        self.storage = storage
        self.graph = build_graph(db.checkpointer if db else None)

    @property
    def configured(self) -> bool:
        return self.provider is not None

    def _require(self) -> None:
        if not self.configured:
            raise ServiceError(503, "internal", "agent_not_configured")

    # ------------------------------------------------------------------ messages

    async def message(
        self, text: str, event_slug: str | None, conversation_id: str | None, caller: Caller
    ) -> AgentResponse:
        self._require()
        assert self.db is not None
        t0 = time.monotonic()
        slug = event_slug or caller.event_slug
        scope_row = await self.db.load_scope(caller.actor, caller.actor_kind, slug)
        if slug and scope_row.event is None:
            raise ServiceError(404, "not_found", "event not found")
        scope = Scope(
            actor_kind=caller.actor_kind,
            viewer_name=scope_row.viewer_name,
            has_claimed_person=scope_row.has_claimed_person,
            locale=caller.locale,
            event=scope_row.event,
        )
        ttl = timedelta(minutes=self.settings.conversation_ttl_min)
        conv = None
        if conversation_id and ids.is_id(conversation_id):
            conv = await self.db.get_conversation(ids.decode(conversation_id), caller.actor)
        if conv is None:
            conv = await self.db.create_conversation(caller.actor, scope_row.event_id, ttl)
        else:
            await self.db.touch_conversation(conv.id, ttl)

        turn_id = ids.new_id()
        ctx = TurnContext(
            settings=self.settings,
            actor=caller.actor,
            actor_kind=caller.actor_kind,
            event_id=scope_row.event_id,
            event_slug=slug,
            turn_id=turn_id,
            locale=caller.locale,
            scope=scope,
            system_prompt=render_system_prompt(scope),
            model=self.provider.planner(),
            db=self.db,
            sandbox=self.sandbox,
            storage=self.storage,
        )
        try:
            mcp_tools = await self.catalog.tools(caller.session_token, slug)
        except Exception as exc:
            log.warning("mcp tools unavailable: %s", exc)
            raise ServiceError(503, "internal", "agent_tools_unavailable") from exc
        ctx.tools = {t.name: t for t in mcp_tools}
        ctx.tools.update({t.name: t for t in build_local_tools(ctx)})

        config = {"configurable": {"thread_id": ids.encode(conv.id)}}
        try:
            state = await self.graph.ainvoke(initial_state(text), config=config, context=ctx)
        except Exception as exc:
            log.exception("graph failed")
            raise ServiceError(502, "internal", "agent_model_error") from exc

        call = PresentCall.model_validate(state["result"])
        wire, chips = to_wire(call, state.get("entities") or {})
        suggestions = chips or [
            Chip(label=label, text=t) for label, t in DEFAULT_SUGGESTIONS[caller.locale]
        ]
        final_call = state.get("final_call")
        attachments = [Attachment.model_validate(a) for a in ctx.attachments]
        latency_ms = int((time.monotonic() - t0) * 1000)
        await self.db.insert_turn(
            turn_id=turn_id,
            actor=caller.actor,
            actor_kind=caller.actor_kind,
            event_id=scope_row.event_id,
            input_text=text,
            tools_used=state.get("tools_used") or [],
            result_kind=wire.kind,
            latency_ms=latency_ms,
            conversation_id=conv.id,
            understood=call.understood,
            final_call=final_call,
            attachments=[
                {"name": a["name"], "key": a["key"], "mime": a["mime"]} for a in ctx.attachments
            ],
        )
        log.info(
            "turn %s kind=%s tools=%s latency=%sms forced=%s",
            ids.encode(turn_id),
            wire.kind,
            state.get("tools_used"),
            latency_ms,
            state.get("forced"),
        )
        return AgentResponse(
            conversation_id=ids.encode(conv.id),
            turn_id=ids.encode(turn_id),
            understood=call.understood,
            result=wire,
            suggestions=suggestions,
            saveable=is_saveable(final_call),
            attachments=attachments,
        )

    # ------------------------------------------------------------------ save as chip

    async def save_command(self, turn_id: str, label: str, caller: Caller) -> dict[str, Any]:
        self._require()
        assert self.db is not None
        if not ids.is_id(turn_id):
            raise ServiceError(400, "bad_request", "invalid turn_id")
        turn = await self.db.get_turn(ids.decode(turn_id))
        if turn is None or (turn.user_id or turn.guest_id) != caller.actor:
            raise ServiceError(404, "not_found", "turn not found")
        if not turn.final_call or turn.final_call.get("name") not in (
            "run_query",
            "search_media",
            "run_python",
        ):
            raise ServiceError(409, "conflict", "turn_not_saveable")
        structured = self.provider.structured(SavedCommandDraft)
        try:
            draft = await draft_command(
                structured, turn.input, label, turn.final_call, caller.locale
            )
        except Exception as exc:
            log.warning("command draft failed: %s", exc)
            raise ServiceError(502, "internal", "agent_model_error") from exc
        event_id = turn.event_id
        if caller.event_slug and event_id is None:
            ev = await self.db.event_by_slug(caller.event_slug)
            event_id = ev[0] if ev else None
        row = await self.db.insert_saved_command(
            owner=caller.actor,
            scope="event" if event_id else "global",
            event_id=event_id,
            name=draft.name,
            label=label[:30],
            description=draft.description,
            params=draft.params,
            kind=draft.kind,
            sql_template=draft.sql_template or "",
            search_args=draft.search_args,
            code=draft.code,
            created_by_agent=False,
            approved=True,
        )
        return saved_command_to_wire(row)

    # ------------------------------------------------------------------ run a python command

    async def run_python_command(
        self, command_id: str, params: dict[str, Any] | None, event_slug: str | None, caller: Caller
    ) -> AgentResponse:
        assert self.db is not None
        if not ids.is_id(command_id):
            raise ServiceError(404, "not_found", "command not found")
        row: SavedCommandRow | None = await self.db.get_saved_command(ids.decode(command_id))
        if row is None:
            raise ServiceError(404, "not_found", "command not found")
        if row.kind != "python" or not row.code:
            raise ServiceError(400, "bad_request", "only python commands run here")
        slug = event_slug or caller.event_slug
        ev = await self.db.event_by_slug(slug) if slug else None
        event_id = ev[0] if ev else row.event_id
        if not can_run_saved_tool(row, caller.actor, event_id):
            raise ServiceError(403, "forbidden", "not allowed to run this command")
        t0 = time.monotonic()
        scope = Scope(
            actor_kind=caller.actor_kind,
            viewer_name=None,
            has_claimed_person=False,
            locale=caller.locale,
            event=ev[1] if ev else None,
        )
        turn_id = ids.new_id()
        ctx = TurnContext(
            settings=self.settings,
            actor=caller.actor,
            actor_kind=caller.actor_kind,
            event_id=event_id,
            event_slug=slug,
            turn_id=turn_id,
            locale=caller.locale,
            scope=scope,
            system_prompt="",
            model=None,  # type: ignore[arg-type]
            db=self.db,
            sandbox=self.sandbox,
            storage=self.storage,
        )
        out = json.loads(await _execute(ctx, row.code, params or {}, [], row.id))
        await self.db.bump_saved_command(row.id)
        call = _result_from_run(row, out, caller.locale)
        wire, chips = to_wire(call, {})
        ttl = timedelta(minutes=self.settings.conversation_ttl_min)
        conv = await self.db.create_conversation(caller.actor, event_id, ttl)
        await self.db.insert_turn(
            turn_id=turn_id,
            actor=caller.actor,
            actor_kind=caller.actor_kind,
            event_id=event_id,
            input_text=f"run:{row.name}",
            tools_used=["run_tool"],
            result_kind=wire.kind,
            latency_ms=int((time.monotonic() - t0) * 1000),
            conversation_id=conv.id,
            understood=call.understood,
            final_call={
                "name": "run_tool",
                "args": {"command_id": command_id, "params": params or {}},
            },
            attachments=[
                {"name": a["name"], "key": a["key"], "mime": a["mime"]} for a in ctx.attachments
            ],
        )
        return AgentResponse(
            conversation_id=ids.encode(conv.id),
            turn_id=ids.encode(turn_id),
            understood=call.understood,
            result=wire,
            suggestions=chips,
            saveable=False,
            attachments=[Attachment.model_validate(a) for a in ctx.attachments],
        )

    # ------------------------------------------------------------------ describe

    async def describe(self, image_url: str, locale: Locale) -> str:
        self._require()
        prompt = {
            "de": "Beschreibe dieses Foto in zwei bis drei kurzen Sätzen auf Deutsch, für ein "
            "Familienalbum. "
            "Keine Namen raten, keine Altersangaben.",
            "en": "Describe this photo in two or three short sentences in English, for a family "
            "album. "
            "Do not guess names or ages.",
            "tr": "Bu fotoğrafı bir aile albümü için Türkçe iki üç kısa cümleyle anlat. "
            "İsim ya da yaş tahmin etme.",
        }[locale]
        msg = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        )
        try:
            ai = await self.provider.vision().ainvoke([msg])
        except Exception as exc:
            log.warning("describe failed: %s", exc)
            raise ServiceError(502, "internal", "agent_model_error") from exc
        if isinstance(ai.content, str):
            text = ai.content
        else:
            text = " ".join(
                c.get("text", "")
                for c in ai.content
                if isinstance(c, dict) and c.get("type") == "text"
            )
        return (text or "").strip()


def _result_from_run(row: SavedCommandRow, out: dict[str, Any], locale: Locale) -> PresentCall:
    understood = {
        "de": f"Befehl „{row.label}“ ausgeführt",
        "en": f"Ran “{row.label}”",
        "tr": f"“{row.label}” çalıştırıldı",
    }[locale]
    if out.get("error"):
        title = {
            "de": "Der Befehl konnte nicht ausgeführt werden",
            "en": "The command could not run",
            "tr": "Komut çalıştırılamadı",
        }[locale]
        return PresentCall(understood=understood, result=EmptyDraft(kind="empty", title=title))
    stdout = (out.get("stdout") or "").strip()
    try:
        parsed = json.loads(stdout) if stdout else None
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("kind"):
        try:
            return PresentCall(understood=understood, result=parsed)  # type: ignore[arg-type]
        except Exception:
            pass
    value = (
        stdout[:80]
        if stdout
        else (
            {"de": "Fertig", "en": "Done", "tr": "Tamam"}[locale]
            if out.get("exit_code") == 0
            else {"de": "Fehler", "en": "Error", "tr": "Hata"}[locale]
        )
    )
    detail = (out.get("stderr") or "")[:300] or None
    return PresentCall(
        understood=understood,
        result=StatDraft(kind="stat", title=row.label, value=value, detail=detail),
    )
