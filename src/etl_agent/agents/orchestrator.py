"""
LangGraph orchestrator — the main agent state machine.
Wires all 5 agents into a directed graph with conditional edges.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger
from etl_agent.core.models import RunResult, RunStatus, UserStory
from etl_agent.core.state import (
    GraphState,
    route_after_approval,
    route_after_pr,
    route_after_tests,
)

logger = get_logger(__name__)


async def _story_parser_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.story_parser import StoryParserAgent
    agent = StoryParserAgent()
    return await agent.run(state)


async def _coding_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.coding_agent import CodingAgent
    agent = CodingAgent()
    return await agent.run(state)


async def _test_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.test_agent import TestAgent
    agent = TestAgent()
    return await agent.run(state)


async def _pr_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.pr_agent import PRAgent
    agent = PRAgent()
    return await agent.run(state)


async def _deploy_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.deploy_agent import DeployAgent
    agent = DeployAgent()
    return await agent.run(state)


async def _failure_node(state: GraphState) -> dict[str, Any]:
    logger.error("pipeline_failed", error=state.get("error_message"), run_id=str(state["run_id"]))
    return {"status": RunStatus.FAILED}


async def _await_approval_node(state: GraphState) -> dict[str, Any]:
    """Interrupt point for human-in-the-loop approval."""
    logger.info("awaiting_human_approval", run_id=str(state["run_id"]))
    # In a real implementation this would use LangGraph's interrupt() mechanism
    return {"status": RunStatus.AWAITING_APPROVAL}


def build_graph() -> Any:
    """Build and compile the LangGraph state machine."""
    graph = StateGraph(GraphState)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    graph.add_node("story_parser", _story_parser_node)
    graph.add_node("coding_agent", _coding_agent_node)
    graph.add_node("test_agent", _test_agent_node)
    graph.add_node("pr_agent", _pr_agent_node)
    graph.add_node("deploy_agent", _deploy_agent_node)
    graph.add_node("await_approval", _await_approval_node)
    graph.add_node("failure", _failure_node)

    # ── Entry point ────────────────────────────────────────────────────────────
    graph.set_entry_point("story_parser")

    # ── Linear edges ──────────────────────────────────────────────────────────
    graph.add_edge("story_parser", "coding_agent")
    graph.add_edge("coding_agent", "test_agent")

    # ── Conditional edges ──────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "test_agent",
        route_after_tests,
        {
            "pr_agent": "pr_agent",
            "coding_agent": "coding_agent",   # retry
            "await_approval": "await_approval",
            "failure": "failure",
        },
    )

    graph.add_conditional_edges(
        "await_approval",
        route_after_approval,
        {
            "pr_agent": "pr_agent",
            "await_approval": "await_approval",
        },
    )

    graph.add_conditional_edges(
        "pr_agent",
        route_after_pr,
        {
            "deploy_agent": "deploy_agent",
            "failure": "failure",
        },
    )

    # ── Terminal edges ─────────────────────────────────────────────────────────
    graph.add_edge("deploy_agent", END)
    graph.add_edge("failure", END)

    return graph.compile()


async def run_pipeline(story: UserStory, deploy: bool = True) -> RunResult:
    """
    Entry point: run the full agent pipeline for a user story.

    Args:
        story: The user story to process.
        deploy: Whether to trigger Airflow deployment after PR.

    Returns:
        RunResult with all outputs and final status.
    """
    settings = get_settings()
    run_id = uuid.uuid4()

    structlog.contextvars.bind_contextvars(run_id=str(run_id), story_id=story.id)
    logger.info("pipeline_started", story_title=story.title)

    initial_state: GraphState = {
        "user_story": story,
        "run_id": run_id,
        "etl_spec": None,
        "generated_code": None,
        "generated_tests": None,
        "generated_readme": None,
        "test_results": None,
        "github_issue_url": None,
        "github_branch_name": None,
        "github_pr_url": None,
        "s3_artifact_url": None,
        "airflow_dag_run_id": None,
        "status": RunStatus.PENDING,
        "retry_count": 0,
        "max_retries": settings.max_retries,
        "error_message": None,
        "awaiting_approval": settings.require_human_approval,
        "messages": [],
    }

    compiled_graph = build_graph()
    final_state = await compiled_graph.ainvoke(initial_state)

    result = RunResult(
        run_id=run_id,
        story_id=story.id,
        status=final_state["status"],
        etl_spec=final_state.get("etl_spec"),
        test_result=final_state.get("test_results"),
        github_issue_url=final_state.get("github_issue_url"),
        github_pr_url=final_state.get("github_pr_url"),
        s3_artifact_url=final_state.get("s3_artifact_url"),
        airflow_dag_run_id=final_state.get("airflow_dag_run_id"),
        retry_count=final_state.get("retry_count", 0),
        error_message=final_state.get("error_message"),
    )

    logger.info("pipeline_completed", status=result.status.value, pr_url=result.github_pr_url)
    structlog.contextvars.clear_contextvars()
    return result
