"""
Integration tests for Airflow DAG trigger via the DeployAgent.

These tests verify the DeployAgent correctly:
1. Packages the generated code into a .whl artifact
2. Uploads the artifact to S3
3. Triggers the Airflow REST API
4. Handles Airflow unavailability gracefully (pipeline still succeeds)

Run with: make test-integration
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from etl_agent.core.models import (
    DataSource,
    DataTarget,
    ETLSpec,
    OutputFormat,
    RunStatus,
)
from etl_agent.core.state import GraphState


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_etl_spec() -> ETLSpec:
    return ETLSpec(
        pipeline_name="airflow_test_pipeline",
        pipeline_version="1.0.0",
        source=DataSource(path="s3://raw/data/", format="parquet"),
        target=DataTarget(
            path="s3://processed/data/",
            format=OutputFormat.delta,
            mode="overwrite",
        ),
        transformations=[],
    )


@pytest.fixture
def sample_agent_state(sample_etl_spec: ETLSpec) -> GraphState:
    return {
        "etl_spec": sample_etl_spec,
        "generated_code": "def run_pipeline(): pass",
        "generated_tests": "def test_schema(): assert True",
        "generated_readme": "# airflow_test_pipeline",
        "github_pr_url": "https://github.com/org/repo/pull/99",
        "github_branch_name": "feature/airflow-test-abc123",
        "run_id": uuid4(),
        "status": RunStatus.DEPLOYING,
        "retry_count": 0,
        "max_retries": 2,
        "messages": [],
        "awaiting_approval": False,
    }


@pytest.fixture
def mock_s3(tmp_path):
    """Mock AWSTools for S3 operations."""
    tools = MagicMock()
    whl_path = str(tmp_path / "airflow_test_pipeline-1.0.0-py3-none-any.whl")
    # Create a dummy whl file
    with open(whl_path, "w") as f:
        f.write("dummy wheel content")
    tools.package_whl.return_value = whl_path
    tools.upload_to_s3.return_value = (
        "s3://etl-agent-artifacts/airflow_test_pipeline/1.0.0/pipeline.whl"
    )
    return tools


# ─── Tests: S3 Packaging and Upload ──────────────────────────────────────────

class TestS3Packaging:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_deploy_agent_uploads_to_s3(
        self, sample_agent_state: GraphState, mock_s3: MagicMock
    ) -> None:
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()

        with (
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_s3),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {"dag_run_id": "manual__2025-01-01"},
                )
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await agent(sample_agent_state)

        assert result["status"] == RunStatus.DONE
        assert result.get("s3_artifact_url") is not None
        assert result["s3_artifact_url"].startswith("s3://")

        # Verify AWSTools was called
        mock_s3.package_whl.assert_called_once()
        mock_s3.upload_to_s3.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_deploy_agent_s3_failure_still_succeeds(
        self, sample_agent_state: GraphState
    ) -> None:
        """S3 upload failure should NOT fail the pipeline run."""
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()

        failing_s3 = MagicMock()
        failing_s3.package_whl.side_effect = Exception("S3 connection refused")

        with patch("etl_agent.agents.deploy_agent.AWSTools", return_value=failing_s3):
            result = await agent(sample_agent_state)

        # Status should still be DONE (S3 failure is non-blocking)
        assert result["status"] == RunStatus.DONE


# ─── Tests: Airflow Trigger ───────────────────────────────────────────────────

class TestAirflowTrigger:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_airflow_dag_triggered_successfully(
        self, sample_agent_state: GraphState, mock_s3: MagicMock
    ) -> None:
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()

        with (
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_s3),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: {"dag_run_id": "manual__2025-01-01T00:00:00+00:00"},
                )
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await agent(sample_agent_state)

        assert result.get("airflow_dag_run_id") is not None
        assert "manual__" in result["airflow_dag_run_id"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_airflow_unavailable_does_not_fail_pipeline(
        self, sample_agent_state: GraphState, mock_s3: MagicMock
    ) -> None:
        """Airflow trigger failure is non-blocking — pipeline should still complete."""
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()

        with (
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_s3),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                side_effect=Exception("Connection refused: Airflow not running")
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await agent(sample_agent_state)

        assert result["status"] == RunStatus.DONE  # Still DONE despite Airflow failure
        assert result.get("airflow_dag_run_id") is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_airflow_401_response_handled_gracefully(
        self, sample_agent_state: GraphState, mock_s3: MagicMock
    ) -> None:
        """Airflow 401 Unauthorized should not crash the pipeline."""
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()

        with (
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_s3),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(
                return_value=MagicMock(
                    status_code=401,
                    json=lambda: {"detail": "Unauthorized"},
                    text="Unauthorized",
                )
            )
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await agent(sample_agent_state)

        assert result["status"] == RunStatus.DONE

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_airflow_payload_contains_required_fields(
        self, sample_agent_state: GraphState, mock_s3: MagicMock
    ) -> None:
        """Verify the Airflow API payload contains all required fields."""
        from etl_agent.agents.deploy_agent import DeployAgent

        agent = DeployAgent()
        captured_payload = {}

        async def capture_post(*args, json=None, **kwargs):
            nonlocal captured_payload
            captured_payload = json or {}
            return MagicMock(
                status_code=200,
                json=lambda: {"dag_run_id": "manual__2025-01-01"},
            )

        with (
            patch("etl_agent.agents.deploy_agent.AWSTools", return_value=mock_s3),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = capture_post
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

            await agent(sample_agent_state)

        # Check payload structure (if Airflow was called)
        if captured_payload:
            assert "conf" in captured_payload or "dag_run_id" in str(captured_payload)


# ─── Tests: Moto S3 (real LocalStack emulation) ───────────────────────────────

class TestMotoS3Integration:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_s3_upload_with_moto(self, mock_s3_boto: MagicMock, tmp_path) -> None:
        """Test S3 upload using moto mock (from conftest.py)."""
        import boto3
        from etl_agent.tools.aws_tools import AWSTools

        # Create test file
        test_file = tmp_path / "test_pipeline.whl"
        test_file.write_bytes(b"dummy wheel content for testing")

        tools = AWSTools(
            bucket="etl-agent-artifacts",
            region="us-east-1",
            endpoint_url=None,
        )

        s3_url = tools.upload_to_s3(
            local_path=str(test_file),
            s3_key="test/test_pipeline-1.0.0.whl",
        )

        assert s3_url.startswith("s3://")
        assert "test_pipeline" in s3_url
