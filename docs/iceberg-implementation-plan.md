# Lambda + Apache Iceberg Implementation Plan

**Deadline:** April 10, 2026
**Available days:** April 4 – April 10 (7 days)
**Delivery:** Live working demo on AWS

---

## Executive Summary

The current Glue crawler requires manual triggering and hardcoded S3 paths per dataset.
This plan replaces it with an event-driven architecture where:

1. A new file uploaded to S3 triggers a Lambda function within seconds
2. Lambda detects whether the prefix is new or existing, reads the file schema using pyarrow, and triggers a Glue ETL job
3. The Glue ETL job converts the raw file to Apache Iceberg format and registers the schema in the Glue Data Catalog automatically
4. The ECS Worker reads source data via `spark.table("glue_catalog.etl_agent_catalog.orders")` instead of raw S3 paths — schema is always accurate and evolution is tracked

The daily Glue crawler is retained as a nightly reconciliation job only.

---

## Architecture: Before vs After

### Before
```
Manual trigger
    → Glue Crawler scans 9 hardcoded S3 paths (~2–5 min)
    → Schema registered in Glue Data Catalog
    → resolve_catalog node fetches columns as dict
    → CodingAgent generates: spark.read.csv("s3://bucket/olist/orders/")
    → Schema inferred from file at runtime (non-deterministic)
```

### After
```
Upload file to s3://raw-bucket/olist/orders/file.csv
    → S3 Event → EventBridge → Lambda (seconds)
    → Lambda: reads schema with pyarrow, triggers Glue ETL job
    → Glue ETL job: CSV → Iceberg table in s3://processed-bucket/iceberg/
    → Schema auto-registered in Glue Data Catalog
    → resolve_catalog node fetches table name
    → CodingAgent generates: spark.table("glue_catalog.etl_agent_catalog.orders")
    → Schema read from Iceberg metadata at runtime (authoritative, always accurate)

Daily 1AM: Glue Crawler reconciliation only (safety net)
```

---

## Repository File Map

### New Files

| File | Purpose |
|---|---|
| `infra/terraform/iceberg.tf` | EventBridge rule, Lambda resource, Glue ETL job, IAM roles |
| `infra/lambda/schema_detector/handler.py` | Lambda: S3 event handler, schema detection, job trigger |
| `infra/lambda/schema_detector/schema_reader.py` | pyarrow CSV/Parquet schema extraction |
| `infra/lambda/schema_detector/glue_helper.py` | Glue table existence check, schema comparison |
| `infra/lambda/schema_detector/requirements.txt` | pyarrow (Lambda layer) |
| `infra/glue_jobs/csv_to_iceberg.py` | Glue ETL: reads raw CSV, writes Iceberg, registers table |
| `scripts/migrate_olist_to_iceberg.py` | One-time migration: converts all 9 Olist tables to Iceberg |

### Modified Files

| File | Change |
|---|---|
| `infra/terraform/glue.tf` | Widen s3_target to parent path, add cron schedule, add Iceberg IAM permissions |
| `infra/terraform/s3.tf` | Add S3 Event Notification on raw bucket → EventBridge |
| `Dockerfile` | Add Iceberg Spark runtime JARs |
| `src/etl_agent/core/config.py` | Add `iceberg_warehouse` setting |
| `src/etl_agent/core/state.py` | Add `glue_table_name: str | None` field to GraphState |
| `src/etl_agent/core/data_catalog.py` | Add `get_table_name_by_path()` method |
| `src/etl_agent/agents/orchestrator.py` | Simplify `_node_resolve_catalog` to return table name |
| `src/etl_agent/prompts/code_generator.py` | Update prompt to generate `spark.table()` with Iceberg config |

---

## Day-by-Day Implementation Plan

### Day 1 — April 4 (Thursday): Infrastructure

**Goal:** All Terraform resources deployed and verified.

#### 1.1 Modify `infra/terraform/glue.tf`

- Replace 9 specific `s3_target` blocks with a single parent path:
  ```hcl
  s3_target { path = "s3://${var.s3_bucket}/olist/" }
  ```
- Add daily schedule to the crawler resource:
  ```hcl
  schedule = "cron(0 1 * * ? *)"
  ```
- Widen the crawler IAM S3 policy from `olist/*` to `olist/**` (recursive)
- Add Glue write permissions to the crawler IAM role for Iceberg table registration:
  ```
  glue:CreateTable, glue:UpdateTable, glue:GetTable, glue:GetTables
  ```

#### 1.2 Create `infra/terraform/iceberg.tf`

