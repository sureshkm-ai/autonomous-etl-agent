"""Configuration management using Pydantic settings."""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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
    return Settings()
