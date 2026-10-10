"""FastAPI surface, called only by the Go API after it authenticated the viewer."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .db import Database
from .models import ModelProvider, resolve_model_id
from .service import AgentService, Caller, ServiceError

log = logging.getLogger("yearbook_agent.app")


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    event_slug: str | None = None
    conversation_id: str | None = None


class SaveCommandRequest(BaseModel):
    turn_id: str
    label: str = Field(min_length=1, max_length=30)


class RunCommandRequest(BaseModel):
    event_slug: str | None = None
    params: dict[str, Any] | None = None


class DescribeRequest(BaseModel):
    media_id: str
    image_url: str
    locale: str = "en"


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


async def build_service(
    settings: Settings, provider: Any = None, db: Database | None = None, **kwargs: Any
) -> AgentService:
    settings.apply_tracing_env()
    if db is None and settings.database_url:
        db = Database(settings.database_url, settings.agent_db_schema)
        await db.open()
    if provider is None:
        model_id = await resolve_model_id(settings)
        provider = ModelProvider(settings, model_id) if model_id else None
    if provider is None:
        log.warning("OPENAI_API_KEY not set: agent endpoints answer 503 agent_not_configured")
    return AgentService(settings, db, provider, **kwargs)


def create_app(
    settings: Settings | None = None,
    service: AgentService | None = None,
    service_factory: Callable[[], Awaitable[AgentService]] | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        if service is not None:
            svc = service
        elif service_factory is not None:
            svc = await service_factory()
        else:
            svc = await build_service(settings)
        app.state.service = svc
        try:
            yield
        finally:
            if service is None and service_factory is None and svc.db is not None:
                await svc.db.close()

    app = FastAPI(title="yearbook-agent", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return error(exc.status, exc.code, exc.message)

    def svc(request: Request) -> AgentService:
        return request.app.state.service

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        s = svc(request)
        return {
            "ok": True,
            "configured": s.configured,
            "model": getattr(s.provider, "model_id", None),
            "db": s.db is not None,
        }

    @app.post("/agent/messages")
    async def messages(body: AgentRequest, request: Request) -> Any:
        s = svc(request)
        if not s.configured:
            raise ServiceError(503, "internal", "agent_not_configured")
        if s.db is None:
            raise ServiceError(503, "internal", "agent_db_unavailable")
        caller = Caller.from_headers(request.headers)
        return await s.message(body.text, body.event_slug, body.conversation_id, caller)

    @app.post("/agent/commands", status_code=201)
    async def commands(body: SaveCommandRequest, request: Request) -> Any:
        s = svc(request)
        if not s.configured:
            raise ServiceError(503, "internal", "agent_not_configured")
        caller = Caller.from_headers(request.headers)
        return await s.save_command(body.turn_id, body.label, caller)

    @app.post("/agent/commands/{command_id}/run")
    async def run_command(
        command_id: str, request: Request, body: RunCommandRequest | None = None
    ) -> Any:
        s = svc(request)
        if s.db is None:
            raise ServiceError(503, "internal", "agent_db_unavailable")
        caller = Caller.from_headers(request.headers)
        body = body or RunCommandRequest()
        return await s.run_python_command(command_id, body.params, body.event_slug, caller)

    @app.post("/describe")
    async def describe(body: DescribeRequest, request: Request) -> dict[str, str]:
        s = svc(request)
        if not s.configured:
            raise ServiceError(503, "internal", "agent_not_configured")
        locale = body.locale if body.locale in ("de", "en", "tr") else "en"
        return {"text": await s.describe(body.image_url, locale)}  # type: ignore[arg-type]

    return app
