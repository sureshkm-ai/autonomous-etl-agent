"""AWS helper tools — S3 artifact upload with governance metadata tagging.

Data governance policy
----------------------
Every object written to S3 is tagged with:
  - data_classification  (public | internal | confidential | restricted)
  - pipeline_run_id      (UUID of the pipeline run)
  - story_id             (user story identifier)
  - environment          (from settings.environment)

These tags feed S3 Lifecycle policies (see infra/terraform/s3_lifecycle.tf)
that enforce retention periods by classification:
  - public / internal   → 90-day Intelligent-Tiering, expire at 365 days
  - confidential        → Glacier after 30 days, expire at 2 years
  - restricted          → Glacier after 7 days, expire at 7 years
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from typing import Any

import boto3

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# AWSTools — convenience class used by DeployAgent
# ---------------------------------------------------------------------------


class AWSTools:
    """Wraps boto3 S3 client for artifact packaging and upload."""

    def __init__(
        self,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        region: str = "us-east-1",
        endpoint_url: str = "",
    ) -> None:
        kwargs: dict[str, Any] = {"region_name": region}
        if aws_access_key_id:
            kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            kwargs["aws_secret_access_key"] = aws_secret_access_key
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._s3 = boto3.client("s3", **kwargs)

    def package_whl(self, pipeline_name: str, pipeline_code: str) -> str:
        """Write pipeline code to a temp dir, build a .whl, return its local path."""
        tmp = tempfile.mkdtemp(prefix="etl_whl_")
        src_dir = os.path.join(tmp, pipeline_name)
        os.makedirs(src_dir, exist_ok=True)

        # Write the pipeline module
        with open(os.path.join(src_dir, "__init__.py"), "w") as f:
            f.write(pipeline_code)

        # Minimal setup.py for bdist_wheel
        setup_py = (
            f"from setuptools import setup, find_packages\n"
            f"setup(name='{pipeline_name}', version='1.0.0', packages=find_packages())\n"
        )
        with open(os.path.join(tmp, "setup.py"), "w") as f:
            f.write(setup_py)

        dist_dir = os.path.join(tmp, "dist")
        subprocess.run(
            ["python", "setup.py", "bdist_wheel", "--dist-dir", dist_dir],
            cwd=tmp,
            check=True,
            capture_output=True,
        )

        wheels = [f for f in os.listdir(dist_dir) if f.endswith(".whl")]
        if not wheels:
            raise RuntimeError(f"No .whl produced for pipeline {pipeline_name}")
        whl_path = os.path.join(dist_dir, wheels[0])
        logger.info("whl_packaged", pipeline=pipeline_name, path=whl_path)
        return whl_path

    def upload_to_s3(self, local_path: str, bucket: str, key: str) -> str:
        """Upload a local file to S3 and return the s3:// URI."""
        self._s3.upload_file(local_path, bucket, key)
        s3_uri = f"s3://{bucket}/{key}"
        logger.info("s3_upload_complete", uri=s3_uri)
        return s3_uri


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_tags(
    data_classification: str,
    run_id: str,
    story_id: str,
    extra: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Return a list of S3 tag dicts suitable for the boto3 Tagging API."""
    settings = get_settings()
    tags = {
        "data_classification": data_classification,
        "pipeline_run_id": run_id,
        "story_id": story_id,
        "environment": getattr(settings, "environment", "production"),
        "managed_by": "autonomous-etl-agent",
    }
    if extra:
        tags.update(extra)
    return [{"Key": k, "Value": str(v)} for k, v in tags.items()]


def _compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------


async def upload_artifact(
    *,
    content: str | bytes,
    s3_key: str,
    run_id: str,
    story_id: str,
    data_classification: str = "internal",
    content_type: str = "text/x-python",
    extra_tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Upload a pipeline artifact to S3 with governance metadata.

    Parameters
    ----------
    content:             File content (str or bytes).
    s3_key:              Full S3 object key (without bucket prefix).
    run_id:              Pipeline run identifier.
    story_id:            User story identifier.
    data_classification: Sensitivity label — drives lifecycle policy.
    content_type:        MIME type for the S3 object.
    extra_tags:          Additional key=value tags merged into the tag set.

    Returns
    -------
    dict with keys: s3_uri, checksum, bucket, key, data_classification
    """
    import aioboto3  # type: ignore[import-untyped]

    settings = get_settings()
    bucket = settings.s3_bucket

    raw: bytes = content.encode() if isinstance(content, str) else content
    checksum = _compute_sha256(raw)

    tags = _build_tags(
        data_classification=data_classification,
        run_id=run_id,
        story_id=story_id,
        extra=extra_tags,
    )
    tag_set = "&".join(f"{t['Key']}={t['Value']}" for t in tags)

    # Server-side encryption — enforce for confidential/restricted
    sse_args: dict[str, str] = {}
    if data_classification in ("confidential", "restricted"):
        sse_args["ServerSideEncryption"] = "aws:kms"

    logger.info(
        "s3_upload_start",
        bucket=bucket,
        key=s3_key,
        run_id=run_id,
        data_classification=data_classification,
        bytes=len(raw),
    )

    session = aioboto3.Session()
    async with session.client("s3", region_name=settings.aws_region) as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=raw,
            ContentType=content_type,
            Tagging=tag_set,
            Metadata={
                "pipeline_run_id": run_id,
                "story_id": story_id,
                "data_classification": data_classification,
                "sha256": checksum,
            },
            **sse_args,
        )

    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info(
        "s3_upload_complete",
        s3_uri=s3_uri,
        checksum=checksum,
        run_id=run_id,
        data_classification=data_classification,
    )

    return {
        "s3_uri": s3_uri,
        "checksum": checksum,
        "bucket": bucket,
        "key": s3_key,
        "data_classification": data_classification,
    }