**EventBridge rule** — fires on every `s3:ObjectCreated` event on the raw bucket:
```hcl
resource "aws_cloudwatch_event_rule" "s3_object_created" {
  name = "${var.project_name}-s3-object-created"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.raw.bucket] }
    }
  })
}
```

**Lambda function resource:**
```hcl
resource "aws_lambda_function" "schema_detector" {
  function_name = "${var.project_name}-schema-detector"
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  role          = aws_iam_role.schema_detector_lambda.arn
  timeout       = 60
  memory_size   = 256
  filename      = "${path.module}/../../infra/lambda/schema_detector.zip"
  layers        = [aws_lambda_layer_version.pyarrow.arn]

  environment {
    variables = {
      GLUE_DATABASE      = var.glue_catalog_database
      GLUE_JOB_NAME      = aws_glue_job.csv_to_iceberg.name
      PROCESSED_BUCKET   = aws_s3_bucket.processed.bucket
      RAW_BUCKET         = aws_s3_bucket.raw.bucket
    }
  }
}
```

**Lambda IAM role** with permissions:
```
s3:GetObject, s3:HeadObject (raw bucket)
glue:GetTable, glue:GetTables
glue:StartJobRun
logs:CreateLogGroup, logs:PutLogEvents
```

**pyarrow Lambda layer:**
```hcl
resource "aws_lambda_layer_version" "pyarrow" {
  layer_name          = "${var.project_name}-pyarrow"
  compatible_runtimes = ["python3.12"]
  filename            = "${path.module}/../../infra/lambda/pyarrow-layer.zip"
}
```

**Glue ETL job resource:**
```hcl
resource "aws_glue_job" "csv_to_iceberg" {
  name         = "${var.project_name}-csv-to-iceberg"
  role_arn     = aws_iam_role.glue_etl.arn
  glue_version = "4.0"
  worker_type  = "G.1X"
  number_of_workers = 2

  command {
    script_location = "s3://${aws_s3_bucket.artifacts.bucket}/glue-jobs/csv_to_iceberg.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-glue-datacatalog"          = "true"
    "--datalake-formats"                 = "iceberg"
    "--conf"                             = "spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.processed.bucket}/iceberg/"
    "--TempDir"                          = "s3://${aws_s3_bucket.artifacts.bucket}/glue-tmp/"
  }
}
```

**Glue ETL IAM role** with permissions:
```
s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket (raw + processed + artifacts buckets)
glue:GetDatabase, glue:GetTable, glue:CreateTable, glue:UpdateTable, glue:GetPartitions
AWSGlueServiceRole (managed policy)
```

#### 1.3 Modify `infra/terraform/s3.tf`

Add S3 EventBridge notification on the raw bucket:
```hcl
resource "aws_s3_bucket_notification" "raw_events" {
  bucket      = aws_s3_bucket.raw.id
  eventbridge = true
}
```

#### 1.4 Verify

```bash
cd infra/terraform
terraform plan
terraform apply
```

Confirm in AWS Console:
- EventBridge rule exists and is enabled
- Lambda function deployed
- Glue ETL job registered
- Crawler updated with new path and schedule

---

### Day 2 — April 5 (Friday): Lambda Function

**Goal:** Lambda correctly detects new vs existing prefixes, reads schema, triggers Glue ETL job.

#### 2.1 `infra/lambda/schema_detector/handler.py`

