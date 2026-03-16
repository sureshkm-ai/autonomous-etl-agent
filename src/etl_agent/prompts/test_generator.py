"""Prompt templates for the Test Agent."""
from etl_agent.core.models import ETLSpec
from etl_agent.prompts.examples.test_gen_examples import TEST_GEN_EXAMPLES


def build_test_generator_prompt(etl_spec: ETLSpec, generated_code: str) -> str:
    examples_text = "\n\n".join(
        f"### Example\n```python\n{ex}\n```" for ex in TEST_GEN_EXAMPLES
    )
    return f"""You are a Senior Data Engineer writing pytest tests for a PySpark pipeline.
Generate comprehensive tests that cover schema validation, null checks, and business logic.

## Test Requirements
- Use pytest with PySpark fixtures
- Include: schema tests, null/empty checks, business logic assertions, row count checks
- Mock S3 reads using local DataFrames (do NOT actually connect to S3)
- Tests must be self-contained and runnable without external dependencies
- Minimum 3 test functions

## Pipeline to Test
```python
{generated_code}
```

## ETL Spec
- Pipeline: {etl_spec.pipeline_name}
- Operations: {[op.value for op in etl_spec.operations]}
- Source schema expectations: {[t.model_dump() for t in etl_spec.transformations]}

## Few-Shot Examples
{examples_text}

Return ONLY a ```python code block with the complete pytest test file."""
