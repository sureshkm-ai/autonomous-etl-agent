"""Prompt templates for the Story Parser Agent."""
import yaml

from etl_agent.core.models import UserStory
from etl_agent.prompts.examples.story_parser_examples import STORY_PARSER_EXAMPLES


def build_story_parser_prompt(story: UserStory) -> str:
    story_yaml = yaml.dump(story.model_dump(), default_flow_style=False)
    examples_text = "\n\n".join(
        f"### Example {i+1}\nInput:\n```yaml\n{ex['input']}\n```\nOutput:\n```json\n{ex['output']}\n```"
        for i, ex in enumerate(STORY_PARSER_EXAMPLES)
    )
    return f"""You are an expert Data Engineering architect. Parse the following DevOps user story
and extract a structured ETL specification in JSON format.

## Instructions
- Identify all transformation operations needed: filter, join, aggregate, dedupe, enrich, upsert, fill_null, rename, cast, sort
- Generate a snake_case pipeline_name from the story title
- Determine if a Delta MERGE, CREATE, UPDATE, or DELETE is appropriate for the target
- Set requires_broadcast_join=true if any join involves a small dimension table (<10MB)
- Estimate complexity as "low", "medium", or "high"

## Few-Shot Examples
{examples_text}

## User Story to Parse
```yaml
{story_yaml}
```

Return ONLY a JSON code block with the ETLSpec fields. No explanation."""
