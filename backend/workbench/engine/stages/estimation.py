from __future__ import annotations

from ..fit_support import _orch
from ..packs.binary_models.adapters import _fit_logit, _fit_probit
from ..packs.count_regression.adapters import _fit_poisson, _fit_negative_binomial, _fit_glm

from collections.abc import Mapping
from typing import Any

from ..context import ModelingContext, RunEnv
from ..inference_kernels import recorded_inference_kernel
from ..pack import AnalysisPack, RerunAction, register_pack
from ...contracts.model.inference_kernel import resolve_inference_kernel
from ...econometrics.normalize import _public_term
from ..registry import (
    ModelHandler,
    ModelOptionsValidationError,
    resolve,
)
from ...contracts.model.ols import (
    OLS_MODEL_OPTIONS_CONTRACT,
    validate_did_model_options,
    validate_ols_model_options,
    validate_panel_ols_model_options,
)
from ...contracts.model.count_models import (
    NEGATIVE_BINOMIAL_MODEL_OPTIONS_CONTRACT,
    GLM_MODEL_OPTIONS_CONTRACT,
    validate_negative_binomial_model_options,
    validate_glm_model_options,
)
from .estimation_survey import _apply_survey_design_variance, _check_survey_composition
from .estimation_fits import (
    _fit_pooled,
    _fit_groups,
    _validate_model_family_weights,
    _kernel_source_packet,
    _result_for_downstream,
    _fit_panel_ols,
    _fit_iv_2sls,
    _fit_did,
    _fit_cs_did,
    _fit_sa_did,
    _fit_dcdh,
    _ols_robust_se_decision,
    _ols_weight_spec,
    _fit_ols,
)
from .estimation_records import (
    _persist_ols_contract_metadata,
    _persist_model_options_execution_binding,
    _write_design_precheck,
)


