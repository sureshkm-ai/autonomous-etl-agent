---
name: pytest-patterns
description: >
  pytest fixture naming, markers, and test structure patterns for this project.
  Use this skill whenever creating or editing any file under tests/. Prevents
  the most common pytest failures: fixtures not injecting, missing unit markers
  causing exit code 5, and ARG002 lint errors breaking fixture injection.
---

# pytest Patterns

These rules come from real CI failures. Apply them every time you write or edit
test files.

---

## 1. Never prefix fixture parameter names with underscore

pytest matches fixtures by **exact parameter name**. If you rename a fixture
parameter to `_mock_github` to satisfy the ARG002 lint rule (unused argument),
pytest looks for a fixture called `_mock_github` — which doesn't exist — and
raises a fixture error.

```python
# ❌ Wrong — pytest can't find fixture "_mock_github"
async def test_pr_agent_creates_issue_and_pr(
    self,
    sample_etl_spec: ETLSpec,
    _mock_github,   # ARG002 "fix" that breaks fixture injection
) -> None: ...

# ✅ Correct — keep the original fixture name, suppress lint inline
async def test_pr_agent_creates_issue_and_pr(
    self,
    sample_etl_spec: ETLSpec,
    mock_github,  # noqa: ARG002
) -> None: ...
```

**Rule:** For pytest fixture parameters that are unused in the test body (but
needed to activate the fixture's side effects), always use `# noqa: ARG002`
instead of adding an underscore prefix.

---

## 2. Every test method needs @pytest.mark.unit

The CI runs `pytest -m unit`. Any test without `@pytest.mark.unit` is silently
excluded, and if NO tests are collected at all, pytest exits with code 5 (which
CI treats as a failure).

```python
# ❌ Wrong — test is silently excluded from CI
def test_something(self) -> None:
    assert True

# ✅ Correct
@pytest.mark.unit
def test_something(self) -> None:
    assert True
```

For async tests add both markers:

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_something(self) -> None: ...
```

---

## 3. Fixture scope and placement

- **Module-level fixtures** (shared across test classes in one file): define at
  module level in the test file itself, or in `tests/conftest.py` if shared
  across multiple files.
- **Integration test fixtures**: place in `tests/integration/conftest.py`.
- **Unit test fixtures**: place in the unit test file itself, or
  `tests/conftest.py` for broadly shared ones.

Never define a fixture in one file and try to use it in another without going
through `conftest.py`.

---

## 4. Mocking async vs sync correctly

When a real method is synchronous (returns a plain value), mock it with
`MagicMock`, not `AsyncMock`:

```python
# GitHubTools.create_issue returns str (sync)
mock_tools.create_issue.return_value = "https://github.com/org/repo/issues/42"

# Only use AsyncMock when the real method is async
mock_llm.ainvoke = AsyncMock(return_value=mock_response)
```

Mixing these causes `"object str can't be used in 'await' expression"` errors.

---

## 5. Fixture type annotations

Always annotate fixture return types so mypy is happy:

```python
@pytest.fixture
def sample_etl_spec() -> ETLSpec:
    return ETLSpec(...)

@pytest.fixture
def mock_github() -> Generator[MagicMock, None, None]:
    with patch("etl_agent.tools.github_tools.Github") as mock:
        yield mock
```

---

## 6. Markers must be declared in pyproject.toml

Any custom marker used in tests must be declared in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: fast isolated unit tests",
  "integration: integration tests with mocked external services",
]
```

---

## 7. GraphState keys in test fixtures

When building a `GraphState` dict in a test, include all keys the agent under
test will access. Missing keys in a `total=False` TypedDict cause `KeyError` at
test runtime, not at definition time:

```python
state: GraphState = {
    "etl_spec": sample_etl_spec,
    "run_id": uuid4(),
    "status": RunStatus.TESTING,
    "retry_count": 0,
    "max_retries": 2,        # required by route_after_tests
    "messages": [],          # required by base agent
    "awaiting_approval": False,
}
```
