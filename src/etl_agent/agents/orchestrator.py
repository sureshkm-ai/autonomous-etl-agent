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
    return await agent(state)


async def _coding_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.coding_agent import CodingAgent
    agent = CodingAgent()
    return await agent(state)


async def _test_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.test_agent import TestAgent
    agent = TestAgent()
    return await agent(state)


async def _pr_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.pr_agent import PRAgent
    agent = PRAgent()
    return await agent(state)


async def _deploy_agent_node(state: GraphState) -> dict[str, Any]:
    from etl_agent.agents.deploy_agent import DeployAgent
    agent = DeployAgent()
    return await agent(state)


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


async def stream_pipeline(
    story: "UserStory | None" = None,
    user_story: "UserStory | dict | None" = None,
    run_id: "uuid.UUID | None" = None,
    require_human_approval: "bool | None" = None,
    max_retries: "int | None" = None,
    on_update: "Any | None" = None,
) -> "dict[str, Any]":
    """
    Run the pipeline with per-node streaming callbacks.

    ``on_update`` is an optional async callable:
        ``await on_update(node_name: str, node_output: dict, full_state: dict)``
    Called after every LangGraph node completes — lets the API layer update
    the in-memory run store with live stage progress.

    Returns the final accumulated state dict (same as run_pipeline).
    """
    resolved_story = user_story if user_story is not None else story
    if isinstance(resolved_story, dict):
        resolved_story = UserStory(**resolved_story)
    if resolved_story is None:
        raise ValueError("Provide 'story' or 'user_story'")

    settings = get_settings()
    resolved_run_id = run_id if run_id is not None else uuid.uuid4()
    resolved_approval = (
        require_human_approval if require_human_approval is not None else settings.require_human_approval
    )
    resolved_max_retries = max_retries if max_retries is not None else settings.max_retries

    structlog.contextvars.bind_contextvars(run_id=str(resolved_run_id), story_id=resolved_story.id)
    logger.info("pipeline_started", story_title=resolved_story.title)

    initial_state: GraphState = {
        "user_story": resolved_story,
        "run_id": resolved_run_id,
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
        "max_retries": resolved_max_retries,
        "error_message": None,
        "awaiting_approval": resolved_approval,
        "messages": [],
    }

    compiled_graph = build_graph()
    # Accumulate state across all node updates
    final_state: dict[str, Any] = dict(initial_state)

    async for chunk in compiled_graph.astream(initial_state):
        for node_name, node_output in chunk.items():
            final_state.update(node_output)
            if on_update is not None:
                await on_update(node_name, node_output, final_state)

    logger.info(
        "pipeline_completed",
        status=final_state.get("status"),
        pr_url=final_state.get("github_pr_url"),
    )
    structlog.contextvars.clear_contextvars()
    return final_state


async def run_pipeline(
    story: "UserStory | None" = None,
    deploy: bool = True,
    user_story: "UserStory | dict | None" = None,
    run_id: "uuid.UUID | None" = None,
    require_human_approval: "bool | None" = None,
    max_retries: "int | None" = None,
) -> "dict[str, Any]":
    """
    Entry point: run the full agent pipeline for a user story.

    Accepts two calling styles:
    - ``run_pipeline(story)``            — original positional style
    - ``run_pipeline(user_story=..., run_id=..., require_human_approval=..., deploy=..., max_retries=...)``
                                         — integration-test keyword style

    Args:
        story: UserStory (positional, legacy)
        deploy: Whether to trigger Airflow deployment after PR.
        user_story: UserStory or plain dict (keyword, preferred by tests)
        run_id: Pre-supplied run UUID (optional; generated if omitted)
        require_human_approval: Override the settings value for this run
        max_retries: Override the settings value for this run

    Returns:
        Final graph state dict with status, PR URL, etc.
    """
    # Normalise: prefer keyword 'user_story', fall back to positional 'story'
    resolved_story = user_story if user_story is not None else story
    if isinstance(resolved_story, dict):
        resolved_story = UserStory(**resolved_story)
    if resolved_story is None:
        raise ValueError("Provide 'story' or 'user_story'")

    settings = get_settings()
    resolved_run_id = run_id if run_id is not None else uuid.uuid4()
    resolved_approval = require_human_approval if require_human_approval is not None else settings.require_human_approval
    resolved_max_retries = max_retries if max_retries is not None else settings.max_retries

    structlog.contextvars.bind_contextvars(run_id=str(resolved_run_id), story_id=resolved_story.id)
    logger.info("pipeline_started", story_title=resolved_story.title)

    initial_state: GraphState = {
        "user_story": resolved_story,
        "run_id": resolved_run_id,
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
        "max_retries": resolved_max_retries,
        "error_message": None,
        "awaiting_approval": resolved_approval,
        "messages": [],
    }

    compiled_graph = build_graph()
    final_state = await compiled_graph.ainvoke(initial_state)

    logger.info(
        "pipeline_completed",
        status=final_state.get("status"),
        pr_url=final_state.get("github_pr_url"),
    )
    structlog.contextvars.clear_contextvars()
    return final_state
