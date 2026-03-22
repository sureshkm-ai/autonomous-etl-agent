"""
ReactAgent base class — implements the Observe → Reason → Act loop.

Every agent in the pipeline inherits from this class and gets:

  react_llm_loop()
    Multi-turn LLM conversation where validation failures are fed back as
    observations so the model can self-correct.  Used by agents that produce
    structured outputs (JSON, Python code).

  react_tool_loop()
    Retry wrapper for deterministic tool calls (GitHub API, S3, Airflow).
    On failure it logs the error and waits before retrying; no LLM involved.

Design
------
The React pattern (Reason + Act + Observe) maps to:
  Reason   — the initial prompt / error-enriched follow-up message
  Act      — calling the LLM or external tool
  Observe  — running the validator / catching the exception
  → cycle back until success or max_attempts exhausted
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

# Default caps — agents can override at the call site
DEFAULT_LLM_REACT_ATTEMPTS = 3
DEFAULT_TOOL_REACT_ATTEMPTS = 3
DEFAULT_TOOL_BACKOFF_BASE = 2.0   # seconds; doubles each retry


class ReactAgent:
    """
    Base class providing React-style loops for all pipeline agents.

    Subclasses should call ``self.react_llm_loop(...)`` inside their
    ``run()`` method instead of calling the LLM directly.
    """

    # ── LLM loop ──────────────────────────────────────────────────────────────

    async def react_llm_loop(
        self,
        *,
        initial_messages: list[dict],
        call_llm: Callable[[list[dict]], Coroutine[Any, Any, str]],
        validate: Callable[[str], tuple[bool, str]],
        build_fix_message: Callable[[str, str, int], str],
        max_attempts: int = DEFAULT_LLM_REACT_ATTEMPTS,
        agent_name: str = "agent",
    ) -> str:
        """
        Observe-Reason-Act loop for LLM-based generation.

        Parameters
        ----------
        initial_messages:
            Conversation history to start with (typically a single user msg).
        call_llm:
            Async callable ``(messages) -> raw_text``.
        validate:
            ``(raw_text) -> (is_valid: bool, error_detail: str)``.
            Return ``(True, "")`` on success.
        build_fix_message:
            ``(raw_response, error_detail, attempt) -> user_message_str``.
            Called when ``validate`` returns False; the result is appended as
            a new user turn so the LLM can self-correct.
        max_attempts:
            Total number of LLM calls (including the first).
        agent_name:
            Used in log messages only.

        Returns
        -------
        str
            The first raw_response that passes ``validate``.

        Raises
        ------
        RuntimeError
            If all attempts are exhausted without a valid response.
        """
        messages = list(initial_messages)
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "react_llm_attempt",
                agent=agent_name,
                attempt=attempt,
                max_attempts=max_attempts,
            )
            raw_response = await call_llm(messages)
            is_valid, error_detail = validate(raw_response)

            if is_valid:
                logger.info(
                    "react_llm_success",
                    agent=agent_name,
                    attempt=attempt,
                )
                return raw_response

            last_error = error_detail
            logger.warning(
                "react_llm_observation",
                agent=agent_name,
                attempt=attempt,
                error=error_detail,
            )

            if attempt < max_attempts:
                # Append the model's (bad) reply + a correction request
                messages = messages + [
                    {"role": "assistant", "content": raw_response},
                    {"role": "user", "content": build_fix_message(raw_response, error_detail, attempt)},
                ]

        raise RuntimeError(
            f"{agent_name}: all {max_attempts} React attempts failed. "
            f"Last error: {last_error}"
        )

    # ── Tool loop ─────────────────────────────────────────────────────────────

    async def react_tool_loop(
        self,
        *,
        action: Callable[[], Any],
        max_attempts: int = DEFAULT_TOOL_REACT_ATTEMPTS,
        backoff_base: float = DEFAULT_TOOL_BACKOFF_BASE,
        errors_to_catch: tuple[type[Exception], ...] = (Exception,),
        agent_name: str = "agent",
        action_name: str = "tool_call",
    ) -> Any:
        """
        Retry wrapper for deterministic tool / API calls.

        Implements exponential backoff.  Unlike the LLM loop there is no
        model involved — we just retry the same callable.

        Parameters
        ----------
        action:
            Zero-argument callable to execute — sync or async.
            If it returns a coroutine/awaitable it is automatically awaited;
            synchronous callables (e.g. PyGithub methods) are called directly.
        max_attempts:
            Total attempts (including the first).
        backoff_base:
            Seconds to wait before the first retry; doubles each time.
        errors_to_catch:
            Exception types that trigger a retry.  All others propagate.
        agent_name / action_name:
            Used in log messages only.

        Returns
        -------
        Any
            Whatever ``action()`` returns on success.

        Raises
        ------
        Exception
            Re-raises the last caught exception after all attempts fail.
        """
        last_exc: Exception | None = None
        wait = backoff_base

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "react_tool_attempt",
                    agent=agent_name,
                    action=action_name,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )
                result = action()
                if inspect.isawaitable(result):
                    result = await result
                logger.info(
                    "react_tool_success",
                    agent=agent_name,
                    action=action_name,
                    attempt=attempt,
                )
                return result
            except errors_to_catch as exc:
                last_exc = exc
                logger.warning(
                    "react_tool_observation",
                    agent=agent_name,
                    action=action_name,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < max_attempts:
                    logger.info(
                        "react_tool_waiting",
                        agent=agent_name,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, 60)

        raise last_exc  # type: ignore[misc]
