"""Prompt templates for the Test Agent."""

from etl_agent.core.models import ETLSpec
from etl_agent.prompts.examples.test_gen_examples import TEST_GEN_EXAMPLES


def build_test_generator_prompt(etl_spec: ETLSpec, generated_code: str) -> str:
    examples_text = "\n\n".join(f"### Example\n```python\n{ex}\n```" for ex in TEST_GEN_EXAMPLES)
    ops_summary = [op.value for op in etl_spec.operations]

    # Surface just enough of the generated code for Claude to find function names.
    code_preview = generated_code[:2500]

    return f"""You are a Senior Data Engineer writing pytest unit tests for a PySpark pipeline.

## ABSOLUTE RULES — every rule is mandatory, no exceptions

### DO NOT:
- DO NOT import or instantiate `SparkSession` anywhere in the test file.
- DO NOT use `pyspark.sql.SparkSession`, `pyspark.sql.functions`, or any pyspark module.
- DO NOT call `SparkSession.builder...getOrCreate()` — not even inside a fixture.
- DO NOT read from S3, write to Delta, or call `run()` with a real filesystem.
- DO NOT write more than 3 test functions.
- DO NOT write more than 70 lines total.

### MUST DO:
- MUST start with `import pipeline` (module is always named `pipeline`, never the pipeline full name).
- MUST use `unittest.mock.MagicMock` for any DataFrame argument.
- MUST have exactly 3 test functions (names starting with `test_`).
- MUST include at least one `assert` statement per test.
- MUST test `pipeline.run` exists and is callable.
- MUST mock `pipeline.SparkSession` using `unittest.mock.patch` before calling `run()`.

## Pipeline code (scan this to find helper function names):
```python
{code_preview}
```

## ETL Spec
- Module name: `pipeline`
- Operations: {ops_summary}

## Few-Shot Example — copy this structure exactly:
{examples_text}

## Output format
Return ONLY a single ```python ... ``` code block.
The file must be syntactically complete and under 70 lines.
No explanations, no markdown outside the code block."""
