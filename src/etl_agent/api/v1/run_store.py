"""DB-backed run store — replaces the in-memory dict with SQLAlchemy persistence.

All public functions are synchronous wrappers that spin up a one-shot event loop
so they can be called from sync FastAPI route handlers AND from async background
tasks without change of call-site.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _utcnow() -> datetime:
    """Return current UTC time as a timezone-naive datetime (for TIMESTAMP columns)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _run_async(coro):
    """Run *coro* in a fresh event loop (safe when called from sync code)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already inside an async context — schedule as a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Internal async helpers (all DB I/O lives here)
# ---------------------------------------------------------------------------


async def _async_create_run(run_id: str, story_id: str, story_title: str) -> None:
    from etl_agent.database.models import PipelineRunRecord
    from etl_agent.database.session import get_session_factory

    factory = get_session_factory()
    record = PipelineRunRecord(
        id=str(uuid4()),
        run_id=run_id,
        story_id=story_id,
        story_title=story_title,
        status="PENDING",
        submitted_at=_utcnow(),
    )
    try:
        async with factory() as session:
            session.add(record)
            await session.commit()
    except Exception as exc:
        logger.error("run_store_create_failed", run_id=run_id, error=str(exc))


def _build_update_values(kwargs: dict) -> dict:
    """Translate public kwarg names into DB column name → value pairs.

    Handles timezone stripping for DateTime columns and flattening of nested
    dicts (test_results).  Returns an empty dict if nothing is actionable.
    """
    values: dict = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if key == "status":
            values["status"] = str(value)
        elif key == "current_stage":
            values["current_stage"] = str(value)
        elif key == "completed_at":
            if isinstance(value, str):
                try:
                    values["completed_at"] = datetime.fromisoformat(value).replace(
                        tzinfo=None
                    )
                except ValueError:
                    values["completed_at"] = _utcnow()
            elif isinstance(value, datetime):
                values["completed_at"] = value.replace(tzinfo=None)
            else:
                values["completed_at"] = value
        elif key == "started_at":
            if isinstance(value, str):
                try:
                    values["started_at"] = datetime.fromisoformat(value).replace(
                        tzinfo=None
                    )
                except ValueError:
                    values["started_at"] = _utcnow()
            elif isinstance(value, datetime):
                values["started_at"] = value.replace(tzinfo=None)
            else:
                values["started_at"] = value
        elif key == "github_pr_url":
            values["github_pr_url"] = value
        elif key == "github_issue_url":
            values["github_issue_url"] = value
        elif key == "s3_artifact_url":
            values["s3_artifact_url"] = value
        elif key == "error_message":
            values["error_message"] = value
        elif key == "test_results" and isinstance(value, dict):
            values["test_passed"] = value.get("passed")
            values["test_passed_count"] = value.get("passed_tests", 0)
            values["test_total"] = value.get("total_tests", 0)
            values["test_coverage_pct"] = value.get("coverage_pct", 0.0)
        elif key == "retry_count":
            values["retry_count"] = int(value)
        elif key == "approval_required":
            values["approval_required"] = bool(value)
        elif key == "approver_actor":
            values["approver_actor"] = value
        elif key == "approval_timestamp":
            if isinstance(value, datetime):
                values["approval_timestamp"] = value.replace(tzinfo=None)
            else:
                values["approval_timestamp"] = value
        elif key == "approval_rationale":
            values["approval_rationale"] = value
        elif key == "data_classification":
            values["data_classification"] = str(value)
        elif key in {
            "model_name",
            "prompt_template_version",
            "system_prompt_hash",
            "task_prompt_hash",
            "token_steps_json",
            "lineage_snapshot_json",
            "commit_sha",
            "artifact_checksum",
        }:
            values[key] = value
        elif key == "total_input_tokens":
            values["total_input_tokens"] = int(value)
        elif key == "total_output_tokens":
            values["total_output_tokens"] = int(value)
        elif key == "total_cost_usd":
            values["total_cost_usd"] = float(value)
        elif key == "budget_pct":
            values["budget_pct"] = float(value)
    return values


async def _async_update_run(run_id: str, **kwargs) -> None:
    """Persist run-field updates using a direct SQL UPDATE (not ORM mutation).

    Using ``update().values()`` instead of loading-and-modifying an ORM object
    guarantees the change reaches the DB regardless of SQLAlchemy session state.
    """
    from sqlalchemy import update

    from etl_agent.database.models import PipelineRunRecord
    from etl_agent.database.session import get_session_factory

    values = _build_update_values(kwargs)
    if not values:
        return  # nothing to do

    try:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                update(PipelineRunRecord)
                .where(PipelineRunRecord.run_id == run_id)
                .values(**values)
            )
            if result.rowcount == 0:
                logger.warning("run_store_update_not_found", run_id=run_id)
                return
            await session.commit()
            logger.info(
                "run_store_updated",
                run_id=run_id,
                fields=list(values.keys()),
            )
    except Exception as exc:
        logger.error("run_store_update_failed", run_id=run_id, error=str(exc))


async def _async_get_run(run_id: str) -> dict[str, Any] | None:
    from sqlalchemy import select

    from etl_agent.database.models import PipelineRunRecord
    from etl_agent.database.session import get_session_factory

    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                select(PipelineRunRecord).where(PipelineRunRecord.run_id == run_id)
            )
            record = result.scalars().first()
            if record is None:
                return None
            return _record_to_dict(record)
    except Exception as exc:
        logger.error("run_store_get_failed", run_id=run_id, error=str(exc))
        return None


async def _async_list_runs(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    from sqlalchemy import desc, select

    from etl_agent.database.models import PipelineRunRecord
    from etl_agent.database.session import get_session_factory

    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                select(PipelineRunRecord)
                .order_by(desc(PipelineRunRecord.submitted_at))
                .limit(limit)
                .offset(offset)
            )
            records = result.scalars().all()
            return [_record_to_dict(r) for r in records]
    except Exception as exc:
        logger.error("run_store_list_failed", error=str(exc))
        return []


def _record_to_dict(r: Any) -> dict[str, Any]:
    """Convert an ORM PipelineRunRecord to a JSON-serialisable dict."""
    token_steps = []
    if r.token_steps_json:
        with contextlib.suppress(Exception):
            token_steps = json.loads(r.token_steps_json)

    lineage = {}
    if r.lineage_snapshot_json:
        with contextlib.suppress(Exception):
            lineage = json.loads(r.lineage_snapshot_json)

    return {
        "run_id": r.run_id,
        "story_id": r.story_id,
        "story_title": r.story_title,
        "status": r.status,
        "current_stage": r.current_stage,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "github_pr_url": r.github_pr_url,
        "github_issue_url": r.github_issue_url,
        "s3_artifact_url": r.s3_artifact_url,
        "artifact_checksum": r.artifact_checksum,
        "commit_sha": r.commit_sha,
        "test_results": {
            "passed": r.test_passed,
            "passed_tests": r.test_passed_count or 0,
            "total_tests": r.test_total or 0,
            "coverage_pct": r.test_coverage_pct or 0.0,
        }
        if r.test_passed is not None
        else None,
        "error_message": r.error_message,
        "retry_count": r.retry_count or 0,
        # Governance
        "approval_required": r.approval_required or False,
        "approver_actor": r.approver_actor,
        "approval_timestamp": (
            r.approval_timestamp.isoformat() if r.approval_timestamp else None
        ),
        "approval_rationale": r.approval_rationale,
        "data_classification": r.data_classification or "internal",
        # LLM provenance
        "model_name": r.model_name,
        "prompt_template_version": r.prompt_template_version,
        "system_prompt_hash": r.system_prompt_hash,
        "task_prompt_hash": r.task_prompt_hash,
        # Token budget
        "total_input_tokens": r.total_input_tokens or 0,
        "total_output_tokens": r.total_output_tokens or 0,
        "total_cost_usd": r.total_cost_usd or 0.0,
        "budget_pct": r.budget_pct or 0.0,
        "token_steps": token_steps,
        "lineage": lineage,
    }


# ---------------------------------------------------------------------------
# Public synchronous API  (drop-in replacement for the old in-memory store)
# ---------------------------------------------------------------------------


def create_run(run_id: str, story_id: str, story_title: str) -> None:
    """Register a new pipeline run. Idempotent on repeated calls with same run_id."""
    _run_async(_async_create_run(run_id, story_id, story_title))


def update_run(run_id: str, **kwargs) -> None:
    """Update arbitrary fields on an existing run record."""
    _run_async(_async_update_run(run_id, **kwargs))


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return run dict or None if not found."""
    return _run_async(_async_get_run(run_id))


def list_runs(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Return runs ordered by submission time descending."""
    return _run_async(_async_list_runs(limit, offset))


# ---------------------------------------------------------------------------
# Async variants (for use inside async route handlers / background tasks)
# ---------------------------------------------------------------------------


async def async_create_run(run_id: str, story_id: str, story_title: str) -> None:
    await _async_create_run(run_id, story_id, story_title)


async def async_get_run(run_id: str) -> dict[str, Any] | None:
    return await _async_get_run(run_id)


async def async_list_runs(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return await _async_list_runs(limit, offset)


async def async_update_run(run_id: str, **kwargs) -> None:
    await _async_update_run(run_id, **kwargs)
