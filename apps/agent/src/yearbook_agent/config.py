"""Environment configuration. Loaded once at startup; `.env` at the repo root is read by mise."""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str | None = Field(default=None, alias="OPENAI_MODEL")
    # Model for the single user-initiated "describe this photo" call; defaults to OPENAI_MODEL.
    openai_vision_model: str | None = Field(default=None, alias="OPENAI_VISION_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    mcp_url: str = Field(default="http://localhost:8080/mcp", alias="MCP_URL")
    sandbox_url: str = Field(default="http://localhost:8092", alias="SANDBOX_URL")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    # Schema that holds the LangGraph checkpoint tables; the app tables stay in public.
    agent_db_schema: str = Field(default="agent", alias="AGENT_DB_SCHEMA")
    agent_port: int = Field(default=8091, alias="AGENT_PORT")

    # S3 for sandbox output files (same keys as the API and worker).
    s3_endpoint: str | None = Field(default=None, alias="S3_ENDPOINT")
    s3_presign_endpoint: str | None = Field(default=None, alias="S3_PRESIGN_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str | None = Field(default=None, alias="S3_ACCESS_KEY")
    s3_secret_key: str | None = Field(default=None, alias="S3_SECRET_KEY")
    s3_bucket_private: str = Field(default="yearbook-private", alias="S3_BUCKET_PRIVATE")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")

    # LangSmith tracing, off by default.
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str | None = Field(default=None, alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="yearbook", alias="LANGSMITH_PROJECT")

    # Loop guards (SDD §7.2).
    max_tool_rounds: int = Field(default=6, alias="AGENT_MAX_ROUNDS")
    wall_clock_s: float = Field(default=20.0, alias="AGENT_WALL_CLOCK_S")
    conversation_ttl_min: int = Field(default=30, alias="AGENT_CONVERSATION_TTL_MIN")
    tool_cache_s: float = Field(default=60.0, alias="AGENT_TOOL_CACHE_S")
    sandbox_timeout_s: int = Field(default=20, alias="AGENT_SANDBOX_TIMEOUT_S")

    @property
    def configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_endpoint and self.s3_access_key and self.s3_secret_key)

    def apply_tracing_env(self) -> None:
        """LangSmith reads its switches from the process environment; mirror ours into it."""
        if self.langsmith_tracing and self.langsmith_api_key:
            os.environ["LANGSMITH_TRACING"] = "true"
            os.environ["LANGSMITH_API_KEY"] = self.langsmith_api_key
            os.environ["LANGSMITH_PROJECT"] = self.langsmith_project
        else:
            os.environ["LANGSMITH_TRACING"] = "false"


def load_settings() -> Settings:
    return Settings()
