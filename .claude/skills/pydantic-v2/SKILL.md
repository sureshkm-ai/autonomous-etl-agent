---
name: pydantic-v2
description: >
  Pydantic v2 and pydantic-settings v2 correct patterns. Use this skill whenever
  creating or editing any Pydantic model, settings class, or enum in this project.
  Prevents Pydantic v2 incompatibility errors, StrEnum mypy issues, and settings
  configuration mistakes before they reach CI.
---

# Pydantic v2 Patterns

These rules come from real CI failures caused by Pydantic v1 patterns that
silently broke under Pydantic v2. Apply them every time you touch a model or
settings class.

---

## 1. Settings configuration: SettingsConfigDict, not inner Config class

Pydantic v2 removed the `class Config:` inner class pattern from `BaseSettings`.

```python
# ❌ Wrong — Pydantic v1 pattern, errors in v2
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False

# ✅ Correct — Pydantic v2
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )
```

---

## 2. StrEnum: use `from enum import StrEnum`, not `(str, Enum)`

Python 3.11+ stdlib has `StrEnum`. mypy (with UP042 rule) rejects
`class Foo(str, Enum)`.

```python
# ❌ Wrong — triggers UP042 lint error
from enum import Enum
class RunStatus(str, Enum):
    PENDING = "PENDING"

# ✅ Correct
from enum import StrEnum
class RunStatus(StrEnum):
    PENDING = "PENDING"
```

---

## 3. No duplicate enum members that shadow str built-in methods

`StrEnum` values are already lowercase strings. If you define members whose
names match Python `str` built-in methods (`filter`, `join`, `cast`, `format`,
etc.), mypy correctly rejects them because they shadow inherited `str` methods.

```python
# ❌ Wrong — 'filter', 'join', etc. shadow str built-ins
class ETLOperation(StrEnum):
    FILTER = "filter"
    filter = "filter"   # alias that shadows str.filter — mypy error
    JOIN = "join"
    join = "join"       # shadows str.join — mypy error

# ✅ Correct — uppercase members only; values are already lowercase strings
class ETLOperation(StrEnum):
    FILTER = "filter"
    JOIN = "join"
    AGGREGATE = "aggregate"
```

If existing code uses `ETLOperation.filter`, update call sites to
`ETLOperation.FILTER`. The string value `"filter"` is unchanged.

---

## 4. No imports inside model class bodies

Pydantic v2 treats any statement inside a model class body as a potential field
definition. An import statement like `from uuid import UUID` inside the class is
interpreted as an unannotated field, causing a `PydanticUserError`.

```python
# ❌ Wrong
class RunResult(BaseModel):
    from uuid import UUID   # PydanticUserError!
    run_id: UUID

# ✅ Correct — all imports at module level
from uuid import UUID
from pydantic import BaseModel

class RunResult(BaseModel):
    run_id: UUID
```

---

## 5. Bare generics in field annotations

Under `disallow_any_generics`, bare `dict` and `list` in model fields are
rejected. Always supply type parameters.

```python
# ❌ Wrong
class DataSource(BaseModel):
    schema_hint: dict | None = None
    config: dict = Field(default_factory=dict)

# ✅ Correct
from typing import Any
from pydantic import BaseModel, Field

class DataSource(BaseModel):
    schema_hint: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
```

---

## 6. Derived properties in Settings

Use `@property` for derived settings values. mypy understands them correctly.

```python
class Settings(BaseSettings):
    github_owner: str = ""
    github_repo: str = ""

    @property
    def github_target_repo(self) -> str:
        """Combined owner/repo expected by GitHubTools."""
        return f"{self.github_owner}/{self.github_repo}"
```

---

## 7. model_post_init for computed field backfill

Use `model_post_init` (not `__init_subclass__` or validators) to backfill
computed fields after all fields are set:

```python
class TestResult(BaseModel):
    passed_tests: int = 0
    num_passed: int = 0   # legacy alias

    def model_post_init(self, __context: Any) -> None:
        if self.passed_tests == 0 and self.num_passed:
            object.__setattr__(self, "passed_tests", self.num_passed)
```

Use `object.__setattr__` (not direct assignment) when the model is frozen.
