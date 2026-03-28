"""
Test Agent — generates pytest tests and executes them.
Inherits ReactAgent:
  - LLM loop fixes syntax errors in generated test code.
  - Tool loop retries subprocess execution on transient failures.
"""
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from etl_agent.agents.base import ReactAgent
from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import TestGenerationError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus, TestResult
from etl_agent.core.state import GraphState
from etl_agent.prompts.test_generator import build_test_generator_prompt

logger = get_logger(__name__)


class _LLMWrapper:
    def __init__(self, settings: Any) -> None:
        self._settings = settings

    async def ainvoke(self, messages: list[dict]) -> Any:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        response = await client.messages.create(
            model=self._settings.llm_model,
            max_tokens=self._settings.llm_max_tokens,
            temperature=self._settings.llm_temperature,
            messages=messages,
        )
        text = response.content[0].text

        class _Resp:
            content = text

        return _Resp()


class TestAgent(ReactAgent):
    """Agent 3: Generates and runs pytest tests for the generated pipeline."""

    _llm: Any = None

    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        try:
            return await self.run(state)
        except Exception as e:
<<<<<<< HEAD
            logger.error("test_agent_call_failed", error=str(e), run_id=state.get("run_id",""), story_id=state.get("story_id",""))
=======
            logger.error("test_agent_call_failed", error=str(e))
>>>>>>> main
            return {"status": RunStatus.FAILED, "error_message": str(e)}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    async def _call_llm(self, messages: list[dict]) -> str:
        if self._llm is None:
            self._llm = _LLMWrapper(self.settings)
        response = await self._llm.ainvoke(messages)
        return response.content

    @staticmethod
    def _extract_test_code(raw: str) -> str:
        import re
        m = re.search(r"```python\n(.*?)\n```", raw, re.DOTALL)
        if m:
            return m.group(1)
        lines = raw.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    @staticmethod
    def _validate_test_syntax(raw: str) -> tuple[bool, str]:
        from etl_agent.tools.code_validator import validate_python_syntax
        code = TestAgent._extract_test_code(raw)
        ok, err = validate_python_syntax(code)
        return ok, err or ""

    @staticmethod
    def _fix_test_syntax_message(raw: str, error: str, attempt: int) -> str:
        return (
            f"The pytest test code you generated has a syntax error:\n\n"
            f"```\n{error}\n```\n\n"
            "Please return the **complete corrected test code** inside a single "
            "```python ... ``` block. Do not truncate."
        )

    def _parse_pytest_output(self, output: str, return_code: int) -> TestResult:
        import re

        passed_count = 0
        failed_count = 0

        passed_match = re.search(r"(\d+) passed", output)
        failed_match = re.search(r"(\d+) failed", output)
        error_match = re.search(r"(\d+) error", output)

        if passed_match:
            passed_count = int(passed_match.group(1))
        if failed_match:
            failed_count = int(failed_match.group(1))
        elif error_match:
            failed_count = int(error_match.group(1))

        total = passed_count + failed_count
        passed = return_code == 0 and failed_count == 0 and passed_count > 0

        cov_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
        coverage = float(cov_match.group(1)) if cov_match else 0.0

        failed_names: list[str] = re.findall(r"FAILED (.*?) -", output)

        return TestResult(
            passed=passed,
            total_tests=total or 1,
            passed_tests=passed_count,
            failed_tests=failed_count,
            coverage_pct=coverage,
            output=output,
            failed_test_names=failed_names,
        )

    # conftest.py injected into every test run so pyspark.sql.functions work
    _CONFTEST = textwrap.dedent("""\
        import pytest
        from pyspark.sql import SparkSession

        @pytest.fixture(scope="session", autouse=True)
        def spark_session():
            \"\"\"Start a minimal local SparkSession once for the whole test session.

            This ensures pyspark.sql.functions (F.col, F.sum, etc.) have an active
            SparkContext and do not raise AssertionError mid-test.
            \"\"\"
            spark = (
                SparkSession.builder
                .master("local[1]")
                .appName("etl_agent_unit_tests")
                .config("spark.sql.shuffle.partitions", "1")
                .config("spark.default.parallelism", "1")
                .config("spark.ui.enabled", "false")
                .config("spark.driver.bindAddress", "127.0.0.1")
                .getOrCreate()
            )
            yield spark
            spark.stop()
    """)

    def _run_tests(self, pipeline_code: str, test_code: str, pipeline_name: str = "pipeline") -> TestResult:
        import os
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "pipeline.py").write_text(pipeline_code)
            safe_name = pipeline_name.replace("-", "_")
            if safe_name != "pipeline":
                (tmp / f"{safe_name}.py").write_text(pipeline_code)
            (tmp / "test_pipeline.py").write_text(test_code)
            (tmp / "conftest.py").write_text(self._CONFTEST)
            (tmp / "__init__.py").touch()
            (tmp / "pytest.ini").write_text("[pytest]\n")

            env = os.environ.copy()
            existing_pypath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = tmpdir + (f":{existing_pypath}" if existing_pypath else "")
            env.setdefault("PYSPARK_SUBMIT_ARGS", "--master local[1] pyspark-shell")

            java_candidates = [
                "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
                "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
                "/usr/lib/jvm/java-21-openjdk-arm64",
                "/usr/lib/jvm/java-21-openjdk-amd64",
            ]
            if "JAVA_HOME" not in env:
                for candidate in java_candidates:
                    if Path(candidate).exists():
                        env["JAVA_HOME"] = candidate
                        break

            env.setdefault("JAVA_TOOL_OPTIONS", " ".join([
                "--add-opens=java.base/java.lang=ALL-UNNAMED",
                "--add-opens=java.base/java.lang.invoke=ALL-UNNAMED",
                "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
                "--add-opens=java.base/java.io=ALL-UNNAMED",
                "--add-opens=java.base/java.net=ALL-UNNAMED",
                "--add-opens=java.base/java.nio=ALL-UNNAMED",
                "--add-opens=java.base/java.util=ALL-UNNAMED",
                "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED",
                "--add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED",
                "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED",
                "--add-opens=java.base/sun.nio.cs=ALL-UNNAMED",
                "--add-opens=java.base/sun.security.action=ALL-UNNAMED",
                "--add-opens=java.base/sun.util.calendar=ALL-UNNAMED",
                "--add-opens=java.security.jgss/sun.security.krb5=ALL-UNNAMED",
            ]))

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(tmp / "test_pipeline.py"),
                 "-v", "--tb=short", "--no-header", "-p", "no:cacheprovider",
                 "--cov=pipeline", "--cov-report=term-missing"],
                capture_output=True, text=True, timeout=300, cwd=tmpdir, env=env,
            )

            output = result.stdout + result.stderr
            logger.info("test_agent_pytest_output", output=output[-3000:])
            return self._parse_pytest_output(output, result.returncode)

    async def run(self, state: GraphState) -> dict[str, Any]:
<<<<<<< HEAD
        run_id = state.get("run_id", "")
        story_id = state.get("story_id", "")
        logger.info("test_agent_started", pipeline=state["etl_spec"].pipeline_name,
                    run_id=run_id, story_id=story_id)
=======
        logger.info("test_agent_started", pipeline=state["etl_spec"].pipeline_name)
>>>>>>> main
        try:
            # React LLM loop: fix syntax errors in generated test code
            base_prompt = build_test_generator_prompt(
                etl_spec=state["etl_spec"],
                generated_code=state["generated_code"],
            )
            pyspark_rules = textwrap.dedent("""

                ── CRITICAL PYSPARK TESTING RULES (follow exactly) ──────────────────────────

                A conftest.py is automatically injected that starts a real SparkSession
                (scope="session") before any test runs. This means pyspark.sql.functions
                (F.col, F.sum, F.count, etc.) will work inside the pipeline methods being
                tested — you do NOT need to patch them.

                Rules you MUST follow in every test you write:

                1. Configure integer return values on any mock that represents a count/numeric:
                      mock_df.count.return_value = 100
                   Never leave count() or similar returning a raw MagicMock — f-string formatting
                   with `:,` or `:d` will raise TypeError on a MagicMock.

                2. Chain mock DataFrame calls so filter/select/groupBy return the mock itself:
                      mock_df.filter.return_value = mock_df
                      mock_df.select.return_value = mock_df
                      mock_df.groupBy.return_value = mock_df
                      mock_df.agg.return_value = mock_df
                      mock_df.withColumn.return_value = mock_df

                3. Do NOT call pyspark.sql.functions directly in test assertions —
                   F.col() etc. return Column objects that cannot be compared with ==.
                   Only assert on Python primitives (counts, booleans, strings).

                4. Prefer testing the top-level `run(mock_spark)` method over individual
                   transform methods, since run() exercises the full pipeline with one
                   well-configured mock.

                5. Mock SparkSession read chain fully:
                      mock_spark.read.parquet.return_value = mock_df
                      mock_spark.read.csv.return_value = mock_df
                      mock_spark.read.format.return_value.load.return_value = mock_df

                ─────────────────────────────────────────────────────────────────────────────
            """)
            full_prompt = base_prompt + pyspark_rules

            raw_response = await self.react_llm_loop(
                initial_messages=[{
                    "role": "user",
                    "content": full_prompt,
                }],
                call_llm=self._call_llm,
                validate=self._validate_test_syntax,
                build_fix_message=self._fix_test_syntax_message,
                agent_name="test_agent",
            )
            generated_tests = self._extract_test_code(raw_response)

            # React tool loop: retry subprocess execution on transient failures
            test_results = await self.react_tool_loop(
                action=lambda: self._run_tests_async(
                    state["generated_code"],
                    generated_tests,
                    pipeline_name=state["etl_spec"].pipeline_name,
                ),
                max_attempts=2,
                errors_to_catch=(subprocess.TimeoutExpired, OSError),
                agent_name="test_agent",
                action_name="pytest_subprocess",
            )

            logger.info(
                "test_agent_completed",
                passed=test_results.passed,
                total=test_results.total_tests,
                coverage=test_results.coverage_pct,
<<<<<<< HEAD
                run_id=run_id,
                story_id=story_id,
=======
>>>>>>> main
            )
            return {
                "generated_tests": generated_tests,
                "test_results": test_results,
                "status": RunStatus.PR_CREATING if test_results.passed else RunStatus.CODING,
                "retry_count": state["retry_count"] + (1 if not test_results.passed else 0),
            }
        except Exception as e:
<<<<<<< HEAD
            logger.error("test_agent_failed", error=str(e), run_id=run_id, story_id=story_id)
=======
            logger.error("test_agent_failed", error=str(e))
>>>>>>> main
            raise TestGenerationError(f"Test execution failed: {e}") from e

    async def _run_tests_async(self, pipeline_code: str, test_code: str, pipeline_name: str) -> TestResult:
        """Wrap the synchronous _run_tests in a coroutine for react_tool_loop."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._run_tests, pipeline_code, test_code, pipeline_name
        )
<<<<<<< HEAD

=======
>>>>>>> main