```python
"""
Schema Detector Lambda
Triggered by S3 ObjectCreated events via EventBridge.
Detects new data sources, reads schema, triggers Glue ETL conversion job.
"""
import os
import json
import logging
import boto3
from glue_helper import table_exists, schemas_differ, get_existing_schema
from schema_reader import read_schema

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

GLUE_DATABASE    = os.environ["GLUE_DATABASE"]
GLUE_JOB_NAME    = os.environ["GLUE_JOB_NAME"]
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
RAW_BUCKET       = os.environ["RAW_BUCKET"]

s3_client   = boto3.client("s3")
glue_client = boto3.client("glue")


def lambda_handler(event: dict, context: object) -> dict:
    detail   = event.get("detail", {})
    bucket   = detail["bucket"]["name"]
    key      = detail["object"]["key"]

    # Skip zero-byte folder marker objects
    if key.endswith("/") or detail["object"].get("size", 1) == 0:
        return {"status": "skipped", "reason": "folder marker"}

    # Extract table name from prefix: olist/orders/file.csv → orders
    parts      = key.strip("/").split("/")
    table_name = parts[-2] if len(parts) >= 2 else parts[0]
    prefix     = "/".join(parts[:-1]) + "/"
    source_path = f"s3://{bucket}/{prefix}"

    logger.info("schema_detector_triggered", bucket=bucket, key=key,
                table_name=table_name, prefix=prefix)

    # Read schema from the new file
    new_schema = read_schema(s3_client, bucket, key)
    if new_schema is None:
        logger.warning("schema_read_failed", key=key)
        return {"status": "skipped", "reason": "schema unreadable"}

    # Determine if we need to trigger a conversion job
    existing = table_exists(glue_client, GLUE_DATABASE, table_name)

    if not existing:
        logger.info("new_dataset_detected", table_name=table_name)
        _trigger_job(source_path, table_name)
    else:
        old_schema = get_existing_schema(glue_client, GLUE_DATABASE, table_name)
        if schemas_differ(old_schema, new_schema):
            logger.info("schema_change_detected", table_name=table_name)
            _trigger_job(source_path, table_name)
        else:
            logger.info("schema_unchanged", table_name=table_name)

    return {"status": "ok", "table": table_name}


def _trigger_job(source_path: str, table_name: str) -> None:
    try:
        glue_client.start_job_run(
            JobName=GLUE_JOB_NAME,
            Arguments={
                "--source_path":       source_path,
                "--table_name":        table_name,
                "--database":          GLUE_DATABASE,
                "--processed_bucket":  PROCESSED_BUCKET,
            },
        )
        logger.info("glue_job_triggered", job=GLUE_JOB_NAME, table=table_name)
    except glue_client.exceptions.ConcurrentRunsExceededException:
        # Another invocation already started a run for this job — safe to ignore,
        # the running job will process all files already uploaded to the prefix.
        logger.warning("glue_job_already_running", table=table_name)
```

#### 2.2 `infra/lambda/schema_detector/schema_reader.py`

```python
"""Reads column names and types from CSV (header + 200 rows) or Parquet (footer)."""
import io
import logging
from typing import Any
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# Minimum non-null values needed before trusting an inferred type
_MIN_NONNULL = 10

# Glue type mapping from pyarrow
_PA_TO_GLUE: dict[str, str] = {
    "int8":    "bigint", "int16":   "bigint", "int32":   "bigint", "int64": "bigint",
    "uint8":   "bigint", "uint16":  "bigint", "uint32":  "bigint", "uint64": "bigint",
    "float":   "double", "double":  "double", "float16": "double", "float32": "double",
    "float64": "double",
    "bool":    "boolean",
    "date32":  "date",   "date64":  "date",
    "timestamp[ns]": "timestamp", "timestamp[us]": "timestamp",
    "string":  "string", "utf8":    "string", "large_utf8": "string",
}


def read_schema(s3_client: Any, bucket: str, key: str) -> list[dict] | None:
    """
    Returns a list of {"name": ..., "type": ...} dicts.
    Returns None if the file cannot be read or schema cannot be determined.
    """
    try:
        suffix = key.rsplit(".", 1)[-1].lower()
        if suffix == "parquet":
            return _read_parquet_schema(s3_client, bucket, key)
        elif suffix in ("csv", "tsv", "txt"):
            return _read_csv_schema(s3_client, bucket, key)
        else:
            logger.warning("unsupported_format", key=key, suffix=suffix)
            return None
    except Exception as exc:
        logger.warning("schema_read_error", key=key, error=str(exc))
        return None


def _read_parquet_schema(s3_client: Any, bucket: str, key: str) -> list[dict]:
    """Read schema from Parquet file footer — exact types, no inference."""
    resp  = s3_client.get_object(Bucket=bucket, Key=key)
    data  = resp["Body"].read()
    buf   = io.BytesIO(data)
    pfile = pq.ParquetFile(buf)
    schema = pfile.schema_arrow

    return [
        {"name": field.name, "type": _pa_type_to_glue(field.type)}
        for field in schema
    ]


def _read_csv_schema(s3_client: Any, bucket: str, key: str) -> list[dict]:
    """
    Sample up to 200 rows.
    - File size < 1MB: read the whole file for maximum accuracy.
    - File size >= 1MB: byte-range request for header + ~200 rows (~50KB).
    """
    head     = s3_client.head_object(Bucket=bucket, Key=key)
    filesize = head["ContentLength"]

    if filesize < 1_000_000:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        raw  = resp["Body"].read()
    else:
        # Read first 50KB — enough for header + ~200 rows of typical CSV
        resp = s3_client.get_object(Bucket=bucket, Key=key,
                                    Range="bytes=0-51200")
        raw  = resp["Body"].read()

    try:
        table = pcsv.read_csv(
            io.BytesIO(raw),
            read_options=pcsv.ReadOptions(block_size=len(raw)),
            parse_options=pcsv.ParseOptions(invalid_row_handler=lambda _: "skip"),
        )
    except Exception:
        # Incomplete last line from byte-range cut — drop it and retry
        raw   = raw[: raw.rfind(b"\n")]
        table = pcsv.read_csv(io.BytesIO(raw))

    columns = []
    for i, field in enumerate(table.schema):
        col_data   = table.column(i).drop_null()
        nonnull    = len(col_data)
        glue_type  = "string"  # safe default

        if nonnull >= _MIN_NONNULL:
            pa_type   = str(field.type)
            glue_type = _pa_type_to_glue(field.type)

            # Detect financial decimal columns: double with consistent 2dp
            if glue_type == "double":
                glue_type = _maybe_decimal(col_data, pa_type) or glue_type

        columns.append({"name": field.name, "type": glue_type})

    return columns


def _pa_type_to_glue(pa_type: Any) -> str:
    key = str(pa_type)
    return _PA_TO_GLUE.get(key, "string")


def _maybe_decimal(col: Any, pa_type: str) -> str | None:
    """Return decimal(10,2) if all values have exactly 2 decimal places."""
    if "float" not in pa_type and "double" not in pa_type:
        return None
    try:
        vals = col.to_pylist()
        if all(
            isinstance(v, float) and len(str(v).rstrip("0").split(".")[-1]) <= 2
            for v in vals[:50]  # sample first 50 to keep Lambda fast
        ):
            return "decimal(10,2)"
    except Exception:
        pass
    return None
```

