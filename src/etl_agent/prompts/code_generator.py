"""Prompt templates for the Coding Agent."""

from etl_agent.core.models import ETLSpec, TestResult
from etl_agent.prompts.examples.code_gen_examples import CODE_GEN_EXAMPLES


def build_code_generator_prompt(
    etl_spec: ETLSpec,
    previous_failure: TestResult | None = None,
    retry_count: int = 0,
) -> str:
    retry_context = ""
    if previous_failure and retry_count > 0:
        retry_context = f"""
## Previous Test Failure (Attempt {retry_count})
The previous code failed these tests:
{chr(10).join(f"- {t}" for t in previous_failure.failed_test_names)}

Test output (last 1000 chars):
```
{previous_failure.output[-1000:]}
```
Please fix these specific failures in your new version.
"""

    examples_text = "\n\n".join(
        f"### Example\nSpec: {ex['spec']}\nCode:\n```python\n{ex['code']}\n```"
        for ex in CODE_GEN_EXAMPLES
    )

    return f"""You are an expert PySpark Data Engineer. Generate production-ready PySpark code
for the following ETL specification. Follow enterprise best practices strictly.

## Code Requirements
- Use PySpark 3.5+ with Delta Lake
- Include SparkSession creation with Delta Lake config
- Use broadcast joins for dimension tables (requires_broadcast_join={etl_spec.requires_broadcast_join})
- Apply partitioning: {etl_spec.partition_columns}
- Use Delta {etl_spec.delta_operation.value} operation for the target
- Add structured logging with print() statements for each major step
- Handle null values gracefully
- Include type hints and docstrings
- Follow snake_case naming conventions

## ETL Specification
- Pipeline: {etl_spec.pipeline_name}
- Description: {etl_spec.description}
- Operations: {[op.value for op in etl_spec.operations]}
- Source: {etl_spec.source.path} ({etl_spec.source.format})
- Target: {etl_spec.target.path} ({etl_spec.target.format})
- Transformations: {[t.model_dump() for t in etl_spec.transformations]}
{retry_context}
## Few-Shot Examples
{examples_text}

Return:
1. A ```python code block with the complete PySpark pipeline
2. A ```markdown code block with a README for this pipeline"""
