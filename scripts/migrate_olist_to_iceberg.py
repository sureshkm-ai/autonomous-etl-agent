"""
One-Time Olist → Apache Iceberg Migration Script
=================================================
Converts all 9 Olist CSV datasets from raw S3 to Apache Iceberg format by
triggering the Glue ETL job for each table in parallel, then waiting for all
runs to complete.

Run ONCE after:
  1. `terraform apply` has deployed the Glue ETL job
  2. The Glue job script is uploaded:
       aws s3 cp infra/glue_jobs/csv_to_iceberg.py \\
         s3://etl-agent-artifacts-prod/glue-jobs/csv_to_iceberg.py

Usage:
  uv run python scripts/migrate_olist_to_iceberg.py

  Or with explicit AWS profile:
  AWS_PROFILE=my-profile uv run python scripts/migrate_olist_to_iceberg.py

Expected output:
  Starting Olist → Iceberg migration (9 tables)...
  [orders] started — run_id: jr_abc123
  [customers] started — run_id: jr_def456
  ...
  Waiting for all jobs...
  [orders] RUNNING...
  [orders] SUCCEEDED ✅
  ...
  ──────────────────────────────
  Migration Summary
  ──────────────────────────────
  orders                  ✅ SUCCEEDED
  order_items             ✅ SUCCEEDED
  ...
  ──────────────────────────────
  9 / 9 succeeded.
"""

from __future__ import annotations

import sys
import time

import boto3

# ── Configuration ─────────────────────────────────────────────────────────────
# Update these if your bucket names or region differ from the defaults.

AWS_REGION = "us-east-1"
JOB_NAME = "etl-agent-csv-to-iceberg"
RAW_BUCKET = "etl-agent-raw-prod"
PROCESSED_BUCKET = "etl-agent-processed-prod"
DATABASE = "etl_agent_catalog"

OLIST_TABLES = [
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "customers",
    "sellers",
    "products",
    "geolocation",
    "product_category_translation",
]

POLL_INTERVAL_SECONDS = 15
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"}

# ── Helpers ───────────────────────────────────────────────────────────────────

glue = boto3.client("glue", region_name=AWS_REGION)


def start_job(table_name: str) -> str:
    """Trigger the csv_to_iceberg Glue job for a single table. Returns the run ID."""
    source_path = f"s3://{RAW_BUCKET}/olist/{table_name}/"
    response = glue.start_job_run(
        JobName=JOB_NAME,
        Arguments={
            "--source_path": source_path,
            "--table_name": table_name,
            "--database": DATABASE,
            "--processed_bucket": PROCESSED_BUCKET,
        },
    )
    return response["JobRunId"]


def wait_for_job(run_id: str, table_name: str) -> str:
    """Poll until the Glue job run reaches a terminal state. Returns the final state."""
    while True:
        resp = glue.get_job_run(JobName=JOB_NAME, RunId=run_id)
        state: str = resp["JobRun"]["JobRunState"]

        if state in TERMINAL_STATES:
            if state != "SUCCEEDED":
                err = resp["JobRun"].get("ErrorMessage", "no error message")
                print(f"  [{table_name}] {state}: {err}")
            return state

        print(f"  [{table_name}] {state}...")
        time.sleep(POLL_INTERVAL_SECONDS)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    print(f"Starting Olist → Iceberg migration ({len(OLIST_TABLES)} tables)...")
    print(f"  Job:              {JOB_NAME}")
    print(f"  Source bucket:    s3://{RAW_BUCKET}/olist/")
    print(f"  Iceberg warehouse: s3://{PROCESSED_BUCKET}/iceberg/")
    print(f"  Glue database:    {DATABASE}")
    print()

    # Start all jobs in parallel
    run_ids: dict[str, str] = {}
    for table in OLIST_TABLES:
        try:
            run_id = start_job(table)
            run_ids[table] = run_id
            print(f"  [{table}] started — run_id: {run_id}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{table}] FAILED to start: {exc}", file=sys.stderr)
            run_ids[table] = ""

    print()
    print("Waiting for all jobs...")

    # Wait for each job in order (all are running in parallel on AWS)
    results: dict[str, str] = {}
    for table, run_id in run_ids.items():
        if not run_id:
            results[table] = "LAUNCH_FAILED"
            continue
        results[table] = wait_for_job(run_id, table)

    # Summary
    separator = "─" * 40
    print()
    print(separator)
    print("Migration Summary")
    print(separator)

    succeeded = 0
    for table, state in results.items():
        icon = "✅" if state == "SUCCEEDED" else "❌"
        print(f"  {table:<35} {icon} {state}")
        if state == "SUCCEEDED":
            succeeded += 1

    print(separator)
    print(f"  {succeeded} / {len(OLIST_TABLES)} succeeded.")
    print()

    if succeeded < len(OLIST_TABLES):
        print("⚠️  Some tables failed. Check the Glue Console for error details.")
        print("   Rerun this script — successfully migrated tables will not be re-processed")
        print("   if you delete the failed Iceberg table from the catalog first.")
        return 1

    print("✅ All tables migrated to Iceberg successfully.")
    print()
    print("Next steps:")
    print("  1. Verify tables in AWS Glue Console → Databases → etl_agent_catalog")
    print("  2. Run: aws glue get-tables --database-name etl_agent_catalog")
    print("  3. Optionally query via Athena: SELECT * FROM etl_agent_catalog.orders LIMIT 10;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
