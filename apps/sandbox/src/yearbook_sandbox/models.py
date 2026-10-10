"""Request and response bodies of POST /run."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from yearbook_sandbox.config import (
    DEFAULT_TIMEOUT_S,
    MAX_CODE_CHARS,
    MAX_FILES,
    MAX_INPUTS_BYTES,
    MAX_TIMEOUT_S,
)

# Plain file names only: no path separators, no leading dot, nothing a shell or URL would mangle.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class InputFile(BaseModel):
    name: str
    url: str

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        if not SAFE_NAME.match(v) or ".." in v:
            raise ValueError("file name must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
        return v


class RunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    inputs: dict[str, Any] = Field(default_factory=dict)
    files: list[InputFile] = Field(default_factory=list, max_length=MAX_FILES)
    timeout_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=1, le=MAX_TIMEOUT_S)

    @field_validator("inputs")
    @classmethod
    def _inputs_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, ensure_ascii=False)) > MAX_INPUTS_BYTES:
            raise ValueError(f"inputs exceed {MAX_INPUTS_BYTES} bytes")
        return v

    @model_validator(mode="after")
    def _unique_names(self) -> RunRequest:
        names = [f.name for f in self.files]
        if len(set(names)) != len(names):
            raise ValueError("file names must be unique")
        if "main.py" in names or "inputs.json" in names:
            raise ValueError("main.py and inputs.json are reserved names")
        return self


class OutputFile(BaseModel):
    name: str
    mime: str
    size: int
    bytes_b64: str


class RunResponse(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    oom_killed: bool = False
    files: list[OutputFile] = Field(default_factory=list)
    # Things the program did that the service refused or truncated (too many files, bad mime, ...).
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    ok: bool
    docker: bool
    docker_version: str | None = None
    image: bool
    image_id: str | None = None
    runtime: str
    max_parallel: int
    in_flight: int
    work_dir: str
    error: str | None = None
