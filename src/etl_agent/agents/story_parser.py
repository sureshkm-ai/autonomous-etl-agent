"""
Story Parser Agent — parses a UserStory YAML into a structured ETLSpec.
Uses Claude to extract transformation intent via prompt engineering.
"""
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

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


class StoryParserAgent:
    """Agent 1: Converts a UserStory into a structured ETLSpec using Claude."""

    # Class-level default — allows integration tests to patch via
    # patch("etl_agent.agents.story_parser.StoryParserAgent._llm").
    # Unit tests can still use patch.object(instance, "_llm").
    _llm: Any = None

    def __init__(self) -> None:
        self.settings = get_settings()
        # Do NOT set self._llm here; lazy-init in _call_llm so the class-level
        # patch applied by integration tests remains visible on new instances.

    async def __call__(self, state: GraphState) -> dict[str, Any]:
        """Make the agent callable as ``await agent(state)``."""
        try:
            return await self.run(state)
        except Exception as e:
            logger.error("story_parser_call_failed", error=str(e))
            return {"status": RunStatus.FAILED, "error_message": str(e)}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _call_llm(self, prompt: str) -> str:
        """Call Claude with retry logic for rate limits and transient errors."""
        if self._llm is None:
            self._llm = _LLMWrapper(self.settings)
        response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
        return response.content

    async def run(self, state: GraphState) -> dict[str, Any]:
        """Parse the user story and return an ETLSpec."""
        story = state["user_story"]
        logger.info("story_parser_started", story_id=story.id)

        try:
            prompt = build_story_parser_prompt(story)
            raw_response = await self._call_llm(prompt)

            # Parse the structured JSON response from Claude
            import json
            import re
            json_match = re.search(r"```json\n(.*?)\n```", raw_response, re.DOTALL)
            if json_match:
                spec_data = json.loads(json_match.group(1))
            else:
                spec_data = json.loads(raw_response)

            etl_spec = ETLSpec(**spec_data)
            logger.info("story_parser_completed", pipeline_name=etl_spec.pipeline_name,
                        operations=[op.value for op in etl_spec.operations])

            return {"etl_spec": etl_spec, "status": RunStatus.CODING}

        except Exception as e:
            logger.error("story_parser_failed", error=str(e))
            raise StoryParseError(f"Failed to parse story: {e}", context={"story_id": story.id}) from e
