<<<<<<< HEAD
"""LangGraph orchestrator — builds and streams the ETL agent pipeline.

Graph topology
--------------
  parse_story
      ↓
  generate_code
      ↓
  run_tests
      ↓
  approval_gate  ──(approval_required=True)──→  AWAITING_APPROVAL (terminal for now)
      ↓ (approved or not required)
  create_pr
      ↓
  deploy

Each node updates a subset of GraphState. stream_pipeline() yields state
snapshots after every node and calls the optional on_update callback.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger
from etl_agent.core.models import DataClassification, RunStatus, UserStory
from etl_agent.core.state import GraphState
from etl_agent.core.llm_governance import RunTokenTracker
=======
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
>>>>>>> main

logger = get_logger(__name__)


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# Sentinel for routing decisions
# ---------------------------------------------------------------------------

_NEEDS_APPROVAL = "needs_approval"
_PROCEED = "proceed"


# ---------------------------------------------------------------------------
# Node wrappers
# ---------------------------------------------------------------------------

async def _node_parse(state: GraphState) -> dict[str, Any]:
    """Parse story → ETLSpec."""
    from etl_agent.agents.story_parser import StoryParserAgent
    agent = StoryParserAgent()
    result = await agent.run(state)
    return {**result, "status": RunStatus.CODING, "current_stage": "parse_story"}


async def _node_code(state: GraphState) -> dict[str, Any]:
    """Generate PySpark pipeline code from ETLSpec."""
    from etl_agent.agents.coding_agent import CodingAgent
    agent = CodingAgent()
    result = await agent.run(state)
    return {**result, "status": RunStatus.TESTING, "current_stage": "generate_code"}


async def _node_test(state: GraphState) -> dict[str, Any]:
    """Generate and run pytest tests against the generated code."""
    from etl_agent.agents.test_agent import TestAgent
    agent = TestAgent()
    result = await agent.run(state)
    return {**result, "current_stage": "run_tests"}


async def _node_approval_gate(state: GraphState) -> dict[str, Any]:
    """Decide whether human approval is required before deployment.

    Approval is required when:
      - data_classification is confidential or restricted, OR
      - token budget consumption exceeded the configured threshold (e.g. 75%)
    """
    settings = get_settings()
    story: UserStory = state.get("story")  # type: ignore[assignment]
    tracker: RunTokenTracker | None = state.get("token_tracker")

    classification = getattr(story, "data_classification", DataClassification.internal)
    high_sensitivity = classification in (
        DataClassification.confidential,
        DataClassification.restricted,
    )

    budget_flag = False
    if tracker is not None:
        budget_flag = tracker.needs_approval(
            threshold_pct=settings.budget_approval_threshold_pct
        )

    approval_required = high_sensitivity or budget_flag

    reason_parts = []
    if high_sensitivity:
        reason_parts.append(f"data_classification={classification.value}")
    if budget_flag:
        reason_parts.append(f"budget_pct={tracker.budget_pct():.1f}%")  # type: ignore[union-attr]

    if approval_required:
        logger.info(
            "approval_gate_hold",
            run_id=state.get("run_id"),
            reasons=reason_parts,
        )
    else:
        logger.info("approval_gate_pass", run_id=state.get("run_id"))

    return {
        "approval_required": approval_required,
        "current_stage": "approval_gate",
        "status": RunStatus.AWAITING_APPROVAL if approval_required else RunStatus.PR_CREATING,
    }


async def _node_pr(state: GraphState) -> dict[str, Any]:
    """Create GitHub PR and issue for the generated pipeline."""
    from etl_agent.agents.pr_agent import PRAgent
    agent = PRAgent()
    result = await agent.run(state)
    return {**result, "current_stage": "create_pr"}


async def _node_deploy(state: GraphState) -> dict[str, Any]:
    """Upload artifact to S3 and trigger Airflow DAG."""
    from etl_agent.agents.deploy_agent import DeployAgent
    agent = DeployAgent()
    result = await agent.run(state)
    return {**result, "status": RunStatus.DONE, "current_stage": "deploy"}


# ---------------------------------------------------------------------------
# Routing function for approval gate
# ---------------------------------------------------------------------------

def _route_after_approval(state: GraphState) -> str:
    """Return edge label based on whether approval is required."""
    if state.get("approval_required"):
        return _NEEDS_APPROVAL
    return _PROCEED


async def _node_dry_run_complete(state: GraphState) -> dict[str, Any]:
    """Terminal node for dry-run mode — code generated but not tested/deployed."""
    logger.info("dry_run_complete", run_id=state.get("run_id"))
    return {
        "status": RunStatus.DRY_RUN_COMPLETE,
        "current_stage": "dry_run_complete",
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _build_graph():
    """Construct and compile the LangGraph StateGraph."""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError(
            "langgraph is required. Install with: pip install langgraph"
        )

    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("parse_story", _node_parse)
    builder.add_node("generate_code", _node_code)
    builder.add_node("run_tests", _node_test)
    builder.add_node("approval_gate", _node_approval_gate)
    builder.add_node("create_pr", _node_pr)
    builder.add_node("deploy", _node_deploy)

    # Linear edges
    builder.set_entry_point("parse_story")
    builder.add_edge("parse_story", "generate_code")
    # dry_run short-circuit: skip tests, PR, deploy
    def _route_after_code(state: GraphState) -> str:
        return "dry_run_end" if state.get("dry_run") else "run_tests"

    builder.add_node("dry_run_end", _node_dry_run_complete)
    builder.add_conditional_edges(
        "generate_code",
        _route_after_code,
        {"dry_run_end": END, "run_tests": "run_tests"},
    )
    builder.add_edge("run_tests", "approval_gate")

    # Conditional: approval gate may halt at AWAITING_APPROVAL
    builder.add_conditional_edges(
        "approval_gate",
        _route_after_approval,
        {
            _NEEDS_APPROVAL: END,  # halt; operator calls /approve to resume
            _PROCEED: "create_pr",
        },
    )

    builder.add_edge("create_pr", "deploy")
    builder.add_edge("deploy", END)

    return builder.compile()


# Module-level compiled graph (lazy init on first call)
_graph = None
_graph_lock = asyncio.Lock()


async def _get_graph():
    global _graph
    if _graph is None:
        async with _graph_lock:
            if _graph is None:
                _graph = _build_graph()
    return _graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

OnUpdateCallback = Callable[
    [str, dict[str, Any], dict[str, Any]],
    Coroutine[Any, Any, None],
]


async def stream_pipeline(
    story: UserStory,
    *,
    run_id: str | None = None,
    on_update: OnUpdateCallback | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute the pipeline and stream state updates after each node.

    Parameters
    ----------
    story:     The validated UserStory to process.
    run_id:    Pre-assigned run identifier (generated if not provided).
    on_update: Async callback called after each LangGraph node completes.
               Receives (node_name, node_output_dict, full_state_dict).
    dry_run:   If True, parse + code only — skip tests, PR, and deploy.

    Returns
    -------
    The final GraphState dict after all nodes have executed.
    """
    settings = get_settings()
    effective_run_id = run_id or str(uuid.uuid4())

    # Initialise per-run token tracker
    tracker = RunTokenTracker(
        run_id=effective_run_id,
        max_tokens=settings.max_tokens_per_run,
    )

    initial_state: GraphState = {
        "story": story,
        "run_id": effective_run_id,
        "story_id": story.id,
        "status": RunStatus.PARSING,
        "current_stage": "init",
        "token_tracker": tracker,
        "approval_required": False,
        "approval_granted": False,
        "data_classification": story.data_classification.value,
        "dry_run": dry_run,
        "retry_count": 0,
    }

    graph = await _get_graph()
    final_state: dict[str, Any] = dict(initial_state)

    try:
        async for event in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():
                if not isinstance(node_output, dict):
                    continue

                # Merge into running state snapshot
                final_state.update(node_output)

                logger.info(
                    "pipeline_node_complete",
                    node=node_name,
                    run_id=effective_run_id,
                    status=str(final_state.get("status", "")),
                )

                # Fire the caller's progress callback
                if on_update is not None:
                    try:
                        await on_update(node_name, node_output, final_state)
                    except Exception as cb_exc:
                        logger.error(
                            "on_update_callback_failed",
                            node=node_name,
                            error=str(cb_exc),
                        )

                # Abort early on failure
                status = final_state.get("status")
                if status == RunStatus.FAILED:
                    logger.error(
                        "pipeline_aborted",
                        run_id=effective_run_id,
                        node=node_name,
                        error=final_state.get("error_message"),
                    )
                    return final_state

    except Exception as exc:
        logger.error("pipeline_exception", run_id=effective_run_id, error=str(exc))
        final_state["status"] = RunStatus.FAILED
        final_state["error_message"] = str(exc)

    # Attach final token summary
    final_state["token_usage"] = tracker.to_dict()

    logger.info(
        "pipeline_finished",
        run_id=effective_run_id,
        status=str(final_state.get("status", "")),
        total_tokens=tracker.total_tokens,
        cost_usd=tracker.total_cost_usd,
    )

=======
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
>>>>>>> main
    return final_state
