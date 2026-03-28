---
name: ruff-clean
description: >
  ruff lint and format rules for this project. Use this skill whenever writing
  or editing any Python file — especially when writing exception handlers,
  context managers, imports, enums, or function signatures with unused arguments.
  Prevents the most common ruff errors from appearing in CI.
---

# Ruff Clean Code Patterns

These rules come from real ruff CI failures. The project runs `ruff check` and
`ruff format` on all Python files. Apply these patterns as you write code.

---

## Import ordering (I001 / isort)

Imports must follow this order, with a blank line between each group and no
blank lines within a group:

```python
# Group 1: stdlib (no blank lines within group)
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from typing import Any

# Group 2: third-party (blank line above)
import structlog
from fastapi import APIRouter
from pydantic import BaseModel

# Group 3: local (blank line above)
from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger
```

**Common mistake:** adding `from typing import Any` as a separate block after
`from datetime import datetime` with a blank line between them. Both are stdlib
— they must be in the same group.

---

## SIM105 — replace try/except pass with contextlib.suppress

```python
# ❌ Wrong
try:
    risky_operation()
except SomeError:
    pass

# ✅ Correct
import contextlib
with contextlib.suppress(SomeError):
    risky_operation()
```

---

## SIM117 — combine nested async with statements

```python
# ❌ Wrong
async with session.client("s3") as s3:
    async with session.client("sqs") as sqs:
        ...

# ✅ Correct
async with session.client("s3") as s3, session.client("sqs") as sqs:
    ...
```

---

## B904 — raise from original exception inside except blocks

```python
# ❌ Wrong — loses the original traceback
try:
    do_something()
except ValueError as e:
    raise MyError("failed") from None   # or just raise MyError(...)

# ✅ Correct — chains the exceptions
try:
    do_something()
except ValueError as e:
    raise MyError("failed") from e
```

---

## UP042 — use StrEnum instead of (str, Enum)

```python
# ❌ Wrong — UP042
from enum import Enum
class Status(str, Enum):
    ACTIVE = "active"

# ✅ Correct
from enum import StrEnum
class Status(StrEnum):
    ACTIVE = "active"
```

---

## ARG002 — unused method argument (fixture params)

For regular unused arguments, prefix with `_`:

```python
def handler(_signum: int, _frame: object) -> None:
    shutdown()
```

**Exception — pytest fixture parameters:** Never prefix fixture parameters with
`_`. Use `# noqa: ARG002` instead:

```python
async def test_something(
    self,
    mock_github,  # noqa: ARG002  ← activates side effects, not used directly
) -> None: ...
```

---

## UP017 — use `UTC` instead of `timezone.utc`

```python
# ❌ Wrong
from datetime import datetime, timezone
now = datetime.now(timezone.utc)

# ✅ Correct
from datetime import UTC, datetime
now = datetime.now(UTC)
```

---

## F841 — unused local variable

Either use the variable or suppress with `_`:

```python
# ❌ Wrong
result = compute()   # result never used

# ✅ Option A — remove it
compute()

# ✅ Option B — rename to indicate intentionally unused
_result = compute()
```

---

## W293 — whitespace on blank lines

Never leave trailing spaces on empty lines inside functions or classes. Most
editors handle this, but double-check generated code.

---

## E501 — line length

The project uses `line-length = 100` (not the ruff default of 88). This rule
is in the ignore list (`"E501"`) so long lines won't fail CI — but keep lines
under 100 characters for readability.

---

## Quick reference: enabled rule sets

```toml
select = ["E", "W", "F", "I", "B", "C4", "UP", "ARG", "SIM"]
ignore = ["E501", "B008", "B905"]
```

If you're unsure whether a pattern is flagged, check against these sets.
