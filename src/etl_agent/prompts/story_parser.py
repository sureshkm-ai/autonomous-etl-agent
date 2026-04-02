"""Prompt builder for the Story Parser Agent.

Constructs the prompt that asks Claude to convert a plain-language user story
into a structured ETLSpec JSON, using the AWS Glue catalog entities as grounding
context for source/target path and schema resolution.
"""

from __future__ import annotations

from etl_agent.core.data_catalog import DataEntity
from etl_agent.core.models import UserStory
from etl_agent.prompts.examples.story_parser_examples import STORY_PARSER_EXAMPLES


def build_story_parser_prompt(
    story: UserStory,
    catalog_entities: list[DataEntity],
    output_data_bucket: str,
) -> str:
    """Build the story parser prompt.

    Parameters
    ----------
    story:               The user story to parse.
    catalog_entities:    All entities registered in the Glue catalog. Pass []
                         if the catalog is unavailable — the LLM will fall back
                         to assumption-based generation.
    output_data_bucket:  S3 URI prefix for pipeline output, e.g.
                         "s3://etl-agent-processed-production/". Pass "" if
                         not configured — the LLM will note the assumption.
    """
    # ── Catalog section ───────────────────────────────────────────────────────
    if catalog_entities:
        catalog_lines = []
        for entity in catalog_entities:
            cols = ", ".join(f"{c.name} ({c.type})" for c in entity.columns)
            catalog_lines.append(
                f"  - **{entity.name}** | S3: `{entity.s3_path}` | format: {entity.format}\n"
                f"    columns: {cols}"
            )
        catalog_section = "## Available Data Entities (from AWS Glue Data Catalog)\n\n" + "\n".join(
            catalog_lines
        )
    else:
        catalog_section = (
            "## Available Data Entities\n\n"
            "No entities are currently registered in the catalog. "
            "Make reasonable assumptions about column names and S3 paths, "
            "and add a comment in the generated code noting that schemas are assumed."
        )

    # ── Output bucket section ─────────────────────────────────────────────────
    if output_data_bucket:
        output_section = (
            f"## Output Bucket\n\n"
            f"Write pipeline output to: `{output_data_bucket}{{pipeline_name}}/`\n"
            f"e.g. `{output_data_bucket}monthly_revenue_by_category/`"
        )
    else:
        output_section = (
            "## Output Bucket\n\n"
            "No output bucket is configured. Use a reasonable S3 path assumption "
            "and add a comment in the code noting it should be replaced."
        )

    # ── Few-shot examples ─────────────────────────────────────────────────────
    examples_text = "\n\n".join(
        f"### Example {i + 1}\n"
        f"Input:\n```\n{ex['input']}\n```\n"
        f"Output:\n```json\n{ex['output']}\n```"
        for i, ex in enumerate(STORY_PARSER_EXAMPLES)
    )

    # ── User story section ────────────────────────────────────────────────────
    criteria_text = "\n".join(f"  - {c}" for c in story.acceptance_criteria) or "  (none)"

    story_section = (
        f"## User Story\n\n"
        f"**Title:** {story.title}\n\n"
        f"**Description:** {story.description}\n\n"
        f"**Acceptance Criteria:**\n{criteria_text}"
    )

    return f"""You are an expert Data Engineering architect. Your task is to read a user story \
and produce a structured ETLSpec JSON that a PySpark code generator will consume.

Use the data entities listed below to resolve which datasets are needed, their \
exact S3 paths, and their column schemas. Do NOT invent S3 paths or column names \
that are not in the catalog — use only what is registered there.

{catalog_section}

{output_section}

## Instructions

1. Identify which catalog entity (or entities) the story requires as **source**.
   - For multi-source pipelines (e.g. a join), pick the primary source for the
     `source` field and list the join entity in `transformations`.
2. Construct the **target** path as `{{output_data_bucket}}{{pipeline_name}}/`
   using the output bucket above.
3. Generate a `snake_case` `pipeline_name` from the story title.
4. Populate `transformations` with one entry per logical step.
5. Set `operations` to the flat list of operation type strings.
6. Use `delta_operation: merge` for upsert patterns, `overwrite` for full reloads.
7. Set `requires_broadcast_join: true` if any join involves a small dimension table.

## Required JSON Schema

You MUST return ALL of the following fields — no exceptions:

{{
  "story_id": "<story id string>",
  "pipeline_name": "<snake_case name derived from title>",
  "description": "<one sentence describing what the pipeline does>",
  "operations": ["<list of: filter|join|aggregate|dedupe|enrich|upsert|fill_null|rename|cast|sort>"],
  "source": {{
    "path": "<exact S3 path from catalog>",
    "format": "<csv|parquet|delta|json>"
  }},
  "target": {{
    "path": "<output_data_bucket + pipeline_name + />",
    "format": "csv"
  }},
  "transformations": [
    {{
      "operation": "<operation type>",
      "description": "<what this step does>",
      "config": {{}}
    }}
  ],
  "delta_operation": "<overwrite|merge|create|update|delete>",
  "requires_broadcast_join": false,
  "partition_columns": [],
  "estimated_complexity": "<low|medium|high>"
}}

## Few-Shot Examples

{examples_text}

{story_section}

Return ONLY a valid JSON code block. No explanation, no preamble."""
