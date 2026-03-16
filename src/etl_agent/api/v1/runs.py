"""Pipeline run history and live log streaming endpoints."""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/runs")
async def list_runs() -> list[dict]:
    """Return list of recent pipeline runs."""
    # TODO: Query PipelineRunRecord from database
    return []


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Return status and details of a specific pipeline run."""
    # TODO: Query PipelineRunRecord by run_id
    return {"run_id": run_id, "status": "PENDING"}


@router.get("/runs/{run_id}/logs")
async def stream_run_logs(run_id: str) -> StreamingResponse:
    """Stream live logs for a running pipeline via Server-Sent Events (SSE)."""
    async def event_generator():  # type: ignore[no-untyped-def]
        yield f"data: {{'run_id': '{run_id}', 'message': 'Log streaming connected'}}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
