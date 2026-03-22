"""
In-memory run store — tracks pipeline run state for the UI.

Each run is a plain dict keyed by run_id.  In a production system this
would be persisted to the database; the schema maps 1-to-1 to the
PipelineRunRecord table that is planned but not yet migrated.

Reset on container restart (acceptable for MVP / demo).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Module-level singleton — safe in asyncio (single-threaded event loop)
_runs: dict[str, dict[str, Any]] = {}


def create_run(run_id: str, story_id: str, story_title: str) -> dict[str, Any]:
    """Register a new run (called at story submission time)."""
    record: dict[str, Any] = {
        "run_id": run_id,
        "story_id": story_id,
        "story_title": story_title,
        "status": "PENDING",
        "current_stage": None,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "github_pr_url": None,
        "github_issue_url": None,
        "s3_artifact_url": None,
        "test_results": None,
        "error_message": None,
    }
    _runs[run_id] = record
    return record


def update_run(run_id: str, **kwargs: Any) -> None:
    """Merge kwargs into the run record (called from the background task)."""
    if run_id in _runs:
        _runs[run_id].update(kwargs)


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return a single run record, or None if not found."""
    return _runs.get(run_id)


def list_runs() -> list[dict[str, Any]]:
    """Return all runs, most recent first."""
    return sorted(_runs.values(), key=lambda r: r["submitted_at"], reverse=True)
