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
