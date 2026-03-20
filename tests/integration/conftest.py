"""
Integration-test fixtures.

Provides:
- ``mock_s3_boto``  — LocalStack-backed S3 with the 'etl-agent-artifacts' bucket
                      pre-created.  Requires LocalStack to be running.
- ``patch_api_key`` — autouse fixture that sets API_KEY=test-api-key, disables
  LangSmith/LangChain tracing, and clears the get_settings() lru_cache so the
  FastAPI middleware picks up the test key on every request.

Note on tracing:
  The definitive tracing kill-switch is the module-level monkey-patch in
  tests/conftest.py — it replaces langsmith.utils.tracing_is_enabled with
  ``lambda: False`` *before* any test module imports langchain_core, so the
  LangChainTracer is never registered and never calls subprocess.run internally.
  The env-var assignments below are a belt-and-suspenders backup.

Note on LocalStack:
  All S3 fixtures use LocalStack instead of moto so that the tests exercise
  the same boto3 code-path as production (real HTTP calls, real request
  signing, real response parsing).  The endpoint is read from the
  AWS_ENDPOINT_URL environment variable (default: http://localhost:4566).

  Start LocalStack before running integration tests:
    cd infra && docker-compose up -d localstack

  The ``_localstack_health`` session fixture checks reachability at startup
  and skips the entire integration suite with a clear message if LocalStack
  is not available, so unit tests are never affected.
"""
from __future__ import annotations

import os
import urllib.request
from collections.abc import Generator
from typing import Any

import boto3
import pytest


# ── LocalStack config (mirrors tests/conftest.py) ─────────────────────────────
_LOCALSTACK_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
_LOCALSTACK_CREDS = {
    "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
}


def _delete_bucket(client: Any, bucket: str) -> None:
    """Empty and delete an S3 bucket (best-effort)."""
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                client.delete_object(Bucket=bucket, Key=obj["Key"])
        client.delete_bucket(Bucket=bucket)
    except Exception:
        pass


# ── LocalStack health check ────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _localstack_health() -> Generator[None, None, None]:
    """Skip all integration tests with a clear message if LocalStack is down.

    This runs once per test session and applies to every test in the
    tests/integration/ directory.  Unit tests (tests/unit/) are not affected.
    """
    try:
        urllib.request.urlopen(
            f"{_LOCALSTACK_ENDPOINT}/_localstack/health",
            timeout=5,
        )
    except Exception:
        pytest.skip(
            f"\n\nLocalStack is not reachable at {_LOCALSTACK_ENDPOINT}.\n"
            "Start it before running integration tests:\n"
            "  cd infra && docker-compose up -d localstack\n"
        )
    yield


# ── S3 fixture (LocalStack) ────────────────────────────────────────────────────

@pytest.fixture
def mock_s3_boto() -> Generator[Any, None, None]:
    """LocalStack-backed S3 client with the 'etl-agent-artifacts' bucket.

    Used by TestMotoS3Integration to exercise AWSTools against a real
    (local) S3 endpoint without touching real AWS.

    The yielded client's ``meta.endpoint_url`` attribute is set to
    ``_LOCALSTACK_ENDPOINT``, so tests that forward it to AWSTools
    (e.g. ``AWSTools(endpoint_url=mock_s3_boto.meta.endpoint_url)``)
    automatically point at LocalStack.
    """
    bucket = "etl-agent-artifacts"
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=_LOCALSTACK_ENDPOINT,
        **_LOCALSTACK_CREDS,
    )
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass  # already exists from a previous test run

    yield client

    _delete_bucket(client, bucket)


# ── API key + tracing fixture ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_api_key() -> Generator[None, None, None]:
    """Force API_KEY=test-api-key and disable LangSmith tracing for every integration test."""
    from etl_agent.core.config import get_settings

    originals = {
        "API_KEY": os.environ.get("API_KEY"),
        "LANGCHAIN_TRACING_V2": os.environ.get("LANGCHAIN_TRACING_V2"),
        "LANGSMITH_TRACING": os.environ.get("LANGSMITH_TRACING"),
        "LANGCHAIN_API_KEY": os.environ.get("LANGCHAIN_API_KEY"),
        "LANGSMITH_API_KEY": os.environ.get("LANGSMITH_API_KEY"),
    }

    os.environ["API_KEY"] = "test-api-key"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGSMITH_API_KEY", None)

    get_settings.cache_clear()

    yield

    for key, value in originals.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
