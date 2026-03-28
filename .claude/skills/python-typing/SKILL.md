---
name: python-typing
description: >
  Python type annotation best practices for projects using mypy strict mode,
  structlog, SQLAlchemy, and boto3. Use this skill whenever creating or editing
  any Python source file in src/ — especially when adding new classes, functions,
  fields, or third-party imports. Prevents the most common mypy and type-checker
  failures before they reach CI.
---

# Python Typing Best Practices

These rules are distilled from real CI failures. Apply them every time you write
or edit Python code in this project.

---

## 1. Always parameterise generics

mypy strict mode (`disallow_any_generics = true`) rejects bare container types.

| ❌ Wrong | ✅ Correct |
|---|---|
| `dict` | `dict[str, Any]` |
| `list` | `list[str]` or `list[Any]` |
| `tuple` | `tuple[str, int]` |
| `dict \| None` | `dict[str, Any] \| None` |

Import `Any` from `typing` when the value type is truly unknown:

```python
from typing import Any

def process(data: dict[str, Any]) -> list[Any]: ...
```

---

## 2. Use `import-untyped` not `import` in type: ignore comments

mypy 1.13+ distinguishes:
- `type: ignore[import-untyped]` — package exists but has no stubs
- `type: ignore[import-missing]` — package cannot be found at all
- `type: ignore[import]` (old catch-all) — triggers "unused ignore" in strict mode when the package DOES have stubs

**Rule:** when suppressing a missing-stub error, always use `[import-untyped]`:

```python
from github import Github  # type: ignore[import-untyped]
import aioboto3  # type: ignore[import-untyped]
```

If the package is already listed in the `[[tool.mypy.overrides]]`
`ignore_missing_imports = true` block in `pyproject.toml`, do NOT add any
`type: ignore` comment — it would become an "unused ignore" error.

---

## 3. SQLAlchemy declarative_base()

`declarative_base()` returns a class object, not a `DeclarativeMeta` instance.
Annotating `Base` as `DeclarativeMeta` makes mypy reject all ORM subclasses.

```python
# ❌ Wrong
from sqlalchemy.orm import DeclarativeMeta, declarative_base
Base: DeclarativeMeta = declarative_base()

# ✅ Correct
from typing import Any
from sqlalchemy.orm import declarative_base
Base: Any = declarative_base()
```

Alternatively, use SQLAlchemy 2.0's preferred pattern:

```python
from sqlalchemy.orm import DeclarativeBase
class Base(DeclarativeBase):
    pass
```

---

## 4. structlog vs stdlib logging

This project uses **structlog** for all structured logging. Never use
`logging.getLogger()` for module-level loggers — stdlib `Logger.debug()` and
friends do NOT accept arbitrary keyword arguments, so calls like
`logger.debug("event", run_id=x)` cause both a `call-arg` mypy error and a
runtime `TypeError`.

```python
# ❌ Wrong — stdlib logger can't accept extra kwargs
import logging
logger = logging.getLogger(__name__)
logger.debug("message", run_id=run_id)  # TypeError at runtime!

# ✅ Correct — structlog accepts any kwargs
from etl_agent.core.logging import get_logger
logger = get_logger(__name__)
logger.debug("message", run_id=run_id)  # works
```

`logging.basicConfig()` (configuration only) is still used in `main()` — fine.

---

## 5. Cast structlog return types

`structlog.get_logger()` is typed as returning `Any`. If your function declares
a return type of `structlog.BoundLogger`, mypy will complain. Use `cast`:

```python
from typing import cast
import structlog

def get_logger(name: str) -> structlog.BoundLogger:
    return cast(structlog.BoundLogger, structlog.get_logger(name))
```

---

## 6. Pydantic field validators — use `list[Any]`, not bare `list`

In Pydantic v2, `@field_validator` methods run in strict mode. Bare `list` in
the signature triggers `disallow_any_generics`:

```python
# ❌ Wrong
@field_validator("tags", mode="before")
@classmethod
def validate_tags(cls, v: list) -> list: ...

# ✅ Correct
@field_validator("tags", mode="before")
@classmethod
def validate_tags(cls, v: list[Any]) -> list[Any]: ...
```

---

## 7. Settings attributes must be declared before use

Any attribute accessed as `settings.some_attr` must be declared in the
`Settings` class in `src/etl_agent/core/config.py`. mypy will flag
`attr-defined` errors for undeclared attributes even when the relaxed override
is active. Before writing code that accesses a settings attribute, check
`config.py`. If missing, add it with a sensible default:

```python
class Settings(BaseSettings):
    new_attribute: str = ""
    new_flag: bool = False
    new_url: str | None = None
```

---

## 8. Import order (stdlib before third-party)

ruff (isort) requires this order with a blank line between groups:

```python
# 1. stdlib — all in one group, no blank lines within
from datetime import datetime
from typing import Any

# 2. third-party — blank line above
from sqlalchemy.orm import declarative_base

# 3. local — blank line above
from etl_agent.core.config import get_settings
```

Never split stdlib imports into two groups with a blank line between them.
