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
    
    # AWS
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    aws_s3_artifacts_bucket: str = "etl-agent-artifacts"
    
    # Airflow
    airflow_api_url: str = "http://localhost:8080"
    airflow_dag_id: str = "etl_agent_pipeline"
    airflow_username: str = "admin"
    airflow_password: str = "admin"
    
    # API
    api_key: str
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
