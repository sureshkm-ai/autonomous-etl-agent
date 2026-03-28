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
from typing import Any

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


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
