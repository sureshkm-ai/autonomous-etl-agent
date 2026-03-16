"""
Test Agent — generates pytest tests and executes them.
Produces schema checks, null checks, and business logic assertions.
"""
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import TestGenerationError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus, TestResult
from etl_agent.core.state import GraphState
from etl_agent.prompts.test_generator import build_test_generator_prompt

logger = get_logger(__name__)


class TestAgent:
    """Agent 3: Generates and runs pytest tests for the generated pipeline."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    async def _call_llm(self, prompt: str) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        response = await client.messages.create(
            model=self.settings.llm_model,
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def _generate_tests(self, state: GraphState) -> str:
        prompt = build_test_generator_prompt(
            etl_spec=state["etl_spec"],
            generated_code=state["generated_code"],
        )
        raw_response = await self._call_llm(prompt)
        import re
        code_match = re.search(r"```python\n(.*?)\n```", raw_response, re.DOTALL)
        return code_match.group(1) if code_match else raw_response

    def _run_tests(self, pipeline_code: str, test_code: str) -> TestResult:
        """Write code to temp files and run pytest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "pipeline.py").write_text(pipeline_code)
            (tmp / "test_pipeline.py").write_text(test_code)
            (tmp / "__init__.py").touch()

            result = subprocess.run(
                ["python", "-m", "pytest", str(tmp / "test_pipeline.py"),
                 "-v", "--tb=short", "--no-header", "--cov=pipeline", "--cov-report=term-missing"],
                capture_output=True, text=True, timeout=300, cwd=tmpdir,
            )

            output = result.stdout + result.stderr
            passed = result.returncode == 0

            # Parse test counts from pytest output
            import re
            summary = re.search(r"(\d+) passed(?:, (\d+) failed)?", output)
            passed_count = int(summary.group(1)) if summary else 0
            failed_count = int(summary.group(2)) if summary and summary.group(2) else 0
            total = passed_count + failed_count

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

    async def run(self, state: GraphState) -> dict[str, Any]:
        logger.info("test_agent_started", pipeline=state["etl_spec"].pipeline_name)
        try:
            generated_tests = await self._generate_tests(state)
            test_results = self._run_tests(state["generated_code"], generated_tests)

            logger.info(
                "test_agent_completed",
                passed=test_results.passed,
                total=test_results.total_tests,
                coverage=test_results.coverage_pct,
            )
            return {
                "generated_tests": generated_tests,
                "test_results": test_results,
                "status": RunStatus.PR_CREATING if test_results.passed else RunStatus.CODING,
                "retry_count": state["retry_count"] + (1 if not test_results.passed else 0),
            }
        except Exception as e:
            logger.error("test_agent_failed", error=str(e))
            raise TestGenerationError(f"Test execution failed: {e}") from e