async def upload_pipeline_script(
    script_content: str,
    *,
    run_id: str,
    story_id: str,
    pipeline_name: str,
    data_classification: str = "internal",
) -> dict[str, Any]:
    """Convenience wrapper: upload a PySpark pipeline script under a canonical key.

    Key format: pipelines/{pipeline_name}/{run_id}/pipeline.py
    """
    s3_key = f"pipelines/{pipeline_name}/{run_id}/pipeline.py"
    return await upload_artifact(
        content=script_content,
        s3_key=s3_key,
        run_id=run_id,
        story_id=story_id,
        data_classification=data_classification,
        content_type="text/x-python",
        extra_tags={"pipeline_name": pipeline_name},
    )


# ---------------------------------------------------------------------------
# Airflow DAG trigger
# ---------------------------------------------------------------------------


async def trigger_airflow_dag(
    *,
    dag_id: str,
    run_id: str,
    conf: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger an Airflow DAG run via the Airflow REST API.

    Returns the dag_run_id on success.
    """
    import aiohttp

    settings = get_settings()
    airflow_url = getattr(settings, "airflow_url", None)
    if not airflow_url:
        logger.warning("airflow_url_not_set", detail="Skipping Airflow trigger")
        return {"dag_run_id": None, "skipped": True}

    url = f"{airflow_url.rstrip('/')}/api/v1/dags/{dag_id}/dagRuns"
    payload: dict[str, Any] = {"dag_run_id": run_id}
    if conf:
        payload["conf"] = conf

    timeout = aiohttp.ClientTimeout(total=30)
    auth = aiohttp.BasicAuth(
        login=getattr(settings, "airflow_username", "airflow"),
        password=getattr(settings, "airflow_password", "airflow"),
    )

    logger.info("airflow_trigger_start", dag_id=dag_id, run_id=run_id)

    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.post(url, json=payload, auth=auth) as resp,
    ):
        resp_json = await resp.json()
        if resp.status not in (200, 201):
            raise RuntimeError(f"Airflow trigger failed: HTTP {resp.status} — {resp_json}")

    dag_run_id = resp_json.get("dag_run_id", run_id)
    logger.info("airflow_trigger_complete", dag_id=dag_id, dag_run_id=dag_run_id)
    return {"dag_run_id": dag_run_id}
