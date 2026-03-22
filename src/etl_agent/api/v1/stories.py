"""Story intake endpoint — accepts user stories and kicks off the agent pipeline."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks

from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus, UserStory
from etl_agent.core.audit import write_audit_event

from .run_store import create_run, update_run

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _persist_user_story(story: UserStory) -> None:
    """Write the UserStory to the database. Non-fatal on error."""
    try:
        from uuid import uuid4 as _uuid4
        from etl_agent.database.session import get_session_factory
        from etl_agent.database.models import UserStoryRecord

        factory = get_session_factory()
        record = UserStoryRecord(
            id=str(_uuid4()),
            story_id=story.id,
            title=story.title,
            description=story.description,
            source_path=story.source.path,
            source_format=story.source.format,
            target_path=story.target.path,
            target_format=story.target.format,
            target_mode=story.target.mode,
            data_classification=story.data_classification.value,
            tags=json.dumps(story.tags),
            raw_json=story.model_dump_json(),
            submitted_at=datetime.now(timezone.utc),
        )
        async with factory() as session:
            # Upsert: if story already exists (re-submission), overwrite raw_json
            from sqlalchemy import select
            existing = await session.execute(
                select(UserStoryRecord).where(UserStoryRecord.story_id == story.id)
            )
            existing_record = existing.scalars().first()
            if existing_record:
                existing_record.raw_json = record.raw_json
                existing_record.submitted_at = record.submitted_at
            else:
                session.add(record)
            await session.commit()
    except Exception as exc:
        logger.error("story_persist_failed", story_id=story.id, error=str(exc))


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/stories", status_code=202)
async def submit_story(
    story: UserStory,
    background_tasks: BackgroundTasks,
    dry_run: bool = False,
) -> dict:
    """
    Submit a user story to the ETL Agent pipeline.

    Returns immediately with a run_id. Poll GET /api/v1/runs/{run_id} for status.
    The story and run are persisted to the database before the background task starts.
    """
    run_id = str(uuid4())
    logger.info("story_submitted", story_id=story.id, run_id=run_id,
                data_classification=story.data_classification.value)

    # 1. Persist story to DB
    await _persist_user_story(story)

    # 2. Register run immediately so the UI can poll
    create_run(run_id=run_id, story_id=story.id, story_title=story.title)

    # 3. Write governance audit events
    await write_audit_event(
        event_type="STORY_SUBMITTED",
        run_id=run_id,
        story_id=story.id,
        actor="api_user",
        trigger_source="api",
        payload={
            "title": story.title,
            "data_classification": story.data_classification.value,
            "tags": story.tags,
            "source_path": story.source.path,
            "target_path": story.target.path,
        },
    )
    await write_audit_event(
        event_type="RUN_CREATED",
        run_id=run_id,
        story_id=story.id,
        actor="system",
        trigger_source="api",
        to_status="PENDING",
        payload={"run_id": run_id},
    )

    # 4. Kick off the pipeline asynchronously
    background_tasks.add_task(_run_pipeline_background, story, run_id, dry_run=dry_run)

    return {
        "run_id": run_id,
        "story_id": story.id,
        "status": RunStatus.PENDING.value,
        "data_classification": story.data_classification.value,
        "dry_run": dry_run,
        "message": f"Pipeline started. Track at GET /api/v1/runs/{run_id}",
    }


# ---------------------------------------------------------------------------
# Background pipeline driver
# ---------------------------------------------------------------------------

async def _run_pipeline_background(story: UserStory, run_id: str, *, dry_run: bool = False) -> None:
    """
    Background task: run the full agent pipeline with per-stage run-store updates.

    Uses stream_pipeline so the run store (and therefore the UI) gets a live
    status update after every LangGraph node completes.
    """
    from etl_agent.agents.orchestrator import stream_pipeline

    await write_audit_event(
        event_type="PARSING_STARTED",
        run_id=run_id,
        story_id=story.id,
        actor="system",
        trigger_source="system",
        from_status="PENDING",
        to_status="PARSING",
    )

    async def _on_update(node_name: str, node_output: dict, full_state: dict) -> None:
        """Called by stream_pipeline after each LangGraph node."""
        kwargs: dict = {"current_stage": node_name}

        # Normalise RunStatus enum → plain string
        if "status" in node_output:
            s = node_output["status"]
            kwargs["status"] = s.value if hasattr(s, "value") else str(s)

        # Write stage-transition audit event
        new_status = kwargs.get("status")
        if new_status:
            _stage_event_map = {
                "CODING": "CODING_STARTED",
                "TESTING": "TESTING_STARTED",
                "PR_CREATING": "PR_CREATING",
                "DEPLOYING": "DEPLOYMENT_TRIGGERED",
            }
            event_type = _stage_event_map.get(new_status)
            if event_type:
                await write_audit_event(
                    event_type=event_type,
                    run_id=run_id,
                    story_id=story.id,
                    actor="system",
                    trigger_source="system",
                    to_status=new_status,
                )

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

        # Persist token usage if available
        if node_output.get("token_tracker"):
            tracker = node_output["token_tracker"]
            td = tracker.to_dict() if hasattr(tracker, "to_dict") else {}
            if td:
                kwargs["total_input_tokens"] = td.get("total_input_tokens", 0)
                kwargs["total_output_tokens"] = td.get("total_output_tokens", 0)
                kwargs["total_cost_usd"] = td.get("total_cost_usd", 0.0)
                kwargs["budget_pct"] = td.get("budget_pct", 0.0)
                import json as _json
                kwargs["token_steps_json"] = _json.dumps(td.get("steps", []))

        update_run(run_id, **kwargs)

    try:
        final_state = await stream_pipeline(story=story, on_update=_on_update, dry_run=dry_run)

        final_status = final_state.get("status")
        status_str = final_status.value if hasattr(final_status, "value") else str(final_status)

        update_run(
            run_id,
            status=status_str,
            completed_at=datetime.now(timezone.utc).isoformat(),
            github_pr_url=final_state.get("github_pr_url"),
            github_issue_url=final_state.get("github_issue_url"),
            s3_artifact_url=final_state.get("s3_artifact_url"),
            error_message=final_state.get("error_message"),
        )

        event_type = "RUN_COMPLETED" if status_str not in ("FAILED",) else "RUN_FAILED"
        await write_audit_event(
            event_type=event_type,
            run_id=run_id,
            story_id=story.id,
            actor="system",
            trigger_source="system",
            to_status=status_str,
            payload={
                "github_pr_url": final_state.get("github_pr_url"),
                "s3_artifact_url": final_state.get("s3_artifact_url"),
            },
        )

        logger.info("background_pipeline_complete", run_id=run_id, status=status_str)

    except Exception as e:
        update_run(
            run_id,
            status="FAILED",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        await write_audit_event(
            event_type="RUN_FAILED",
            run_id=run_id,
            story_id=story.id,
            actor="system",
            trigger_source="system",
            to_status="FAILED",
            payload={"error": str(e)},
        )
        logger.error("background_pipeline_failed", run_id=run_id, error=str(e))
