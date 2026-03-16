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


class StoryParserAgent:
    """Agent 1: Converts a UserStory into a structured ETLSpec using Claude."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _call_llm(self, prompt: str) -> str:
        """Call Claude with retry logic for rate limits and transient errors."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        response = await client.messages.create(
            model=self.settings.llm_model,
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

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
