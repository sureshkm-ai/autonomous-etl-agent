"""Audit event service — append-only governance event log.

Every call to write_audit_event() persists one immutable record to the
AuditEventRecord table. Failures are caught and logged; they never propagate
to the caller so that a DB hiccup cannot interrupt the pipeline.
"""

import json
from datetime import UTC, datetime
from typing import Any

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

VALID_EVENT_TYPES = {
    "STORY_SUBMITTED",
    "RUN_CREATED",
    "PARSING_STARTED",
    "CODING_STARTED",
    "TESTING_STARTED",
    "PR_CREATING",
    "DEPLOYMENT_APPROVED",
    "DEPLOYMENT_TRIGGERED",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_CANCELLED",
    "OVERRIDE_GRANTED",
}


async def write_audit_event(
    event_type: str,
    run_id: str | None = None,
    story_id: str | None = None,
    actor: str = "system",
    trigger_source: str = "api",
    from_status: str | None = None,
    to_status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one audit event record. Never raises — logs errors silently."""
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("invalid_audit_event_type", event_type=event_type)
        return

    from etl_agent.database.models import AuditEventRecord
    from etl_agent.database.session import get_session_factory

    ts = datetime.now(UTC)
    record_id = f"{event_type}_{run_id or 'none'}_{ts.timestamp():.0f}"

    record = AuditEventRecord(
        id=record_id,
        event_type=event_type,
        run_id=run_id,
        story_id=story_id,
        actor=actor,
        trigger_source=trigger_source,
        from_status=from_status,
        to_status=to_status,
        payload_json=json.dumps(payload or {}),
        timestamp=ts.replace(tzinfo=None),  # TIMESTAMP WITHOUT TIME ZONE column
    )

    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(record)
            await session.commit()
        logger.info(
            "audit_event_written",
            event_type=event_type,
            run_id=run_id,
            story_id=story_id,
            actor=actor,
        )
    except Exception as exc:
        # Audit failures must never break the calling pipeline
        logger.error(
            "audit_event_write_failed",
            event_type=event_type,
            run_id=run_id,
            error=str(exc),
        )


async def list_audit_events(run_id: str) -> list[dict[str, Any]]:
    """Return all audit events for a run, ordered by timestamp ascending."""
    from sqlalchemy import select

    from etl_agent.database.models import AuditEventRecord
    from etl_agent.database.session import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(AuditEventRecord)
                .where(AuditEventRecord.run_id == run_id)
                .order_by(AuditEventRecord.timestamp)
            )
            records = result.scalars().all()
            return [_record_to_dict(r) for r in records]
    except Exception as exc:
        logger.error("audit_list_failed", run_id=run_id, error=str(exc))
        return []


def _record_to_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "event_type": r.event_type,
        "run_id": r.run_id,
        "story_id": r.story_id,
        "actor": r.actor,
        "trigger_source": r.trigger_source,
        "from_status": r.from_status,
        "to_status": r.to_status,
        "payload": json.loads(r.payload_json or "{}"),
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
    }
