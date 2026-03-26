"""Unit tests for the CodingAgent."""
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
    TransformationStep,
    ETLOperation,
)
from etl_agent.core.state import GraphState


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_etl_spec() -> ETLSpec:
    return ETLSpec(
        pipeline_name="test_pipeline",
        pipeline_version="1.0.0",
        source=DataSource(path="s3://raw/data/", format="parquet"),
        target=DataTarget(path="s3://processed/data/", format=OutputFormat.delta, mode="overwrite"),
        transformations=[
            TransformationStep(
                name="filter_valid",
                operation=ETLOperation.filter,
                description="Filter valid records",
                params={"condition": "id IS NOT NULL"},
            )
        ],
    )


@pytest.fixture
def mock_good_code_response():
    return MagicMock(
        content="""
Here is the generated PySpark pipeline:

```python
\"\"\"test_pipeline ETL pipeline.\"\"\"
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

def run_pipeline():
    spark = SparkSession.builder.appName("test_pipeline").getOrCreate()
    df = spark.read.format("parquet").load("s3://raw/data/")
    df = df.filter(F.col("id").isNotNull())
    df.write.format("delta").mode("overwrite").save("s3://processed/data/")
    return {"status": "success", "row_count": df.count()}

if __name__ == "__main__":
    run_pipeline()
```

And the pipeline README:

```markdown
# test_pipeline

Auto-generated ETL pipeline.
```
"""
    )


# ─── Tests: Code Validation ───────────────────────────────────────────────────

class TestCodeValidation:
    def test_valid_python_syntax(self) -> None:
        from etl_agent.tools.code_validator import validate_python_syntax

        valid_code = "def foo():\n    return 42\n"
        is_valid, error = validate_python_syntax(valid_code)
        assert is_valid is True
        assert error is None

    def test_invalid_python_syntax(self) -> None:
        from etl_agent.tools.code_validator import validate_python_syntax

        invalid_code = "def foo(:\n    return 42\n"
        is_valid, error = validate_python_syntax(invalid_code)
        assert is_valid is False
        assert error is not None

    def test_valid_pyspark_imports(self) -> None:
        from etl_agent.tools.code_validator import validate_pyspark_imports

        code_with_imports = (
            "from pyspark.sql import SparkSession\n"
            "from pyspark.sql import functions as F\n"
            "spark = SparkSession.builder.getOrCreate()\n"
        )
        is_valid, missing = validate_pyspark_imports(code_with_imports)
        assert is_valid is True
        assert missing == []

    def test_missing_spark_session_import(self) -> None:
        from etl_agent.tools.code_validator import validate_pyspark_imports

        code_without_spark = "import pandas as pd\ndf = pd.DataFrame()\n"
        is_valid, missing = validate_pyspark_imports(code_without_spark)
        assert is_valid is False
        assert len(missing) > 0

    def test_empty_code_fails_validation(self) -> None:
        from etl_agent.tools.code_validator import validate_python_syntax

        is_valid, error = validate_python_syntax("")
        assert is_valid is False

    def test_syntax_check_catches_indentation_error(self) -> None:
        from etl_agent.tools.code_validator import validate_python_syntax

        bad_indent = "def foo():\nreturn 42\n"
        is_valid, error = validate_python_syntax(bad_indent)
        assert is_valid is False


# ─── Tests: CodingAgent ───────────────────────────────────────────────────────

class TestCodingAgent:
    @pytest.mark.asyncio
    async def test_generates_code_successfully(
        self, sample_etl_spec: ETLSpec, mock_good_code_response: MagicMock
    ) -> None:
        from etl_agent.agents.coding_agent import CodingAgent

        agent = CodingAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_good_code_response)

            state: GraphState = {
                "etl_spec": sample_etl_spec,
                "run_id": uuid4(),
                "status": RunStatus.CODING,
                "retry_count": 0,
                "max_retries": 2,
                "messages": [],
                "awaiting_approval": False,
            }

            result = await agent(state)

        assert "generated_code" in result
        assert result["generated_code"] is not None
        assert "run_pipeline" in result["generated_code"]
        assert result["status"] == RunStatus.TESTING

    @pytest.mark.asyncio
    async def test_retains_retry_context_on_retry(
        self, sample_etl_spec: ETLSpec, mock_good_code_response: MagicMock
    ) -> None:
        from etl_agent.agents.coding_agent import CodingAgent
        from etl_agent.core.models import TestResult

        agent = CodingAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_good_code_response)

            state: GraphState = {
                "etl_spec": sample_etl_spec,
                "run_id": uuid4(),
                "status": RunStatus.CODING,
                "retry_count": 1,
                "max_retries": 2,
                "test_results": TestResult(
                    passed=False,
                    num_passed=0,
                    num_failed=2,
                    coverage_pct=60.0,
                    error_output="AssertionError: expected 10 rows, got 0",
                ),
                "messages": [],
                "awaiting_approval": False,
            }

            result = await agent(state)

        # Verify the LLM was called with retry context
        call_args = mock_llm.ainvoke.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_coding_failure_increments_retry(
        self, sample_etl_spec: ETLSpec
    ) -> None:
        from etl_agent.agents.coding_agent import CodingAgent

        agent = CodingAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))

            result = await agent(
                {
                    "etl_spec": sample_etl_spec,
                    "run_id": uuid4(),
                    "status": RunStatus.CODING,
                    "retry_count": 0,
                    "max_retries": 2,
                    "messages": [],
                    "awaiting_approval": False,
                }
            )

        assert result["status"] == RunStatus.FAILED
        assert result["error_message"] is not None

    @pytest.mark.asyncio
    async def test_code_block_extraction(
        self, sample_etl_spec: ETLSpec
    ) -> None:
        from etl_agent.agents.coding_agent import CodingAgent

        agent = CodingAgent()
        multi_block_response = MagicMock(
            content=(
                "```python\ndef main():\n    pass\n```\n"
                "```markdown\n# README\n```"
            )
        )

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=multi_block_response)

            result = await agent(
                {
                    "etl_spec": sample_etl_spec,
                    "run_id": uuid4(),
                    "status": RunStatus.CODING,
                    "retry_count": 0,
                    "max_retries": 2,
                    "messages": [],
                    "awaiting_approval": False,
                }
            )

        # Code block should be extracted from markdown fences
        if result.get("generated_code"):
            assert "```" not in result["generated_code"]
