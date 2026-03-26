"""LLM governance — token tracking, cost estimation, budget enforcement, prompt hashing.

Usage in an agent:
    tracker = RunTokenTracker(run_id=run_id, max_tokens=settings.max_tokens_per_run)
    # after each LLM call:
    tracker.record_step(model, input_tokens, output_tokens, agent_name, attempt, prompt_hash)
    tracker.check_budget()   # raises TokenBudgetExceeded if over limit
"""
from __future__ import annotations

import hashlib
from typing import Any

from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

# Approximate cost per 1M tokens (input_rate, output_rate) in USD.
# Update as Anthropic pricing changes.
_COST_PER_MTK: dict[str, tuple[float, float]] = {
    "claude-opus-4-6":           (15.00, 75.00),
    "claude-sonnet-4-6":         (3.00,  15.00),
    "claude-haiku-4-5-20251001": (0.80,   4.00),
}


class TokenBudgetExceeded(Exception):
    """Raised when a run's cumulative token usage exceeds its configured budget."""


def compute_prompt_hash(prompt: str) -> str:
    """Return the first 16 hex chars of the SHA-256 hash of the rendered prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD. Returns 0.0 for unrecognised models."""
    rates = _COST_PER_MTK.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * rates[0] + (output_tokens / 1_000_000) * rates[1]


class RunTokenTracker:
    """Accumulates token usage across all LLM calls within one pipeline run."""

    def __init__(self, run_id: str, max_tokens: int = 0) -> None:
        self.run_id = run_id
        self.max_tokens = max_tokens  # 0 means unlimited
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self._steps: list[dict[str, Any]] = []

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def record_step(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_name: str,
        attempt: int = 1,
        prompt_hash: str = "",
    ) -> None:
        """Record one LLM invocation and accumulate totals."""
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost
        self._steps.append({
            "agent": agent_name,
            "attempt": attempt,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
            "prompt_hash": prompt_hash,
        })
        logger.info(
            "llm_token_usage",
            run_id=self.run_id,
            agent=agent_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            cumulative_tokens=self.total_tokens,
            budget_pct=round(self.budget_pct(), 1),
        )

    def check_budget(self) -> None:
        """Raise TokenBudgetExceeded if over limit. No-op when max_tokens == 0."""
        if self.max_tokens > 0 and self.total_tokens > self.max_tokens:
            raise TokenBudgetExceeded(
                f"Run {self.run_id} exceeded token budget: "
                f"{self.total_tokens:,} tokens used, limit is {self.max_tokens:,}"
            )

    def budget_pct(self) -> float:
        """Return percentage of budget consumed. 0.0 when unlimited."""
        if self.max_tokens <= 0:
            return 0.0
        return (self.total_tokens / self.max_tokens) * 100.0

    def needs_approval(self, threshold_pct: float = 75.0) -> bool:
        """Return True when budget consumption exceeds the approval threshold."""
        return self.max_tokens > 0 and self.budget_pct() >= threshold_pct

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "budget_pct": round(self.budget_pct(), 1),
            "steps": self._steps,
        }