#### 2.3 `infra/lambda/schema_detector/glue_helper.py`

```python
"""Glue catalog helper: table existence check and schema comparison."""
import logging
from typing import Any
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def table_exists(glue_client: Any, database: str, table_name: str) -> bool:
    try:
        glue_client.get_table(DatabaseName=database, Name=table_name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            return False
        raise


def get_existing_schema(glue_client: Any, database: str,
                        table_name: str) -> list[dict]:
    """Return list of {"name": ..., "type": ...} from existing Glue table."""
    resp    = glue_client.get_table(DatabaseName=database, Name=table_name)
    columns = resp["Table"]["StorageDescriptor"]["Columns"]
    return [{"name": c["Name"], "type": c["Type"]} for c in columns]


def schemas_differ(old: list[dict], new: list[dict]) -> bool:
    """True if column names or types differ between old and new schema."""
    old_map = {c["name"]: c["type"] for c in old}
    new_map = {c["name"]: c["type"] for c in new}
    return old_map != new_map
```

#### 2.4 Unit Tests

Create `tests/unit/test_schema_detector.py`:
- `test_new_prefix_triggers_job` — table doesn't exist → job triggered
- `test_same_schema_no_trigger` — schema matches → no job triggered
- `test_schema_change_triggers_job` — new column → job triggered
- `test_concurrent_run_handled` — `ConcurrentRunsExceededException` caught silently
- `test_folder_marker_skipped` — zero-byte key ending in `/` returns skipped
- `test_csv_schema_types` — price column inferred as decimal(10,2), not double
- `test_small_file_full_read` — files < 1MB read entirely
- `test_min_nonnull_guard` — column with 5 non-null values defaults to string

---

### Day 3 — April 6 (Saturday): Glue ETL Job + Olist Migration

**Goal:** Glue job converts raw CSV to Iceberg and registers in Glue catalog.
All 9 Olist tables migrated to Iceberg.

#### 3.1 `infra/glue_jobs/csv_to_iceberg.py`

