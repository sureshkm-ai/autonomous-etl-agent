"""Prompt templates for the Story Parser Agent."""

import yaml

from etl_agent.core.models import UserStory
from etl_agent.prompts.examples.story_parser_examples import STORY_PARSER_EXAMPLES


def build_story_parser_prompt(story: UserStory) -> str:
    story_yaml = yaml.dump(story.model_dump(), default_flow_style=False)
    examples_text = "\n\n".join(
        f"### Example {i + 1}\nInput:\n```yaml\n{ex['input']}\n```\nOutput:\n```json\n{ex['output']}\n```"
        for i, ex in enumerate(STORY_PARSER_EXAMPLES)
    )
    return f"""You are an expert Data Engineering architect. Parse the following DevOps user story
and extract a structured ETL specification as a JSON object.

## Required JSON Schema
You MUST return ALL of the following fields — no exceptions:

{{
  "story_id": "<story id string>",
  "pipeline_name": "<snake_case name derived from title>",
  "description": "<one sentence describing what the pipeline does>",
  "operations": ["<list of operation types: filter|join|aggregate|dedupe|enrich|upsert|fill_null|rename|cast|sort>"],
  "source": {{
    "path": "<source path from the story>",
    "format": "<parquet|delta|csv|json>"
  }},
  "target": {{
    "path": "<target path from the story>",
    "format": "<parquet|delta|csv|json>"
  }},
  "transformations": [
    {{
      "operation": "<one of the operation types above>",
      "description": "<what this step does>",
      "config": {{}}
    }}
  ],
  "delta_operation": "<overwrite|merge|create|update|delete>",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "<low|medium|high>"
}}

## Instructions
- `transformations` MUST be a list with one entry per transformation step
- `operations` is the flat list of operation type strings derived from transformations
- Generate a snake_case `pipeline_name` from the story title
- Use `delta_operation: merge` for upsert patterns, `overwrite` for full reloads
- Set `requires_broadcast_join: true` if any join involves a small dimension table

## Few-Shot Examples
{examples_text}

## User Story to Parse
```yaml
{story_yaml}
```

Return ONLY a valid JSON code block. No explanation."""
