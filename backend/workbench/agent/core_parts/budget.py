"""AgentCore errors and the per-command run budget."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Real
from typing import Any


class AgentCoreBusyError(RuntimeError):
    """Raised when a second control command races an active agent turn."""


class AgentCoreContinuationError(ValueError):
    """Raised when continuation would send an invalid message tail to the model."""


class AgentCoreBudgetError(ValueError):
    """Raised when a run budget cannot be enforced safely."""


@dataclass(frozen=True)
class AgentRunBudget:
    """Cooperative limits for one prompt/continue command."""

    max_steps: int | None = None
    timeout_s: float | None = None
    # The first repeat is answered with "already answered, stop inspecting"; at 2
    # the loop guard fired on that same call, so the model never saw it.
    max_consecutive_identical_tool_calls: int = 3

    @classmethod
    def from_value(
        cls,
        value: "AgentRunBudget | Mapping[str, Any] | None",
    ) -> "AgentRunBudget":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise AgentCoreBudgetError("budget must be a mapping")

        max_steps = value.get("max_steps")
        if max_steps is not None:
            if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
                raise AgentCoreBudgetError("max_steps must be a positive integer")

        timeout_s = value.get("timeout_s")
        if timeout_s is not None:
            if (
                isinstance(timeout_s, bool)
                or not isinstance(timeout_s, Real)
                or not math.isfinite(float(timeout_s))
                or float(timeout_s) <= 0
            ):
                raise AgentCoreBudgetError("timeout_s must be a positive finite number")

        max_consecutive_identical_tool_calls = value.get(
            "max_consecutive_identical_tool_calls", 3
        )
        if (
            isinstance(max_consecutive_identical_tool_calls, bool)
            or not isinstance(max_consecutive_identical_tool_calls, int)
            or max_consecutive_identical_tool_calls <= 0
        ):
            raise AgentCoreBudgetError(
                "max_consecutive_identical_tool_calls must be a positive integer"
            )

        return cls(
            max_steps=max_steps,
            timeout_s=float(timeout_s) if timeout_s is not None else None,
            max_consecutive_identical_tool_calls=max_consecutive_identical_tool_calls,
        )
