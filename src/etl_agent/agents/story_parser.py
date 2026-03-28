"""
Story Parser Agent — parses a UserStory YAML into a structured ETLSpec.
Uses the ReactAgent loop: if the LLM returns malformed JSON it is shown the
parse error and asked to return corrected JSON (up to 3 attempts).
"""

from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from etl_agent.agents.base import ReactAgent
from etl_agent.core.config import get_settings
from etl_agent.core.exceptions import StoryParseError
from etl_agent.core.logging import get_logger
from etl_agent.core.models import ETLSpec, RunStatus
from etl_agent.core.state import GraphState
from etl_agent.prompts.story_parser import build_story_parser_prompt

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


class StoryParserAgent(ReactAgent):
    """Agent 1: Converts a UserStory into a structured ETLSpec using Claude."""

    _llm: Any = None

    def __init__(self) -> None:
        self.settings = get_settings()

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("story_parser_call_failed", error=str(e))
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
    def _validate_json(raw: str) -> tuple[bool, str]:
        """Check that the response contains a valid JSON ETLSpec block."""
        import json
        import re

        json_match = re.search(r"```json\n(.*?)\n```", raw, re.DOTALL)
        candidate = json_match.group(1) if json_match else raw
        try:
            data = json.loads(candidate)
            ETLSpec(**data)  # validate pydantic model
            return True, ""
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _fix_message(error: str) -> str:
        return (
            f"Your previous response could not be parsed as a valid ETLSpec JSON.\n\n"
            f"Error: {error}\n\n"
            "Please return **only** a corrected JSON object inside a single "
            "```json ... ``` block. Make sure every field matches the ETLSpec schema."
        )

    async def run(self, state: GraphState) -> dict[str, Any]:
        story = state["user_story"]
        logger.info("story_parser_started", story_id=story.id)

        try:
            prompt = build_story_parser_prompt(story)
            raw_response = await self.react_llm_loop(
                initial_messages=[{"role": "user", "content": prompt}],
                call_llm=self._call_llm,
                validate=self._validate_json,
                build_fix_message=self._fix_message,
                agent_name="story_parser",
            )

            import json
            import re

            json_match = re.search(r"```json\n(.*?)\n```", raw_response, re.DOTALL)
            spec_data = json.loads(json_match.group(1) if json_match else raw_response)
            etl_spec = ETLSpec(**spec_data)

            logger.info(
                "story_parser_completed",
                pipeline_name=etl_spec.pipeline_name,
                operations=[op.value for op in etl_spec.operations],
            )
            return {"etl_spec": etl_spec, "status": RunStatus.CODING}

        except Exception as e:
            logger.error("story_parser_failed", error=str(e))
            raise StoryParseError(
                f"Failed to parse story: {e}", context={"story_id": story.id}
            ) from e
