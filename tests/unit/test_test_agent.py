"""Unit tests for the TestAgent."""
from __future__ import annotations

import textwrap
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from etl_agent.core.models import (
    DataSource,
    DataTarget,
    ETLSpec,
    OutputFormat,
    RunStatus,
    TestResult,
)
from etl_agent.core.state import GraphState


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_etl_spec() -> ETLSpec:
    return ETLSpec(
        pipeline_name="test_pipeline",
        source=DataSource(path="/tmp/input", format="parquet"),
        target=DataTarget(path="/tmp/output", format=OutputFormat.delta, mode="overwrite"),
        transformations=[],
    )


@pytest.fixture
def sample_generated_code() -> str:
    return textwrap.dedent("""
        from pyspark.sql import SparkSession

        def run_pipeline():
            spark = SparkSession.builder.appName("test").getOrCreate()
            df = spark.read.parquet("/tmp/input")
            df.write.format("delta").mode("overwrite").save("/tmp/output")
            return {"status": "success"}

        if __name__ == "__main__":
            run_pipeline()
    """)


@pytest.fixture
def mock_test_code_response():
    return MagicMock(
        content="""
```python
import pytest
from unittest.mock import MagicMock

def test_schema_validation():
    \"\"\"Test output schema has required columns.\"\"\"
    assert True

def test_null_check():
    \"\"\"Test no null IDs in output.\"\"\"
    assert True

def test_row_count():
    \"\"\"Test output has rows.\"\"\"
    assert True

def test_business_logic():
    \"\"\"Test business logic correctness.\"\"\"
    assert True
```
"""
    )


# ─── Tests: Pytest Output Parsing ─────────────────────────────────────────────

class TestPytestOutputParsing:
    def test_parse_all_passed(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()
        output = "4 passed in 1.23s"
        result = agent._parse_pytest_output(output, return_code=0)

        assert result.passed is True
        assert result.num_passed == 4
        assert result.num_failed == 0

    def test_parse_some_failed(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()
        output = "3 passed, 1 failed in 2.00s"
        result = agent._parse_pytest_output(output, return_code=1)

        assert result.passed is False
        assert result.num_passed == 3
        assert result.num_failed == 1

    def test_parse_coverage_percentage(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()
        output = "4 passed in 1.23s\nTOTAL                          100     15    85%\n"
        result = agent._parse_pytest_output(output, return_code=0)

        assert result.coverage_pct == 85.0

    def test_parse_no_tests_collected(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()
        output = "no tests ran"
        result = agent._parse_pytest_output(output, return_code=5)

        assert result.passed is False
        assert result.num_passed == 0

    def test_parse_collection_error(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()
        output = "ERROR collecting test_pipeline.py\nImportError: No module named 'pyspark'"
        result = agent._parse_pytest_output(output, return_code=2)

        assert result.passed is False
        assert result.error_output is not None
        assert "ImportError" in result.error_output


# ─── Tests: TestAgent ─────────────────────────────────────────────────────────

class TestTestAgent:
    @pytest.mark.asyncio
    async def test_generates_and_runs_tests_successfully(
        self,
        sample_etl_spec: ETLSpec,
        sample_generated_code: str,
        mock_test_code_response: MagicMock,
    ) -> None:
        from etl_agent.agents.test_agent import TestAgent

        agent = TestAgent()

        mock_subprocess_result = MagicMock(
            returncode=0,
            stdout="4 passed in 1.23s\nTOTAL  100  10  90%\n",
            stderr="",
        )

        with (
            patch.object(agent, "_llm") as mock_llm,
            patch("etl_agent.agents.test_agent.subprocess.run", return_value=mock_subprocess_result),
        ):
            mock_llm.ainvoke = AsyncMock(return_value=mock_test_code_response)

            state: GraphState = {
                "etl_spec": sample_etl_spec,
                "generated_code": sample_generated_code,
                "run_id": uuid4(),
                "status": RunStatus.TESTING,
                "retry_count": 0,
                "max_retries": 2,
                "messages": [],
                "awaiting_approval": False,
            }

            result = await agent(state)

        assert "test_results" in result
        assert result["test_results"] is not None

    @pytest.mark.asyncio
    async def test_failed_tests_trigger_retry_routing(
        self,
        sample_etl_spec: ETLSpec,
        sample_generated_code: str,
        mock_test_code_response: MagicMock,
    ) -> None:
        from etl_agent.agents.test_agent import TestAgent
        from etl_agent.core.state import route_after_tests

        agent = TestAgent()

        mock_subprocess_result = MagicMock(
            returncode=1,
            stdout="1 passed, 2 failed in 1.00s",
            stderr="AssertionError in test_business_logic",
        )

        with (
            patch.object(agent, "_llm") as mock_llm,
            patch("etl_agent.agents.test_agent.subprocess.run", return_value=mock_subprocess_result),
        ):
            mock_llm.ainvoke = AsyncMock(return_value=mock_test_code_response)

            state: GraphState = {
                "etl_spec": sample_etl_spec,
                "generated_code": sample_generated_code,
                "run_id": uuid4(),
                "status": RunStatus.TESTING,
                "retry_count": 0,
                "max_retries": 2,
                "messages": [],
                "awaiting_approval": False,
            }

            result = await agent(state)

        # Routing should send back to coding_agent for retry
        merged_state = {**state, **result}
        route = route_after_tests(merged_state)
        assert route == "coding_agent"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_routes_to_failure(
        self,
        sample_etl_spec: ETLSpec,
        sample_generated_code: str,
        mock_test_code_response: MagicMock,
    ) -> None:
        from etl_agent.core.state import route_after_tests
        from etl_agent.core.models import TestResult

        state: GraphState = {
            "etl_spec": sample_etl_spec,
            "generated_code": sample_generated_code,
            "run_id": uuid4(),
            "status": RunStatus.TESTING,
            "retry_count": 2,   # max_retries = 2, so this is exhausted
            "max_retries": 2,
            "test_results": TestResult(
                passed=False,
                num_passed=0,
                num_failed=3,
                coverage_pct=40.0,
                error_output="Multiple failures",
            ),
            "messages": [],
            "awaiting_approval": False,
        }

        route = route_after_tests(state)
        assert route == "failure"

    def test_test_agent_instantiation(self) -> None:
        from etl_agent.agents.test_agent import TestAgent

        with patch("etl_agent.agents.test_agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                anthropic_api_key="test-key",
                llm_model="claude-sonnet-4-20250514",
                llm_max_tokens=4096,
                llm_temperature=0.7,
            )
            agent = TestAgent()
            assert agent is not None
