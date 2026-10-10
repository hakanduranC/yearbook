"""Settings read from the environment (mise loads `.env` at the repo root)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment keys shared with api and web (see docs/CONVENTIONS.md) plus worker knobs."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    database_url: str
    test_database_url: str | None = None

    s3_endpoint: str
    s3_region: str = "us-east-1"
    s3_access_key: str
    s3_secret_key: str
    s3_force_path_style: bool = True
    s3_bucket_private: str = "yearbook-private"
    s3_bucket_public: str = "yearbook-public"
    public_base_url: str

    worker_concurrency: int = Field(default=4, ge=1)
    worker_kinds: str = "ingest"
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    worker_heartbeat_seconds: float = Field(default=30.0, gt=0)
    worker_tmp_dir: Path | None = None
    worker_log_level: str = "INFO"
    default_timezone: str = "Europe/Berlin"

    # ML (round 2). Models are downloaded on first use into `worker_models_dir`
    # (HF_HOME = <dir>/hf, InsightFace root = <dir>/insightface); `/models` in the container.
    worker_models_dir: Path = Path(__file__).resolve().parents[2] / ".cache"
    worker_tags_enabled: bool = True
    worker_siglip_model: str = "google/siglip2-so400m-patch14-384"
    worker_florence_model: str = "florence-community/Florence-2-base"
    worker_age_model: str = "iitolstykh/mivolo_v2"
    worker_face_pack: str = "antelopev2"
    worker_face_det_size: int = Field(default=640, ge=320)
    worker_face_det_thresh: float = Field(default=0.6, ge=0.1, le=1.0)
    worker_face_min_side: int = Field(default=32, ge=8)
    worker_cluster_debounce_seconds: float = Field(default=60.0, ge=0)
    worker_caption_max_tokens: int = Field(default=96, ge=16)
    worker_torch_threads: int | None = Field(default=None, ge=1)
    ml_port: int = Field(default=8090, ge=1, le=65535)

    @property
    def kinds(self) -> list[str]:
        """Job kinds this worker claims, from the comma separated `WORKER_KINDS`."""
        return [k.strip() for k in self.worker_kinds.split(",") if k.strip()]


def load_settings(**overrides: object) -> Settings:
    """Build settings from the environment, with explicit overrides for tests."""
    return Settings(**overrides)  # type: ignore[arg-type]
