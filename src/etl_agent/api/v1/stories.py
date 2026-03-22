"""Story intake endpoint — accepts user stories and kicks off the agent pipeline."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks

from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus, UserStory

from .run_store import create_run, update_run

logger = get_logger(__name__)
router = APIRouter()


@router.post("/stories", status_code=202)
async def submit_story(
    story: UserStory,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Submit a user story to the ETL Agent pipeline.

    Returns immediately with a run_id. Poll GET /api/v1/runs/{run_id} for status.
    """
    run_id = str(uuid4())
    logger.info("story_submitted", story_id=story.id, run_id=run_id)

    # Register in the run store immediately so the UI can poll straight away
    create_run(run_id=run_id, story_id=story.id, story_title=story.title)

    background_tasks.add_task(_run_pipeline_background, story, run_id)

    return {
        "run_id": run_id,
        "story_id": story.id,
        "status": RunStatus.PENDING.value,
        "message": f"Pipeline started. Track at GET /api/v1/runs/{run_id}",
    }


async def _run_pipeline_background(story: UserStory, run_id: str) -> None:
    """
    Background task: run the full agent pipeline with per-stage run-store updates.

    Uses stream_pipeline so the run store (and therefore the UI) gets a live
    status update after every LangGraph node completes.
    """
    from etl_agent.agents.orchestrator import stream_pipeline

    async def _on_update(node_name: str, node_output: dict, full_state: dict) -> None:
        """Called by stream_pipeline after each LangGraph node."""
        kwargs: dict = {"current_stage": node_name}

        # Normalise RunStatus enum → plain string
        if "status" in node_output:
            s = node_output["status"]
            kwargs["status"] = s.value if hasattr(s, "value") else str(s)

        # Capture outputs as they arrive so the UI can show them immediately
        for field in ("github_pr_url", "github_issue_url", "s3_artifact_url", "error_message"):
            if node_output.get(field):
                kwargs[field] = node_output[field]

        if node_output.get("test_results"):
            tr = node_output["test_results"]
            kwargs["test_results"] = {
                "passed": tr.passed,
                "passed_tests": tr.passed_tests,
                "total_tests": tr.total_tests,
                "coverage_pct": tr.coverage_pct,
            }

        update_run(run_id, **kwargs)

    try:
        final_state = await stream_pipeline(story=story, on_update=_on_update)

        final_status = final_state.get("status")
        status_str = final_status.value if hasattr(final_status, "value") else str(final_status)

        update_run(
            run_id,
            status=status_str,
            completed_at=datetime.now(timezone.utc).isoformat(),
            # Persist final values (may already be set by _on_update, but ensure consistency)
            github_pr_url=final_state.get("github_pr_url"),
            github_issue_url=final_state.get("github_issue_url"),
            s3_artifact_url=final_state.get("s3_artifact_url"),
            error_message=final_state.get("error_message"),
        )
        logger.info("background_pipeline_complete", run_id=run_id, status=status_str)

    except Exception as e:
        update_run(
            run_id,
            status="FAILED",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.error("background_pipeline_failed", run_id=run_id, error=str(e))
