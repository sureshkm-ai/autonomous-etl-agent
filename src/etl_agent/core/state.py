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
    user_story: UserStory | None  # alias populated by story_parser (same as "story")
    source_schema: dict[str, Any] | None  # inferred from S3 parquet/delta before codegen
    generated_code: str | None
    generated_tests: str | None
    generated_readme: str | None
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

    # Pipeline control
    max_retries: int
    messages: list[Any]
    awaiting_approval: bool


# ---------------------------------------------------------------------------
# Routing helpers — used as LangGraph conditional edge functions and in tests
# ---------------------------------------------------------------------------


def route_after_tests(state: GraphState) -> str:
    """Route after the test agent runs.

    - Tests passed               → ``pr_agent``
    - Tests failed, retries left → ``coding_agent`` (retry loop)
    - Tests failed, retries gone → ``failure``
    """
    test_results = state.get("test_results")
    retry_count = int(state.get("retry_count") or 0)
    max_retries = int(state.get("max_retries") or 2)

    if test_results is not None and test_results.passed:
        return "pr_agent"

    if retry_count < max_retries:
        return "coding_agent"

    return "failure"


def route_after_pr(state: GraphState) -> str:
    """Route after the PR agent runs.

    - PR URL present → ``deploy_agent``
    - No PR URL      → ``failure``
    """
    if state.get("github_pr_url"):
        return "deploy_agent"
    return "failure"
