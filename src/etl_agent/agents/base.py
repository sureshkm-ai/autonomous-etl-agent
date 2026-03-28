<<<<<<< HEAD
"""Base agent class — ReactAgent with LLM governance built in.

All concrete agents inherit from ReactAgent, which provides:
  - Structured LLM call wrapper with token tracking and prompt hashing
  - Model allow-list enforcement
  - Budget gate via RunTokenTracker.check_budget()
  - Consistent logging of every LLM invocation

Usage in a concrete agent::

    class MyAgent(ReactAgent):
        async def run(self, state: GraphState) -> dict[str, Any]:
            response, usage = await self._governed_llm_call(
                messages=[{"role": "user", "content": prompt}],
                agent_name="my_agent",
                tracker=state.get("token_tracker"),
            )
            return {"result": response}
"""
from __future__ import annotations

import abc
from typing import Any

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger
from etl_agent.core.llm_governance import (
    RunTokenTracker,
    TokenBudgetExceeded,
    compute_prompt_hash,
    estimate_cost_usd,
)

logger = get_logger(__name__)


class ReactAgent(abc.ABC):
    """Base class for all ETL agent nodes in the LangGraph pipeline.

    Concrete subclasses must implement ``run()``.  The governance helpers
    ``_governed_llm_call()`` and ``_check_model_allowed()`` are available to
    every subclass transparently.
    """

    # Subclasses may override to pin a specific model for their role.
    _default_agent_name: str = "agent"

    # -----------------------------------------------------------------------
    # Abstract interface
    # -----------------------------------------------------------------------

    @abc.abstractmethod
    async def run(self, state: Any) -> dict[str, Any]:  # type: ignore[type-arg]
        """Execute the agent node and return a partial GraphState update."""

    # -----------------------------------------------------------------------
    # Governance helpers
    # -----------------------------------------------------------------------

    def _check_model_allowed(self, model: str) -> str:
        """Return *model* if it is on the allow-list, else the fallback model.

        Logs a warning when a substitution is made so it appears in the audit
        log and is visible to the operator.
        """
        settings = get_settings()
        allowed = settings.approved_model_list
        if not allowed or model in allowed:
            return model
        fallback = settings.fallback_model or allowed[0]
        logger.warning(
            "model_not_allowlisted",
            requested_model=model,
            fallback_model=fallback,
            allowed_models=allowed,
        )
        return fallback

    async def _governed_llm_call(
        self,
        messages: list[dict[str, str]],
        *,
        agent_name: str | None = None,
        tracker: RunTokenTracker | None = None,
        attempt: int = 1,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Make an Anthropic API call with governance wrappers.

        Parameters
        ----------
        messages:    Anthropic messages array.
        agent_name:  Label attached to token-tracking records.
        tracker:     ``RunTokenTracker`` for the current pipeline run.
                     If *None*, token usage is still logged but not budgeted.
        attempt:     Retry attempt number (passed through to tracker).
        model:       Override the default model from settings.
        max_tokens:  Override the default max_tokens from settings.
        temperature: Override the default temperature from settings.

        Returns
        -------
        (response_text, usage_dict)
            ``usage_dict`` contains ``input_tokens``, ``output_tokens``,
            ``cost_usd``, and ``prompt_hash``.
        """
        import anthropic

        settings = get_settings()
        effective_model = self._check_model_allowed(model or settings.llm_model)
        effective_max_tokens = max_tokens or settings.llm_max_tokens
        effective_temperature = temperature if temperature is not None else settings.llm_temperature
        effective_agent = agent_name or self._default_agent_name

        # Hash the rendered prompt for provenance tracking
        prompt_text = " ".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )
        prompt_hash = compute_prompt_hash(prompt_text)

        logger.debug(
            "llm_call_start",
            agent=effective_agent,
            model=effective_model,
            prompt_hash=prompt_hash,
            attempt=attempt,
        )

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=effective_model,
            max_tokens=effective_max_tokens,
            temperature=effective_temperature,
            messages=messages,
        )

        response_text = response.content[0].text
        input_tokens: int = getattr(response.usage, "input_tokens", 0)
        output_tokens: int = getattr(response.usage, "output_tokens", 0)
        cost = estimate_cost_usd(effective_model, input_tokens, output_tokens)

        usage: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "prompt_hash": prompt_hash,
            "model": effective_model,
        }

        if tracker is not None:
            tracker.record_step(
                model=effective_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                agent_name=effective_agent,
                attempt=attempt,
                prompt_hash=prompt_hash,
            )
            try:
                tracker.check_budget()
            except TokenBudgetExceeded as exc:
                logger.error(
                    "token_budget_exceeded",
                    agent=effective_agent,
                    total_tokens=tracker.total_tokens,
                    budget=tracker.max_tokens,
                )
                raise
        else:
            # Log even without a tracker so we always have a record
            logger.info(
                "llm_call_complete_untracked",
                agent=effective_agent,
                model=effective_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
                prompt_hash=prompt_hash,
            )

        return response_text, usage

    # -----------------------------------------------------------------------
    # Convenience: keep backward-compat for agents that call _call_llm directly
    # -----------------------------------------------------------------------

    async def _call_llm(self, messages: list[dict]) -> str:
        """Simple LLM call without governance tracking (backward compatible).

        Prefer ``_governed_llm_call()`` in new code.
        """
        import anthropic

        settings = get_settings()
        model = self._check_model_allowed(settings.llm_model)
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            messages=messages,
        )
        return response.content[0].text

    # -----------------------------------------------------------------------
    # ReAct loop helpers  (used by concrete agents)
    # -----------------------------------------------------------------------
=======
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
>>>>>>> main

    async def react_llm_loop(
        self,
        *,
        initial_messages: list[dict],
<<<<<<< HEAD
        call_llm,
        validate,
        build_fix_message,
        agent_name: str = "",
        max_rounds: int = 3,
    ) -> str:
        """ReAct LLM loop: call → validate → fix → repeat.

        Parameters
        ----------
        initial_messages:   Initial message list to send to the LLM.
        call_llm:           Async callable(messages) → str.
        validate:           Callable(response) → (bool, error_str).
        build_fix_message:  Callable(response, error, attempt) → str fix message.
        agent_name:         Label for logging.
        max_rounds:         Maximum fix attempts (default 3).

        Returns
        -------
        The last raw LLM response string.
        """
        messages = list(initial_messages)
        raw = ""
        for attempt in range(1, max_rounds + 1):
            raw = await call_llm(messages)
            ok, err = validate(raw)
            if ok:
                return raw
            logger.warning(
                "react_llm_loop_fix",
                agent=agent_name,
                attempt=attempt,
                error=err[:200],
            )
            if attempt < max_rounds:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": build_fix_message(raw, err, attempt)},
                ]
        return raw  # Return best attempt even if still invalid
=======
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
>>>>>>> main

    async def react_tool_loop(
        self,
        *,
<<<<<<< HEAD
        action,
        max_attempts: int = 2,
        errors_to_catch: tuple = (Exception,),
        agent_name: str = "",
        action_name: str = "action",
    ):
        """ReAct tool loop: execute action with retry on transient errors.

        Parameters
        ----------
        action:          Async callable () → result.
        max_attempts:    Maximum execution attempts.
        errors_to_catch: Exception types to catch and retry.
        agent_name:      Label for logging.
        action_name:     Descriptive name of the action for logs.

        Returns
        -------
        The result of the successful action call.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await action()
            except errors_to_catch as exc:
                last_exc = exc
                logger.warning(
                    "react_tool_loop_retry",
                    agent=agent_name,
                    action=action_name,
                    attempt=attempt,
                    error=str(exc)[:200],
                )
=======
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

>>>>>>> main
        raise last_exc  # type: ignore[misc]
