"""
Shared pytest fixtures for unit and integration tests.
All external services (AWS S3, GitHub) are mocked here.

S3 fixtures now use LocalStack instead of moto.
Start LocalStack before running integration tests:
  cd infra && docker-compose up -d localstack
"""

# ── Disable LangSmith/LangChain tracing ───────────────────────────────────────
# This MUST happen at module level, before any test modules import langchain_core.
# The tracer caches its enabled state; env-var-only fixes in function-scoped
# fixtures run too late.  We also directly monkey-patch tracing_is_enabled() so
# the tracer stays off even if it has already cached a True value.
import contextlib
import os

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_API_KEY", None)
os.environ.pop("LANGSMITH_API_KEY", None)

try:
    import langsmith.utils as _ls_utils  # noqa: E402

    _ls_utils.tracing_is_enabled = lambda: False  # override any cached True
    _ls_utils.test_tracking_is_disabled = lambda: True
except Exception:  # langsmith not installed or API changed
    pass

try:
    from langsmith import utils as _ls2

    _ls2.tracing_is_enabled = lambda: False
except Exception:
    pass

import asyncio
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import boto3  # type: ignore[import]
import pytest

from etl_agent.core.models import (
    DataSource,
    DataTarget,
    ETLOperation,
    ETLSpec,
    OutputFormat,
    TransformationStep,
    UserStory,
)

# ── LocalStack config ──────────────────────────────────────────────────────────
# Use AWS_ENDPOINT_URL env var if set (e.g. inside docker-compose: http://localstack:4566)
# otherwise fall back to the host-accessible default.
_LOCALSTACK_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
_LOCALSTACK_CREDS = {
    "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
}


def _localstack_s3_client(region: str = "us-east-1") -> Any:
    """Return a boto3 S3 client pointed at LocalStack."""
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=_LOCALSTACK_ENDPOINT,
        **_LOCALSTACK_CREDS,
    )


def _delete_bucket(client: Any, bucket: str) -> None:
    """Empty and delete an S3 bucket (best-effort)."""
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                client.delete_object(Bucket=bucket, Key=obj["Key"])
        client.delete_bucket(Bucket=bucket)
    except Exception:
        pass  # bucket may not exist; ignore


# ── Event Loop ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ── AWS S3 Fixture (LocalStack) ────────────────────────────────────────────────
@pytest.fixture
def mock_s3() -> Generator[Any, None, None]:
    """LocalStack-backed S3 client with test buckets pre-created.

    Requires LocalStack to be running:
      cd infra && docker-compose up -d localstack
    """
    buckets = ["test-raw", "test-processed", "test-artifacts"]
    client = _localstack_s3_client()
    for bucket in buckets:
        with contextlib.suppress(client.exceptions.BucketAlreadyOwnedByYou):
            client.create_bucket(Bucket=bucket)

    yield client

    for bucket in buckets:
        _delete_bucket(client, bucket)


# ── GitHub Mock ────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_github() -> Generator[MagicMock, None, None]:
    """Mocked PyGitHub client."""
    with patch("etl_agent.tools.github_tools.Github") as mock:
        mock_repo = MagicMock()
        mock_repo.create_issue.return_value = MagicMock(
            html_url="https://github.com/test/repo/issues/1", number=1
        )
        mock_repo.create_pull.return_value = MagicMock(
            html_url="https://github.com/test/repo/pull/1"
        )
        mock.return_value.get_repo.return_value = mock_repo
        yield mock


# ── Sample User Story ──────────────────────────────────────────────────────────
@pytest.fixture
def sample_story() -> UserStory:
    """A minimal valid UserStory for testing."""
    return UserStory(
        id="story-test-001",
        title="Test: Clean nulls in customer data",
        description="Filter null customer_ids from the customer table.",
        acceptance_criteria=["Rows with null customer_id must be removed"],
        source=DataSource(
            path="s3://test-raw/customers.parquet",
            format="parquet",
        ),
        target=DataTarget(
            path="s3://test-processed/customers_clean",
            format="delta",
        ),
        transformations=[
            TransformationStep(
                operation=ETLOperation.FILTER,
                column="customer_id",
                condition="is_not_null",
            )
        ],
        output_format=OutputFormat.SCRIPT,
        tags=["test"],
    )


# ── Sample ETL Spec ────────────────────────────────────────────────────────────
@pytest.fixture
def sample_etl_spec(sample_story: UserStory) -> ETLSpec:
    """A minimal valid ETLSpec parsed from the sample story."""
    return ETLSpec(
        story_id=sample_story.id,
        pipeline_name="clean_nulls_pipeline",
        description="Filter null customer_ids from the customer table.",
        operations=[ETLOperation.FILTER],
        source=sample_story.source,
        target=sample_story.target,
        transformations=sample_story.transformations,
        partition_columns=["year", "month"],
    )


# ── Story YAML Loader ──────────────────────────────────────────────────────────
@pytest.fixture
def load_story():
    """Factory fixture: loads a story YAML from the fixtures directory."""
    import yaml

    def _load(story_name: str) -> UserStory:
        path = f"tests/fixtures/stories/{story_name}.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        return UserStory(**data)

    return _load
