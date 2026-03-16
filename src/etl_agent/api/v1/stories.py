"""Story intake endpoint — accepts user stories and kicks off the agent pipeline."""
import asyncio
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunResult, RunStatus, UserStory
from etl_agent.database.session import get_db

logger = get_logger(__name__)
router = APIRouter()


@router.post("/stories", status_code=202)
async def submit_story(
    story: UserStory,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Submit a user story to the ETL Agent pipeline.

    Returns immediately with a run_id. Poll GET /api/v1/runs/{run_id} for status.
    """
    run_id = str(uuid4())
    logger.info("story_submitted", story_id=story.id, run_id=run_id)

    background_tasks.add_task(_run_pipeline_background, story, run_id)

    return {
        "run_id": run_id,
        "story_id": story.id,
        "status": RunStatus.PENDING.value,
        "message": f"Pipeline started. Track at GET /api/v1/runs/{run_id}",
    }


async def _run_pipeline_background(story: UserStory, run_id: str) -> None:
    """Background task: run the full agent pipeline."""
    from etl_agent.agents.orchestrator import run_pipeline
    try:
        result = await run_pipeline(story)
        logger.info("background_pipeline_complete", run_id=run_id, status=result.status.value)
    except Exception as e:
        logger.error("background_pipeline_failed", run_id=run_id, error=str(e))
