<<<<<<< HEAD
"""Application configuration via pydantic-settings."""
from functools import lru_cache

=======
"""Configuration management using Pydantic settings."""
from functools import lru_cache
>>>>>>> main
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
<<<<<<< HEAD
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
    s3_region: str = "us-east-1"        # kept for backward-compat
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # ── SQS (ECS Fargate mode — leave empty for local/EC2 BackgroundTasks) ───
    sqs_queue_url: str = ""             # set to the pipeline queue URL in ECS
    sqs_dlq_url: str = ""
    sqs_visibility_timeout: int = 900   # must match Terraform visibility_timeout

    # ── Database ──────────────────────────────────────────────────────────────
    # Local dev  : sqlite+aiosqlite:///./etl_agent.db
    # ECS Fargate: postgresql+asyncpg://user:pass@rds-host:5432/etl_agent
    database_url: str = "sqlite+aiosqlite:///./etl_agent.db"

    # ── LLM governance ────────────────────────────────────────────────────────
    max_tokens_per_run: int = 500_000
    budget_approval_threshold_pct: float = 75.0
    approved_models: str = (
        "claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5-20251001"
    )
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
=======
    """Application settings from environment variables."""

    # Anthropic
    anthropic_api_key: str
    llm_model: str = "claude-sonnet-4-20250514"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.7

    # GitHub
    github_token: str
    github_target_repo: str

    # AWS — optional so EC2 IAM instance profiles work without explicit credentials
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    aws_s3_raw_bucket: str = "etl-agent-raw"
    aws_s3_processed_bucket: str = "etl-agent-processed"
    aws_s3_artifacts_bucket: str = "etl-agent-artifacts"

    # Database
    database_url: str = "sqlite+aiosqlite:///./etl_agent.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Airflow — set airflow_enabled=false to skip triggering (e.g. when Airflow is not deployed)
    airflow_enabled: bool = False
    airflow_api_url: str = "http://localhost:8080"
    airflow_dag_id: str = "etl_agent_pipeline"
    airflow_username: str = "admin"
    airflow_password: str = "admin"

    # API
    api_key: str
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    # Pipeline
    max_retries: int = 2
    require_human_approval: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
>>>>>>> main
    return Settings()
