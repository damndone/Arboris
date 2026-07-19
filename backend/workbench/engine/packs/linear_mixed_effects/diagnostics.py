"""Deterministic diagnostics for the locked linear mixed-effects recipe."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from workbench.contracts.agent.repeated_measures import (
    LMM_RECOVERY_ACTION_ID,
    LMM_RECOVERY_OPERATION_ID,
    LMM_RECOVERY_PATCH,
)
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic

from .input import LmmInputError


def _recovery_candidate() -> dict[str, object]:
    return {
        "action_id": LMM_RECOVERY_ACTION_ID,
        "operation_id": LMM_RECOVERY_OPERATION_ID,
        "patch": LMM_RECOVERY_PATCH,
        "required_confirmation": True,
    }


def _convergence_failure() -> list[LmmDiagnostic]:
    """Use the existing locked terminal path for unsafe estimator facts."""

    return [
        LmmDiagnostic(
            code="LMM_CONVERGENCE_FAILED",
            severity="error",
            status="failed",
            evidence={"optimizer": "lbfgs"},
            action_candidate=None,
        )
    ]


def terminal_input_error_diagnostic(error: LmmInputError) -> LmmDiagnostic:
    """Map an existing input error into its pack-local terminal diagnostic fact."""

    return LmmDiagnostic(
        code=error.code,
        severity="error",
        status="blocked",
        evidence=error.evidence,
        action_candidate=None,
    )


def _valid_covariance_matrix(
    *,
    covariance_matrix: Sequence[Sequence[float]],
    residual_variance: float,
    random_slope: bool,
) -> np.ndarray | None:
    """Require finite, symmetric covariance facts before any recovery proposal."""

    try:
        residual = float(residual_variance)
        matrix = np.asarray(covariance_matrix, dtype=float)
    except (TypeError, ValueError):
        return None
    expected_shape = (2, 2) if random_slope else (1, 1)
    if (
        matrix.shape != expected_shape
        or not math.isfinite(residual)
        or residual < 0.0
        or not np.isfinite(matrix).all()
        or not np.array_equal(matrix, matrix.T)
    ):
        return None
    try:
        eigenvalues = np.linalg.eigvalsh(matrix)
    except np.linalg.LinAlgError:
        return None
    if not np.isfinite(eigenvalues).all():
        return None
    if np.any(np.diag(matrix) < 0.0) or float(eigenvalues[0]) < 0.0:
        return None
    return matrix


def classify_lmm_diagnostics(
    *,
    converged: bool,
    random_slope: bool,
    covariance_matrix: Sequence[Sequence[float]],
    residual_variance: float,
    blocking_code: str | None = None,
) -> list[LmmDiagnostic]:
    """Classify a recoverable random-slope covariance warning."""

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
        return _convergence_failure()
    matrix = _valid_covariance_matrix(
        covariance_matrix=covariance_matrix,
        residual_variance=residual_variance,
        random_slope=random_slope,
    )
    if matrix is None:
        return _convergence_failure()
    eigenvalues = np.linalg.eigvalsh(matrix)
    largest_eigenvalue = float(eigenvalues[-1])
    if random_slope:
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
