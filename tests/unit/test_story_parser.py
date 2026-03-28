"""Unit tests for the StoryParser agent."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from etl_agent.core.models import ETLSpec, ETLOperation, RunStatus, UserStory
from etl_agent.core.state import GraphState


# ─── Fixtures ─────────────────────────────────────────────────────────────────

VALID_STORY_YAML = """
id: test_story
title: Test ETL Pipeline
description: A simple test ETL pipeline for unit tests.
source:
  path: s3://test-bucket/raw/
  format: parquet
target:
  path: s3://test-bucket/processed/
  format: delta
transformations:
  - name: filter_active
    operation: filter
    description: Keep only active records
    params:
      condition: "status = 'active'"
acceptance_criteria:
  - No null IDs
  - Row count > 0
tags:
  - test
  - unit
"""

INVALID_STORY_YAML = """
id: missing_source
title: Missing Source
description: This story is missing a source definition.
"""

MINIMAL_STORY_YAML = """
id: minimal
title: Minimal Story
description: Minimal valid story.
source:
  path: /tmp/input
  format: parquet
target:
  path: /tmp/output
  format: parquet
"""


@pytest.fixture
def valid_user_story() -> UserStory:
    data = yaml.safe_load(VALID_STORY_YAML)
    return UserStory(**data)


@pytest.fixture
def minimal_user_story() -> UserStory:
    data = yaml.safe_load(MINIMAL_STORY_YAML)
    return UserStory(**data)


@pytest.fixture
def mock_llm_response():
    """Mock an LLM response containing a valid ETLSpec JSON."""
    return MagicMock(
        content="""
I've analysed the user story. Here is the ETL specification:

```json
{
  "pipeline_name": "test_story",
  "pipeline_version": "1.0.0",
  "source": {
    "path": "s3://test-bucket/raw/",
    "format": "parquet"
  },
  "target": {
    "path": "s3://test-bucket/processed/",
    "format": "delta",
    "mode": "overwrite"
  },
  "transformations": [
    {
      "name": "filter_active",
      "operation": "filter",
      "description": "Keep only active records",
      "params": {"condition": "status = 'active'"}
    }
  ]
}
```
"""
    )


# ─── Tests: YAML Parsing ──────────────────────────────────────────────────────

class TestStoryYamlParsing:
    @pytest.mark.unit
    def test_parse_valid_story(self, valid_user_story: UserStory) -> None:
        assert valid_user_story.id == "test_story"
        assert valid_user_story.title == "Test ETL Pipeline"
        assert valid_user_story.source.path == "s3://test-bucket/raw/"
        assert valid_user_story.source.format == "parquet"
        assert valid_user_story.target.format == "delta"
        assert len(valid_user_story.transformations) == 1

    @pytest.mark.unit
    def test_parse_minimal_story(self, minimal_user_story: UserStory) -> None:
        assert minimal_user_story.id == "minimal"
        assert minimal_user_story.transformations == []
        assert minimal_user_story.acceptance_criteria == []

    @pytest.mark.unit
    def test_invalid_story_missing_source(self) -> None:
        data = yaml.safe_load(INVALID_STORY_YAML)
        with pytest.raises(ValueError):
            UserStory(**data)

    @pytest.mark.unit
    def test_story_tags_default_to_empty_list(self, minimal_user_story: UserStory) -> None:
        assert minimal_user_story.tags == []

    @pytest.mark.unit
    def test_transformation_step_has_required_fields(self, valid_user_story: UserStory) -> None:
        step = valid_user_story.transformations[0]
        assert step.name == "filter_active"
        assert step.operation == ETLOperation.filter
        assert step.description is not None


# ─── Tests: StoryParserAgent ──────────────────────────────────────────────────

class TestStoryParserAgent:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parse_returns_etl_spec(
        self, valid_user_story: UserStory, mock_llm_response: MagicMock
    ) -> None:
        from etl_agent.agents.story_parser import StoryParserAgent

        agent = StoryParserAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

            state: GraphState = {
                "user_story": valid_user_story,
                "run_id": uuid4(),
                "status": RunStatus.PARSING,
                "retry_count": 0,
                "max_retries": 2,
                "messages": [],
                "awaiting_approval": False,
            }

            result = await agent(state)

        assert "etl_spec" in result
        assert result["etl_spec"] is not None
        assert result["status"] == RunStatus.CODING

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parse_extracts_json_from_response(
        self, valid_user_story: UserStory, mock_llm_response: MagicMock
    ) -> None:
        from etl_agent.agents.story_parser import StoryParserAgent

        agent = StoryParserAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
            result = await agent(
                {
                    "user_story": valid_user_story,
                    "run_id": uuid4(),
                    "status": RunStatus.PARSING,
                    "retry_count": 0,
                    "max_retries": 2,
                    "messages": [],
                    "awaiting_approval": False,
                }
            )

        spec = result["etl_spec"]
        assert isinstance(spec, ETLSpec)
        assert spec.pipeline_name == "test_story"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parse_failure_sets_error_status(self, valid_user_story: UserStory) -> None:
        from etl_agent.agents.story_parser import StoryParserAgent

        agent = StoryParserAgent()

        with patch.object(agent, "_llm") as mock_llm:
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))

            result = await agent(
                {
                    "user_story": valid_user_story,
                    "run_id": uuid4(),
                    "status": RunStatus.PARSING,
                    "retry_count": 0,
                    "max_retries": 2,
                    "messages": [],
                    "awaiting_approval": False,
                }
            )

        assert result["status"] == RunStatus.FAILED
        assert result["error_message"] is not None

    @pytest.mark.unit
    def test_story_parser_agent_instantiation(self) -> None:
        from etl_agent.agents.story_parser import StoryParserAgent

        with patch("etl_agent.agents.story_parser.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                anthropic_api_key="test-key",
                llm_model="claude-sonnet-4-20250514",
                llm_max_tokens=4096,
                llm_temperature=0.7,
            )
            agent = StoryParserAgent()
            assert agent is not None
