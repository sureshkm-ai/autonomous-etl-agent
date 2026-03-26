# Configuration Guide

This guide explains how to write user stories, configure the agent framework, and tune the ETL pipeline for your environment.

---

## User Story Format

User stories are YAML (or JSON) files that describe an ETL requirement in plain English plus structured metadata. The agent parses the story and uses it to generate a production-ready PySpark pipeline.

### Full Schema

```yaml
# ── Required fields ──────────────────────────────────────────────────────────
id: rfm_analysis                        # Unique identifier (snake_case)
title: RFM Customer Segmentation        # Human-readable title

description: >                          # Multi-line plain-English description
  Compute Recency, Frequency, and Monetary scores for Amazon customers
  based on their 12-month order history. Segment customers into five
  cohorts using quintile bucketing.

# ── Source ───────────────────────────────────────────────────────────────────
source:
  path: s3://my-bucket/raw/amazon_orders/   # S3 path, local path, or HDFS URI
  format: parquet                            # parquet | delta | csv | json | orc
  options:                                   # Optional Spark read options
    header: "true"
    delimiter: ","
  schema:                                    # Optional: enforce schema at read
    - name: order_id
      type: StringType
      nullable: false
    - name: customer_id
      type: StringType
      nullable: false
    - name: order_date
      type: DateType
      nullable: false
    - name: total_amount
      type: DoubleType
      nullable: true

# ── Target ───────────────────────────────────────────────────────────────────
target:
  path: s3://my-bucket/processed/rfm_scores/
  format: delta                              # delta (recommended) | parquet | csv
  mode: overwrite                            # overwrite | append | merge
  partition_by:                              # Optional partition columns
    - rfm_segment

# ── Transformations (ordered pipeline steps) ─────────────────────────────────
transformations:
  - name: aggregate_orders                  # Step name (used as function name)
    operation: aggregate                    # See Operation Types below
    description: Compute R/F/M metrics per customer
    params:
      group_by: [customer_id]
      aggregations:
        - function: max
          column: order_date
          alias: last_order_date
        - function: count
          column: order_id
          alias: frequency
        - function: sum
          column: total_amount
          alias: monetary

  - name: fill_null_monetary
    operation: fill_null
    description: Replace null monetary values with 0
    params:
      fill_values:
        monetary: 0.0

  - name: compute_rfm_scores
    operation: enrich
    description: Add R/F/M quintile scores and segment label
    params:
      derived_columns:
        - name: recency_days
          expression: "datediff(current_date(), last_order_date)"
        - name: rfm_segment
          expression: "CASE WHEN r_score=5 AND f_score=5 THEN 'Champions' ELSE 'Other' END"

# ── Acceptance Criteria ───────────────────────────────────────────────────────
acceptance_criteria:
  - All customers present in source appear in output
  - No null values in rfm_segment column
  - Row count is stable across reruns (idempotent)
  - Minimum test coverage 80%

# ── Tags ─────────────────────────────────────────────────────────────────────
tags:
  - rfm
  - segmentation
  - analytics
  - amazon
```

---

## Operation Types

The `operation` field in each transformation step controls what code is generated:

| Operation | Description | Key `params` |
|-----------|-------------|--------------|
| `filter` | Keep rows matching a SQL condition | `condition` (SQL expr) |
| `fill_null` | Replace null values in specified columns | `fill_values` (dict) |
| `rename` | Rename columns | `column_map` (dict old→new) |
| `cast` | Change column data types | `cast_map` (dict col→type) |
| `aggregate` | Group-by and aggregate | `group_by`, `aggregations` |
| `join` | Join with another dataset | `right_path`, `join_keys`, `join_type` |
| `dedupe` | Remove duplicate rows | `subset_cols` (optional) |
| `enrich` | Add derived columns via SQL expressions | `derived_columns` |
| `sort` | Order the DataFrame | `sort_columns` (list of col+desc) |
| `upsert` | Delta merge (handled at write stage) | — |

---

## Framework Configuration

The agent framework is configured in `config/framework_config.yaml`. This file controls code generation standards, naming conventions, and test requirements.

