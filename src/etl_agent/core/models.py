"""Pydantic models for user stories, ETL specs, and results."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DataClassification(StrEnum):
    """Dataset sensitivity classification — drives approval and retention policy."""

    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class Operation(StrEnum):
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


class ETLOperation(StrEnum):
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
    filter = "filter"
    join = "join"
    aggregate = "aggregate"
    dedupe = "dedupe"
    enrich = "enrich"
    upsert = "upsert"
    fill_null = "fill_null"
    rename = "rename"
    cast = "cast"
    sort = "sort"


class DeltaOperation(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    UPDATE = "update"
    DELETE = "delete"


class OutputFormat(StrEnum):
    delta = "delta"
    parquet = "parquet"
    csv = "csv"
    json = "json"
    script = "script"
    DELTA = "delta"
    PARQUET = "parquet"
    SCRIPT = "script"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    PARSING = "PARSING"
    CODING = "CODING"
    TESTING = "TESTING"
    PR_CREATING = "PR_CREATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DEPLOYING = "DEPLOYING"
    DONE = "DONE"
    FAILED = "FAILED"
    DRY_RUN_COMPLETE = "DRY_RUN_COMPLETE"


class DataSource(BaseModel):
    path: str
    format: str = "parquet"
    schema_hint: dict | None = None
    mode: str = "overwrite"


DataTarget = DataSource


class Transformation(BaseModel):
    operation: Operation
    description: str = ""
    config: dict = Field(default_factory=dict)


class TransformationStep(BaseModel):
    operation: Operation | ETLOperation
    name: str = ""
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    column: str | None = None
    condition: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class UserStory(BaseModel):
    """User story input with governance field constraints."""

    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[\w\-\.]+$")
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1, max_length=2000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    source: DataSource
    target: DataSource
    transformations: list[TransformationStep | Transformation] = []
    tags: list[str] = Field(default_factory=list, max_length=20)
    output_format: str = "script"
    data_classification: DataClassification = DataClassification.internal

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def validate_criteria(cls, v: list) -> list:
        for item in v:
            if len(str(item)) > 500:
                raise ValueError("Each acceptance criterion must be 500 characters or fewer.")
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v: list) -> list:
        for tag in v:
            if len(str(tag)) > 50:
                raise ValueError("Each tag must be 50 characters or fewer.")
        return v


class ETLSpec(BaseModel):
    story_id: str = ""
    pipeline_name: str
    pipeline_version: str = "1.0.0"
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
    passed: bool
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    coverage_pct: float = 0.0
    output: str = ""
    failed_test_names: list[str] = []
    num_passed: int = 0
    num_failed: int = 0
    error_output: str = ""

    def model_post_init(self, __context: Any) -> None:
        if self.passed_tests == 0 and self.num_passed:
            object.__setattr__(self, "passed_tests", self.num_passed)
        if self.failed_tests == 0 and self.num_failed:
            object.__setattr__(self, "failed_tests", self.num_failed)
        if not self.output and self.error_output:
            object.__setattr__(self, "output", self.error_output)
        if self.total_tests == 0:
            object.__setattr__(self, "total_tests", self.passed_tests + self.failed_tests)
        if self.num_passed == 0 and self.passed_tests:
            object.__setattr__(self, "num_passed", self.passed_tests)
        if self.num_failed == 0 and self.failed_tests:
            object.__setattr__(self, "num_failed", self.failed_tests)
        if not self.error_output and self.output:
            object.__setattr__(self, "error_output", self.output)


class RunResult(BaseModel):
    run_id: Any
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
    token_usage: dict | None = None
    cost_usd: float | None = None
    data_classification: DataClassification = DataClassification.internal
    approval_required: bool = False
