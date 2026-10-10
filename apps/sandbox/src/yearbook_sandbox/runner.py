"""One execution = one throwaway container. Everything Docker-specific lives here.

The equivalent `docker run` for auditing is in README.md; keep the two in sync.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docker
import docker.errors
import requests.exceptions
from docker.types import LogConfig, Mount

from yearbook_sandbox.config import (
    MAX_OUTPUT_FILES,
    MAX_OUTPUT_TOTAL_BYTES,
    MAX_STREAM_BYTES,
    SANDBOX_UID,
    Settings,
)
from yearbook_sandbox.models import OutputFile

log = logging.getLogger("yearbook_sandbox.runner")

TRUNCATED = "\n[sandbox: output truncated at 1 MiB]\n"
# Docker keeps the container's output in a json-file log until we read it. The cap bounds disk use
# under a flood; we then cut what we got down to MAX_STREAM_BYTES per stream.
LOG_FILE_CAP = "16m"

# Extension -> (mime, magic prefixes). Text types are checked for valid UTF-8 instead.
MIME_BY_EXT: dict[str, tuple[str, tuple[bytes, ...]]] = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".webp": ("image/webp", (b"RIFF",)),
    ".pdf": ("application/pdf", (b"%PDF-",)),
    ".csv": ("text/csv", ()),
    ".json": ("application/json", ()),
    ".txt": ("text/plain", ()),
}


class SandboxUnavailable(Exception):
    """Docker or the image is not usable; the request cannot be served (503)."""


@dataclass
class RunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    oom_killed: bool
    files: list[OutputFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Observability: how long Docker took before the program could start.
    create_ms: int = 0
    start_ms: int = 0


@dataclass
class RunDir:
    """Per-run host directory: in/ (read-only to the program), out/ (its only writable export)."""

    root: Path
    in_dir: Path
    out_dir: Path
    main_py: Path
    inputs_json: Path


class DockerRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = docker.from_env(timeout=60)
        self.work_dir = settings.work_dir

    # -- lifecycle ---------------------------------------------------------------------------

    def check(self) -> dict[str, Any]:
        """Docker reachability and image presence, as a dict for /health."""
        info: dict[str, Any] = {
            "docker": False,
            "image": False,
            "docker_version": None,
            "image_id": None,
        }
        try:
            info["docker_version"] = self.client.version().get("Version")
            info["docker"] = True
        except Exception as e:  # any failure means "not reachable"
            info["error"] = f"docker: {type(e).__name__}: {e}"
            return info
        try:
            img = self.client.images.get(self.settings.sandbox_image)
            info["image"] = True
            info["image_id"] = img.id
        except docker.errors.ImageNotFound:
            info["error"] = f"image {self.settings.sandbox_image} not found"
        except Exception as e:
            info["error"] = f"image: {type(e).__name__}: {e}"
        return info

    def ensure_ready(self) -> None:
        """Refuse to start without Docker and the image. Prints how to build it."""
        info = self.check()
        if not info["docker"]:
            raise SandboxUnavailable(f"Docker is not reachable: {info.get('error')}")
        if not info["image"]:
            raise SandboxUnavailable(
                f"sandbox image {self.settings.sandbox_image!r} is missing. Build it with:\n"
                "    sh apps/sandbox/image/build.sh"
            )
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Traverse-only for other local users; run directories have random names.
        os.chmod(self.work_dir, 0o711)

    def selfcheck(self) -> RunResult:
        """Run a trivial program end to end: catches "mounts denied", a bad work dir or runtime."""
        result = self.run("import json; print(json.dumps({'ok': True}))", {}, [], timeout_s=20)
        if result.exit_code != 0 or '"ok": true' not in result.stdout:
            raise SandboxUnavailable(
                "self-check container failed: "
                f"exit={result.exit_code} stderr={result.stderr[:500]!r}"
            )
        return result

    # -- one run ------------------------------------------------------------------------------

    def prepare(self, code: str, inputs: dict[str, Any]) -> RunDir:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="run-", dir=self.work_dir))
        # The container user (10002) is not us: directories must be world-traversable and
        # out/ world-writable. Nothing secret lives here beyond what the program may read anyway.
        os.chmod(root, 0o755)
        in_dir = root / "in"
        out_dir = root / "out"
        in_dir.mkdir(mode=0o755)
        out_dir.mkdir(mode=0o777)
        os.chmod(out_dir, 0o777)  # mkdir's mode is subject to the umask
        main_py = root / "main.py"
        inputs_json = root / "inputs.json"
        main_py.write_text(code, encoding="utf-8")
        inputs_json.write_text(json.dumps(inputs, ensure_ascii=False), encoding="utf-8")
        os.chmod(main_py, 0o644)
        os.chmod(inputs_json, 0o644)
        return RunDir(root, in_dir, out_dir, main_py, inputs_json)

    def run(
        self,
        code: str,
        inputs: dict[str, Any],
        files: list[tuple[str, bytes]],
        *,
        timeout_s: int,
        prepared: RunDir | None = None,
    ) -> RunResult:
        """Run `code` in a fresh container. `files` are (name, bytes) written to in/ when no
        prepared RunDir is given (the HTTP path fetches into the RunDir itself)."""
        rd = prepared or self.prepare(code, inputs)
        if prepared is None:
            for name, data in files:
                (rd.in_dir / name).write_bytes(data)
                os.chmod(rd.in_dir / name, 0o644)
        try:
            return self._run_container(rd, timeout_s)
        finally:
            self.cleanup(rd)

    def container_config(self, rd: RunDir, run_id: str) -> dict[str, Any]:
        """The exact HostConfig we hand to Docker. Mirrored in README.md as `docker run` flags."""
        s = self.settings
        cfg: dict[str, Any] = dict(
            image=s.sandbox_image,
            command=["python", "/work/main.py"],
            name=f"ybsb-{run_id}",
            user=f"{SANDBOX_UID}:{SANDBOX_UID}",
            working_dir="/work",
            hostname="sandbox",
            network_mode="none",
            read_only=True,
            tmpfs={"/work": "size=256m,mode=1777", "/tmp": "size=64m,mode=1777"},
            mounts=[
                Mount("/work/in", str(rd.in_dir), type="bind", read_only=True),
                Mount("/work/out", str(rd.out_dir), type="bind", read_only=False),
                Mount("/work/main.py", str(rd.main_py), type="bind", read_only=True),
                Mount("/work/inputs.json", str(rd.inputs_json), type="bind", read_only=True),
            ],
            mem_limit="512m",
            memswap_limit="512m",
            nano_cpus=1_000_000_000,
            pids_limit=64,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            # The image's ENV (PATH, MPLBACKEND, ...) stays; nothing from this process leaks in.
            environment={
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "PYTHONSAFEPATH": "1",
                "HOME": "/tmp",
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": "/tmp/mpl",
                "LANG": "C.UTF-8",
            },
            init=True,
            stdin_open=False,
            tty=False,
            detach=True,
            log_config=LogConfig(
                type="json-file", config={"max-size": LOG_FILE_CAP, "max-file": "1"}
            ),
            labels={"app": "yearbook", "yearbook.sandbox": "1", "yearbook.run_id": run_id},
        )
        if s.sandbox_runtime:
            cfg["runtime"] = s.sandbox_runtime
        return cfg

    def _run_container(self, rd: RunDir, timeout_s: int) -> RunResult:
        run_id = uuid.uuid4().hex[:12]
        cfg = self.container_config(rd, run_id)
        t0 = time.monotonic()
        try:
            container = self.client.containers.create(**cfg)
        except docker.errors.ImageNotFound as e:
            raise SandboxUnavailable(f"image {self.settings.sandbox_image} missing") from e
        except docker.errors.APIError as e:
            raise SandboxUnavailable(f"docker create failed: {e.explanation or e}") from e
        t_created = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        oom_killed = False
        warnings: list[str] = []
        try:
            container.start()
            t_started = time.monotonic()
            try:
                status = container.wait(timeout=timeout_s)
                exit_code = status.get("StatusCode")
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                timed_out = True
                self._kill(container)
                try:
                    exit_code = container.wait(timeout=10).get("StatusCode")
                except Exception:  # the container is being removed anyway
                    exit_code = None
            t_done = time.monotonic()
            try:
                container.reload()
                oom_killed = bool(container.attrs.get("State", {}).get("OOMKilled"))
            except docker.errors.APIError:
                pass
            stdout = _cap(container.logs(stdout=True, stderr=False))
            stderr = _cap(container.logs(stdout=False, stderr=True))
            files = collect_output(rd.out_dir, warnings)
            result = RunResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=int((t_done - t_started) * 1000),
                timed_out=timed_out,
                oom_killed=oom_killed,
                files=files,
                warnings=warnings,
                create_ms=int((t_created - t0) * 1000),
                start_ms=int((t_started - t_created) * 1000),
            )
            log.info(
                "run %s exit=%s timed_out=%s oom=%s duration_ms=%d create_ms=%d start_ms=%d "
                "stdout=%d stderr=%d files=%d",
                run_id,
                exit_code,
                timed_out,
                oom_killed,
                result.duration_ms,
                result.create_ms,
                result.start_ms,
                len(stdout),
                len(stderr),
                len(files),
            )
            return result
        finally:
            try:
                container.remove(force=True, v=True)
            except docker.errors.NotFound:
                pass
            except docker.errors.APIError as e:
                log.warning("remove %s failed: %s", run_id, e)

    @staticmethod
    def _kill(container: Any) -> None:
        try:
            container.kill()
        except docker.errors.APIError:
            # Already dead, or the daemon is slow; stop(timeout=0) is the second hammer.
            with contextlib.suppress(docker.errors.APIError):
                container.stop(timeout=0)

    def cleanup(self, rd: RunDir) -> None:
        shutil.rmtree(rd.root, ignore_errors=True)
        if not rd.root.exists():
            return
        # On a native Linux host the program may have created subdirectories owned by uid 10002
        # that we cannot delete. A root helper container on the same image removes them.
        try:
            self.client.containers.run(
                self.settings.sandbox_image,
                ["sh", "-c", "find /clean -mindepth 1 -delete"],
                user="0:0",
                network_mode="none",
                mounts=[Mount("/clean", str(rd.root), type="bind", read_only=False)],
                remove=True,
                cap_drop=["ALL"],
                cap_add=["DAC_OVERRIDE", "FOWNER"],
                security_opt=["no-new-privileges"],
                mem_limit="64m",
                pids_limit=16,
            )
        except docker.errors.DockerException as e:
            log.warning("cleanup helper failed for %s: %s", rd.root, e)
        shutil.rmtree(rd.root, ignore_errors=True)


def _cap(raw: bytes) -> str:
    if len(raw) > MAX_STREAM_BYTES:
        return raw[:MAX_STREAM_BYTES].decode("utf-8", errors="replace") + TRUNCATED
    return raw.decode("utf-8", errors="replace")


def collect_output(out_dir: Path, warnings: list[str]) -> list[OutputFile]:
    """Pick up what the program left in /work/out. Regular files only (never follow symlinks:
    they would resolve on the host), whitelisted types, at most MAX_OUTPUT_FILES and 50 MB."""
    candidates: list[tuple[str, Path, int]] = []
    try:
        entries = sorted(os.listdir(out_dir))
    except OSError as e:
        warnings.append(f"could not list /work/out: {e}")
        return []
    for name in entries:
        p = out_dir / name
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            warnings.append(f"{name}: not a regular file, skipped")
            continue
        candidates.append((name, p, st.st_size))
    total = sum(size for _, _, size in candidates)
    if total > MAX_OUTPUT_TOTAL_BYTES:
        warnings.append(
            f"/work/out holds {total} bytes, more than {MAX_OUTPUT_TOTAL_BYTES}; no files returned"
        )
        return []
    out: list[OutputFile] = []
    for name, p, _ in candidates:
        if len(out) >= MAX_OUTPUT_FILES:
            warnings.append(f"{name}: more than {MAX_OUTPUT_FILES} files, skipped")
            continue
        ext = os.path.splitext(name)[1].lower()
        spec = MIME_BY_EXT.get(ext)
        if spec is None:
            warnings.append(f"{name}: type {ext or '<none>'!r} not allowed, skipped")
            continue
        mime, magics = spec
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read()
        if magics and not any(data.startswith(m) for m in magics):
            warnings.append(f"{name}: content does not look like {mime}, skipped")
            continue
        if not magics:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                warnings.append(f"{name}: not UTF-8 text, skipped")
                continue
        out.append(
            OutputFile(
                name=name, mime=mime, size=len(data), bytes_b64=base64.b64encode(data).decode()
            )
        )
    return out
