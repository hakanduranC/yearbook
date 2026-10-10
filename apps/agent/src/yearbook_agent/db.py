"""Postgres access: scope lookups, agent bookkeeping tables, and the LangGraph checkpointer.

One psycopg pool (autocommit, dict rows) serves both. The checkpointer's tables live in their
own schema (`AGENT_DB_SCHEMA`, default `agent`) so they never collide with goose migrations or
other test suites; the application tables stay in `public`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from . import ids
from .prompts import EventInfo


@dataclass
class ScopeRow:
    viewer_name: str | None
    has_claimed_person: bool
    event: EventInfo | None
    event_id: bytes | None


@dataclass
class Conversation:
    id: bytes
    actor: bytes
    event_id: bytes | None
    expires_at: datetime


@dataclass
class TurnRow:
    id: bytes
    user_id: bytes | None
    guest_id: bytes | None
    event_id: bytes | None
    input: str
    final_call: dict[str, Any] | None
    conversation_id: bytes | None


@dataclass
class SavedCommandRow:
    id: bytes
    owner: bytes
    scope: str
    name: str
    label: str
    description: str
    params: dict[str, Any]
    sql_template: str
    kind: str
    search_args: dict[str, Any] | None
    code: str | None
    event_id: bytes | None
    shared: bool
    approved_at: datetime | None
    created_by_agent: bool
    run_count: int
    event_slug: str | None = None


class Database:
    def __init__(
        self, url: str, schema: str = "agent", min_size: int = 1, max_size: int = 8
    ) -> None:
        if not schema.isidentifier():
            raise ValueError("schema must be an identifier")
        self.schema = schema
        conninfo = make_conninfo(url, options=f"-c search_path={schema},public")
        self.pool = AsyncConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        self.checkpointer: AsyncPostgresSaver | None = None

    async def open(self) -> None:
        await self.pool.open(wait=True)
        async with self.pool.connection() as conn:
            await conn.execute(
                sql.SQL("create schema if not exists {}").format(sql.Identifier(self.schema))
            )
        self.checkpointer = AsyncPostgresSaver(self.pool)
        await self.checkpointer.setup()

    async def close(self) -> None:
        await self.pool.close()

    # ------------------------------------------------------------------ scope

    async def event_by_slug(self, slug: str) -> tuple[bytes, EventInfo] | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "select id, slug, title, starts_at, ends_at, timezone from events "
                    "where slug = %s",
                    (slug,),
                )
            ).fetchone()
        if not row:
            return None
        return row["id"], EventInfo(
            slug=row["slug"],
            title=row["title"],
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            timezone=row["timezone"],
        )

    async def load_scope(self, actor: bytes, actor_kind: str, event_slug: str | None) -> ScopeRow:
        event = await self.event_by_slug(event_slug) if event_slug else None
        event_id = event[0] if event else None
        async with self.pool.connection() as conn:
            if actor_kind == "user":
                name_row = await (
                    await conn.execute("select display_name from users where id = %s", (actor,))
                ).fetchone()
            else:
                name_row = await (
                    await conn.execute(
                        "select display_name from guests "
                        "where cookie_id = %s and display_name is not null "
                        "order by created_at desc limit 1",
                        (actor,),
                    )
                ).fetchone()
            claimed = await (
                await conn.execute(
                    """
                    select exists (
                      select 1 from identities i
                      join person_links pl on pl.identity_id = i.id
                      join persons p on p.id = pl.person_id
                      where (i.user_id = %(actor)s or i.guest_cookie_id = %(actor)s)
                        and (%(event)s::bytea is null or p.event_id = %(event)s)
                    ) as claimed
                    """,
                    {"actor": actor, "event": event_id},
                )
            ).fetchone()
        return ScopeRow(
            viewer_name=name_row["display_name"] if name_row else None,
            has_claimed_person=bool(claimed and claimed["claimed"]),
            event=event[1] if event else None,
            event_id=event_id,
        )

    # ------------------------------------------------------------------ conversations

    async def get_conversation(self, cid: bytes, actor: bytes) -> Conversation | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "select id, actor, event_id, expires_at from agent_conversations "
                    "where id = %s and actor = %s and expires_at > now()",
                    (cid, actor),
                )
            ).fetchone()
        return Conversation(**row) if row else None

    async def create_conversation(
        self, actor: bytes, event_id: bytes | None, ttl: timedelta
    ) -> Conversation:
        cid = ids.new_id()
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "insert into agent_conversations "
                    "(id, actor, event_id, provider_ref, expires_at) "
                    "values (%s, %s, %s, %s, now() + %s) returning id, actor, event_id, expires_at",
                    (cid, actor, event_id, ids.encode(cid), ttl),
                )
            ).fetchone()
        assert row is not None
        return Conversation(**row)

    async def touch_conversation(self, cid: bytes, ttl: timedelta) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "update agent_conversations set expires_at = now() + %s where id = %s", (ttl, cid)
            )

    # ------------------------------------------------------------------ turns

    async def insert_turn(
        self,
        *,
        turn_id: bytes,
        actor: bytes,
        actor_kind: str,
        event_id: bytes | None,
        input_text: str,
        tools_used: list[str],
        result_kind: str | None,
        latency_ms: int,
        conversation_id: bytes | None,
        understood: str | None,
        final_call: dict[str, Any] | None,
        attachments: list[dict[str, Any]],
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                insert into agent_turns (id, user_id, guest_id, event_id, input, tools_used,
                  result_kind,
                  latency_ms, conversation_id, understood, final_call, attachments)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    turn_id,
                    actor if actor_kind == "user" else None,
                    actor if actor_kind != "user" else None,
                    event_id,
                    input_text,
                    Jsonb(tools_used),
                    result_kind,
                    latency_ms,
                    conversation_id,
                    understood,
                    Jsonb(final_call) if final_call is not None else None,
                    Jsonb(attachments),
                ),
            )

    async def get_turn(self, turn_id: bytes) -> TurnRow | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "select id, user_id, guest_id, event_id, input, final_call, conversation_id "
                    "from agent_turns where id = %s",
                    (turn_id,),
                )
            ).fetchone()
        return TurnRow(**row) if row else None

    # ------------------------------------------------------------------ saved commands

    async def insert_saved_command(
        self,
        *,
        owner: bytes,
        scope: str,
        event_id: bytes | None,
        name: str,
        label: str,
        description: str,
        params: dict[str, Any],
        kind: str,
        sql_template: str = "",
        search_args: dict[str, Any] | None = None,
        code: str | None = None,
        created_by_agent: bool = False,
        approved: bool = True,
    ) -> SavedCommandRow:
        cmd_id = ids.new_id()
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                insert into saved_commands (id, owner, scope, event_id, name, label, description,
                  params,
                  sql_template, kind, search_args, code, created_by_agent, approved_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        case when %s then now() else null end)
                """,
                (
                    cmd_id,
                    owner,
                    scope,
                    event_id,
                    name,
                    label,
                    description,
                    Jsonb(params),
                    sql_template,
                    kind,
                    Jsonb(search_args) if search_args is not None else None,
                    code,
                    created_by_agent,
                    approved,
                ),
            )
        row = await self.get_saved_command(cmd_id)
        assert row is not None
        return row

    async def get_saved_command(self, cmd_id: bytes) -> SavedCommandRow | None:
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    select c.id, c.owner, c.scope, c.name, c.label, c.description, c.params,
                           c.sql_template,
                           c.kind, c.search_args, c.code, c.event_id, c.shared, c.approved_at,
                           c.created_by_agent, c.run_count, e.slug as event_slug
                    from saved_commands c left join events e on e.id = c.event_id
                    where c.id = %s
                    """,
                    (cmd_id,),
                )
            ).fetchone()
        return SavedCommandRow(**row) if row else None

    async def bump_saved_command(self, cmd_id: bytes) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "update saved_commands set run_count = run_count + 1, last_run_at = now() "
                "where id = %s",
                (cmd_id,),
            )

    # ------------------------------------------------------------------ sandbox runs

    async def insert_sandbox_run(
        self,
        *,
        turn_id: bytes | None,
        command_id: bytes | None,
        actor: bytes,
        code_sha256: bytes,
        exit_code: int | None,
        duration_ms: int,
        stdout_bytes: int,
        error: str | None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                insert into sandbox_runs (id, turn_id, command_id, actor, code_sha256, exit_code,
                  duration_ms,
                  stdout_bytes, error)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ids.new_id(),
                    turn_id,
                    command_id,
                    actor,
                    code_sha256,
                    exit_code,
                    duration_ms,
                    stdout_bytes,
                    error,
                ),
            )


def saved_command_to_wire(row: SavedCommandRow) -> dict[str, Any]:
    return {
        "id": ids.encode(row.id),
        "name": row.name,
        "label": row.label,
        "description": row.description,
        "scope": row.scope,
        "event_slug": row.event_slug,
        "params": row.params if isinstance(row.params, dict) else json.loads(row.params),
        "shared": row.shared,
        "kind": row.kind,
        "created_by_agent": row.created_by_agent,
        "run_count": row.run_count,
    }
