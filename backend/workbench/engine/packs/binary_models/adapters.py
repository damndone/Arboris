"""Adapt shared model context to this pack's family-owned fit functions."""
from __future__ import annotations
from ...fit_support import _orch, _model_id, _record_fitted_kernel
from ....contracts.model.count_models import validate_glm_family_options

def _fit_logit(ctx, env):
    model_id = _model_id(ctx, "logit_1")
    primary, fitted = _orch().run_logit(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id=model_id,
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return model_id, primary, fitted



def _fit_probit(ctx, env):
    model_id = _model_id(ctx, "probit_1")
    primary, fitted = _orch().run_probit(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id=model_id,
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return model_id, primary, fitted