```python
"""
Glue ETL Job: CSV → Apache Iceberg
Reads raw CSV from S3, writes as Iceberg table to processed bucket.
Table is automatically registered in Glue Data Catalog.

Arguments:
  --source_path:      S3 URI of the source folder  (e.g. s3://raw/olist/orders/)
  --table_name:       Glue table name               (e.g. orders)
  --database:         Glue database name            (e.g. etl_agent_catalog)
  --processed_bucket: Destination bucket for Iceberg (e.g. etl-agent-processed-prod)
"""
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job

args = getResolvedOptions(sys.argv, [
    "JOB_NAME", "source_path", "table_name", "database", "processed_bucket",
])

sc         = SparkContext()
glueCtx    = GlueContext(sc)
spark      = glueCtx.spark_session
job        = Job(glueCtx)
job.init(args["JOB_NAME"], args)

# Configure Iceberg with Glue Data Catalog as the catalog backend
spark.conf.set(
    "spark.sql.catalog.glue_catalog.warehouse",
    f"s3://{args['processed_bucket']}/iceberg/",
)

# Read raw CSV — Spark infers types (far more reliable than Lambda-based inference)
df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .option("mergeSchema", "true")  # handles mixed-schema files in same folder
    .csv(args["source_path"])
)

print(f"[csv_to_iceberg] Read {df.count()} rows from {args['source_path']}")
print(f"[csv_to_iceberg] Schema: {df.schema.simpleString()}")

# Write as Iceberg — createOrReplace handles both new tables and schema evolution
(
    df.writeTo(f"glue_catalog.{args['database']}.{args['table_name']}")
    .tableProperty("format-version", "2")
    .tableProperty("write.format.default", "parquet")
    .tableProperty("write.parquet.compression-codec", "snappy")
    .createOrReplace()
)

print(f"[csv_to_iceberg] Iceberg table written: "
      f"glue_catalog.{args['database']}.{args['table_name']}")
job.commit()
```

#### 3.2 Upload Glue Job Script to S3

```bash
aws s3 cp infra/glue_jobs/csv_to_iceberg.py \
  s3://etl-agent-artifacts-prod/glue-jobs/csv_to_iceberg.py
```

#### 3.3 `scripts/migrate_olist_to_iceberg.py`

```python
"""
One-time migration: converts all 9 Olist CSV tables to Apache Iceberg format.
Run once after Terraform is applied and before the first pipeline execution.

Usage:
  uv run python scripts/migrate_olist_to_iceberg.py
"""
import boto3
import time

glue   = boto3.client("glue", region_name="us-east-1")

OLIST_TABLES = [
    "orders", "order_items", "order_payments", "order_reviews",
    "customers", "sellers", "products", "geolocation",
    "product_category_translation",
]

JOB_NAME         = "etl-agent-csv-to-iceberg"
RAW_BUCKET       = "etl-agent-raw-prod"
PROCESSED_BUCKET = "etl-agent-processed-prod"
DATABASE         = "etl_agent_catalog"


def start_job(table_name: str) -> str:
    response = glue.start_job_run(
        JobName=JOB_NAME,
        Arguments={
            "--source_path":       f"s3://{RAW_BUCKET}/olist/{table_name}/",
            "--table_name":        table_name,
            "--database":          DATABASE,
            "--processed_bucket":  PROCESSED_BUCKET,
        },
    )
    return response["JobRunId"]


def wait_for_job(run_id: str, table_name: str) -> bool:
    while True:
        resp   = glue.get_job_run(JobName=JOB_NAME, RunId=run_id)
        state  = resp["JobRun"]["JobRunState"]
        print(f"  [{table_name}] {state}")
        if state in ("SUCCEEDED",):
            return True
        if state in ("FAILED", "STOPPED", "ERROR", "TIMEOUT"):
            print(f"  [{table_name}] FAILED: {resp['JobRun'].get('ErrorMessage')}")
            return False
        time.sleep(15)


if __name__ == "__main__":
    print("Starting Olist → Iceberg migration...")
    run_ids = {}

    # Start all jobs in parallel
    for table in OLIST_TABLES:
        run_id = start_job(table)
        run_ids[table] = run_id
        print(f"Started job for '{table}': {run_id}")

    # Wait for all to complete
    results = {}
    for table, run_id in run_ids.items():
        results[table] = wait_for_job(run_id, table)

    print("\nMigration Summary:")
    for table, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"  {table}: {status}")
```

#### 3.4 Run Migration

```bash
uv run python scripts/migrate_olist_to_iceberg.py
```

Verify in AWS Glue Console → Tables: all 9 tables have `iceberg` table type.

---

### Day 4 — April 7 (Sunday): Application Changes

**Goal:** ECS Worker reads Iceberg tables. CodingAgent generates `spark.table()` code.

#### 4.1 Modify `Dockerfile`

Add Iceberg JARs for Spark 3.5 to the runtime stage.
The JARs are downloaded during the Docker build from Maven Central:

