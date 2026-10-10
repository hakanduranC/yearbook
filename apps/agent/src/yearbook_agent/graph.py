"""The LangGraph loop: call_model -> (tools | present | nudge | force) with the SDD §7.2 guards.

`present` is enforced structurally: it is a tool the model must call, the graph intercepts it
before execution and validates its arguments against the AgentResult contract; invalid calls go
back to the model as tool errors, prose answers get one nudge, and after 6 tool rounds or 20 s
the graph writes a kind `empty` result itself. Nothing reaches the user except a validated
`present`.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from pydantic import ValidationError

from .entities import collect, merge_entities, parse_tool_output
from .prompts import DEFAULT_SUGGESTIONS, FORCED_TITLE, NUDGE
from .result import Chip, EmptyDraft, PresentCall, format_validation_error, validate_present
from .turn import TurnContext

log = logging.getLogger("yearbook_agent.graph")


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    entities: Annotated[dict[str, dict[str, Any]], merge_entities]
    rounds: int
    nudged: bool
    result: dict[str, Any] | None  # PresentCall dump once the turn is done
    final_call: dict[str, Any] | None
    tools_used: list[str]
    forced: bool


def initial_state(text: str) -> AgentState:
    return {
        "messages": [HumanMessage(content=text)],
        "rounds": 0,
        "nudged": False,
        "result": None,
        "final_call": None,
        "tools_used": [],
        "forced": False,
    }


def _forced(state: AgentState, ctx: TurnContext) -> dict[str, Any]:
    title = FORCED_TITLE[ctx.locale]
    last = state["messages"][-1] if state.get("messages") else None
    if isinstance(last, AIMessage) and not last.tool_calls:
        text = _text_of(last).strip()
        if text:
            title = text[:160]
    chips = [Chip(label=label, text=text) for label, text in DEFAULT_SUGGESTIONS[ctx.locale]]
    call = PresentCall(
        understood=title[:200], result=EmptyDraft(kind="empty", title=title, suggestions=chips)
    )
    return {"result": call.model_dump(), "forced": True}


def _text_of(msg: AIMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return " ".join(
        c.get("text", "") for c in msg.content if isinstance(c, dict) and c.get("type") == "text"
    )


async def call_model(state: AgentState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    ctx = runtime.context
    if state["rounds"] >= ctx.max_rounds or time.monotonic() > ctx.deadline:
        log.info(
            "guard hit: rounds=%s elapsed=%.1fs", state["rounds"], time.monotonic() - ctx.started
        )
        return _forced(state, ctx)
    model = ctx.model.bind_tools(list(ctx.tools.values()))
    messages = [SystemMessage(content=ctx.system_prompt), *state["messages"]]
    ai = await model.ainvoke(messages)
    return {"messages": [ai]}


def route_after_model(
    state: AgentState,
) -> Literal["tools", "present", "nudge", "force", "__end__"]:
    if state.get("result"):
        return END
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return "force" if state.get("nudged") else "nudge"
    if any(tc["name"] == "present" for tc in last.tool_calls):
        return "present"
    return "tools"


async def nudge(state: AgentState) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=NUDGE)],
        "nudged": True,
        "rounds": state["rounds"] + 1,
    }


async def force(state: AgentState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    return _forced(state, runtime.context)


async def present(state: AgentState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    out: list[ToolMessage] = []
    result: dict[str, Any] | None = None
    for tc in last.tool_calls:
        if tc["name"] != "present":
            out.append(ToolMessage(content="skipped: present ends the turn", tool_call_id=tc["id"]))
            continue
        if result is not None:
            out.append(
                ToolMessage(content="ignored: present was already called", tool_call_id=tc["id"])
            )
            continue
        try:
            call = validate_present(tc["args"])
        except ValidationError as err:
            out.append(
                ToolMessage(
                    content=format_validation_error(err), tool_call_id=tc["id"], status="error"
                )
            )
            continue
        result = call.model_dump()
        out.append(ToolMessage(content="ok", tool_call_id=tc["id"]))
    update: dict[str, Any] = {"messages": out}
    if result is not None:
        update["result"] = result
    else:
        update["rounds"] = state["rounds"] + 1
    return update


def route_after_present(state: AgentState) -> Literal["call_model", "__end__"]:
    return END if state.get("result") else "call_model"


async def tools(state: AgentState, runtime: Runtime[TurnContext]) -> dict[str, Any]:
    ctx = runtime.context
    ctx.entities = state.get("entities") or {}
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    out: list[ToolMessage] = []
    used = list(state.get("tools_used") or [])
    final_call = state.get("final_call")
    gathered: dict[str, dict[str, Any]] = {}
    for tc in last.tool_calls:
        name = tc["name"]
        tool = ctx.tools.get(name)
        if tool is None:
            out.append(
                ToolMessage(content=f"unknown tool {name}", tool_call_id=tc["id"], status="error")
            )
            continue
        if time.monotonic() > ctx.deadline:
            out.append(
                ToolMessage(content="skipped: out of time", tool_call_id=tc["id"], status="error")
            )
            continue
        try:
            msg = await tool.ainvoke(
                {"name": name, "args": tc["args"], "id": tc["id"], "type": "tool_call"}
            )
        except Exception as exc:
            log.warning("tool %s failed: %s", name, exc)
            msg = ToolMessage(
                content=f"{name} failed: {exc}"[:2000], tool_call_id=tc["id"], status="error"
            )
        if not isinstance(msg, ToolMessage):
            msg = ToolMessage(content=str(msg), tool_call_id=tc["id"])
        used.append(name)
        final_call = {"name": name, "args": tc["args"]}
        data = parse_tool_output(msg.content, getattr(msg, "artifact", None))
        gathered = merge_entities(gathered, collect(data))
        ctx.entities = merge_entities(ctx.entities, gathered)
        out.append(msg)
    return {
        "messages": out,
        "rounds": state["rounds"] + 1,
        "tools_used": used,
        "final_call": final_call,
        "entities": gathered,
    }


def build_graph(checkpointer: BaseCheckpointSaver | None) -> Any:
    g: StateGraph = StateGraph(AgentState, context_schema=TurnContext)
    g.add_node("call_model", call_model)
    g.add_node("tools", tools)
    g.add_node("present", present)
    g.add_node("nudge", nudge)
    g.add_node("force", force)
    g.add_edge(START, "call_model")
    g.add_conditional_edges(
        "call_model",
        route_after_model,
        {"tools": "tools", "present": "present", "nudge": "nudge", "force": "force", END: END},
    )
    g.add_edge("tools", "call_model")
    g.add_edge("nudge", "call_model")
    g.add_conditional_edges("present", route_after_present, {"call_model": "call_model", END: END})
    g.add_edge("force", END)
    return g.compile(checkpointer=checkpointer)
