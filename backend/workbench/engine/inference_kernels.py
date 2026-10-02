"""How a model runtime hands its inference kernel to the estimation stage.

Most fitted objects expose ``params`` and ``cov_params()`` and the stage
extracts the kernel itself. A runtime records one explicitly when the fitted
object is not returned, or when its parameter names differ from the names the
result packet reports (an ordered model's relabelled cut-points, a multinomial
model's ``category:term`` keys).
"""

from __future__ import annotations

import math
from typing import Any

from ..contracts.model.inference_kernel import build_inference_kernel, validate_inference_kernel

_KEY = "_inference_kernels"


def record_inference_kernel(ctx: Any, kernel: dict[str, Any]) -> None:
    validate_inference_kernel(kernel)
    ctx.artifacts.setdefault(_KEY, {})[kernel["model_id"]] = kernel


def record_single_estimate_kernel(
    ctx: Any,
    *,
    model_id: str,
    model_type: str,
    name: str,
    estimate: Any,
    std_error: Any,
    nobs: int,
) -> None:
    """A one-parameter kernel for estimators that report a single aggregate.

    Aggregated treatment-effect estimators report one headline estimate and its
    standard error, not a coefficient vector with a joint covariance. A 1x1
    kernel is exact for that estimate; building a larger one from separate
    standard errors would invent zero covariances, so this stops at one.
    Nothing is recorded when the standard error is missing, and the stage then
    states that post-estimation is unavailable.
    """
    try:
        value, se = float(estimate), float(std_error)
    except (TypeError, ValueError):
        return
    if not (math.isfinite(value) and math.isfinite(se) and se >= 0):
        return
    record_inference_kernel(
        ctx,
        build_inference_kernel(
            model_id=model_id,
            model_type=model_type,
            param_names=[name],
            params=[value],
            vcov=[[se * se]],
            reference_distribution="z",
            df_resid=None,
            loglik=None,
            nobs=nobs,
            covariance_estimator=None,
            unavailable={"loglik": "This estimator aggregates effects; it is not fitted by maximum likelihood."},
        ),
    )


def recorded_inference_kernel(ctx: Any, model_id: str) -> dict[str, Any] | None:
    recorded = ctx.artifacts.get(_KEY)
    return recorded.get(model_id) if isinstance(recorded, dict) else None
