<<<<<<< HEAD
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
=======
"""LangGraph state definitions and routing functions."""
from typing import Any, TypedDict
from uuid import UUID
from etl_agent.core.models import ETLSpec, RunStatus, TestResult


class GraphState(TypedDict, total=False):
    """LangGraph state for the ETL agent pipeline."""
    user_story: Any
    run_id: UUID
    etl_spec: ETLSpec | None
    generated_code: str | None
    generated_tests: str | None
    generated_readme: str | None
    test_results: TestResult | None
    github_issue_url: str | None
    github_branch_name: str | None
    github_pr_url: str | None
    s3_artifact_url: str | None
    airflow_dag_run_id: str | None
    status: RunStatus
    retry_count: int
    max_retries: int
    error_message: str | None
    awaiting_approval: bool
    messages: list[str]


def route_after_tests(state: GraphState) -> str:
    """Route after test execution."""
    if state.get("test_results") and state["test_results"].passed:
        if state.get("awaiting_approval"):
            return "await_approval"
        return "pr_agent"
    if state.get("retry_count", 0) < state.get("max_retries", 2):
        return "coding_agent"
    return "failure"


def route_after_approval(state: GraphState) -> str:
    """Route after human approval."""
    return "pr_agent"


def route_after_pr(state: GraphState) -> str:
    """Route after PR creation."""
    if state.get("github_pr_url"):
        return "deploy_agent"
    return "failure"
>>>>>>> main
