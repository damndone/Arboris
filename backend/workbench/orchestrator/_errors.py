"""Orchestrator-level exceptions extracted from orchestrator
(V1.5.4.5, behavior-frozen). Re-exported from the package __init__ so
workbench.orchestrator.WorkflowValidationError keeps resolving for the
core driver and the estimation stage.
"""
from __future__ import annotations

from typing import Any


class WorkflowValidationError(ValueError):
    """Structured validation error with error code and evidence context.

    Raised when a workflow cannot proceed due to a known, diagnosable
    configuration or input issue (unsupported model, bad GLM family,
    etc.).  The error code and evidence are used to write a structured
    ``errors.json`` entry so the failure is machine-readable, not a
    generic ``WORKFLOW_FAILED``.
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.evidence = evidence or {}
