"""A scripted stand-in for ChatOpenAI.

Each call to the model pops the next scripted step: a list of tool calls, plain text, or a
pydantic object (for structured output). `bind_tools` records the tool names it was offered and
returns the same model, which is what the graph needs. When the script runs out, the model calls
`present` with an empty result so a run always terminates.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

Step = list[tuple[str, dict[str, Any]]] | str | BaseModel | dict[str, Any]


def present(understood: str, **result: Any) -> tuple[str, dict[str, Any]]:
    return ("present", {"understood": understood, "result": result})


class ScriptedChatModel(BaseChatModel):
    script: list[Step] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    counter: int = 0
    exhausted_present: dict[str, Any] = Field(
        default_factory=lambda: {
            "understood": "Nothing more to show",
            "result": {"kind": "empty", "title": "Script exhausted"},
        }
    )

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:  # type: ignore[override]
        self.bound_tools = [getattr(t, "name", None) or t.get("name") for t in tools]
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:  # type: ignore[override]
        def parse(msg: AIMessage) -> Any:
            if isinstance(msg.content, str):
                return schema.model_validate_json(msg.content)
            return schema.model_validate(msg.content)

        return self | RunnableLambda(parse)

    def _next(self) -> AIMessage:
        step = self.script.pop(0) if self.script else [("present", self.exhausted_present)]
        if isinstance(step, str):
            return AIMessage(content=step)
        if isinstance(step, BaseModel):
            return AIMessage(content=step.model_dump_json())
        if isinstance(step, dict):
            return AIMessage(content=json.dumps(step))
        tool_calls = []
        for name, args in step:
            self.counter += 1
            tool_calls.append(
                {"name": name, "args": args, "id": f"call_{self.counter}", "type": "tool_call"}
            )
        return AIMessage(content="", tool_calls=tool_calls)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self._next())])


class FakeProvider:
    """Drop-in for `models.ModelProvider` backed by scripted models."""

    def __init__(
        self,
        planner: ScriptedChatModel | None = None,
        structured: Any = None,
        vision: ScriptedChatModel | None = None,
    ) -> None:
        self._planner = planner or ScriptedChatModel(script=[])
        self._structured = structured
        self._vision = vision or ScriptedChatModel(
            script=["A table outdoors with cake and three people."]
        )
        self.model_id = "scripted"

    def planner(self) -> BaseChatModel:
        return self._planner

    def structured(self, schema: type) -> Any:
        model = ScriptedChatModel(script=[self._structured] if self._structured is not None else [])
        return model.with_structured_output(schema)

    def vision(self) -> BaseChatModel:
        return self._vision
