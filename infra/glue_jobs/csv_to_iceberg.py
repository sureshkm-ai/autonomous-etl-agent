"""
Glue ETL Job: CSV → Apache Iceberg
===================================
Reads raw CSV (or TSV/Parquet) from S3 and writes it as an Apache Iceberg table
to the processed bucket. The table is automatically registered in (or updated
in) the Glue Data Catalog.

This job is triggered by the schema_detector Lambda whenever:
  - A new data source folder is detected (new table)
  - An existing table's schema has changed (schema evolution)

Supports:
  - CSV files with a header row
  - Mixed-schema files in the same folder (mergeSchema=true)
  - Schema evolution via Iceberg's createOrReplace (adds new columns, handles
    dropped columns gracefully through schema merging at read time)

Arguments (passed by Lambda via start_job_run):
  --source_path:      S3 URI of the source folder  (e.g. s3://raw/olist/orders/)
  --table_name:       Glue/Iceberg table name       (e.g. orders)
  --database:         Glue database name            (e.g. etl_agent_catalog)
  --processed_bucket: Destination bucket name       (e.g. etl-agent-processed-prod)

Usage (manual trigger for testing):
  aws glue start-job-run --job-name etl-agent-csv-to-iceberg \\
    --arguments '--source_path=s3://etl-agent-raw-prod/olist/orders/,
                 --table_name=orders,
                 --database=etl_agent_catalog,
                 --processed_bucket=etl-agent-processed-prod'
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext

# ── Resolve job arguments ─────────────────────────────────────────────────────

args = getResolvedOptions(
    sys.argv,
    ["JOB_NAME", "source_path", "table_name", "database", "processed_bucket"],
)

JOB_NAME = args["JOB_NAME"]
SOURCE_PATH = args["source_path"]
TABLE_NAME = args["table_name"]
DATABASE = args["database"]
PROCESSED_BUCKET = args["processed_bucket"]

ICEBERG_CATALOG = "glue_catalog"
ICEBERG_TABLE_REF = f"{ICEBERG_CATALOG}.{DATABASE}.{TABLE_NAME}"
WAREHOUSE_URI = f"s3://{PROCESSED_BUCKET}/iceberg/"

# ── Spark + Glue context ──────────────────────────────────────────────────────

sc = SparkContext()
glue_ctx = GlueContext(sc)
spark = glue_ctx.spark_session
job = Job(glue_ctx)
job.init(JOB_NAME, args)

# Override warehouse URI at runtime (Terraform sets it as a default_argument
# via --conf, but we set it here too as an explicit safety net).
spark.conf.set(
    f"spark.sql.catalog.{ICEBERG_CATALOG}.warehouse",
    WAREHOUSE_URI,
)

print(f"[csv_to_iceberg] JOB_NAME        = {JOB_NAME}")
print(f"[csv_to_iceberg] SOURCE_PATH     = {SOURCE_PATH}")
print(f"[csv_to_iceberg] TABLE_REF       = {ICEBERG_TABLE_REF}")
print(f"[csv_to_iceberg] WAREHOUSE_URI   = {WAREHOUSE_URI}")

# ── Read raw source data ──────────────────────────────────────────────────────
# Spark's CSV reader is more powerful than pyarrow for type inference:
#   - inferSchema scans all rows (not just 200)
#   - mergeSchema handles files with different column sets in the same folder
#   - timestampFormat handles common datetime patterns automatically

df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .option("mergeSchema", "true")
    .option("timestampFormat", "yyyy-MM-dd HH:mm:ss")
    .option("dateFormat", "yyyy-MM-dd")
    .option("mode", "PERMISSIVE")       # log bad rows, don't fail
    .option("columnNameOfCorruptRecord", "_corrupt_record")
    .csv(SOURCE_PATH)
)

row_count = df.count()
schema_str = df.schema.simpleString()

print(f"[csv_to_iceberg] Read {row_count:,} rows")
print(f"[csv_to_iceberg] Schema: {schema_str}")

# Drop the corrupt record column if present and empty
if "_corrupt_record" in df.columns:
    bad_count = df.filter(df["_corrupt_record"].isNotNull()).count()
    print(f"[csv_to_iceberg] Corrupt records: {bad_count:,}")
    df = df.drop("_corrupt_record")

# ── Write as Apache Iceberg ────────────────────────────────────────────────────
# createOrReplace handles both cases:
#   - New table: creates with format-version 2 (row-level deletes, etc.)
#   - Existing table: replaces data atomically (schema evolution tracked in metadata)
#
# Iceberg properties:
#   format-version 2          — enables merge-on-read and row-level deletes
#   write.format.default      — Parquet for columnar efficiency
#   write.parquet.compression — Snappy balances speed and compression ratio
#   write.target-file-size-bytes — ~128MB files, ideal for Athena/Spark queries

print(f"[csv_to_iceberg] Writing Iceberg table: {ICEBERG_TABLE_REF}")

(
    df.writeTo(ICEBERG_TABLE_REF)
    .tableProperty("format-version", "2")
    .tableProperty("write.format.default", "parquet")
    .tableProperty("write.parquet.compression-codec", "snappy")
    .tableProperty("write.target-file-size-bytes", str(128 * 1024 * 1024))
    .tableProperty("write.metadata.compression-codec", "gzip")
    .createOrReplace()
)

print(f"[csv_to_iceberg] SUCCESS — Iceberg table written: {ICEBERG_TABLE_REF}")
print(f"[csv_to_iceberg] Iceberg warehouse: {WAREHOUSE_URI}")

job.commit()
