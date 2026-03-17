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


class _LLMWrapper:
    """Thin LangChain-style wrapper so tests can mock agent._llm.ainvoke."""

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


class TestAgent:
    """Agent 3: Generates and runs pytest tests for the generated pipeline."""

    _llm: Any = None  # class-level default; lazy-init in _call_llm

    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        """Make the agent callable as ``await agent(state)``."""
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("test_agent_call_failed", error=str(e))
            return {"status": RunStatus.FAILED, "error_message": str(e)}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    async def _call_llm(self, prompt: str) -> str:
        if self._llm is None:
            self._llm = _LLMWrapper(self.settings)
        response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
        return response.content

    async def _generate_tests(self, state: GraphState) -> str:
        from etl_agent.tools.code_validator import validate_python_syntax
        import re

        prompt = build_test_generator_prompt(
            etl_spec=state["etl_spec"],
            generated_code=state["generated_code"],
        )
        raw_response = await self._call_llm(prompt)

        code_match = re.search(r"```python\n(.*?)\n```", raw_response, re.DOTALL)
        if code_match:
            test_code = code_match.group(1)
        else:
            # Fallback: strip any leading/trailing fence lines the LLM may have included
            lines = raw_response.strip().splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            test_code = "\n".join(lines)

        # Validate syntax before returning — catches truncated LLM responses early
        is_valid, syntax_error = validate_python_syntax(test_code)
        if not is_valid:
            raise TestGenerationError(
                f"Generated test code has a syntax error (likely truncated response): {syntax_error}"
            )

        return test_code

    def _parse_pytest_output(self, output: str, return_code: int) -> TestResult:
        """Parse pytest stdout/stderr into a TestResult.

        Public so unit tests can exercise it in isolation.
        """
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

    def _run_tests(self, pipeline_code: str, test_code: str, pipeline_name: str = "pipeline") -> TestResult:
        """Write code to temp files and run pytest."""
        import os
        import sys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Write pipeline under the canonical name AND the full pipeline name.
            # Generated tests may import either `pipeline` or `{pipeline_name}`.
            (tmp / "pipeline.py").write_text(pipeline_code)
            safe_name = pipeline_name.replace("-", "_")
            if safe_name != "pipeline":
                (tmp / f"{safe_name}.py").write_text(pipeline_code)
            (tmp / "test_pipeline.py").write_text(test_code)
            (tmp / "__init__.py").touch()
            # Drop pytest's own addopts (--cov-fail-under etc.) from any parent config
            (tmp / "pytest.ini").write_text("[pytest]\n")

            # Inherit the current env so the venv's site-packages are available,
            # but override PYTHONPATH to include tmpdir for `import pipeline`.
            env = os.environ.copy()
            existing_pypath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = tmpdir + (f":{existing_pypath}" if existing_pypath else "")

            # Suppress Maven JAR downloads when pipeline.py is imported
            # (configure_spark_with_delta_pip tries to pull packages on import of the session)
            env.setdefault("PYSPARK_SUBMIT_ARGS", "--master local[1] pyspark-shell")

            # Prefer Java 17 for PySpark 3.5 compatibility (Java 21 breaks Hadoop 3.3.x)
            java17_candidates = [
                "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
                "/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home",
            ]
            java_any_candidates = java17_candidates + [
                "/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home",
                "/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home",
                "/usr/lib/jvm/java-21-openjdk-arm64",
                "/usr/lib/jvm/java-21-openjdk-amd64",
            ]
            if "JAVA_HOME" not in env:
                for candidate in java_any_candidates:
                    if Path(candidate).exists():
                        env["JAVA_HOME"] = candidate
                        break

            # JVM --add-opens flags required by PySpark 3.5 on Java 17+
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

            # Log full pytest output so CodingAgent retries have useful context
            logger.info("test_agent_pytest_output", output=output[-3000:])

            return self._parse_pytest_output(output, result.returncode)

    async def run(self, state: GraphState) -> dict[str, Any]:
        logger.info("test_agent_started", pipeline=state["etl_spec"].pipeline_name)
        try:
            generated_tests = await self._generate_tests(state)
            test_results = self._run_tests(
                state["generated_code"],
                generated_tests,
                pipeline_name=state["etl_spec"].pipeline_name,
            )

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
