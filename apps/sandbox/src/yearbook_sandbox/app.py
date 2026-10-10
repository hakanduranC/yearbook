"""FastAPI app: POST /run, GET /health. Docker work happens in a thread behind a semaphore."""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from yearbook_sandbox.config import Settings, load_settings
from yearbook_sandbox.fetch import FetchError, fetch_files
from yearbook_sandbox.models import HealthResponse, RunRequest, RunResponse
from yearbook_sandbox.preflight import find_forbidden_token
from yearbook_sandbox.runner import DockerRunner, RunDir, RunResult, SandboxUnavailable

log = logging.getLogger("yearbook_sandbox.app")


class Runner(Protocol):
    """What the app needs from a runner; DockerRunner is the real one, tests inject a fake."""

    work_dir: Any

    def check(self) -> dict[str, Any]: ...
    def ensure_ready(self) -> None: ...
    def selfcheck(self) -> RunResult: ...
    def prepare(self, code: str, inputs: dict[str, Any]) -> RunDir: ...
    def run(
        self,
        code: str,
        inputs: dict[str, Any],
        files: list[tuple[str, bytes]],
        *,
        timeout_s: int,
        prepared: RunDir | None = None,
    ) -> RunResult: ...
    def cleanup(self, rd: RunDir) -> None: ...


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def create_app(
    settings: Settings | None = None,
    runner: Runner | None = None,
    *,
    selfcheck: bool = True,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        r = runner or DockerRunner(settings)
        try:
            r.ensure_ready()
            if selfcheck:
                res = r.selfcheck()
                log.info(
                    "self-check ok: create_ms=%d start_ms=%d duration_ms=%d",
                    res.create_ms,
                    res.start_ms,
                    res.duration_ms,
                )
        except SandboxUnavailable as e:
            # Printed, not just logged: this is the message the operator must see.
            print(f"\nyearbook-sandbox cannot start: {e}\n", flush=True)
            raise SystemExit(1) from e
        app.state.runner = r
        app.state.semaphore = asyncio.Semaphore(settings.sandbox_max_parallel)
        app.state.in_flight = 0
        log.info(
            "ready: image=%s max_parallel=%d runtime=%s work_dir=%s allowed_hosts=%s",
            settings.sandbox_image,
            settings.sandbox_max_parallel,
            settings.sandbox_runtime or "default",
            r.work_dir,
            sorted(settings.allowed_hosts),
        )
        yield

    app = FastAPI(title="Yearbook sandbox", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(SandboxUnavailable)
    async def _unavailable(_: Request, exc: SandboxUnavailable) -> JSONResponse:
        log.error("sandbox unavailable: %s", exc)
        return JSONResponse(
            status_code=503, content={"detail": {"code": "unavailable", "message": str(exc)}}
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> JSONResponse:
        r: Runner = request.app.state.runner
        info = await asyncio.to_thread(r.check)
        body = HealthResponse(
            ok=bool(info["docker"] and info["image"]),
            docker=info["docker"],
            docker_version=info.get("docker_version"),
            image=info["image"],
            image_id=info.get("image_id"),
            runtime=settings.sandbox_runtime or "default",
            max_parallel=settings.sandbox_max_parallel,
            in_flight=request.app.state.in_flight,
            work_dir=str(r.work_dir),
            error=info.get("error"),
        )
        return JSONResponse(status_code=200 if body.ok else 503, content=body.model_dump())

    @app.post("/run", response_model=RunResponse)
    async def run(request: Request, body: RunRequest) -> RunResponse:
        token = find_forbidden_token(body.code)
        if token:
            raise _error(
                400,
                "forbidden_token",
                f"code uses {token!r}, which the sandbox refuses",
                token=token,
            )

        r: Runner = request.app.state.runner
        sem: asyncio.Semaphore = request.app.state.semaphore
        try:
            await asyncio.wait_for(sem.acquire(), timeout=settings.sandbox_queue_wait_s)
        except TimeoutError:
            raise HTTPException(
                status_code=429,
                detail={"code": "busy", "message": "all sandbox slots are busy, retry later"},
                headers={"Retry-After": "5"},
            ) from None
        request.app.state.in_flight += 1
        try:
            return await asyncio.to_thread(_execute, r, body, settings)
        finally:
            request.app.state.in_flight -= 1
            sem.release()

    return app


def _execute(r: Runner, body: RunRequest, settings: Settings) -> RunResponse:
    """Blocking part of a run: prepare the directory, fetch files, run, clean up."""
    rd = r.prepare(body.code, body.inputs)
    try:
        if body.files:
            try:
                fetch_files(body.files, rd.in_dir, settings.allowed_hosts)
            except FetchError as e:
                raise _error(400, e.code, e.message, file=e.name) from e
        result = r.run(body.code, body.inputs, [], timeout_s=body.timeout_s, prepared=rd)
    except HTTPException:
        shutil.rmtree(rd.root, ignore_errors=True)
        raise
    except Exception:
        r.cleanup(rd)
        raise
    return RunResponse(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        oom_killed=result.oom_killed,
        files=result.files,
        warnings=result.warnings,
    )
