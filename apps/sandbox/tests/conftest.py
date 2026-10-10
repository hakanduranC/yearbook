"""Fixtures: settings pointing at a scratch work dir, a fake runner for API tests, a local HTTP
server for file fetches, and the real DockerRunner for tests marked `docker`."""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from yearbook_sandbox.app import create_app
from yearbook_sandbox.config import Settings, load_settings
from yearbook_sandbox.runner import DockerRunner, RunDir, RunResult, SandboxUnavailable

# Timings of real container runs, printed at the end of the session.
TIMINGS: list[tuple[str, RunResult]] = []


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not TIMINGS:
        return
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    tr.write_sep("-", "container timings (ms)")
    tr.write_line(f"{'test':<28}{'create':>8}{'start':>8}{'run':>8}  exit timed_out oom")
    for name, r in TIMINGS:
        tr.write_line(
            f"{name:<28}{r.create_ms:>8}{r.start_ms:>8}{r.duration_ms:>8}  "
            f"{r.exit_code!s:>4} {r.timed_out!s:<9} {r.oom_killed}"
        )


def _work_dir() -> Path:
    # Docker Desktop shares the home directory with its VM but not /tmp, so tests use a
    # scratch directory under the configured (home-based) work dir.
    base = os.environ.get("SANDBOX_WORK_DIR", "~/.cache/yearbook-sandbox")
    return Path(base).expanduser() / "pytest"


@pytest.fixture(scope="session")
def work_dir() -> Iterator[Path]:
    d = _work_dir()
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


class FileServer:
    """Serves bytes from memory on 127.0.0.1 so fetch tests need no network."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                data = server.files.get(self.path)
                if data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                if not self.path.endswith("-nolength"):
                    self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def url(self, path: str) -> str:
        return f"http://{self.host}{path}"

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture(scope="session")
def file_server() -> Iterator[FileServer]:
    s = FileServer()
    yield s
    s.close()


@pytest.fixture(scope="session")
def settings(work_dir: Path, file_server: FileServer) -> Settings:
    return load_settings(
        sandbox_work_dir=work_dir,
        sandbox_max_parallel=1,
        sandbox_queue_wait_s=0.3,
        public_base_url="http://localhost:8333/yearbook-public",
        s3_endpoint="http://localhost:8333",
        s3_presign_endpoint="",
        sandbox_allowed_hosts=file_server.host,
    )


@dataclass
class FakeRunner:
    """Records what the app asked for and answers canned results; no Docker involved."""

    work_dir: Path
    delay_s: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    prepared: list[RunDir] = field(default_factory=list)

    def check(self) -> dict[str, Any]:
        return {"docker": True, "image": True, "docker_version": "fake", "image_id": "sha256:fake"}

    def ensure_ready(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def selfcheck(self) -> RunResult:
        return RunResult(0, "", "", 0, False, False)

    def prepare(self, code: str, inputs: dict[str, Any]) -> RunDir:
        rd = DockerRunner.prepare.__get__(self, FakeRunner)(code, inputs)  # reuse the real layout
        self.prepared.append(rd)
        return rd

    def run(
        self,
        code: str,
        inputs: dict[str, Any],
        files: list[tuple[str, bytes]],
        *,
        timeout_s: int,
        prepared: RunDir | None = None,
    ) -> RunResult:
        assert prepared is not None
        in_files = {p.name: p.read_bytes() for p in sorted(prepared.in_dir.iterdir())}
        self.calls.append({"code": code, "inputs": inputs, "timeout_s": timeout_s, "in": in_files})
        time.sleep(self.delay_s)
        try:
            return RunResult(0, "fake", "", 1, False, False)
        finally:
            self.cleanup(prepared)

    def cleanup(self, rd: RunDir) -> None:
        shutil.rmtree(rd.root, ignore_errors=True)


@pytest.fixture
def fake_runner(work_dir: Path) -> FakeRunner:
    return FakeRunner(work_dir=work_dir / "fake")


@pytest.fixture
def client(settings: Settings, fake_runner: FakeRunner) -> Iterator[TestClient]:
    app = create_app(settings, runner=fake_runner, selfcheck=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def docker_runner(settings: Settings) -> DockerRunner:
    try:
        r = DockerRunner(settings)
        r.ensure_ready()
    except SandboxUnavailable as e:
        pytest.fail(f"docker tests need Docker and the sandbox image: {e}")
    except Exception as e:  # docker.from_env failing: no socket
        pytest.fail(f"docker tests need a reachable Docker daemon: {e}")
    return r


@pytest.fixture(scope="session")
def docker_client(settings: Settings, docker_runner: DockerRunner) -> Iterator[TestClient]:
    """The real app over the real runner, with the start-up self-check."""
    app = create_app(settings, runner=docker_runner, selfcheck=True)
    with TestClient(app) as c:
        yield c
