"""Errors shared by the contract layer and everything that validates against it."""

from __future__ import annotations


class OperationValidationError(RuntimeError):
    """Raised when a registered operation proposal is structurally invalid."""
