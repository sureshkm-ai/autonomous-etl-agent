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
from collections.abc import Callable, Coroutine
from typing import Any

from etl_agent.core.config import get_settings
from etl_agent.core.llm_governance import RunTokenTracker
from etl_agent.core.logging import get_logger
from etl_agent.core.models import DataClassification, RunStatus, UserStory
from etl_agent.core.state import GraphState

logger = get_logger(__name__)


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
        budget_flag = tracker.needs_approval(threshold_pct=settings.budget_approval_threshold_pct)

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
        from langgraph.graph import END, StateGraph
    except ImportError as e:
        raise ImportError("langgraph is required. Install with: pip install langgraph") from e

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
        {"dry_run_end": "dry_run_end", "run_tests": "run_tests"},
    )
    builder.add_edge("dry_run_end", END)
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

    return final_state
