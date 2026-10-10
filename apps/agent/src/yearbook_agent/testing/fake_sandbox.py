"""A stand-in for apps/sandbox: the same `POST /run` contract, but the program runs as a plain
subprocess in a temporary directory (``/work`` paths are rewritten to it). Only for tests and
evals, where the code is ours; the real service runs containers with no network.
"""

from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI


class FakeSandbox:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.runs: list[dict[str, Any]] = []
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

        @self.app.post("/run")
        def run(body: dict[str, Any]) -> dict[str, Any]:
            self.runs.append(body)
            return execute(body)

        @self.app.get("/health")
        def health() -> dict[str, bool]:
            return {"ok": True}

    def __enter__(self) -> FakeSandbox:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake sandbox did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)


def execute(body: dict[str, Any]) -> dict[str, Any]:
    timeout = min(int(body.get("timeout_s") or 20), 20)
    with tempfile.TemporaryDirectory(prefix="yb-sandbox-") as tmp:
        work = Path(tmp)
        (work / "in").mkdir()
        (work / "out").mkdir()
        (work / "inputs.json").write_text(json.dumps(body.get("inputs") or {}), encoding="utf-8")
        for f in body.get("files") or []:  # files are not fetched by the fake; names exist, empty
            (work / "in" / Path(f["name"]).name).write_bytes(b"")
        code = str(body.get("code") or "").replace("/work", str(work))
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code, stdout, stderr = 124, (exc.stdout or ""), "killed: timeout"
        files = []
        for p in sorted((work / "out").iterdir()):
            if p.is_file():
                files.append(
                    {"name": p.name, "bytes_b64": base64.b64encode(p.read_bytes()).decode()}
                )
        return {
            "exit_code": exit_code,
            "stdout": stdout[-20000:],
            "stderr": stderr[-5000:],
            "files": files,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