```dockerfile
# ── Iceberg JARs for Spark 3.5 ──────────────────────────────────────────────
ARG ICEBERG_VERSION=1.5.2

RUN mkdir -p /opt/spark/jars && \
    curl -fsSL -o /opt/spark/jars/iceberg-spark-runtime.jar \
      "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar" && \
    curl -fsSL -o /opt/spark/jars/iceberg-aws-bundle.jar \
      "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar"

# Tell PySpark to include Iceberg JARs on the driver and executor classpaths
ENV PYSPARK_SUBMIT_ARGS="--jars /opt/spark/jars/iceberg-spark-runtime.jar,/opt/spark/jars/iceberg-aws-bundle.jar --master local[*] pyspark-shell"
```

#### 4.2 Add `iceberg_warehouse` to `src/etl_agent/core/config.py`

```python
# Iceberg
iceberg_warehouse: str = Field(
    default="",
    description="S3 URI for the Iceberg warehouse (e.g. s3://bucket/iceberg/)"
)
```

Add the corresponding environment variable to ECS task definition and Secrets Manager:
```
ICEBERG_WAREHOUSE = s3://etl-agent-processed-prod/iceberg/
```

#### 4.3 Add `glue_table_name` to `src/etl_agent/core/state.py`

```python
glue_table_name: str | None   # Resolved by resolve_catalog node
```

#### 4.4 Simplify `_node_resolve_catalog` in `src/etl_agent/agents/orchestrator.py`

Before, the node returned a `source_schema` dict of column names/types.
After, it returns the `glue_table_name` — schema is resolved by Spark from Iceberg at runtime.

```python
async def _node_resolve_catalog(state: GraphState) -> dict[str, Any]:
    """Resolve the Glue/Iceberg table name for the source dataset.

    Instead of fetching schema columns, we now return the table name.
    Spark reads the authoritative schema from Iceberg metadata at execution time.
    """
    from etl_agent.core.data_catalog import get_catalog

    etl_spec = state.get("etl_spec")
    if etl_spec is None:
        return {"glue_table_name": None, "source_schema": None,
                "current_stage": "resolve_catalog"}

    source_path: str = etl_spec.source.path

    try:
        entity         = get_catalog().get_entity_by_path(source_path)
        table_name     = entity.name if entity else None
        # Keep source_schema populated for backwards compatibility
        # and fallback if Iceberg is not yet available for this table
        source_schema  = (
            {"columns": [{"name": f.name, "type": f.type} for f in entity.columns],
             "format": entity.format, "source": source_path}
            if entity else None
        )
    except Exception as exc:
        logger.warning("resolve_catalog_failed", error=str(exc))
        table_name    = None
        source_schema = None

    return {
        "glue_table_name": table_name,
        "source_schema":   source_schema,
        "current_stage":   "resolve_catalog",
    }
```

#### 4.5 Update `src/etl_agent/prompts/code_generator.py`

Add the `glue_table_name` parameter and update the Spark session template.

**Key changes to the prompt:**

1. Add `glue_table_name: str | None` parameter to `build_code_generator_prompt()`
2. When `glue_table_name` is available, instruct the LLM to read via Iceberg:
   ```
   Read the source data using:
     df = spark.table("glue_catalog.{database}.{table_name}")

   This reads from an Apache Iceberg table. Do NOT use spark.read.csv()
   or hardcode S3 paths for the source dataset.
   ```
3. Update the SparkSession template the prompt instructs the LLM to generate:
   ```python
   spark = (
       SparkSession.builder
       .appName("{pipeline_name}")
       # Delta Lake for output writes
       .config("spark.sql.extensions",
               "io.delta.sql.DeltaSparkSessionExtension,"
               "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
       .config("spark.sql.catalog.spark_catalog",
               "org.apache.spark.sql.delta.catalog.DeltaCatalog")
       # Iceberg + Glue Data Catalog for source reads
       .config("spark.sql.catalog.glue_catalog",
               "org.apache.iceberg.spark.SparkCatalog")
       .config("spark.sql.catalog.glue_catalog.catalog-impl",
               "org.apache.iceberg.aws.glue.GlueCatalog")
       .config("spark.sql.catalog.glue_catalog.io-impl",
               "org.apache.iceberg.aws.s3.S3FileIO")
       .config("spark.sql.catalog.glue_catalog.warehouse",
               "{iceberg_warehouse}")
       .getOrCreate()
   )
   ```

4. Fallback: if `glue_table_name` is None (table not yet in Iceberg), fall back to the existing `spark.read.csv(source_path)` approach. This ensures the pipeline doesn't break during the migration window.

#### 4.6 Add `get_table_name_by_path()` to `src/etl_agent/core/data_catalog.py`

