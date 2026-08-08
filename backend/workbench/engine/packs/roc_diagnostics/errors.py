"""Stable errors for the score-only ROC diagnostics pack."""

from __future__ import annotations


class RocDiagnosticsPackError(ValueError):
    """A fail-closed, machine-readable ROC diagnostics input error."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"{reason_code}: {message}")


__all__ = ["RocDiagnosticsPackError"]
