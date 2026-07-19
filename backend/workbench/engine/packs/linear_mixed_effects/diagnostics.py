"""Deterministic diagnostics for the locked linear mixed-effects recipe."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
)
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic


def _recovery_candidate() -> dict[str, object]:
    return {
        "action_id": LMM_RECOVERY_ACTION_ID,
        "operation_id": LMM_RECOVERY_OPERATION_ID,
        "patch": LMM_RECOVERY_PATCH,
        "required_confirmation": True,
    }


def classify_lmm_diagnostics(
    *,
    converged: bool,
    random_slope: bool,
    covariance_matrix: Sequence[Sequence[float]],
    residual_variance: float,
    blocking_code: str | None = None,
) -> list[LmmDiagnostic]:
    """Classify a recoverable random-slope covariance warning."""

    del residual_variance
    if blocking_code is not None:
        return [
            LmmDiagnostic(
                code=blocking_code,
                severity="error",
                status="blocked",
                evidence={},
                action_candidate=None,
            )
        ]
    if not converged:
        return [
            LmmDiagnostic(
                code="LMM_CONVERGENCE_FAILED",
                severity="error",
                status="failed",
                evidence={"optimizer": "lbfgs"},
                action_candidate=None,
            )
        ]
    matrix = np.asarray(covariance_matrix, dtype=float)
    if random_slope and matrix.shape == (2, 2):
        largest_eigenvalue = float(np.linalg.eigvalsh(matrix)[-1])
        slope_threshold = max(1e-8, 1e-6 * largest_eigenvalue)
        if float(matrix[1, 1]) <= slope_threshold:
            return [
                LmmDiagnostic(
                    code="LMM_RANDOM_SLOPE_NEAR_ZERO",
                    severity="warning",
                    status="complete",
                    evidence={
                        "slope_variance": float(matrix[1, 1]),
                        "threshold": slope_threshold,
                    },
                    action_candidate=_recovery_candidate(),
                )
            ]
    if matrix.ndim == 2 and matrix.shape[0] == matrix.shape[1]:
        eigenvalues = np.linalg.eigvalsh(matrix)
        largest_eigenvalue = float(eigenvalues[-1])
        threshold = max(1e-8, 1e-6 * largest_eigenvalue)
        if float(eigenvalues[0]) <= threshold:
            return [
                LmmDiagnostic(
                    code="LMM_RANDOM_EFFECTS_SINGULAR",
                    severity="warning",
                    status="complete",
                    evidence={
                        "smallest_eigenvalue": float(eigenvalues[0]),
                        "largest_eigenvalue": largest_eigenvalue,
                        "threshold": threshold,
                    },
                    action_candidate=(
                        _recovery_candidate() if random_slope else None
                    ),
                )
            ]
    return []
