"""
Integration-test fixtures.

Provides:
- ``mock_s3_boto``  — moto-backed S3 with the 'etl-agent-artifacts' bucket pre-created.
- ``patch_api_key`` — autouse fixture that sets API_KEY=test-api-key in the process
  environment and clears the lru_cache on get_settings() so the middleware picks it up.
"""
from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def mock_s3_boto() -> Generator[Any, None, None]:
    """Moto-backed AWS S3 mock with the artifacts bucket pre-created.

    Used by TestMotoS3Integration to test AWSTools without a real AWS account.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        # Pre-create the bucket the test will upload into
        client.create_bucket(Bucket="etl-agent-artifacts")
        yield client


@pytest.fixture(autouse=True)
def patch_api_key() -> Generator[None, None, None]:
    """Force API_KEY=test-api-key for every integration test.

    The FastAPI APIKeyMiddleware reads api_key from settings on every request.
    Because get_settings() is @lru_cache we must clear the cache so the new
    env var is picked up when create_app() / middleware initialises settings.
    """
    from etl_agent.core.config import get_settings

    original = os.environ.get("API_KEY")
    os.environ["API_KEY"] = "test-api-key"
    get_settings.cache_clear()

    yield

    # Restore
    if original is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = original
    get_settings.cache_clear()
