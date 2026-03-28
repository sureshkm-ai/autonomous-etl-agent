"""SQS consumer worker — runs pipeline tasks received from the queue.

One Fargate task = one worker process = one in-flight pipeline run at a time.
ECS autoscaling adjusts the number of tasks based on SQS queue depth,
so concurrency is handled at the infrastructure level, not inside this process.

Lifecycle
---------
1. Long-poll SQS for a message (up to 20 s wait).
2. Parse the message body as a StoryMessage (run_id + UserStory JSON).
3. Update run status to PARSING in the DB and write a PARSING_STARTED audit event.
4. Run stream_pipeline() with the on_update callback that writes progress to DB.
5. On success  → delete the SQS message.
6. On failure  → let visibility timeout expire; after maxReceiveCount the message
                 moves to the DLQ automatically.

Signal handling
---------------
SIGTERM (sent by ECS when scaling in or stopping a task) is caught and sets a
flag so the main loop drains after the current pipeline run completes, rather
than dying mid-run.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("etl_agent.worker")


# ─── Configuration ────────────────────────────────────────────────────────────

QUEUE_URL = os.environ["SQS_QUEUE_URL"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
VISIBILITY_TIMEOUT = int(os.environ.get("SQS_VISIBILITY_TIMEOUT", "900"))
MAX_MESSAGES = int(os.environ.get("SQS_MAX_MESSAGES", "1"))
WAIT_TIME_SECONDS = 20  # long-poll

# ─── Graceful shutdown flag ───────────────────────────────────────────────────

_shutdown = False


def _handle_sigterm(_signum, _frame):
    global _shutdown
    logger.info("worker_sigterm_received — finishing current run then exiting")
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# ─── SQS client ───────────────────────────────────────────────────────────────


def _sqs_client():
    return boto3.client("sqs", region_name=AWS_REGION)


# ─── Heartbeat — extend visibility while pipeline is running ─────────────────


async def _heartbeat(sqs, receipt_handle: str, interval: int = 240) -> None:
    """Extend message visibility by VISIBILITY_TIMEOUT every *interval* seconds.

    Prevents the message reappearing in the queue while a long pipeline run
    is in progress. This coroutine is run concurrently with the pipeline.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            sqs.change_message_visibility(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=VISIBILITY_TIMEOUT,
            )
            logger.debug("worker_heartbeat_extended", receipt_handle=receipt_handle[:20])
        except ClientError as exc:
            # Message may have already been deleted — stop heartbeat
            logger.warning("worker_heartbeat_failed", error=str(exc))
            return


# ─── Process one message ──────────────────────────────────────────────────────


async def _process_message(sqs, message: dict[str, Any]) -> bool:
    """Run the pipeline for one SQS message.

    Returns True if the run completed (success or business failure),
    False if a system error occurred that should not delete the message.
    """
    from etl_agent.agents.orchestrator import stream_pipeline
    from etl_agent.api.v1.run_store import async_update_run
    from etl_agent.core.audit import write_audit_event
    from etl_agent.core.models import UserStory

    receipt_handle = message["ReceiptHandle"]
    body: dict[str, Any] = {}

    try:
        body = json.loads(message["Body"])
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("worker_bad_message_body", error=str(exc), body=message.get("Body", "")[:200])
        # Poison pill — delete it rather than cycling through the DLQ uselessly
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    run_id = body.get("run_id", "")
    dry_run = body.get("dry_run", False)
    story_raw = body.get("story")

    if not run_id or not story_raw:
        logger.error("worker_missing_fields", run_id=run_id, has_story=bool(story_raw))
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    try:
        story = UserStory.model_validate(story_raw)
    except Exception as exc:
        logger.error("worker_story_validation_failed", run_id=run_id, error=str(exc))
        await async_update_run(
            run_id, status="FAILED", error_message=f"Story validation failed: {exc}"
        )
        await write_audit_event(
            "RUN_FAILED",
            run_id=run_id,
            story_id=body.get("story_id"),
            actor="worker",
            trigger_source="sqs",
            payload={"error": str(exc)},
        )
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    logger.info(
        "worker_run_start",
        run_id=run_id,
        story_id=story.id,
        data_classification=story.data_classification.value,
    )

    await async_update_run(run_id, status="PARSING", started_at=datetime.now(UTC))
    await write_audit_event(
        "PARSING_STARTED",
        run_id=run_id,
        story_id=story.id,
        actor="worker",
        trigger_source="sqs",
        from_status="PENDING",
        to_status="PARSING",
    )

    # Start heartbeat task concurrently
    heartbeat_task = asyncio.create_task(_heartbeat(sqs, receipt_handle))

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
        final_state = await stream_pipeline(
            story=story,
            run_id=run_id,
            on_update=_on_update,
            dry_run=dry_run,
        )

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
            actor="worker",
            trigger_source="sqs",
            to_status=status_str,
            payload={
                "github_pr_url": final_state.get("github_pr_url"),
                "s3_artifact_url": final_state.get("s3_artifact_url"),
            },
        )

        logger.info("worker_run_complete", run_id=run_id, status=status_str)
        sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt_handle)
        return True

    except Exception as exc:
        logger.error("worker_pipeline_exception", run_id=run_id, error=str(exc), exc_info=True)
        await async_update_run(
            run_id,
            status="FAILED",
            error_message=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )
        await write_audit_event(
            "RUN_FAILED",
            run_id=run_id,
            story_id=story.id,
            actor="worker",
            trigger_source="sqs",
            payload={"error": str(exc)},
        )
        # Do NOT delete — let SQS retry then DLQ
        return False

    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


# ─── Main poll loop ───────────────────────────────────────────────────────────


async def run_worker() -> None:
    """Main event loop — poll SQS and process messages until shutdown."""
    from etl_agent.core.config import get_settings
    from etl_agent.core.logging import configure_logging
    from etl_agent.database.session import create_all_tables, dispose_engine

    settings = get_settings()
    configure_logging(
        log_level="DEBUG" if settings.debug else "INFO",
        json_logs=not settings.debug,
    )

    logger.info("worker_starting", queue=QUEUE_URL, region=AWS_REGION)
    await create_all_tables()

    sqs = _sqs_client()
    consecutive_errors = 0

    while not _shutdown:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=MAX_MESSAGES,
                WaitTimeSeconds=WAIT_TIME_SECONDS,
                AttributeNames=["ApproximateReceiveCount"],
            )
            messages = response.get("Messages", [])

            if not messages:
                consecutive_errors = 0
                continue

            for message in messages:
                if _shutdown:
                    break
                await _process_message(sqs, message)

            consecutive_errors = 0

        except ClientError as exc:
            consecutive_errors += 1
            wait = min(2**consecutive_errors, 60)
            logger.error("worker_sqs_error", error=str(exc), retry_in=wait)
            await asyncio.sleep(wait)

        except Exception as exc:
            consecutive_errors += 1
            wait = min(2**consecutive_errors, 60)
            logger.error("worker_unexpected_error", error=str(exc), retry_in=wait, exc_info=True)
            await asyncio.sleep(wait)

    await dispose_engine()
    logger.info("worker_stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
