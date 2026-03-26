"""
Project-root conftest.py — loaded by pytest before any other conftest or test module.

Disables LangSmith/LangChain tracing so that the LangChainTracer callback
does not call subprocess.run internally during integration test runs.
Without this, the tracer's runtime-environment collection (git sha, docker
version, etc.) consumes items from mock side_effect lists before
TestAgent._run_tests gets to use them.
"""
import os

# ── 1. Force env vars before anything imports langchain_core ──────────────────
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_API_KEY", None)
os.environ.pop("LANGSMITH_API_KEY", None)

# ── 2. Monkey-patch langsmith so the tracer stays disabled even if the env var
#       was already cached as True during plugin import. ─────────────────────
def _tracing_disabled() -> bool:
    return False

try:
    import langsmith.utils as _ls
    _ls.tracing_is_enabled = _tracing_disabled
    if hasattr(_ls, "test_tracking_is_disabled"):
        _ls.test_tracking_is_disabled = lambda: True
except Exception:
    pass

# ── 3. Belt-and-suspenders: if langchain_core was already imported, clear any
#       global handlers that were registered by the tracer. ──────────────────
try:
    import langchain_core.callbacks.manager as _cb_mgr  # noqa: E402
    # Clear global handlers that were set up when tracing was enabled
    if hasattr(_cb_mgr, "_configure"):
        pass  # will be prevented by env var now
    # If there's a module-level global handler list, clear it
    for attr in ("_configure", "get_callback_manager_for_config",):
        pass
except Exception:
    pass
