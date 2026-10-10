"""Fixtures: fake MCP and sandbox servers (threads), a Postgres database with its own checkpoint
schema (`agent_test`) on TEST_DATABASE_URL, and fixture rows (user, event, claimed person) with
random ids that are removed afterwards so the shared test database stays clean."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from fake_mcp import FakeMCPServer
from yearbook_agent import ids
from yearbook_agent.config import Settings
from yearbook_agent.db import Database
from yearbook_agent.mcp_tools import ToolCatalog
from yearbook_agent.sandbox import SandboxClient
from yearbook_agent.service import AgentService, Caller
from yearbook_agent.testing.fake_model import FakeProvider, ScriptedChatModel
from yearbook_agent.testing.fake_sandbox import FakeSandbox
from yearbook_agent.testing.memory_storage import MemoryStorage

TEST_DB_URL = os.environ.get("AGENT_TEST_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def mcp() -> Iterator[FakeMCPServer]:
    with FakeMCPServer() as srv:
        yield srv


@pytest.fixture(scope="session")
def mcp_ambiguous() -> Iterator[FakeMCPServer]:
    with FakeMCPServer(ambiguous_anna=True) as srv:
        yield srv


@pytest.fixture(scope="session")
def sandbox() -> Iterator[FakeSandbox]:
    with FakeSandbox() as sb:
        yield sb


@pytest.fixture
def settings(mcp: FakeMCPServer, sandbox: FakeSandbox) -> Settings:
    return Settings(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="scripted",
        MCP_URL=mcp.url,
        SANDBOX_URL=sandbox.url,
        DATABASE_URL=TEST_DB_URL,
        AGENT_DB_SCHEMA="agent_test",
        AGENT_TOOL_CACHE_S=0,
    )


@pytest.fixture(scope="session")
async def db() -> AsyncIterator[Database]:
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    database = Database(TEST_DB_URL, schema="agent_test", max_size=4)
    await database.open()
    yield database
    await database.close()


@dataclass
class Fixture:
    user_id: bytes
    guest_cookie_id: bytes
    event_id: bytes
    slug: str
    person_id: bytes

    @property
    def actor(self) -> str:
        return ids.encode(self.user_id)


@pytest.fixture
async def rows(db: Database) -> AsyncIterator[Fixture]:
    user_id, event_id, person_id, identity_id = (ids.new_id() for _ in range(4))
    cookie_id = ids.new_id()
    slug = f"sommerfest-{secrets.token_hex(3)}"
    async with db.pool.connection() as conn:
        await conn.execute(
            "insert into users (id, email, display_name, locale) values (%s, %s, %s, 'de')",
            (user_id, f"agent-test-{secrets.token_hex(4)}@example.test", "Hakan Duran"),
        )
        await conn.execute(
            "insert into events (id, slug, title, starts_at, timezone, owner_id) "
            "values (%s, %s, 'Sommerfest', %s, 'Europe/Berlin', %s)",
            (event_id, slug, datetime(2026, 7, 18, 12, 0, tzinfo=UTC), user_id),
        )
        await conn.execute("insert into guest_cookies (id) values (%s)", (cookie_id,))
        await conn.execute(
            "insert into persons (id, event_id, display_name, face_count) values (%s, %s, 'Hakan', 5)",
            (person_id, event_id),
        )
        await conn.execute(
            "insert into identities (id, user_id, display_name) values (%s, %s, 'Hakan')",
            (identity_id, user_id),
        )
        await conn.execute(
            "insert into person_links (person_id, identity_id) values (%s, %s)",
            (person_id, identity_id),
        )
    try:
        yield Fixture(user_id, cookie_id, event_id, slug, person_id)
    finally:
        async with db.pool.connection() as conn:
            for table, col in (
                ("sandbox_runs", "actor"),
                ("saved_commands", "owner"),
                ("agent_turns", "user_id"),
                ("agent_conversations", "actor"),
            ):
                await conn.execute(f"delete from {table} where {col} = %s", (user_id,))
            await conn.execute("delete from events where owner_id = %s", (user_id,))
            await conn.execute("delete from users where id = %s", (user_id,))
            await conn.execute("delete from guest_cookies where id = %s", (cookie_id,))


def make_service(
    settings: Settings,
    db: Database,
    planner: ScriptedChatModel | None = None,
    structured: Any = None,
    mcp_url: str | None = None,
) -> AgentService:
    provider = FakeProvider(planner=planner, structured=structured)
    return AgentService(
        settings,
        db,
        provider,
        catalog=ToolCatalog(mcp_url or settings.mcp_url, ttl_s=0),
        sandbox=SandboxClient(settings.sandbox_url),
        storage=MemoryStorage(),
    )


def caller_for(
    fx: Fixture, locale: str = "en", event: bool = True, token: str = "tok-123"
) -> Caller:
    return Caller(
        actor=fx.user_id,
        actor_kind="user",
        event_slug=fx.slug if event else None,
        locale=locale,
        session_token=token,
    )  # type: ignore[arg-type]


def headers_for(
    fx: Fixture, locale: str = "en", event: bool = True, token: str = "tok-123"
) -> dict[str, str]:
    h = {"X-Actor": fx.actor, "X-Actor-Kind": "user", "X-Locale": locale, "X-Session-Token": token}
    if event:
        h["X-Event-Slug"] = fx.slug
    return h


def text_of(msg: Any) -> str:
    """ToolMessage content as text (the MCP adapter returns a list of text blocks)."""
    c = msg.content
    if isinstance(c, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c)
    return str(c)
