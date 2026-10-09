"""Adapt shared model context to this pack's family-owned fit functions."""
from __future__ import annotations
from ...fit_support import _orch, _model_id, _record_fitted_kernel
from ....contracts.model.count_models import validate_glm_family_options

def _fit_poisson(ctx, env):
    model_id = _model_id(ctx, "poisson_1")
    poisson_x = ctx.artifacts["_poisson_x"]
    cat_all = ctx.artifacts.get("_categorical_vars") or set()
    poisson_cat = {v for v in cat_all if v in poisson_x}
    primary, fitted = _orch().run_poisson(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=poisson_x,
        model_id=model_id,
        exposure_col=ctx.exposure_col,
        categorical_x=poisson_cat,
    )
    return model_id, primary, fitted



def _fit_negative_binomial(ctx, env):
    options = ctx.artifacts.get("_model_options") or {}
    primary, fitted = _orch().run_negative_binomial(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="negative_binomial_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
        dispersion=options.get("dispersion", "mean"),
        alpha=options.get("alpha"),
    )
    # This owner fits beta first, followed by the estimated ancillary term.
    # Positions retain a real regressor named alpha, even with duplicate names.
    _record_fitted_kernel(ctx, fitted, model_id="negative_binomial_1",
        model_type="negative_binomial", param_positions=tuple(range(fitted.model.exog.shape[1])))
    return "negative_binomial_1", primary, fitted



def _fit_glm(ctx, env):
    options = ctx.artifacts.get("_model_options") or {}
    family = ctx.artifacts.get("_glm_family") or ""
    validate_glm_family_options(options, family)
    primary, fitted = _orch().run_glm(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="glm_1",
        family_name=family,
        categorical_x=ctx.artifacts.get("_categorical_vars"),
        alpha=options.get("alpha"),
    )
    # The packet stays `glm`; its kernel names the family, because what is
    # valid after the fit (and how it predicts) depends on the family.
    primary["kernel_family"] = f"glm:{primary.get('glm_family')}"
    return "glm_1", primary, fitted
