from __future__ import annotations

from typing import Any

from ..context import ModelingContext, RunEnv
from ..registry import (
    ModelHandler,
    MODEL_REGISTRY,
    register_model,
    set_default,
    resolve,
)


# ---- handler adapters (each builds its model-specific kwargs from ctx) ----
# NB: every runner call goes through the orchestrator module (`_orch.run_X`)
# so existing tests that monkeypatch `workbench.orchestrator.run_panel_ols`,
# `run_logit`, etc. continue to work. Importing the runners directly here
# would bypass those monkeypatches.

def _orch():
    from ... import orchestrator as _o
    return _o


def _fit_panel_ols(ctx, env):
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    primary, fitted = _orch().run_panel_ols(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        model_id="panel_ols_1",
    )
    # NB: today's code does NOT store panel_ols fitted; preserve that.
    return "panel_ols_1", primary, None


def _fit_probit(ctx, env):
    primary, fitted = _orch().run_probit(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="probit_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "probit_1", primary, fitted


def _fit_negative_binomial(ctx, env):
    primary, fitted = _orch().run_negative_binomial(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="negative_binomial_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "negative_binomial_1", primary, fitted


def _fit_glm(ctx, env):
    primary, fitted = _orch().run_glm(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="glm_1",
        family_name=(ctx.artifacts.get("_glm_family") or ""),
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "glm_1", primary, fitted


def _fit_logit(ctx, env):
    primary, fitted = _orch().run_logit(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        model_id="logit_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "logit_1", primary, fitted


def _fit_poisson(ctx, env):
    poisson_x = ctx.artifacts["_poisson_x"]
    cat_all = ctx.artifacts.get("_categorical_vars") or set()
    poisson_cat = {v for v in cat_all if v in poisson_x}
    primary, fitted = _orch().run_poisson(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=poisson_x,
        model_id="poisson_1",
        exposure_col=ctx.exposure_col,
        categorical_x=poisson_cat,
    )
    return "poisson_1", primary, fitted


def _fit_ols(ctx, env):
    primary, fitted = _orch().run_ols(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        robust=True,
        model_id="ols_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "ols_1", primary, fitted


# ---- core pack registration (dogfood the registry) ----
# Both auto-default names AND explicit aliases share the same handlers.
register_model(ModelHandler("panel_ols", "panel_ols_1", ("continuous",), _fit_panel_ols))
register_model(ModelHandler("probit", "probit_1", ("binary",), _fit_probit))
register_model(ModelHandler("negative_binomial", "negative_binomial_1", ("count",), _fit_negative_binomial))
register_model(ModelHandler("glm", "glm_1", ("count", "continuous", "binary"), _fit_glm))
register_model(ModelHandler("logit", "logit_1", ("binary",), _fit_logit))
# Explicit `poisson` and auto `poisson_rate` both route to the same handler.
register_model(ModelHandler("poisson_rate", "poisson_1", ("count",), _fit_poisson))
register_model(ModelHandler("poisson", "poisson_1", ("count",), _fit_poisson))
register_model(ModelHandler("ols", "ols_1", ("continuous",), _fit_ols))

set_default("continuous", "ols")
set_default("binary", "logit")
set_default("count", "poisson_rate")


# Prediction model types are dispatched by DiagnosticsStage as a supplementary
# step (sklearn-backed). For the primary estimation, they fall through to the
# y_type default, identical to legacy behavior.
_PREDICTION_PASSTHROUGH = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}


class EstimationStage:
    """Replaces the inline if/elif estimation block. Preserves the exact
    behavior, including the 1.5.3.2 contract: explicit model_type failure
    => structured `failed`, no silent OLS fallback."""

    name = "estimation"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Lazy imports to avoid circular deps with orchestrator helpers/state.
        from ...orchestrator import (
            _model_failure_details,
            _write_model_result,
            _write_manifest,
            _safe_flush_recorder,
            _lineage,
            _Y_TYPE_TO_ATTEMPTED_MODEL,
            dpf,
            WorkflowValidationError,
        )
        from ...artifacts import write_json
        from ...domain import GuardrailIssue, Severity

        model_type = ctx.requested_model_type or "auto"
        normalized_y = ctx.artifacts["_normalized_y"]
        normalized_x = ctx.artifacts["_normalized_x"]

        # Pre-compute poisson_x (must match original line 562-564 EXACTLY).
        poisson_x = list(normalized_x)
        if ctx.exposure_col:
            poisson_x = [v for v in normalized_x if v != ctx.exposure_col]
        ctx.artifacts["_poisson_x"] = poisson_x

        # Pre-check: panel_ols needs entity OR time (raise BEFORE try, propagates
        # to the outer _run_workflow handler — original behavior).
        id_cands = ctx.artifacts.get("_id_candidates") or []
        t_cands = ctx.artifacts.get("_time_candidates") or []
        if model_type == "panel_ols" and not id_cands and not t_cands:
            raise WorkflowValidationError(
                "PANEL_FIELDS_MISSING",
                "panel_ols requires entity or time.",
                {
                    "model_type": "panel_ols",
                    "has_entity": bool(id_cands),
                    "has_time": bool(t_cands),
                },
            )

        env.step("estimation", "start", f"Fitting {ctx.y_type} model (y type: {ctx.y_type})...")

        model_results: list[tuple[str, dict[str, Any]]] = []
        fitted_models: dict[str, Any] = {}
        _robust_se_dp = None

        issue_dicts = ctx.artifacts["_issue_dicts"]
        run_root = env.run_root
        run_id = env.run_id
        recorder = env.recorder
        model_input_ids = [ctx.data.artifact_id]

        # Build a resolve view: prediction model types fall through to the
        # y_type default identically to legacy behavior (they're dispatched
        # later by DiagnosticsStage).
        resolve_ctx = ctx
        if model_type in _PREDICTION_PASSTHROUGH:
            # Temporarily mask the requested type so resolve() picks the
            # y_type default. The original `model_type` is still used for
            # the explicit-vs-auto failure semantics below.
            from dataclasses import replace
            resolve_ctx = replace(ctx, requested_model_type="auto")

        try:
            handler = resolve(resolve_ctx)
            model_id, primary, fitted = handler.fit(ctx, env)
            _write_model_result(run_root, model_id, primary, inputs=model_input_ids)
            model_results.append((model_id, primary))
            if fitted is not None:
                fitted_models[model_id] = fitted
            # OLS path (auto-continuous OR explicit `ols`) records robust SE DP.
            if model_id == "ols_1":
                _robust_se_dp = dpf.ols_default_robust_se(variant="HC1")
        except ValueError as exc:
            # NB: WorkflowValidationError IS-A ValueError but we raised the only
            # pre-check above the try, so any ValueError here is a real fit failure.
            failure_evidence = _model_failure_details(
                model_type=(
                    model_type
                    if model_type != "auto"
                    else _Y_TYPE_TO_ATTEMPTED_MODEL.get(ctx.y_type, ctx.y_type)
                ),
                y=normalized_y,
                x=normalized_x,
                root_cause=str(exc),
                step="estimation",
            )
            failure_evidence["y_type"] = ctx.y_type
            if model_type != "auto":
                failure_evidence["requested_model_type"] = model_type

            issue_dicts.append(GuardrailIssue(
                Severity.BLOCKER if model_type != "auto" else Severity.WARNING,
                "MODEL_FIT_FAILED",
                str(exc),
                failure_evidence,
            ).to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            env.step("estimation", "blocked", f"Model fit failed: {exc}")

            if model_type != "auto":
                # 1.5.3.2 CONTRACT: explicit failure => structured `failed`.
                # NO silent OLS fallback.
                _write_manifest(
                    run_root,
                    run_id,
                    ctx.artifacts["_mode"],
                    "failed",
                    _lineage(ctx.artifacts["_input_files"]),
                    started_at=ctx.artifacts["_started_at"],
                    y=ctx.artifacts["_y"],
                    x=ctx.artifacts["_x"],
                    requested_model_type=model_type,
                )
                _safe_flush_recorder(recorder, context="failed@estimation")
                ctx.terminal_status = "failed"
                ctx.artifacts["_model_results"] = model_results
                ctx.artifacts["_fitted_models"] = fitted_models
                ctx.artifacts["_robust_se_dp"] = _robust_se_dp
                return ctx

            # Auto fallback: OLS.
            # Clear the auto model_type DP since it no longer applies.
            ctx.artifacts["_model_type_dp"] = None
            try:
                ols_result, ols_fitted = _orch().run_ols(
                    ctx.data.frame,
                    y=normalized_y,
                    x=normalized_x,
                    robust=True,
                    model_id="ols_1",
                    categorical_x=ctx.artifacts.get("_categorical_vars"),
                )
            except ValueError as ols_exc:
                # OLS fallback itself failed.
                issue_dicts.append(GuardrailIssue(
                    Severity.BLOCKER,
                    "MODEL_FIT_FAILED",
                    f"OLS fallback also failed: {ols_exc}",
                    _model_failure_details(
                        model_type="ols",
                        y=normalized_y,
                        x=normalized_x,
                        root_cause=str(ols_exc),
                        step="estimation",
                    ),
                ).to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})
                _write_manifest(
                    run_root,
                    run_id,
                    ctx.artifacts["_mode"],
                    "failed",
                    _lineage(ctx.artifacts["_input_files"]),
                    started_at=ctx.artifacts["_started_at"],
                    y=ctx.artifacts["_y"],
                    x=ctx.artifacts["_x"],
                    requested_model_type=model_type,
                )
                _safe_flush_recorder(recorder, context="failed@estimation")
                ctx.terminal_status = "failed"
                ctx.artifacts["_model_results"] = model_results
                ctx.artifacts["_fitted_models"] = fitted_models
                ctx.artifacts["_robust_se_dp"] = _robust_se_dp
                return ctx

            _robust_se_dp = dpf.ols_default_robust_se(variant="HC1")
            _write_model_result(run_root, "ols_1", ols_result, inputs=model_input_ids)
            model_results.append(("ols_1", ols_result))
            fitted_models["ols_1"] = ols_fitted
            ctx.y_type = "continuous"

        ctx.artifacts["_model_results"] = model_results
        ctx.artifacts["_fitted_models"] = fitted_models
        ctx.artifacts["_robust_se_dp"] = _robust_se_dp
        return ctx
