"""Pydantic models for user stories, ETL specs, and results."""
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field


class Operation(str, Enum):
    """ETL operation types."""
    FILTER = "filter"
    JOIN = "join"
    AGGREGATE = "aggregate"
    DEDUPE = "dedupe"
    ENRICH = "enrich"
    UPSERT = "upsert"
    FILL_NULL = "fill_null"
    RENAME = "rename"
    CAST = "cast"
    SORT = "sort"


class DeltaOperation(str, Enum):
    """Delta Lake write operations."""
    CREATE = "create"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    UPDATE = "update"
    DELETE = "delete"


class RunStatus(str, Enum):
    """Pipeline run status."""
    PENDING = "PENDING"
    CODING = "CODING"
    TESTING = "TESTING"
    PR_CREATING = "PR_CREATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DEPLOYING = "DEPLOYING"
    DONE = "DONE"
    FAILED = "FAILED"


class DataSource(BaseModel):
    """Data source specification."""
    path: str
    format: str = "parquet"
    schema_hint: dict | None = None


class Transformation(BaseModel):
    """Single transformation step."""
    operation: Operation
    description: str = ""
    config: dict = Field(default_factory=dict)


class UserStory(BaseModel):
    """User story input."""
    id: str
    title: str
    description: str
    acceptance_criteria: list[str] = []
    source: DataSource
    target: DataSource
    transformations: list[Transformation]
    tags: list[str] = []


class ETLSpec(BaseModel):
    """Structured ETL specification."""
    story_id: str
    pipeline_name: str
    description: str
    operations: list[Operation]
    source: DataSource
    target: DataSource
    transformations: list[Transformation]
    delta_operation: DeltaOperation = DeltaOperation.OVERWRITE
    requires_broadcast_join: bool = False
    partition_columns: list[str] = []
    estimated_complexity: str = "medium"


class TestResult(BaseModel):
    """Test execution result."""
    passed: bool
    total_tests: int
    passed_tests: int
    failed_tests: int
    coverage_pct: float
    output: str
    failed_test_names: list[str] = []


class RunResult(BaseModel):
    """Final pipeline run result."""
    run_id: UUID
    story_id: str
    status: RunStatus
    etl_spec: ETLSpec | None = None
    test_result: TestResult | None = None
    github_issue_url: str | None = None
    github_pr_url: str | None = None
    s3_artifact_url: str | None = None
    airflow_dag_run_id: str | None = None
    retry_count: int = 0
    error_message: str | None = None
