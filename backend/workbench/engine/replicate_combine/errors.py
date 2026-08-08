"""Stable runtime errors for the replicate-and-combine foundation."""

from __future__ import annotations


STABLE_FAILURE_REASONS = frozenset(
    {
        "REPLICATE_STRATEGY_FAILED",
        "REPLICATE_STRATEGY_EXCEPTION",
        "REPLICATE_ADAPTER_FAILED",
        "REPLICATE_ADAPTER_EXCEPTION",
    }
)


class ReplicateCombineError(ValueError):
    """A runtime request or evidence boundary was rejected."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class ReplicateExecutionError(ReplicateCombineError):
    """A registered strategy reported a stable, expected replicate failure."""


__all__ = ["STABLE_FAILURE_REASONS", "ReplicateCombineError", "ReplicateExecutionError"]
