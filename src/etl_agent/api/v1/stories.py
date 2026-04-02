"""Story intake endpoint — accepts user stories and kicks off the agent pipeline.

Execution mode is selected automatically:
  - SQS_QUEUE_URL set  → ECS Fargate mode: message published to SQS, a
                          separate worker Fargate task picks it up.
  - SQS_QUEUE_URL unset → Local / EC2 mode: FastAPI BackgroundTask (original
                          behaviour, zero config needed for development).
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import boto3
from fastapi import APIRouter, BackgroundTasks

from etl_agent.core.audit import write_audit_event
from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunStatus, UserStory, UserStoryRequest

from .run_store import async_create_run, async_update_run

logger = get_logger(__name__)
router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _persist_user_story(story: UserStory) -> None:
    """Write the UserStory to the database. Non-fatal on error."""
    try:
        from sqlalchemy import select

        from etl_agent.database.models import UserStoryRecord
        from etl_agent.database.session import get_session_factory

        factory = get_session_factory()
        record = UserStoryRecord(
            id=str(uuid4()),
            story_id=story.id,
            title=story.title,
            description=story.description,
            source_path=story.source.path if story.source else None,
            source_format=story.source.format if story.source else None,
            target_path=story.target.path if story.target else None,
            target_format=story.target.format if story.target else None,
            target_mode=story.target.mode if story.target else None,
            data_classification=story.data_classification.value,
            tags=json.dumps(story.tags),
            raw_json=story.model_dump_json(),
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        async with factory() as session:
            from etl_agent.database.models import UserStoryRecord as _USR

            existing = await session.execute(select(_USR).where(_USR.story_id == story.id))
            existing_record = existing.scalars().first()
            if existing_record:
                existing_record.raw_json = record.raw_json
                existing_record.submitted_at = record.submitted_at
            else:
                session.add(record)
            await session.commit()
    except Exception as exc:
        logger.error("story_persist_failed", story_id=story.id, error=str(exc))


def _publish_to_sqs(run_id: str, story: UserStory, dry_run: bool) -> None:
    """Publish a pipeline job message to SQS (ECS Fargate mode)."""
    settings = get_settings()
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    message_body = json.dumps(
        {
            "run_id": run_id,
            "story_id": story.id,
            "dry_run": dry_run,
            "story": json.loads(story.model_dump_json()),
        }
    )
    response = sqs.send_message(
        QueueUrl=settings.sqs_queue_url,
        MessageBody=message_body,
        MessageAttributes={
            "run_id": {"StringValue": run_id, "DataType": "String"},
            "story_id": {"StringValue": story.id, "DataType": "String"},
            "data_classification": {
                "StringValue": story.data_classification.value,
                "DataType": "String",
            },
        },
    )
    logger.info(
        "sqs_message_sent", run_id=run_id, story_id=story.id, message_id=response.get("MessageId")
    )


# ─── Route ────────────────────────────────────────────────────────────────────


@router.post("/stories", status_code=202)
async def submit_story(
    request: UserStoryRequest,
    background_tasks: BackgroundTasks,
    dry_run: bool = False,
) -> dict:
    """
    Submit a user story to the ETL Agent pipeline.

    Returns immediately with a run_id. Poll GET /api/v1/runs/{run_id} for status.

    Execution mode:
      - ECS Fargate  (SQS_QUEUE_URL is set): publishes to SQS queue.
      - Local / EC2  (SQS_QUEUE_URL empty):  runs in a FastAPI background task.
    """
    settings = get_settings()
    run_id = str(uuid4())

    # Build the internal UserStory from the simplified request.
    # source and target are None — the StoryParserAgent resolves them from
    # the Glue catalog during the parse_story node.
    story = UserStory(
        id=str(uuid4()),
        title=request.title,
        description=request.description,
        acceptance_criteria=request.acceptance_criteria,
    )

    logger.info(
        "story_submitted",
        story_id=story.id,
        run_id=run_id,
        data_classification=story.data_classification.value,
        execution_mode="sqs" if settings.use_sqs else "background_task",
    )

    # 1. Persist story
    await _persist_user_story(story)

    # 2. Register run
    await async_create_run(run_id=run_id, story_id=story.id, story_title=story.title)

    # 3. Audit events
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
            "source_path": story.source.path if story.source else None,
            "target_path": story.target.path if story.target else None,
            "execution_mode": "sqs" if settings.use_sqs else "background_task",
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

    # 4. Dispatch
    if settings.use_sqs:
        # ECS Fargate: drop a message on SQS; a worker task will pick it up.
        # This is synchronous but very fast (< 50 ms).
        try:
            _publish_to_sqs(run_id=run_id, story=story, dry_run=dry_run)
            execution_mode = "sqs"
        except Exception as exc:
            logger.error("sqs_publish_failed", run_id=run_id, error=str(exc))
            await async_update_run(
                run_id,
                status="FAILED",
                error_message=f"SQS publish failed: {exc}",
            )
            return {
                "run_id": run_id,
                "story_id": story.id,
                "status": "FAILED",
                "error": str(exc),
            }
    else:
        # Local / EC2: run the pipeline in a FastAPI background task.
        background_tasks.add_task(_run_pipeline_background, story, run_id, dry_run=dry_run)
        execution_mode = "background_task"

    return {
        "run_id": run_id,
        "story_id": story.id,
        "status": RunStatus.PENDING.value,
        "data_classification": story.data_classification.value,
        "execution_mode": execution_mode,
        "dry_run": dry_run,
        "message": f"Pipeline queued. Track at GET /api/v1/runs/{run_id}",
    }


# ─── Background pipeline driver (local / EC2 mode only) ──────────────────────


async def _run_pipeline_background(
    story: UserStory,
    run_id: str,
    *,
    dry_run: bool = False,
) -> None:
    """Runs inside a FastAPI BackgroundTask (no-SQS path)."""
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

    async def _on_update(node_name: str, node_output: dict, _full_state: dict) -> None:
        kwargs: dict = {"current_stage": node_name}
        if "status" in node_output:
            s = node_output["status"]
            kwargs["status"] = s.value if hasattr(s, "value") else str(s)
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
        if node_output.get("token_tracker"):
            tracker = node_output["token_tracker"]
            td = tracker.to_dict() if hasattr(tracker, "to_dict") else {}
            if td:
                kwargs.update(
                    {
                        "total_input_tokens": td.get("total_input_tokens", 0),
                        "total_output_tokens": td.get("total_output_tokens", 0),
                        "total_cost_usd": td.get("total_cost_usd", 0.0),
                        "budget_pct": td.get("budget_pct", 0.0),
                        "token_steps_json": json.dumps(td.get("steps", [])),
                    }
                )
        await async_update_run(run_id, **kwargs)

    try:
        final_state = await stream_pipeline(story=story, on_update=_on_update, dry_run=dry_run)
        status_val = final_state.get("status")
        status_str = status_val.value if hasattr(status_val, "value") else str(status_val)

        await async_update_run(
            run_id,
            status=status_str,
            completed_at=datetime.now(UTC).isoformat(),
            github_pr_url=final_state.get("github_pr_url"),
            s3_artifact_url=final_state.get("s3_artifact_url"),
            error_message=final_state.get("error_message"),
        )
        event_type = "RUN_FAILED" if status_str == "FAILED" else "RUN_COMPLETED"
        await write_audit_event(
            event_type,
            run_id=run_id,
            story_id=story.id,
            actor="system",
            trigger_source="system",
            to_status=status_str,
        )
        logger.info("background_pipeline_complete", run_id=run_id, status=status_str)

    except Exception as e:
        await async_update_run(
            run_id,
            status="FAILED",
            error_message=str(e),
            completed_at=datetime.now(UTC).isoformat(),
        )
        await write_audit_event(
            "RUN_FAILED",
            run_id=run_id,
            story_id=story.id,
            actor="system",
            trigger_source="system",
            to_status="FAILED",
            payload={"error": str(e)},
        )
        logger.error("background_pipeline_failed", run_id=run_id, error=str(e))
