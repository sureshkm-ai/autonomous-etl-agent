"""
Schema Detector Lambda
======================
Triggered by S3 ObjectCreated events via EventBridge.

Flow:
  1. Extract bucket + key from the EventBridge event detail.
  2. Skip zero-byte folder-marker objects.
  3. Derive the table name from the S3 prefix:
       olist/orders/orders_2024.csv  →  table_name = "orders"
  4. Read the file schema with pyarrow (CSV header + 200 rows, or Parquet footer).
  5. Check if a Glue table already exists for this prefix.
     - If not → trigger Glue ETL job (new dataset).
     - If yes  → compare schemas; trigger ETL only if schema changed.
  6. Handle ConcurrentRunsExceededException gracefully (another invocation
     already started a job run for this table — safe to skip).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3

from glue_helper import get_existing_schema, schemas_differ, table_exists
from schema_reader import read_schema

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Environment variables injected by Terraform ────────────────────────────────
GLUE_DATABASE = os.environ["GLUE_DATABASE"]
GLUE_JOB_NAME = os.environ["GLUE_JOB_NAME"]
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
RAW_BUCKET = os.environ["RAW_BUCKET"]

s3_client = boto3.client("s3")
glue_client = boto3.client("glue")


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Main entry point — called by EventBridge on every S3 ObjectCreated event."""
    detail = event.get("detail", {})
    bucket: str = detail["bucket"]["name"]
    key: str = detail["object"]["key"]

    # Skip zero-byte folder marker objects (created when you make a "folder" in S3 console)
    if key.endswith("/") or detail["object"].get("size", 1) == 0:
        logger.info("skipping_folder_marker", key=key)
        return {"status": "skipped", "reason": "folder marker"}

    # ── Derive table name and source path ────────────────────────────────────────
    # Convention:  <root>/<table_name>/<filename>
    # Example:     olist/orders/orders_2024.csv   →  table_name = "orders"
    #              olist/product_category_translation/translation.csv  →  "product_category_translation"
    parts = key.strip("/").split("/")
    if len(parts) >= 2:
        table_name = parts[-2]
        prefix = "/".join(parts[:-1]) + "/"
    else:
        # Top-level file — use the filename stem as table name
        table_name = parts[0].rsplit(".", 1)[0]
        prefix = ""

    source_path = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}/"

    logger.info(
        "schema_detector_triggered",
        bucket=bucket,
        key=key,
        table_name=table_name,
        source_path=source_path,
    )

    # ── Read schema from the uploaded file ───────────────────────────────────────
    new_schema = read_schema(s3_client, bucket, key)
    if new_schema is None:
        logger.warning("schema_read_failed", key=key)
        return {"status": "skipped", "reason": "schema unreadable"}

    # ── Decide whether to trigger the Glue ETL job ───────────────────────────────
    existing = table_exists(glue_client, GLUE_DATABASE, table_name)

    if not existing:
        logger.info("new_dataset_detected", table_name=table_name, source_path=source_path)
        _trigger_job(source_path, table_name)
    else:
        old_schema = get_existing_schema(glue_client, GLUE_DATABASE, table_name)
        if schemas_differ(old_schema, new_schema):
            logger.info(
                "schema_change_detected",
                table_name=table_name,
                old_columns=[c["name"] for c in old_schema],
                new_columns=[c["name"] for c in new_schema],
            )
            _trigger_job(source_path, table_name)
        else:
            logger.info("schema_unchanged_no_job_needed", table_name=table_name)

    return {"status": "ok", "table": table_name}


def _trigger_job(source_path: str, table_name: str) -> None:
    """Start the csv_to_iceberg Glue ETL job for this prefix."""
    try:
        response = glue_client.start_job_run(
            JobName=GLUE_JOB_NAME,
            Arguments={
                "--source_path": source_path,
                "--table_name": table_name,
                "--database": GLUE_DATABASE,
                "--processed_bucket": PROCESSED_BUCKET,
            },
        )
        logger.info(
            "glue_job_triggered",
            job=GLUE_JOB_NAME,
            table=table_name,
            run_id=response["JobRunId"],
        )
    except glue_client.exceptions.ConcurrentRunsExceededException:
        # Another Lambda invocation already started a job for this table.
        # The running job will process all files already in the prefix — safe to skip.
        logger.warning(
            "glue_job_already_running",
            table=table_name,
            detail="ConcurrentRunsExceededException — skipping duplicate trigger",
        )