```python
def get_table_name_by_path(self, s3_path: str) -> str | None:
    """Return just the Glue table name for a given S3 path.
    More lightweight than get_entity_by_path() — no column fetch needed."""
    entity = self.get_entity_by_path(s3_path)
    return entity.name if entity else None
```

---

### Day 5 — April 8 (Monday): Integration Testing

**Goal:** Full pipeline runs end-to-end using Iceberg tables.

#### 5.1 Test: Upload New CSV → Lambda → Glue Job → Catalog

```bash
# Upload a test CSV to a new folder
aws s3 cp tests/fixtures/test_shipments.csv \
  s3://etl-agent-raw-prod/olist/shipments/shipments_2024.csv

# Check CloudWatch logs for Lambda execution
aws logs tail /aws/lambda/etl-agent-schema-detector --follow

# Check Glue job ran
aws glue get-job-runs --job-name etl-agent-csv-to-iceberg \
  --query 'JobRuns[0].{State:JobRunState,Table:Arguments."--table_name"}'

# Verify table in Glue catalog
aws glue get-table --database-name etl_agent_catalog --name shipments \
  --query 'Table.{Name:Name,Type:TableType,Columns:StorageDescriptor.Columns}'
```

#### 5.2 Test: Pipeline Uses Iceberg Table

Submit a story referencing the new dataset via the web UI or API:

```bash
curl -X POST http://etl-agent-alb-.../api/v1/stories \
  -b "etl_session=..." \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Shipment delay analysis",
    "description": "Analyse shipments data to identify average delay by region",
    "acceptance_criteria": [
      "Output must include region and average delay in days",
      "Filter out cancelled shipments"
    ]
  }'
```

Verify generated code uses `spark.table("glue_catalog.etl_agent_catalog.shipments")`.

#### 5.3 Test: Schema Evolution

Upload a second CSV to an existing table folder with an additional column:

```bash
aws s3 cp tests/fixtures/orders_v2.csv \
  s3://etl-agent-raw-prod/olist/orders/orders_2024.csv
```

Verify:
- Lambda detects schema difference
- Glue job triggered
- Glue catalog updated with new column
- Existing `orders` Iceberg table still queryable

#### 5.4 CI Tests

```bash
uv run pytest tests/unit/ -v -m unit
uv run pytest tests/integration/ -v -m integration
```

All tests must pass including the new `test_schema_detector.py` tests.

---

### Day 6 — April 9 (Tuesday): Buffer + Polish

**Goal:** Fix any issues from integration testing. Documentation finalized.

- Fix any failing tests or integration issues
- Update `docs/sphinx/` — add Iceberg section to `aws_services.rst` and `architecture.rst`
- Update the architecture Mermaid diagram to show the new event-driven flow
- Update `docs/eval-plan.md` — note that schema grounding eval now validates `spark.table()` usage
- Push all changes, confirm CI is green
- Final `terraform apply` to ensure all infrastructure is current
- Seed the live database with demo runs: `uv run python scripts/seed_db.py`

---

### Day 7 — April 10 (Wednesday): Demo Day

**Goal:** Live working demo walkthrough.

---

## Demo Script (Live)

The demo runs in three acts. Total time: ~15 minutes.

### Act 1 — The Problem (2 minutes)

Show the current Glue crawler in the AWS Console:
- 9 hardcoded S3 targets
- No schedule — manual only
- Generated PySpark code with hardcoded S3 path and inferred schema

This is the "before" state.

### Act 2 — Event-Driven Schema Registration (7 minutes)

**Step 1:** Open two browser tabs side by side:
- Tab 1: AWS CloudWatch Logs → `/aws/lambda/etl-agent-schema-detector`
- Tab 2: AWS Glue Console → Tables (showing current 9 Olist tables)

**Step 2:** Upload a new CSV file representing a new data source:
```bash
aws s3 cp tests/fixtures/demo_shipments.csv \
  s3://etl-agent-raw-prod/olist/shipments/shipments_2024.csv
```

**Step 3:** Switch to CloudWatch tab — Lambda log appears within ~5 seconds:
```
schema_detector_triggered: table=shipments
new_dataset_detected: table=shipments
glue_job_triggered: job=etl-agent-csv-to-iceberg
```

**Step 4:** Switch to Glue Console → Jobs → Show Glue ETL job running (~90 seconds).

**Step 5:** Once job completes, refresh Glue Console → Tables — `shipments` table appears with correct types (`decimal(10,2)` for amounts, `timestamp` for dates, `bigint` for counts).

