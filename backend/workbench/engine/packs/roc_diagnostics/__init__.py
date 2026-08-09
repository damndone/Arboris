"""Standalone, score-only ROC and classification diagnostics kernels."""

from typing import Any

from workbench.contracts.model.roc_diagnostics import (
    ROC_DIAGNOSTICS_FAILED,
    ROC_DIAGNOSTICS_REJECTED,
    make_error_envelope,
)

from .calibration import (
    compute_roc_calibration,
    evaluate_calibration,
    roc_calibration,
    run_roc_calibration,
)
from .common import _make_provenance
from .curve import compute_roc_curve, evaluate_roc, roc_curve, run_roc_curve
from .errors import RocDiagnosticsPackError


def run_roc_diagnostics(
    operation_id: str, y_true: Any, scores: Any, **kwargs: Any
) -> dict[str, Any]:
    """Dispatch only the two declared score-only ROC operations."""

    if type(operation_id) is not str or operation_id not in {
        "roc.curve",
        "roc.calibration",
    }:
        raise RocDiagnosticsPackError(
            "ROC_DIAGNOSTICS_UNKNOWN_OPERATION",
            "operation_id is not a declared ROC diagnostics operation",
        )
    try:
        if operation_id == "roc.curve":
            return run_roc_curve(y_true, scores, **kwargs)
        return run_roc_calibration(y_true, scores, **kwargs)
    except RocDiagnosticsPackError as exc:
        return make_error_envelope(
            operation_id=operation_id,
            status="rejected",
            reason_code=ROC_DIAGNOSTICS_REJECTED,
            error_code=exc.reason_code,
            message=exc.message,
            provenance=_make_provenance(
                None,
                metric_semantics="dispatcher_rejection",
            ),
        )
    except Exception:
        return make_error_envelope(
            operation_id=operation_id,
            status="failed",
            reason_code=ROC_DIAGNOSTICS_FAILED,
            error_code="ROC_DIAGNOSTICS_INTERNAL_ERROR",
            message="ROC diagnostics execution failed",
            provenance=_make_provenance(
                None,
                metric_semantics="dispatcher_failure",
            ),
        )


__all__ = [
    "RocDiagnosticsPackError",
    "compute_roc_calibration",
    "compute_roc_curve",
    "evaluate_calibration",
    "evaluate_roc",
    "roc_calibration",
    "roc_curve",
    "run_roc_calibration",
    "run_roc_curve",
    "run_roc_diagnostics",
]
