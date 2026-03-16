"""
Shared pytest fixtures for unit and integration tests.
All external services (AWS S3, GitHub) are mocked here.
"""
import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
import yaml
from moto import mock_aws  # type: ignore[import]

from etl_agent.core.models import (
    DataSource,
    DataTarget,
    ETLOperation,
    ETLSpec,
    OutputFormat,
    RunStatus,
    TransformationStep,
    UserStory,
)


# ── Event Loop ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ── AWS S3 Mock ────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_s3() -> Generator[Any, None, None]:
    """Mocked AWS S3 using moto. Creates test buckets automatically."""
    import boto3  # type: ignore[import]

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        for bucket in ["test-raw", "test-processed", "test-artifacts"]:
            client.create_bucket(Bucket=bucket)
        yield client


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
    def _load(story_name: str) -> UserStory:
        path = f"tests/fixtures/stories/{story_name}.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        return UserStory(**data)
    return _load
