"""Prompt templates for the Coding Agent."""

from typing import Any

from etl_agent.core.models import ETLSpec, TestResult
from etl_agent.prompts.examples.code_gen_examples import CODE_GEN_EXAMPLES


def build_code_generator_prompt(
    etl_spec: ETLSpec,
    previous_failure: TestResult | None = None,
    retry_count: int = 0,
    source_schema: dict[str, Any] | None = None,
    glue_table_name: str | None = None,
    glue_database: str = "etl_agent_catalog",
    iceberg_warehouse: str = "",
) -> str:
    """Build the code generation prompt.

    Parameters
    ----------
    etl_spec:         Parsed ETL specification from StoryParserAgent.
    previous_failure: TestResult from the previous failed attempt (retry mode).
    retry_count:      Which retry attempt this is (0 = first attempt).
    source_schema:    Column list from Glue catalog — used as fallback when
                      Iceberg is not available (e.g. during migration window).
    glue_table_name:  Glue/Iceberg table name (e.g. "orders").  When set, the
                      generated code uses spark.table() instead of spark.read.csv().
    glue_database:    Glue catalog database name (default: etl_agent_catalog).
    iceberg_warehouse: S3 URI of the Iceberg warehouse (e.g. s3://bucket/iceberg/).
    """
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

    # ── Spark session template ─────────────────────────────────────────────────
    # When Iceberg is available, generate the full dual-catalog SparkSession.
    # When it is not, generate the simpler Delta-only session (existing behaviour).

    if glue_table_name and iceberg_warehouse:
        spark_session_template = f"""\
spark = (
    SparkSession.builder
    .appName("{etl_spec.pipeline_name}")
    # Delta Lake extension for output writes
    .config(
        "spark.sql.extensions",
        "io.delta.sql.DeltaSparkSessionExtension,"
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    .config(
        "spark.sql.catalog.spark_catalog",
        "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    )
    # Iceberg + Glue Data Catalog for source reads
    .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
    .config(
        "spark.sql.catalog.glue_catalog.catalog-impl",
        "org.apache.iceberg.aws.glue.GlueCatalog",
    )
    .config(
        "spark.sql.catalog.glue_catalog.io-impl",
        "org.apache.iceberg.aws.s3.S3FileIO",
    )
    .config("spark.sql.catalog.glue_catalog.warehouse", "{iceberg_warehouse}")
    .getOrCreate()
)"""
    else:
        spark_session_template = f"""\
spark = (
    SparkSession.builder
    .appName("{etl_spec.pipeline_name}")
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config(
        "spark.sql.catalog.spark_catalog",
        "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    )
    .getOrCreate()
)"""

    # ── Source data section ────────────────────────────────────────────────────
    # Priority:
    #   1. Iceberg table available → spark.table() (authoritative schema)
    #   2. Glue schema available but no Iceberg → spark.read.csv() with columns comment
    #   3. Nothing available → spark.read.csv() with assumption comment

    if glue_table_name and iceberg_warehouse:
        iceberg_table_ref = f"glue_catalog.{glue_database}.{glue_table_name}"
        source_section = f"""
## Source Data — Apache Iceberg (Authoritative)
Read the source dataset using the Iceberg catalog. Do NOT use spark.read.csv()
or hardcode S3 paths — the Iceberg table always contains the current, versioned
data and its schema is read from metadata at runtime.

```python
# Read from Iceberg — schema is authoritative (no inference needed)
df = spark.table("{iceberg_table_ref}")
```

Iceberg table reference: `{iceberg_table_ref}`
"""
        if source_schema and source_schema.get("columns"):
            columns = source_schema["columns"]
            col_lines = "\n".join(f"  - {c['name']}: {c['type']}" for c in columns)
            source_section += f"""
The catalog reports these columns ({len(columns)} total) — Iceberg schema may
have evolved since the last crawler run, so trust the spark.table() output:
{col_lines}
"""

    elif source_schema and source_schema.get("columns"):
        columns = source_schema["columns"]
        col_lines = "\n".join(f"  - {c['name']}: {c['type']}" for c in columns)
        sample_key = source_schema.get("sample_key", source_schema.get("source", ""))
        source_section = f"""
## Source Schema (Glue catalog — Iceberg not yet available for this table)
The following column names and types were read from the Glue catalog.
Use spark.read.csv() for now; the pipeline will automatically switch to
spark.table() after the Iceberg migration completes.

```python
df = spark.read.option("header", "true").option("inferSchema", "true").csv("{etl_spec.source.path}")
```

Columns from {sample_key} ({len(columns)} total):
{col_lines}

You MUST use these exact column names — do not invent or rename columns.
"""
    else:
        source_section = f"""
## Source Schema
No schema available from Glue catalog (bucket may be empty or Iceberg migration
not yet run). Generate code using reasonable assumptions based on the pipeline
description. Read via:

```python
df = spark.read.option("header", "true").option("inferSchema", "true").csv("{etl_spec.source.path}")
```

Add a comment at the top of the generated file noting that column names are
assumed and must be verified against actual source data before deployment.
"""

    examples_text = "\n\n".join(
        f"### Example\nSpec: {ex['spec']}\nCode:\n```python\n{ex['code']}\n```"
        for ex in CODE_GEN_EXAMPLES
    )

    return f"""You are an expert PySpark Data Engineer. Generate production-ready PySpark code
for the following ETL specification. Follow enterprise best practices strictly.

## Code Requirements
- Use PySpark 3.5+ with Delta Lake (output) and Apache Iceberg (source, when available)
- Include SparkSession creation using EXACTLY this template:

```python
{spark_session_template}
```

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
{source_section}{retry_context}
## Few-Shot Examples
{examples_text}

Return:
1. A ```python code block with the complete PySpark pipeline
2. A ```markdown code block with a README for this pipeline"""
