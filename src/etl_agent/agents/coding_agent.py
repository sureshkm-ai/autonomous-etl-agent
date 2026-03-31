"""
Coding Agent — generates production-ready PySpark code and a README.
Inherits ReactAgent:
  - Inner LLM loop fixes syntax errors in multi-turn conversation.
  - Test-failure context from a previous graph retry is injected so the model
    can address specific assertion failures.
"""

from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from etl_agent.agents.base import ReactAgent
from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import CodeGenerationError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus
from etl_agent.core.state import GraphState
from etl_agent.prompts.code_generator import build_code_generator_prompt

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


class CodingAgent(ReactAgent):
    """Agent 2: Generates PySpark code + README from an ETLSpec."""

    _llm: Any = None

    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("coding_agent_call_failed", error=str(e))
            return {"status": RunStatus.FAILED, "error_message": str(e)}

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True
    )
    async def _call_llm(self, messages: list[dict]) -> str:
        if self._llm is None:
            self._llm = _LLMWrapper(self.settings)
        response = await self._llm.ainvoke(messages)
        return response.content

    @staticmethod
    def _extract_code(raw: str) -> str:
        import re

        m = re.search(r"```python\n(.*?)\n```", raw, re.DOTALL)
        return m.group(1) if m else raw

    @staticmethod
    def _validate_syntax(raw: str) -> tuple[bool, str]:
        from etl_agent.tools.code_validator import validate_python_syntax

        code = CodingAgent._extract_code(raw)
        ok, err = validate_python_syntax(code)
        return ok, err or ""

    @staticmethod
    def _fix_syntax_message(error: str) -> str:
        return (
            f"The Python code you generated has a syntax error:\n\n"
            f"```\n{error}\n```\n\n"
            "Please return the **complete corrected Python code** inside a single "
            "```python ... ``` block. Do not truncate — output the full file."
        )

    async def run(self, state: GraphState) -> dict[str, Any]:
        import re

        etl_spec = state["etl_spec"]
        retry_count = state["retry_count"]
        previous_failure = state.get("test_results")

        logger.info(
            "coding_agent_started", pipeline=etl_spec.pipeline_name, attempt=retry_count + 1
        )

        try:
            prompt = build_code_generator_prompt(
                etl_spec=etl_spec,
                previous_failure=previous_failure,
                retry_count=retry_count,
                source_schema=state.get("source_schema"),
            )

            raw_response = await self.react_llm_loop(
                initial_messages=[{"role": "user", "content": prompt}],
                call_llm=self._call_llm,
                validate=self._validate_syntax,
                build_fix_message=self._fix_syntax_message,
                agent_name="coding_agent",
            )

            generated_code = self._extract_code(raw_response)
            readme_match = re.search(r"```markdown\n(.*?)\n```", raw_response, re.DOTALL)
            generated_readme = readme_match.group(1) if readme_match else _default_readme(etl_spec)

            logger.info(
                "coding_agent_completed",
                pipeline=etl_spec.pipeline_name,
                code_lines=len(generated_code.splitlines()),
            )

            return {
                "generated_code": generated_code,
                "generated_readme": generated_readme,
                "retry_count": retry_count + (1 if retry_count > 0 else 0),
                "status": RunStatus.TESTING,
            }

        except Exception as e:
            logger.error("coding_agent_failed", error=str(e))
            raise CodeGenerationError(f"Code generation failed: {e}") from e


def _default_readme(etl_spec: Any) -> str:
    return f"""# {etl_spec.pipeline_name}

## Description
{etl_spec.description}

## Operations
{", ".join(op.value for op in etl_spec.operations)}

## Source
`{etl_spec.source.path}`

## Target
`{etl_spec.target.path}`

*Auto-generated by Autonomous ETL Agent*
"""
