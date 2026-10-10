"""Settings from the environment (mise loads the repo's .env)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hard limits of the contract (docs/CONVENTIONS.md, "Sandbox"). Not configurable on purpose.
MAX_CODE_CHARS = 20_000
MAX_INPUTS_BYTES = 1_000_000
MAX_FILES = 20
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TIMEOUT_S = 20
DEFAULT_TIMEOUT_S = 10
MAX_STREAM_BYTES = 1024 * 1024
MAX_OUTPUT_FILES = 10
MAX_OUTPUT_TOTAL_BYTES = 50 * 1024 * 1024
FETCH_TIMEOUT_S = 10.0
SANDBOX_UID = 10002


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    sandbox_image: str = "yearbook-sandbox:latest"
    sandbox_max_parallel: int = Field(default=2, ge=1, le=64)
    # Seconds a request waits for a free slot before it is answered with 429.
    sandbox_queue_wait_s: float = 5.0
    # OCI runtime passed to Docker; "runsc" for gVisor in production, empty for the default runc.
    sandbox_runtime: str = ""
    # Per-run directories live here. Must be visible to the Docker daemon under the SAME path:
    # under Docker Desktop that means a shared directory (home is, /tmp is not); when the service
    # itself runs in a container the directory must be bind-mounted from the host at this path.
    sandbox_work_dir: Path = Path("~/.cache/yearbook-sandbox")
    # Extra "host[:port]" entries allowed for file URLs (tests, local tooling). Comma separated.
    sandbox_allowed_hosts: str = ""

    public_base_url: str = ""
    s3_endpoint: str = ""
    s3_presign_endpoint: str = ""

    @property
    def work_dir(self) -> Path:
        return self.sandbox_work_dir.expanduser()

    @property
    def allowed_hosts(self) -> frozenset[str]:
        hosts: set[str] = set()
        for url in (self.public_base_url, self.s3_endpoint, self.s3_presign_endpoint):
            if url:
                netloc = urlparse(url if "//" in url else f"//{url}").netloc.lower()
                if netloc:
                    hosts.add(netloc)
        for entry in self.sandbox_allowed_hosts.split(","):
            if entry.strip():
                hosts.add(entry.strip().lower())
        return frozenset(hosts)


def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]