**Key talking point:** No Terraform change. No manual trigger. Zero engineering effort to add a new data source.

### Act 3 — Pipeline Uses the New Table (6 minutes)

**Step 1:** Open the ETL Agent web UI.

**Step 2:** Submit a new story referencing the shipments dataset:
```
Title: Shipment delay analysis
Description: Analyse shipments data to calculate average delivery delay
             by seller region, identifying the top 5 delayed regions.
Acceptance criteria:
  - Output must include region name and average delay in days
  - Filter out cancelled shipments
  - Sort by delay descending
```

**Step 3:** Watch the pipeline tracker panel:
- `parse_story` — ETLSpec generated, source resolved to `shipments` table
- `resolve_catalog` — Glue table name resolved: `etl_agent_catalog.shipments`
- `generate_code` — code generated
- `run_tests` — tests pass
- `create_pr` — GitHub PR created

**Step 4:** Open the GitHub PR — show the generated PySpark code:
```python
df = spark.table("glue_catalog.etl_agent_catalog.shipments")
```

No hardcoded S3 path. Schema sourced from Iceberg at runtime.

**Step 5:** Show the Glue Catalog table — all column types are correct (`decimal(10,2)`, `timestamp`, `bigint`), not `string`.

**Closing point:** From file upload to production-ready PR — fully automated, no manual steps, correct types throughout.

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Iceberg + Delta Lake JAR conflict in same SparkSession | Medium | High | Both are registered in the same `spark.sql.extensions` string with different catalog names — this is a supported pattern. Validate on Day 4. |
| Glue ETL job cold start (1–3 min) | High | Low | Expected and acceptable. Demo includes a 90-second wait — frame as "still faster than manual". |
| Lambda pyarrow layer size exceeds 250MB | Low | Medium | pyarrow wheel is ~35MB compressed. Well within Lambda's 250MB limit. |
| Iceberg table not yet available when pipeline runs | Low | Low | `_node_resolve_catalog` falls back to `spark.read.csv()` if `glue_table_name` is None. Pipeline never breaks. |
| AWS Maven Central download blocked during Docker build | Low | High | Pre-download JARs and store in S3 artifacts bucket as fallback. |
| ECS task IAM role missing Glue permissions | Medium | Medium | Add `glue:GetTable`, `glue:GetTables`, `glue:GetDatabase`, `glue:GetPartitions` to ECS task role on Day 1. Verify on Day 4. |

---

## New Environment Variables

| Variable | Value | Where |
|---|---|---|
| `ICEBERG_WAREHOUSE` | `s3://etl-agent-processed-prod/iceberg/` | ECS task + Secrets Manager |
| `GLUE_JOB_NAME` | `etl-agent-csv-to-iceberg` | Lambda env var (Terraform) |
| `PROCESSED_BUCKET` | `etl-agent-processed-prod` | Lambda env var (Terraform) |

---

## IAM Permissions Summary

### ECS Task Role (new additions)
```
glue:GetDatabase
glue:GetTable
glue:GetTables
glue:GetPartitions
glue:GetPartition
```

### Lambda Execution Role
```
s3:GetObject
s3:HeadObject
glue:GetTable
glue:GetTables
glue:StartJobRun
logs:CreateLogGroup
logs:CreateLogStream
logs:PutLogEvents
```

### Glue ETL Job Role
```
s3:GetObject, s3:PutObject, s3:DeleteObject, s3:ListBucket (raw + processed + artifacts)
glue:GetDatabase
glue:GetTable, glue:CreateTable, glue:UpdateTable
glue:GetPartitions, glue:BatchCreatePartition
AWSGlueServiceRole (managed)
```

---

## Definition of Done

- [ ] All 9 Olist tables migrated to Iceberg and visible in Glue Console with correct types
- [ ] Upload of a new CSV to a new S3 prefix triggers Lambda within 5 seconds
- [ ] Glue ETL job completes and registers the new table in the catalog
- [ ] Upload of a new CSV to an existing prefix with same schema does NOT trigger a job
- [ ] Upload of a new CSV to an existing prefix with schema change DOES trigger a job
- [ ] ConcurrentRunsExceededException handled gracefully (no Lambda error)
- [ ] Generated PySpark code uses `spark.table("glue_catalog.etl_agent_catalog.{table}")` for source reads
- [ ] Generated code tests pass in the ECS Worker
- [ ] Daily Glue crawler runs at 1AM (verify via EventBridge schedule)
- [ ] All unit and integration tests pass in CI
- [ ] Live demo completes end-to-end without errors
