<<<<<<< HEAD
"""Run status endpoints — reads from the persistent DB-backed run store."""
from fastapi import APIRouter, HTTPException

from etl_agent.core.logging import get_logger
from etl_agent.core.audit import list_audit_events

from .run_store import async_get_run, async_list_runs
=======
"""Pipeline run history and live status endpoints."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from etl_agent.core.logging import get_logger

from .run_store import get_run, list_runs
>>>>>>> main

logger = get_logger(__name__)
router = APIRouter()


<<<<<<< HEAD
@router.get("/runs/{run_id}")
async def get_run_status(run_id: str) -> dict:
    """
    Return the current state of a pipeline run.

    Includes live status, test results, LLM token usage, cost, and
    governance fields (approval_required, data_classification).
    """
    run = await async_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return run


@router.get("/runs/{run_id}/audit")
async def get_run_audit(run_id: str) -> dict:
    """
    Return the append-only audit trail for a pipeline run.

    Events are ordered chronologically and include actor, trigger_source,
    status transitions, and arbitrary governance payload.
    """
    run = await async_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")

    events = await list_audit_events(run_id)
    return {
        "run_id": run_id,
        "story_id": run.get("story_id"),
        "events": events,
        "total": len(events),
    }


@router.get("/runs")
async def list_runs(limit: int = 50, offset: int = 0) -> dict:
    """
    Return a paginated list of all pipeline runs, most recent first.

    Query parameters:
      - limit  (default 50, max 200)
      - offset (default 0)
    """
    limit = min(limit, 200)
    runs = await async_list_runs(limit=limit, offset=offset)
    return {
        "runs": runs,
        "count": len(runs),
        "limit": limit,
        "offset": offset,
    }


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, body: dict) -> dict:
    """
    Grant deployment approval for a run that is AWAITING_APPROVAL.

    Body fields:
      - actor      (str, required) — approver identity
      - rationale  (str, optional) — reason for approval
    """
    from datetime import datetime, timezone
    from etl_agent.core.audit import write_audit_event
    from .run_store import async_update_run

    run = await async_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")

    if run.get("status") != "AWAITING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Run is in status {run.get('status')!r}, expected AWAITING_APPROVAL",
        )

    actor = body.get("actor", "").strip()
    if not actor:
        raise HTTPException(status_code=422, detail="'actor' field is required")

    rationale = body.get("rationale", "")
    now = datetime.now(timezone.utc)

    await async_update_run(
        run_id,
        status="DEPLOYING",
        approver_actor=actor,
        approval_timestamp=now,
        approval_rationale=rationale,
    )

    await write_audit_event(
        event_type="DEPLOYMENT_APPROVED",
        run_id=run_id,
        story_id=run.get("story_id"),
        actor=actor,
        trigger_source="api",
        from_status="AWAITING_APPROVAL",
        to_status="DEPLOYING",
        payload={"rationale": rationale},
    )

    logger.info("run_approved", run_id=run_id, actor=actor)
    return {
        "run_id": run_id,
        "status": "DEPLOYING",
        "approver": actor,
        "message": "Approval recorded. Deployment will proceed.",
    }
=======
@router.get("/runs")
async def list_all_runs() -> list[dict]:
    """Return all pipeline runs submitted in this session, most recent first."""
    return list_runs()


@router.get("/runs/{run_id}")
async def get_run_status(run_id: str) -> dict:
    """Return the current status and details of a pipeline run."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


@router.get("/runs/{run_id}/logs")
async def stream_run_logs(run_id: str) -> StreamingResponse:
    """Stream live logs for a running pipeline via Server-Sent Events (SSE)."""
    async def event_generator():  # type: ignore[no-untyped-def]
        yield f"data: {{\"run_id\": \"{run_id}\", \"message\": \"Log streaming connected\"}}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
>>>>>>> main
