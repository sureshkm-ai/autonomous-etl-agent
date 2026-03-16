"""
Airflow DAG: etl_agent_pipeline
Triggered by the Deploy Agent via the Airflow REST API.
Receives an S3 artifact URL and executes the generated PySpark pipeline.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.param import Param


DEFAULT_ARGS = {
    "owner": "etl-agent",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=2),
}


@dag(
    dag_id="etl_agent_pipeline",
    default_args=DEFAULT_ARGS,
    schedule=None,                    # Triggered externally via REST API
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["etl-agent", "autonomous"],
    params={
        "artifact_url": Param(type="string", description="S3 URL of the .whl artifact"),
        "pipeline_name": Param(type="string", description="Name of the pipeline to execute"),
        "run_id": Param(type="string", description="ETL Agent run ID for tracing"),
        "story_id": Param(type="string", description="User story ID that generated this pipeline"),
    },
    doc_md="""
    ## ETL Agent Pipeline DAG

    Triggered automatically by the Autonomous ETL Agent after a PR is merged
    and the pipeline artifact is uploaded to S3.

    ### Parameters
    - `artifact_url`: S3 URL of the packaged `.whl` pipeline artifact
    - `pipeline_name`: Name of the pipeline module to execute
    - `run_id`: Trace ID linking this run back to the agent run
    - `story_id`: The originating user story ID
    """,
)
def etl_agent_pipeline() -> None:

    @task
    def download_artifact(artifact_url: str, pipeline_name: str) -> str:
        """Download the .whl artifact from S3 to local disk."""
        import boto3  # type: ignore[import]

        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("AWS_ENDPOINT_URL"),  # LocalStack in dev
        )
        bucket, key = artifact_url.replace("s3://", "").split("/", 1)
        local_path = f"/tmp/{pipeline_name}.whl"
        s3.download_file(bucket, key, local_path)
        print(f"✅ Downloaded {artifact_url} → {local_path}")
        return local_path

    @task
    def install_and_run(local_whl_path: str, pipeline_name: str, run_id: str) -> dict:
        """Install the .whl and execute the pipeline module."""
        import subprocess

        # Install the .whl package
        result = subprocess.run(
            ["pip", "install", "--quiet", local_whl_path],
            capture_output=True, text=True, check=True,
        )
        print(f"✅ Installed {local_whl_path}")

        # Execute the pipeline
        run_result = subprocess.run(
            ["python", "-m", pipeline_name],
            capture_output=True, text=True, timeout=7200,
        )

        if run_result.returncode != 0:
            raise RuntimeError(
                f"Pipeline {pipeline_name} failed:\n{run_result.stderr}"
            )

        print(f"✅ Pipeline {pipeline_name} completed successfully")
        return {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "status": "SUCCESS",
            "stdout": run_result.stdout[-2000:],  # last 2000 chars
        }

    @task
    def report_completion(result: dict, story_id: str) -> None:
        """Log final status — in production, call back to the ETL Agent API."""
        print(
            f"Pipeline run complete | story_id={story_id} | "
            f"pipeline={result['pipeline_name']} | status={result['status']}"
        )

    # DAG wiring
    from airflow.models import DagRun  # noqa: F401 — imported for Airflow context

    # Access params via Jinja templating
    artifact_url = "{{ params.artifact_url }}"
    pipeline_name = "{{ params.pipeline_name }}"
    run_id = "{{ params.run_id }}"
    story_id = "{{ params.story_id }}"

    whl_path = download_artifact(artifact_url, pipeline_name)
    result = install_and_run(whl_path, pipeline_name, run_id)
    report_completion(result, story_id)


etl_agent_pipeline()
