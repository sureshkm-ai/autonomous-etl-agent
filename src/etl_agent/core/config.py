"""Application configuration via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 8096
    llm_temperature: float = 0.2

    # ── API auth ──────────────────────────────────────────────────────────────
    api_key: str = "changeme"

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = ""

    # ── AWS ───────────────────────────────────────────────────────────────────
    s3_bucket: str = ""
    aws_region: str = "us-east-1"
    s3_region: str = "us-east-1"  # kept for backward-compat
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # ── SQS (ECS Fargate mode — leave empty for local/EC2 BackgroundTasks) ───
    sqs_queue_url: str = ""  # set to the pipeline queue URL in ECS
    sqs_dlq_url: str = ""
    sqs_visibility_timeout: int = 900  # must match Terraform visibility_timeout

    # ── Database ──────────────────────────────────────────────────────────────
    # Local dev  : sqlite+aiosqlite:///./etl_agent.db
    # ECS Fargate: postgresql+asyncpg://user:pass@rds-host:5432/etl_agent
    database_url: str = "sqlite+aiosqlite:///./etl_agent.db"

    # ── LLM governance ────────────────────────────────────────────────────────
    max_tokens_per_run: int = 500_000
    budget_approval_threshold_pct: float = 75.0
    approved_models: str = "claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5-20251001"
    fallback_model: str = "claude-sonnet-4-6"

    # ── Pipeline behaviour ────────────────────────────────────────────────────
    max_retries: int = 2
    require_human_approval: bool = False
    airflow_enabled: bool = False
    airflow_url: str = ""
    airflow_username: str = "airflow"
    airflow_password: str = "airflow"

    # ── Misc ──────────────────────────────────────────────────────────────────
    debug: bool = False
    redis_url: str | None = None
    environment: str = "production"

    # ── Security ─────────────────────────────────────────────────────────────
    cors_origins: str = "*"
    max_request_body_bytes: int = 32_768

    # ── Derived properties ───────────────────────────────────────────────────

    @property
    def approved_model_list(self) -> list[str]:
        return [m.strip() for m in self.approved_models.split(",") if m.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_sqs(self) -> bool:
        """True when SQS is configured — enables the ECS Fargate async mode."""
        return bool(self.sqs_queue_url.strip())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