# ---- core pack registration (dogfood the registry) ----
# Built-in handlers reach MODEL_REGISTRY via the SAME AnalysisPack mechanism
# that third-party / future packs (Panel / DID / RDD / TimeSeries / ML) use.
# Both auto-default names AND explicit aliases share the same handlers; the
# explicit `poisson` alias and auto `poisson_rate` both route to _fit_poisson.
CORE_PACK = AnalysisPack(
    pack_id="core",
    model_handlers=[
        ModelHandler(
            "panel_ols",
            "panel_ols_1",
            ("continuous",),
            _fit_panel_ols,
            validate_model_options=validate_panel_ols_model_options,
            model_options_contract=OLS_MODEL_OPTIONS_CONTRACT,
        ),
        ModelHandler("probit", "probit_1", ("binary",), _fit_probit),
        ModelHandler("negative_binomial", "negative_binomial_1", ("count",), _fit_negative_binomial,
            validate_model_options=validate_negative_binomial_model_options,
            model_options_contract=NEGATIVE_BINOMIAL_MODEL_OPTIONS_CONTRACT),
        ModelHandler("glm", "glm_1", ("count", "continuous", "binary"), _fit_glm,
            validate_model_options=validate_glm_model_options,
            model_options_contract=GLM_MODEL_OPTIONS_CONTRACT),
        ModelHandler("logit", "logit_1", ("binary",), _fit_logit),
        ModelHandler("poisson_rate", "poisson_1", ("count",), _fit_poisson),
        ModelHandler("poisson", "poisson_1", ("count",), _fit_poisson),
        ModelHandler(
            "ols",
            "ols_1",
            ("continuous",),
            _fit_ols,
            validate_model_options=validate_ols_model_options,
            model_options_contract=OLS_MODEL_OPTIONS_CONTRACT,
        ),
        ModelHandler("iv_2sls", "iv_2sls_1", ("continuous",), _fit_iv_2sls),
        ModelHandler(
            "did",
            "did_1",
            ("continuous",),
            _fit_did,
            validate_model_options=validate_did_model_options,
            model_options_contract=OLS_MODEL_OPTIONS_CONTRACT,
        ),
        ModelHandler("cs_did", "cs_did_1", ("continuous",), _fit_cs_did),
        ModelHandler("sa_did", "sa_did_1", ("continuous",), _fit_sa_did),
        ModelHandler("dcdh", "dcdh_1", ("continuous",), _fit_dcdh),
    ],
    defaults_by_y_type={
        "continuous": "ols",
        "binary": "logit",
        "count": "poisson_rate",
    },
    rerun_actions=[
        RerunAction(
            key="iv_switch_to_ols",
            label="Switch to OLS",
            param_overrides={"model_type": "ols", "model_options": {}},
            applies_to=["iv_2sls"],
        ),
        RerunAction(
            key="did_switch_to_panel_ols",
            label="Switch to plain Panel FE",
            param_overrides={"model_type": "panel_ols", "model_options": {}},
            applies_to=["did"],
        ),
        RerunAction(
            key="cs_did_switch_to_did",
            label="Switch to classic DID",
            param_overrides={"model_type": "did", "model_options": {}},
            applies_to=["cs_did"],
        ),
    ],
)
register_pack(CORE_PACK)


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
        # Future model packs are declared explicitly and loaded idempotently.
        # Keep this immediately before handler resolution rather than relying on
        # process import order (the capability endpoint bootstraps separately).
        from ..packs.loader import bootstrap_builtin_packs

        bootstrap_builtin_packs()
        # Lazy imports to avoid circular deps with orchestrator helpers/state.
        from ...orchestrator import (
            _model_failure_details,
            _write_inference_kernel,
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
        from ...services.pinned_run_directory import LmmPersistenceError
        from ..packs.linear_mixed_effects.input import LmmInputError

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

        if model_type == "did" and (not id_cands or not t_cands):
            raise WorkflowValidationError(
                "DID_FIELDS_MISSING",
                "did requires both an entity and a time column.",
                {"model_type": "did", "has_entity": bool(id_cands), "has_time": bool(t_cands)},
            )

        if model_type == "cs_did" and (not id_cands or not t_cands):
            raise WorkflowValidationError(
                "CS_DID_FIELDS_MISSING",
                "cs_did requires both an entity and a time column.",
                {"model_type": "cs_did", "has_entity": bool(id_cands), "has_time": bool(t_cands)},
            )

        if model_type == "sa_did" and (not id_cands or not t_cands):
            raise WorkflowValidationError(
                "SA_DID_FIELDS_MISSING",
                "sa_did requires both an entity and a time column.",
                {"model_type": "sa_did", "has_entity": bool(id_cands), "has_time": bool(t_cands)},
            )

        if model_type == "dcdh" and (not id_cands or not t_cands):
            raise WorkflowValidationError(
                "DCDH_FIELDS_MISSING",
                "dcdh requires both an entity and a time column.",
                {"model_type": "dcdh", "has_entity": bool(id_cands), "has_time": bool(t_cands)},
            )

        env.step("estimation", "start", f"Fitting {ctx.y_type} model (y type: {ctx.y_type})...")

        model_results: list[tuple[str, dict[str, Any]]] = []
        fitted_models: dict[str, Any] = {}
        _robust_se_dp = None

        issue_dicts = ctx.artifacts["_issue_dicts"]
        run_root = env.run_root
        run_id = env.run_id
        recorder = env.recorder
        # With multiple imputation the model reads every imputed dataset.
        model_input_ids = list(ctx.artifacts.get("_model_input_ids") or [ctx.data.artifact_id])
        mi_handles = ctx.artifacts.get("_imputation_handles") or []
        mi_pooling_attempted = False
        by_group_request = ctx.artifacts.get("_by_group_request")
        by_group_attempted = False
        model_options = ctx.artifacts.get("_model_options", {})
        model_options_binding = ctx.artifacts.get("_model_options_binding")

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
            frequency_weight = str(ctx.artifacts.get("_frequency_weight") or "").strip()
            analysis_weight = str(ctx.artifacts.get("_analysis_weight") or "").strip()
            sampling_weight = str(ctx.artifacts.get("_sampling_weight") or "").strip()
            if frequency_weight and analysis_weight:
                raise WorkflowValidationError(
                    "WEIGHT_SEMANTICS_CONFLICT",
                    "choose one of frequency_weight or analysis_weight",
                    {
                        "model_type": handler.model_type,
                        "frequency_weight": frequency_weight,
                        "analysis_weight": analysis_weight,
                    },
                )
            # v1.8.7 A1-11 / A1-13: refuse combinations that would otherwise
            # succeed while answering a different question. Checked before the
            # weight-support gate so an incoherent pairing is reported as such,
            # rather than as a family that has not been wired up yet.
            _check_survey_composition(ctx, handler.model_type, sampling_weight)
            try:
                _validate_model_family_weights(
                    handler.model_type,
                    frequency_weight=frequency_weight,
                    analysis_weight=analysis_weight,
                    sampling_weight=sampling_weight,
                )
            except ValueError as exc:
                if sampling_weight and handler.model_type == "ols":
                    raise WorkflowValidationError(
                        "OLS_SAMPLING_WEIGHT_UNSUPPORTED",
                        "sampling_weight requires a declared strata/PSU design; "
                        "declare strata/PSU through the existing entity_col + "
                        "covariance=clustered channel",
                        {"model_type": handler.model_type, "sampling_weight": sampling_weight},
                    ) from exc
                raise WorkflowValidationError(
                    "MODEL_WEIGHT_UNSUPPORTED",
                    str(exc),
                    {
                        "model_type": handler.model_type,
                        "weight_kinds": [
                            kind
                            for kind, value in (
                                ("frequency", frequency_weight),
                                ("analysis", analysis_weight),
                                ("sampling", sampling_weight),
                            )
                            if value
                        ],
                    },
                ) from exc
            if model_options:
                if handler.validate_model_options is None:
                    raise ModelOptionsValidationError(
                        "MODEL_OPTIONS_UNSUPPORTED",
                        f"Model type {handler.model_type} does not declare model_options.",
                        {
                            "model_type": handler.model_type,
                            "provided_option_keys": sorted(model_options),
                        },
                    )
                try:
                    from ...model_options import (
                        ModelOptionsError,
                        verify_binding_owner_for_model_type,
                        verify_bound_model_options,
                    )

                    bound = verify_bound_model_options(
                        model_options, model_options_binding
                    )
                    assert bound.binding is not None
                    verify_binding_owner_for_model_type(
                        bound.binding, handler.model_type
                    )
                except ModelOptionsError as exc:
                    raise ModelOptionsValidationError(
                        exc.code,
                        str(exc),
                        {
                            "model_type": handler.model_type,
                            "provided_option_keys": sorted(model_options),
                        },
                    ) from exc
                try:
                    handler.validate_model_options(model_options)
                except ModelOptionsValidationError:
                    raise
                except (TypeError, ValueError) as exc:
                    raise ModelOptionsValidationError(
                        "MODEL_OPTIONS_INVALID_VALUE",
                        f"Model type {handler.model_type} rejected model_options: {exc}",
                        {
                            "model_type": handler.model_type,
                            "provided_option_keys": sorted(model_options),
                        },
                    ) from exc
            if handler.model_type == "linear_mixed_effects":
                if env.lmm_execution_admission is None:
                    raise ModelOptionsValidationError("LMM_EXECUTION_BINDING_REQUIRED", "LMM requires a live admission.")
            if len(mi_handles) > 1:
                mi_pooling_attempted = True
                fits = [_fit_pooled(handler, ctx, env, mi_handles, WorkflowValidationError)]
            elif by_group_request:
                by_group_attempted = True
                fits = _fit_groups(handler, ctx, env, by_group_request, WorkflowValidationError)
            else:
                fits = [handler.fit(ctx, env)]
            primary_inputs = ctx.artifacts.get("_primary_model_input_ids")
            if primary_inputs is not None:
                if not isinstance(primary_inputs, list) or not all(
                    isinstance(item, str) and item for item in primary_inputs
                ):
                    raise ValueError(
                        "_primary_model_input_ids must be a list of non-empty strings"
                    )
                model_input_ids = list(primary_inputs)
                ctx.artifacts["_model_input_ids"] = list(model_input_ids)
            for model_id, primary, fitted in fits:
                # LMM's registered PacketEnvelope is its sole model-result source;
                # never create a competing legacy ``model_results/*.json`` copy.
                if handler.model_type != "linear_mixed_effects":
                    _write_model_result(run_root, model_id, primary, inputs=model_input_ids)
                _write_inference_kernel(
                    run_root,
                    resolve_inference_kernel(
                        model_id=model_id,
                        # The packet may refine the handler's family (a Poisson fit
                        # with an exposure is `poisson_rate`); the kernel names
                        # what the packet names.
                        model_type=str(
                            primary.get("kernel_family") or primary.get("model_type") or handler.model_type
                        ),
                        primary=_kernel_source_packet(primary),
                        fitted=fitted,
                        recorded=recorded_inference_kernel(ctx, model_id),
                        public_name=_public_term,
                    ),
                    inputs=[model_id] if handler.model_type != "linear_mixed_effects" else list(model_input_ids),
                )
                if handler.model_type != "linear_mixed_effects":
                    _persist_model_options_execution_binding(
                        run_root,
                        model_type=handler.model_type,
                        model_options=model_options,
                        model_options_binding=model_options_binding,
                    )
                if model_id == "ols_1":
                    _persist_ols_contract_metadata(run_root, primary)
                model_results.append(
                    (model_id, _result_for_downstream(handler.model_type, primary))
                )
                if fitted is not None:
                    fitted_models[model_id] = fitted
                # OLS path (auto-continuous OR explicit `ols`) records robust SE DP.
                if model_id == "ols_1" or (by_group_attempted and handler.model_type == "ols"):
                    _robust_se_dp = _ols_robust_se_decision(ctx)
        except LmmInputError:
            if (
                handler.model_type == "linear_mixed_effects"
                and "_linear_mixed_effects_diagnostic" in ctx.artifacts
            ):
                # The runner has already durably recorded the sole
                # tombstone-bound blocked diagnostic.  Do not duplicate it in
                # generic lifecycle files.
                env.step("estimation", "blocked", "Linear Mixed Effects input blocked.")
                ctx.terminal_status = "blocked"
                ctx.artifacts["_model_results"] = model_results
                ctx.artifacts["_fitted_models"] = fitted_models
                ctx.artifacts["_robust_se_dp"] = _robust_se_dp
                return ctx
            raise
        except LmmPersistenceError:
            # The admitted worker owns the private lifecycle sink.  This stage
            # must never use generic errors.json/manifest fallback.
            raise
        except ValueError as exc:
            # NB: WorkflowValidationError IS-A ValueError but we raised the only
            # pre-check above the try, so any ValueError here is a real fit failure.
            is_model_options_error = isinstance(exc, ModelOptionsValidationError)
            structured_code = getattr(exc, "code", None)
            structured_evidence = getattr(exc, "evidence", None)
            is_structured_model_error = (
                isinstance(structured_code, str)
                and bool(structured_code)
                and isinstance(structured_evidence, Mapping)
            )
            if is_model_options_error:
                failure_evidence = {
                    **exc.evidence,
                    "y_type": ctx.y_type,
                    "requested_model_type": model_type,
                }
                issue_code = exc.error_code
            elif isinstance(exc, WorkflowValidationError):
                failure_evidence = {
                    **exc.evidence,
                    "y_type": ctx.y_type,
                    "requested_model_type": model_type,
                }
                issue_code = exc.error_code
            elif is_structured_model_error:
                failure_evidence = {
                    **dict(structured_evidence),
                    "impact": getattr(exc, "impact", None),
                    "recommended_actions": [
                        dict(item)
                        for item in getattr(exc, "recommended_actions", ())
                        if isinstance(item, Mapping)
                    ],
                    "y_type": ctx.y_type,
                    "requested_model_type": model_type,
                }
                issue_code = structured_code
            else:
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
                from ..recommended_actions import actions_for_model_fit_failure
                failure_evidence["recommended_actions"] = actions_for_model_fit_failure(
                    requested_model_type=model_type,
                    y_type=ctx.y_type,
                )
                issue_code = "MODEL_FIT_FAILED"

            issue_dicts.append(GuardrailIssue(
                Severity.BLOCKER if (model_type != "auto" or is_model_options_error or mi_pooling_attempted or by_group_attempted)
                else Severity.WARNING,
                issue_code,
                str(exc),
                failure_evidence,
            ).to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            env.step("estimation", "blocked", f"Model fit failed: {exc}")

            if model_type != "auto" or is_model_options_error or mi_pooling_attempted or by_group_attempted:
                # 1.5.3.2 CONTRACT: explicit failure => structured `failed`.
                # NO silent OLS fallback (nor a single-dataset fit for a
                # multiple-imputation request).
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
                    weights=_ols_weight_spec(ctx),
                )
            except ValueError as ols_exc:
                # OLS fallback itself failed.
                fallback_evidence = _model_failure_details(
                    model_type="ols",
                    y=normalized_y,
                    x=normalized_x,
                    root_cause=str(ols_exc),
                    step="estimation",
                )
                from ..recommended_actions import actions_for_model_fit_failure
                fallback_evidence["recommended_actions"] = actions_for_model_fit_failure(
                    requested_model_type="auto",
                    y_type=ctx.y_type,
                )
                issue_dicts.append(GuardrailIssue(
                    Severity.BLOCKER,
                    "MODEL_FIT_FAILED",
                    f"OLS fallback also failed: {ols_exc}",
                    fallback_evidence,
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

            _robust_se_dp = _ols_robust_se_decision(ctx)
            _write_model_result(run_root, "ols_1", ols_result, inputs=model_input_ids)
            _write_inference_kernel(
                run_root,
                resolve_inference_kernel(
                    model_id="ols_1",
                    model_type="ols",
                    primary=ols_result,
                    fitted=ols_fitted,
                    recorded=None,
                    public_name=_public_term,
                ),
                inputs=["ols_1"],
            )
            _persist_ols_contract_metadata(run_root, ols_result)
            model_results.append(("ols_1", ols_result))
            fitted_models["ols_1"] = ols_fitted
            ctx.y_type = "continuous"

        ctx.artifacts["_model_results"] = model_results
        ctx.artifacts["_fitted_models"] = fitted_models
        ctx.artifacts["_robust_se_dp"] = _robust_se_dp
        _write_design_precheck(ctx, env, model_results)
        return ctx


