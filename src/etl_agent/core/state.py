"""GraphState — shared state TypedDict for the LangGraph pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import TypedDict

from etl_agent.core.models import ETLSpec, RunStatus, TestResult, UserStory

if TYPE_CHECKING:
    pass


class GraphState(TypedDict, total=False):
    """Shared mutable state passed between LangGraph nodes.

    All fields are optional (total=False) so each node can update a subset.
    """

    # Input
    story: UserStory
    run_id: str
    story_id: str
    dry_run: bool

    # Pipeline progress
    status: RunStatus
    current_stage: str
    error_message: str | None
    retry_count: int

    # Agent outputs
    etl_spec: ETLSpec | None
    generated_code: str | None
    test_results: TestResult | None

    # Release artifacts
    github_pr_url: str | None
    github_issue_url: str | None
    s3_artifact_url: str | None
    commit_sha: str | None
    artifact_checksum: str | None

    # Governance
    token_tracker: Any | None  # RunTokenTracker (avoid circular import)
    approval_required: bool
    approval_granted: bool
    data_classification: str
