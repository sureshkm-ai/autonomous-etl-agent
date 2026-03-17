"""Pydantic models for user stories, ETL specs, and results."""
from enum import Enum
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


# ── Operation enums ───────────────────────────────────────────────────────────

class Operation(str, Enum):
    """ETL operation types (canonical names, uppercase)."""
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


class ETLOperation(str, Enum):
    """Backwards-compatible operation enum.

    Supports both uppercase (ETLOperation.FILTER) and lowercase
    (ETLOperation.filter) access — lowercase members are enum aliases.
    """
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
    # lowercase aliases (same value → Python Enum treats as alias)
    filter = "filter"        # noqa: PIE796
    join = "join"            # noqa: PIE796
    aggregate = "aggregate"  # noqa: PIE796
    dedupe = "dedupe"        # noqa: PIE796
    enrich = "enrich"        # noqa: PIE796
    upsert = "upsert"        # noqa: PIE796
    fill_null = "fill_null"  # noqa: PIE796
    rename = "rename"        # noqa: PIE796
    cast = "cast"            # noqa: PIE796
    sort = "sort"            # noqa: PIE796


class DeltaOperation(str, Enum):
    """Delta Lake write operations."""
    CREATE = "create"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    UPDATE = "update"
    DELETE = "delete"


class OutputFormat(str, Enum):
    """Output / target format for generated pipelines."""
    delta = "delta"
    parquet = "parquet"
    csv = "csv"
    json = "json"
    script = "script"
    # uppercase aliases
    DELTA = "delta"    # noqa: PIE796
    PARQUET = "parquet"  # noqa: PIE796
    SCRIPT = "script"  # noqa: PIE796


class RunStatus(str, Enum):
    """Pipeline run status."""
    PENDING = "PENDING"
    PARSING = "PARSING"          # used in some test stubs
    CODING = "CODING"
    TESTING = "TESTING"
    PR_CREATING = "PR_CREATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DEPLOYING = "DEPLOYING"
    DONE = "DONE"
    FAILED = "FAILED"


# ── Data models ───────────────────────────────────────────────────────────────

class DataSource(BaseModel):
    """Data source or target specification."""
    path: str
    format: str = "parquet"
    schema_hint: dict | None = None
    mode: str = "overwrite"   # write mode (relevant when used as a target)


# Backwards-compatible alias: tests construct DataTarget(path=..., format=..., mode=...)
DataTarget = DataSource


class Transformation(BaseModel):
    """Single transformation step (canonical model)."""
    operation: Operation
    description: str = ""
    config: dict = Field(default_factory=dict)


class TransformationStep(BaseModel):
    """Extended transformation model used in test stubs.

    Accepts the canonical fields plus older field names (name, params,
    column, condition) so test fixtures compile without changes.
    """
    operation: Operation | ETLOperation
    name: str = ""
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    column: str | None = None
    condition: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class UserStory(BaseModel):
    """User story input."""
    id: str
    title: str
    description: str
    acceptance_criteria: list[str] = []
    source: DataSource
    target: DataSource
    transformations: list[TransformationStep | Transformation] = []
    tags: list[str] = []
    output_format: str = "script"   # extended field used in some test stubs


class ETLSpec(BaseModel):
    """Structured ETL specification."""
    story_id: str = ""               # optional so test stubs that omit it still work
    pipeline_name: str
    pipeline_version: str = "1.0.0"  # extended field used in some test stubs
    description: str = ""
    operations: list[Operation | ETLOperation] = []
    source: DataSource
    target: DataSource
    transformations: list[TransformationStep | Transformation] = []
    delta_operation: DeltaOperation = DeltaOperation.OVERWRITE
    requires_broadcast_join: bool = False
    partition_columns: list[str] = []
    estimated_complexity: str = "medium"


class TestResult(BaseModel):
    """Test execution result.

    Provides both the canonical names used by the implementation and the
    legacy names used in early test stubs so both compile without changes.
    """
    passed: bool
    # Canonical names (used by test_agent.py)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    coverage_pct: float = 0.0
    output: str = ""
    failed_test_names: list[str] = []
    # Legacy names (used by test stubs)
    num_passed: int = 0
    num_failed: int = 0
    error_output: str = ""

    def model_post_init(self, __context: Any) -> None:
        """Keep canonical and legacy field names in sync."""
        # legacy → canonical
        if self.passed_tests == 0 and self.num_passed:
            object.__setattr__(self, "passed_tests", self.num_passed)
        if self.failed_tests == 0 and self.num_failed:
            object.__setattr__(self, "failed_tests", self.num_failed)
        if not self.output and self.error_output:
            object.__setattr__(self, "output", self.error_output)
        if self.total_tests == 0:
            object.__setattr__(self, "total_tests", self.passed_tests + self.failed_tests)
        # canonical → legacy
        if self.num_passed == 0 and self.passed_tests:
            object.__setattr__(self, "num_passed", self.passed_tests)
        if self.num_failed == 0 and self.failed_tests:
            object.__setattr__(self, "num_failed", self.failed_tests)
        if not self.error_output and self.output:
            object.__setattr__(self, "error_output", self.output)


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
