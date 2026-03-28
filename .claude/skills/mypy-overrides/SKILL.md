---
name: mypy-overrides
description: >
  mypy configuration rules for pyproject.toml in this project. Use this skill
  whenever adding a new module to src/etl_agent/, adding a new third-party
  dependency, or editing [tool.mypy] in pyproject.toml. Prevents new modules
  from accidentally being checked under strict mode when they should be relaxed,
  and prevents third-party packages without stubs from causing import errors.
---

# mypy Override Rules

This project uses `strict = true` globally in `pyproject.toml`, with two override
blocks that relax checking for specific modules. Getting this wrong causes either
unexpected type errors in CI or missed errors in modules that should be strict.

---

## The two-tier model

**Tier 1 — Strict** (no override; checked with full strict mode):
- `etl_agent.core.models`
- `etl_agent.core.config`
- `etl_agent.core.exceptions`
- `etl_agent.core.state`
- `etl_agent.core.logging`

These are the project's data contracts and configuration. They must be fully typed.

**Tier 2 — Relaxed** (in the `disable_error_code` override):
- `etl_agent.agents.*`
- `etl_agent.worker`
- `etl_agent.api.*`
- `etl_agent.tools.*`
- `etl_agent.analytics.*`
- `etl_agent.spark.*`
- `etl_agent.cli`
- `etl_agent.prompts.*`
- `etl_agent.core.audit`
- `etl_agent.core.llm_governance`
- `etl_agent.database.*`

---

## Rule 1: Add every new module to an override

When you create a new Python module under `src/etl_agent/`, immediately decide
which tier it belongs in and add it to `pyproject.toml`.

```toml
# If it should be relaxed — add to the existing override list:
[[tool.mypy.overrides]]
module = [
    "etl_agent.agents.*",
    "etl_agent.worker",
    "etl_agent.new_module",   # ← add here
    ...
]
disallow_untyped_defs = false
...
```

Forgetting this means the new module gets strict checking, which produces
unexpected CI failures for code that was intentionally not fully typed.

---

## Rule 2: Add third-party packages without stubs to ignore_missing_imports

When adding a new third-party dependency that has no type stubs, add it to the
`ignore_missing_imports = true` override block:

```toml
[[tool.mypy.overrides]]
module = [
    "pyspark.*",
    "delta.*",
    "langchain.*",
    "langgraph.*",
    "anthropic.*",
    "aioboto3.*",
    "aiobotocore.*",
    "aiohttp.*",
    "github.*",
    "alembic.*",
    "slowapi.*",
    "your_new_package.*",   # ← add here
]
ignore_missing_imports = true
```

**How to decide:** If the package ships a `py.typed` marker or has stubs
installable via `pip install types-<package>` (e.g., `fastapi`, `pydantic`,
`sqlalchemy`, `structlog`, `boto3-stubs`), do NOT add it here — mypy can check
it natively. If it doesn't have stubs, add it.

---

## Rule 3: Use `[import-untyped]` not `[import]` for inline suppression

If you must suppress a missing-stub error inline (for packages not in the
`ignore_missing_imports` list), use the specific code:

```python
import aioboto3  # type: ignore[import-untyped]
```

The old `# type: ignore[import]` is treated as "unused ignore" in strict mode
when the package is already handled by an override, causing a new error.

---

## Rule 4: Disabled error codes in the relaxed override

The relaxed override currently disables these error codes:

```toml
disable_error_code = [
    "union-attr", "arg-type", "return-value", "assignment", "misc",
    "no-untyped-def", "no-untyped-call", "unused-ignore",
    "import-untyped", "attr-defined", "call-arg",
    "typeddict-item", "name-defined"
]
```

Before adding a new error code to this list, first try to fix the actual error.
This list is a safety net for genuinely unresolvable situations, not a blanket
suppressor.

---

## Rule 5: Strict-tier modules must have full type annotations

For any file that stays in Tier 1 (strict):

- All function parameters and return types annotated
- No bare `dict` or `list` — always `dict[str, Any]`, `list[str]`, etc.
- No `type: ignore` without a specific error code
- All enum classes use `StrEnum`, not `(str, Enum)`
- No class-body imports in Pydantic models
