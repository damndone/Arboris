"""Shared adapter mechanics, independent of model family names."""
from __future__ import annotations
from ..contracts.model.inference_kernel import kernel_from_fitted
from ..econometrics.normalize import _public_term
from .inference_kernels import record_inference_kernel

def _orch():
    from .. import orchestrator as _o
    return _o



def _model_id(ctx, default: str) -> str:
    """The result id a fit writes: the family's own, or a combinator's per-member id.

    By-group execution fits the same family once per group; each group's
    result, kernel, stable ids and source ids must carry the group's id.
    """
    override = ctx.artifacts.get("_model_id_override")
    return str(override) if override else default



def _record_fitted_kernel(ctx, fitted, *, model_id: str, model_type: str,
                          param_positions: tuple[int, ...] | None = None) -> None:
    """Record the kernel of the fit whose covariance the result reports."""
    kernel = kernel_from_fitted(
        fitted, model_id=model_id, model_type=model_type,
        nobs=int(getattr(fitted, "nobs", 0) or 0), public_name=_public_term,
        param_positions=param_positions,
    )
    if kernel is not None:
        record_inference_kernel(ctx, kernel)
