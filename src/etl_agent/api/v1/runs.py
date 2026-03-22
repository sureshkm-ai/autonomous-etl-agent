"""Pipeline run history and live status endpoints."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from etl_agent.core.logging import get_logger

from .run_store import get_run, list_runs

logger = get_logger(__name__)
router = APIRouter()


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
