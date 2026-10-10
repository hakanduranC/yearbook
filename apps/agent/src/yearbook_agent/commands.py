"""Save-as-chip: turn a turn's final tool call into a SavedCommand template with one structured
model call (SDD §9 layer 3)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .result import Locale

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


class SavedCommandDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="snake_case identifier, 3-40 characters")
    description: str = Field(max_length=300, description="One sentence in the user's language")
    params: dict[str, Any] = Field(
        description="JSON schema (type object) of the parameters; {} if none"
    )
    kind: Literal["sql", "search", "python"]
    sql_template: str | None = Field(
        default=None, description="For kind sql: the SELECT with :param placeholders"
    )
    search_args: dict[str, Any] | None = Field(
        default=None,
        description="For kind search: search_media arguments; "
        "parameterised values are strings ':param'",
    )
    code: str | None = Field(
        default=None, description="For kind python: the program; params arrive in /work/inputs.json"
    )

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip().lower().replace("-", "_").replace(" ", "_")
        if not NAME_RE.match(v):
            raise ValueError("name must be snake_case, 3-40 characters")
        return v

    def check(self) -> None:
        if self.kind == "sql" and not (self.sql_template or "").lower().lstrip().startswith(
            "select"
        ):
            raise ValueError("sql_template must be a SELECT")
        if self.kind == "search" and not isinstance(self.search_args, dict):
            raise ValueError("search_args required for kind search")
        if self.kind == "python" and not self.code:
            raise ValueError("code required for kind python")


SYSTEM = """You turn one finished assistant action into a reusable saved command for a photo
album app.
Given the user's request, the label they chose and the final tool call, produce:
- name: snake_case
- description: one sentence in the user's language ({locale})
- params: a JSON schema (type object) with the values a user would want to change next time
  (a date, a person name, a count, a threshold); keep ids fixed, keep it small,
  {{}} if nothing varies
- kind: "sql" when the final call was run_query, "search" when it was search_media,
  "python" when run_python
- sql_template: the SELECT with named placeholders :param for every parameter (kind sql)
- search_args: the search_media arguments, parameterised values written as the string
  ":param" (kind search)
- code: the program unchanged except that varying literals read from /work/inputs.json (kind python)
Answer with the JSON object only."""

KIND_BY_TOOL = {"run_query": "sql", "search_media": "search", "run_python": "python"}


def draft_messages(
    user_text: str, label: str, final_call: dict[str, Any], locale: Locale
) -> list[Any]:
    payload = {
        "user_request": user_text,
        "label": label,
        "final_call": final_call,
        "expected_kind": KIND_BY_TOOL.get(final_call.get("name", ""), "sql"),
    }
    return [
        SystemMessage(content=SYSTEM.format(locale=locale)),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]


async def draft_command(
    structured: Any, user_text: str, label: str, final_call: dict[str, Any], locale: Locale
) -> SavedCommandDraft:
    draft: SavedCommandDraft = await structured.ainvoke(
        draft_messages(user_text, label, final_call, locale)
    )
    if isinstance(draft, dict):
        draft = SavedCommandDraft.model_validate(draft)
    expected = KIND_BY_TOOL.get(final_call.get("name", ""))
    if expected and draft.kind != expected:
        draft.kind = expected  # the final call decides; the model only fills the template
    draft.check()
    return draft
