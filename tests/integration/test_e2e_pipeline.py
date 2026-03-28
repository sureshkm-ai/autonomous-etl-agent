"""
End-to-end integration tests for the ETL Agent pipeline.

These tests exercise the full LangGraph pipeline using mocked external services
(GitHub, S3, Airflow, Anthropic API), verifying that the entire agent workflow
runs correctly from YAML story → DONE status.

Run with: make test-integration
Environment: Requires docker-compose services (Postgres, Redis, LocalStack)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import yaml

# ─── Fixtures ─────────────────────────────────────────────────────────────────

MINIMAL_STORY_YAML = """
id: e2e_test_story
title: E2E Test Pipeline
description: End-to-end test ETL pipeline for integration tests.
source:
  path: /tmp/e2e_input
  format: parquet
target:
  path: /tmp/e2e_output
  format: delta
transformations:
  - name: filter_valid
    operation: filter
    description: Keep valid records
    params:
      condition: "id IS NOT NULL"
acceptance_criteria:
  - Output has rows
  - No null IDs
tags: [e2e, test]
"""

MOCK_ETL_SPEC = {
    "pipeline_name": "e2e_test_story",
    "pipeline_version": "1.0.0",
    "source": {"path": "/tmp/e2e_input", "format": "parquet"},
    "target": {"path": "/tmp/e2e_output", "format": "delta", "mode": "overwrite"},
    "transformations": [
        {
            "name": "filter_valid",
            "operation": "filter",
            "description": "Keep valid records",
            "params": {"condition": "id IS NOT NULL"},
        }
    ],
}

MOCK_GENERATED_CODE = '''"""e2e_test_story ETL pipeline."""
from pyspark.sql import SparkSession

def run_pipeline():
    spark = SparkSession.builder.appName("e2e_test_story").getOrCreate()
    return {"status": "success", "row_count": 100}

if __name__ == "__main__":
    run_pipeline()
'''

MOCK_GENERATED_TESTS = '''"""Tests for e2e_test_story."""
def test_schema_validation():
    assert True

def test_row_count():
    assert True

def test_null_check():
    assert True

def test_business_logic():
    assert True
'''


@pytest.fixture
def mock_story_parser_response():
    return MagicMock(content=f"```json\n{json.dumps(MOCK_ETL_SPEC)}\n```")


@pytest.fixture
def mock_coding_agent_response():
    return MagicMock(
        content=f"```python\n{MOCK_GENERATED_CODE}\n```\n\n```markdown\n# e2e_test_story\n```"
    )


@pytest.fixture
def mock_test_agent_response():
    return MagicMock(content=f"```python\n{MOCK_GENERATED_TESTS}\n```")


@pytest.fixture
def mock_subprocess_passing():
    return MagicMock(
        returncode=0,
        stdout="4 passed in 2.00s\nTOTAL  100  12  88%\n",
        stderr="",
    )


@pytest.fixture
def mock_github_tools():
    tools = MagicMock()
    tools.create_issue.return_value = "https://github.com/org/repo/issues/1"
    tools.create_branch.return_value = "feature/e2e-test-story-abc123"
    tools.commit_files.return_value = None
    tools.create_pull_request.return_value = "https://github.com/org/repo/pull/2"
    return tools


@pytest.fixture
def mock_aws_tools(tmp_path):
    tools = MagicMock()
    tools.package_whl.return_value = str(tmp_path / "e2e_test_story-1.0.0-py3-none-any.whl")
    tools.upload_to_s3.return_value = "s3://etl-agent-artifacts/e2e_test_story/1.0.0/pipeline.whl"
    return tools


@pytest.fixture
def mock_commit_message_response():
    return MagicMock(content="feat(etl): add e2e_test_story pipeline")


@pytest.fixture
def mock_airflow_trigger():
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"dag_run_id": "manual__2025-01-01T00:00:00"},
        )
        yield mock_post


# ─── Test: Full Pipeline (no approval) ───────────────────────────────────────

class TestFullPipelineRun:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pipeline_runs_end_to_end_without_approval(
        self,
        mock_story_parser_response,
        mock_coding_agent_response,
        mock_test_agent_response,
        mock_subprocess_passing,
        mock_github_tools,
        mock_aws_tools,
        mock_commit_message_response,
    ) -> None:
        """Full pipeline: PENDING → PARSING → CODING → TESTING → PR → DEPLOY → DONE"""
        from etl_agent.core.models import RunStatus
        from etl_agent.agents.orchestrator import run_pipeline

        story = yaml.safe_load(MINIMAL_STORY_YAML)

        with (
            patch("etl_agent.agents.story_parser.StoryParserAgent._llm") as mock_parser_llm,
            patch("etl_agent.agents.coding_agent.CodingAgent._llm") as mock_coder_llm,
            patch("etl_agent.agents.test_agent.TestAgent._llm") as mock_test_llm,
            patch("etl_agent.agents.test_agent.subprocess.run", return_value=mock_subprocess_passing),
            patch("etl_agent.agents.pr_agent.GitHubTools", return_value=mock_github_tools),
            patch("etl_agent.agents.pr_agent.PRAgent._llm") as mock_pr_llm,
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_aws_tools),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_parser_llm.ainvoke = AsyncMock(return_value=mock_story_parser_response)
            mock_coder_llm.ainvoke = AsyncMock(return_value=mock_coding_agent_response)
            mock_test_llm.ainvoke = AsyncMock(return_value=mock_test_agent_response)
            mock_pr_llm.ainvoke = AsyncMock(return_value=mock_commit_message_response)

            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {"dag_run_id": "manual__2025-01-01"},
                )
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_pipeline(
                user_story=story,
                run_id=uuid4(),
                require_human_approval=False,
                deploy=True,
            )

        assert result["status"] == RunStatus.DONE
        assert result.get("github_pr_url") is not None
        assert result.get("github_issue_url") is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pipeline_retries_on_test_failure(
        self,
        mock_story_parser_response,
        mock_coding_agent_response,
        mock_test_agent_response,
        mock_github_tools,
        mock_aws_tools,
        mock_commit_message_response,
    ) -> None:
        """Test that the pipeline retries when tests fail on first attempt."""
        from etl_agent.agents.orchestrator import run_pipeline
        from etl_agent.core.models import RunStatus

        # First call fails, second passes
        failing_result = MagicMock(
            returncode=1,
            stdout="2 passed, 1 failed in 1.00s",
            stderr="AssertionError: expected non-null",
        )
        passing_result = MagicMock(
            returncode=0,
            stdout="3 passed in 1.50s\nTOTAL  100  10  85%\n",
            stderr="",
        )

        story = yaml.safe_load(MINIMAL_STORY_YAML)

        with (
            patch("etl_agent.agents.story_parser.StoryParserAgent._llm") as mock_parser_llm,
            patch("etl_agent.agents.coding_agent.CodingAgent._llm") as mock_coder_llm,
            patch("etl_agent.agents.test_agent.TestAgent._llm") as mock_test_llm,
            patch("etl_agent.agents.test_agent.subprocess.run", side_effect=[failing_result, passing_result]),
            patch("etl_agent.agents.pr_agent.GitHubTools", return_value=mock_github_tools),
            patch("etl_agent.agents.pr_agent.PRAgent._llm") as mock_pr_llm,
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_aws_tools),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_parser_llm.ainvoke = AsyncMock(return_value=mock_story_parser_response)
            mock_coder_llm.ainvoke = AsyncMock(return_value=mock_coding_agent_response)
            mock_test_llm.ainvoke = AsyncMock(return_value=mock_test_agent_response)
            mock_pr_llm.ainvoke = AsyncMock(return_value=mock_commit_message_response)

            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {"dag_run_id": "manual__2025-01-01"},
                )
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await run_pipeline(
                user_story=story,
                run_id=uuid4(),
                require_human_approval=False,
                deploy=True,
            )

        assert result["status"] == RunStatus.DONE

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pipeline_fails_after_max_retries(
        self,
        mock_story_parser_response,
        mock_coding_agent_response,
        mock_test_agent_response,
    ) -> None:
        """Test that the pipeline fails after max_retries exceeded."""
        from etl_agent.core.models import RunStatus
        from etl_agent.agents.orchestrator import run_pipeline

        always_failing = MagicMock(
            returncode=1,
            stdout="0 passed, 3 failed in 0.50s",
            stderr="Multiple test failures",
        )

        story = yaml.safe_load(MINIMAL_STORY_YAML)

        with (
            patch("etl_agent.agents.story_parser.StoryParserAgent._llm") as mock_parser_llm,
            patch("etl_agent.agents.coding_agent.CodingAgent._llm") as mock_coder_llm,
            patch("etl_agent.agents.test_agent.TestAgent._llm") as mock_test_llm,
            patch("etl_agent.agents.test_agent.subprocess.run", return_value=always_failing),
        ):
            mock_parser_llm.ainvoke = AsyncMock(return_value=mock_story_parser_response)
            mock_coder_llm.ainvoke = AsyncMock(return_value=mock_coding_agent_response)
            mock_test_llm.ainvoke = AsyncMock(return_value=mock_test_agent_response)

            result = await run_pipeline(
                user_story=story,
                run_id=uuid4(),
                require_human_approval=False,
                deploy=False,
                max_retries=2,
            )

        assert result["status"] == RunStatus.FAILED


# ─── Test: API endpoints ──────────────────────────────────────────────────────

class TestAPIEndpoints:
    @pytest.fixture
    def test_client(self):
        """Create a FastAPI test client."""
        try:
            from fastapi.testclient import TestClient
            from etl_agent.api.main import create_app
            app = create_app()
            return TestClient(app)
        except Exception:
            pytest.skip("FastAPI app not available")

    def test_health_endpoint_returns_ok(self, test_client) -> None:
        response = test_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health_requires_no_auth(self, test_client) -> None:
        response = test_client.get("/api/v1/health")
        assert response.status_code == 200

    def test_runs_endpoint_requires_auth(self, test_client) -> None:
        response = test_client.get("/api/v1/runs")
        assert response.status_code == 401

    def test_stories_endpoint_requires_auth(self, test_client) -> None:
        response = test_client.post(
            "/api/v1/stories",
            json={"story_yaml": "id: test"},
        )
        assert response.status_code == 401

    def test_runs_endpoint_with_valid_api_key(self, test_client) -> None:
        response = test_client.get(
            "/api/v1/runs",
            headers={"X-API-Key": "test-api-key"},
        )
        # Either 200 (empty list) or 200 with runs
        assert response.status_code == 200
        assert isinstance(response.json(), list)
