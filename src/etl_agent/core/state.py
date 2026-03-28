"""GraphState — shared state TypedDict for the LangGraph pipeline."""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from typing_extensions import TypedDict

from etl_agent.core.models import ETLSpec, RunStatus, TestResult, UserStory

if TYPE_CHECKING:
    from etl_agent.core.llm_governance import RunTokenTracker


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
    error_message: Optional[str]
    retry_count: int

    # Agent outputs
    etl_spec: Optional[ETLSpec]
    generated_code: Optional[str]
    test_results: Optional[TestResult]

    # Release artifacts
    github_pr_url: Optional[str]
    github_issue_url: Optional[str]
    s3_artifact_url: Optional[str]
    commit_sha: Optional[str]
    artifact_checksum: Optional[str]

    # Governance
    token_tracker: Optional[Any]        # RunTokenTracker (avoid circular import)
    approval_required: bool
    approval_granted: bool
    data_classification: str
