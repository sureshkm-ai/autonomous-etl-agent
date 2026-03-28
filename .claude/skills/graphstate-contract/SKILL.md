---
name: graphstate-contract
description: >
  LangGraph agent patterns and GraphState contract rules for this project.
  Use this skill whenever creating or editing any agent under src/etl_agent/agents/,
  or when touching src/etl_agent/core/state.py. Prevents TypedDict key mismatches,
  missing GraphState fields, sync/async callable confusion in react_tool_loop,
  and missing class/function exports that break imports.
---

# GraphState Contract & Agent Patterns

These rules come from real failures in the autonomous-etl-agent pipeline.
Apply them every time you write or edit an agent.

---

## 1. Check GraphState before accessing state keys

`GraphState` is a `TypedDict` defined in `src/etl_agent/core/state.py`. Every
key an agent accesses via `state["key"]` or `state.get("key")` must be declared
there. Accessing an undeclared key produces a `typeddict-item` mypy error and
can cause `KeyError` at runtime.

**Before writing `state.get("some_field")` in an agent:**
1. Open `src/etl_agent/core/state.py`
2. Confirm `some_field` exists in `GraphState`
3. If it doesn't exist, add it (with `| None` since `total=False`):

```python
class GraphState(TypedDict, total=False):
    # existing fields ...
    generated_tests: str | None    # ← add new fields here
    generated_readme: str | None
```

**Current GraphState keys** (as of latest version):
`story`, `user_story`, `run_id`, `story_id`, `dry_run`, `status`,
`current_stage`, `error_message`, `retry_count`, `etl_spec`, `generated_code`,
`generated_tests`, `generated_readme`, `test_results`, `github_pr_url`,
`github_issue_url`, `s3_artifact_url`, `commit_sha`, `artifact_checksum`,
`token_tracker`, `approval_required`, `approval_granted`, `data_classification`,
`max_retries`, `messages`, `awaiting_approval`

---

## 2. react_tool_loop handles both sync and async callables

`ReactAgent.react_tool_loop()` uses `inspect.isawaitable()` to decide whether
to await the result of `action()`. This means you can pass either a sync or
async lambda — do not add `async` to the lambda itself unless the function it
calls is actually async:

```python
# ✅ Sync tool (GitHubTools methods are synchronous)
issue_url = await self.react_tool_loop(
    action=lambda: gh.create_issue(title=title, body=body),
    ...
)

# ✅ Async tool
result = await self.react_tool_loop(
    action=lambda: some_async_function(arg),
    ...
)

# ❌ Wrong — don't make the lambda itself async
issue_url = await self.react_tool_loop(
    action=async lambda: gh.create_issue(...),  # SyntaxError anyway
    ...
)
```

`GitHubTools`, `AWSTools`, and all tool classes in `etl_agent/tools/` are
**synchronous**. They use blocking I/O (PyGithub, boto3). Do not await them
directly; let `react_tool_loop` handle it.

---

## 3. Verify class/function exports before importing

If an agent imports a class or function from a tool module, verify it exists
in that module before writing the import. A missing export causes an
`ImportError` at runtime and a `name-defined` mypy error.

```python
# Before writing this in an agent:
from etl_agent.tools.aws_tools import AWSTools

# Verify AWSTools is defined in aws_tools.py
# If it's missing, add it to aws_tools.py first
```

**Exports currently available:**
- `etl_agent.tools.github_tools` → `GitHubTools`
- `etl_agent.tools.aws_tools` → `AWSTools`, `upload_artifact`, `upload_pipeline_script`, `trigger_airflow_dag`
- `etl_agent.tools.llm_cache` → `configure_llm_cache`
- `etl_agent.agents.base` → `ReactAgent`
- `etl_agent.core.state` → `GraphState`, `route_after_tests`, `route_after_pr`

---

## 4. Settings attributes must exist before agents access them

Agents typically do `self.settings = get_settings()` and then access attributes.
Any attribute not declared in `Settings` (in `core/config.py`) will raise
`AttributeError` at runtime.

**Current Settings attributes** relevant to agents:
- `github_token`, `github_owner`, `github_repo`, `github_target_repo` (property)
- `aws_access_key_id`, `aws_secret_access_key`, `aws_region`, `aws_endpoint_url`
- `s3_bucket`, `aws_s3_artifacts_bucket`
- `airflow_enabled`, `airflow_url`, `airflow_api_url`, `airflow_dag_id`, `airflow_username`, `airflow_password`
- `anthropic_api_key`, `llm_model`, `llm_max_tokens`, `llm_temperature`
- `max_retries`, `max_tokens_per_run`, `budget_approval_threshold_pct`
- `approved_models`, `approved_model_list` (property), `fallback_model`
- `require_human_approval`, `use_sqs` (property)
- `sqs_queue_url`, `sqs_dlq_url`, `sqs_visibility_timeout`
- `database_url`, `environment`, `debug`

If you need a new attribute, add it to `Settings` in `core/config.py` with a
default value before using it in an agent.

---

## 5. Routing functions must be in core/state.py

LangGraph conditional edge functions (`route_after_tests`, `route_after_pr`, etc.)
must be importable from `etl_agent.core.state`. Do not define them only inside
agent or orchestrator files — tests import them directly from `state.py`.

```python
# src/etl_agent/core/state.py
def route_after_tests(state: GraphState) -> str:
    """Used as LangGraph conditional edge AND imported directly in tests."""
    ...

def route_after_pr(state: GraphState) -> str: ...
```

---

## 6. Agent __call__ signature

All agents must implement `__call__` wrapping `run` with error handling, so
LangGraph can use them as nodes:

```python
async def __call__(self, state: GraphState) -> dict[str, Any]:
    try:
        return await self.run(state)
    except Exception as e:
        logger.error("agent_call_failed", error=str(e))
        return {"status": RunStatus.FAILED, "error_message": str(e)}
```

The `run` method does the real work; `__call__` ensures a node failure never
crashes the whole graph.
