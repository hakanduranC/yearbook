"""`yearbook-agent eval`: replay evals/cases.yaml through the real graph.

Default: the scripted fake model plays each case's tool steps against the in-process fake MCP
server (deterministic; checks the harness end to end: tool schemas accept the arguments, the
tool results parse, `present` validates, saveable and kind match). `--real` swaps in ChatOpenAI
and scores the model's own tool sequence against the expectation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from . import ids
from .config import Settings
from .graph import build_graph, initial_state
from .mcp_tools import ToolCatalog
from .prompts import EventInfo, Scope, render_system_prompt
from .result import PresentCall
from .sandbox import SandboxClient
from .saveable import is_saveable
from .testing.fake_mcp import FakeMCPServer
from .testing.fake_model import ScriptedChatModel
from .testing.fake_sandbox import FakeSandbox
from .testing.memory_storage import MemoryStorage
from .tools_local import build_local_tools
from .turn import TurnContext

CASES = Path(__file__).resolve().parents[2] / "evals" / "cases.yaml"
EVENT = EventInfo(
    slug="sommerfest-x1y2",
    title="Sommerfest",
    timezone="Europe/Berlin",
    starts_at=datetime(2026, 7, 18, 14, 0, tzinfo=UTC),
    ends_at=None,
)


@dataclass
class CaseResult:
    id: str
    ok: bool
    kind: str
    expected_kind: str
    tools: list[str]
    expected_tools: list[str]
    saveable: bool
    expected_saveable: bool
    latency_ms: int
    note: str = ""


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["cases"]


def scripted_model(case: dict[str, Any]) -> ScriptedChatModel:
    steps: list[Any] = []
    for step in case["steps"]:
        steps.append([(step["tool"], step.get("args") or {})])
    steps.append([("present", case["present"])])
    return ScriptedChatModel(script=steps)


async def run_case(
    case: dict[str, Any],
    catalog: ToolCatalog,
    settings: Settings,
    model: Any,
    graph: Any,
    sandbox: SandboxClient | None = None,
) -> CaseResult:
    locale = case["locale"]
    scope = Scope(
        actor_kind="user",
        viewer_name="Hakan Duran",
        has_claimed_person=True,
        locale=locale,
        event=EVENT if case.get("scope", "event") == "event" else None,
    )
    ctx = TurnContext(
        settings=settings,
        actor=b"eval-actor-000001",
        actor_kind="user",
        event_id=None,
        event_slug=scope.event.slug if scope.event else None,
        turn_id=ids.new_id(),
        locale=locale,
        scope=scope,
        system_prompt=render_system_prompt(scope),
        model=model,
        storage=MemoryStorage(),
        sandbox=sandbox,
    )
    mcp_tools = await catalog.tools("eval-token", ctx.event_slug)
    ctx.tools = {t.name: t for t in mcp_tools}
    ctx.tools.update({t.name: t for t in build_local_tools(ctx)})
    t0 = time.monotonic()
    state = await graph.ainvoke(
        initial_state(case["text"]),
        config={"configurable": {"thread_id": ids.encode(ids.new_id())}},
        context=ctx,
    )
    latency = int((time.monotonic() - t0) * 1000)
    call = PresentCall.model_validate(state["result"])
    tools = state.get("tools_used") or []
    expected_tools = [s["tool"] for s in case["steps"]]
    expected_kind = case["present"]["result"]["kind"]
    expected_saveable = bool(case.get("saveable", False))
    saveable = is_saveable(state.get("final_call"))
    ok = (
        tools == expected_tools
        and call.result.kind == expected_kind
        and saveable == expected_saveable
        and not state.get("forced")
    )
    note = "forced" if state.get("forced") else ""
    return CaseResult(
        case["id"],
        ok,
        call.result.kind,
        expected_kind,
        tools,
        expected_tools,
        saveable,
        expected_saveable,
        latency,
        note,
    )


async def run_all(
    real: bool = False, only: str | None = None, mcp_url: str | None = None
) -> list[CaseResult]:
    settings = Settings()
    cases = [c for c in load_cases() if not only or only in c["id"]]
    results: list[CaseResult] = []
    graph = build_graph(InMemorySaver())
    real_model = None
    if real:
        from .models import ModelProvider, resolve_model_id

        model_id = await resolve_model_id(settings)
        if not model_id:
            raise SystemExit("OPENAI_API_KEY is not set; --real needs it")
        real_model = ModelProvider(settings, model_id).planner()

    async def go(catalog: ToolCatalog, sandbox: SandboxClient) -> None:
        for case in cases:
            model = real_model if real_model is not None else scripted_model(case)
            results.append(await run_case(case, catalog, settings, model, graph, sandbox))

    with FakeSandbox() as sb:
        sandbox = SandboxClient(sb.url)
        if mcp_url:
            await go(ToolCatalog(mcp_url), sandbox)
        else:
            with FakeMCPServer() as srv:
                await go(ToolCatalog(srv.url), sandbox)
    return results


def print_report(results: list[CaseResult]) -> int:
    passed = sum(r.ok for r in results)
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        extra = (
            ""
            if r.ok
            else (
                f"  got {r.kind}/{r.tools}/saveable={r.saveable}"
                f" want {r.expected_kind}/{r.expected_tools}"
                f"/saveable={r.expected_saveable} {r.note}"
            )
        )
        print(f"{mark} {r.id:<28} {r.latency_ms:>5} ms{extra}")
    lat = sorted(r.latency_ms for r in results)
    median = lat[len(lat) // 2] if lat else 0
    print(f"\n{passed}/{len(results)} passed, median latency {median} ms")
    return 0 if passed == len(results) else 1


def main(real: bool = False, only: str | None = None, mcp_url: str | None = None) -> int:
    return print_report(asyncio.run(run_all(real=real, only=only, mcp_url=mcp_url)))