```yaml
# config/framework_config.yaml

schema_standards:
  require_schema_validation: true     # Always validate schema on read
  allow_schema_evolution: true        # Delta table schema evolution enabled
  null_handling: strict               # Fail on unexpected nulls

transformation_rules:
  broadcast_join_threshold_mb: 10     # Auto-broadcast tables smaller than this
  prefer_delta_for_target: true       # Default target format is Delta Lake
  enable_aqe: true                    # Enable Adaptive Query Execution

naming_conventions:
  pipeline_prefix: ""                 # e.g. set to "etl_" to get etl_rfm_analysis
  function_style: snake_case          # snake_case | camelCase
  test_prefix: "test_"                # Test function prefix

test_coverage:
  minimum_coverage_pct: 80            # CI fails if coverage drops below this
  required_checks:
    - schema_validation               # Output schema matches expected
    - null_check                      # No nulls in required columns
    - business_logic                  # Domain-specific assertions
    - row_count                       # Non-zero output rows

output:
  default_format: delta               # delta | parquet
  partition_by: [year, month]         # Default partition scheme

performance:
  broadcast_join_threshold_mb: 10
  target_file_size_mb: 128            # Target Parquet/Delta file size
  enable_z_order: true                # Enable Z-ORDER after Delta write
```

---

## Environment Variables

All agent configuration is driven by environment variables (or a `.env` file). Copy `.env.example` to `.env` and fill in the required values.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | `sk-ant-...` |
| `GITHUB_TOKEN` | GitHub Personal Access Token | `ghp_...` |
| `GITHUB_TARGET_REPO` | Repo where agent creates PRs | `my-org/etl-pipelines-demo` |
| `AWS_ACCESS_KEY_ID` | AWS access key (or `test` for LocalStack) | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key (or `test` for LocalStack) | `wJalrXUtnFEMI/...` |
| `API_KEY` | API key for protecting agent REST endpoints | `your-secret-key` |

### Optional Variables (with defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Anthropic model ID |
| `LLM_MAX_TOKENS` | `4096` | Max LLM response tokens |
| `LLM_TEMPERATURE` | `0.7` | LLM sampling temperature |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_ENDPOINT_URL` | *(unset)* | LocalStack URL (`http://localstack:4566`) |
| `AWS_S3_ARTIFACTS_BUCKET` | `etl-agent-artifacts` | S3 bucket for packaged pipelines |
| `AIRFLOW_API_URL` | `http://localhost:8080` | Airflow REST API base URL |
| `AIRFLOW_DAG_ID` | `etl_agent_pipeline` | Target DAG for scheduling |
| `AIRFLOW_USERNAME` | `admin` | Airflow basic auth username |
| `AIRFLOW_PASSWORD` | `admin` | Airflow basic auth password |
| `MAX_RETRIES` | `2` | Max test-fail retry attempts |
| `REQUIRE_HUMAN_APPROVAL` | `false` | Pause before PR creation |
| `DEBUG` | `false` | Enable debug logging |

---

## Local Development with LocalStack

For local development, the agent uses LocalStack to emulate AWS S3. No real AWS credentials are needed.

```bash
# Start all services including LocalStack
make up

# Verify LocalStack is running
curl http://localhost:4566/_localstack/health

# List S3 buckets (created by Airflow init or app startup)
aws --endpoint-url=http://localhost:4566 s3 ls
```

The `AWS_ENDPOINT_URL=http://localstack:4566` environment variable (set automatically in `docker-compose.yml`) redirects all boto3 calls to LocalStack.

---

## Customising the LLM Prompts

Agent prompts are in `src/etl_agent/prompts/`. Each prompt module exposes a function that returns a `ChatPromptTemplate`.

To customise code generation style (e.g. add a specific logging pattern), edit `src/etl_agent/prompts/code_generator.py`. To customise few-shot examples, edit the corresponding file in `src/etl_agent/prompts/examples/`.

---

## Adding New Transformation Operations

1. Add the operation name to the `ETLOperation` enum in `src/etl_agent/core/models.py`.
2. Add a new `elif step.operation == "your_operation"` block in `src/etl_agent/spark/templates/transformations.py.j2`.
3. Add a few-shot example to `src/etl_agent/prompts/examples/code_gen_examples.py` showing the expected YAML → code mapping.
4. Write a unit test in `tests/unit/test_coding_agent.py` that validates the generated code for your new operation.
