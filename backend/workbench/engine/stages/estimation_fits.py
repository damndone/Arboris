"""Per-family fit adapters for the core estimation pack: pooled and grouped fits, weights, panel, IV, DID families and OLS."""

from __future__ import annotations

from ..fit_support import _orch, _model_id, _record_fitted_kernel
import math
from typing import Any
from pandas import RangeIndex
from ..inference_kernels import (
    record_inference_kernel,
    record_single_estimate_kernel,
    recorded_inference_kernel,
)
from ...contracts.model.inference_kernel import kernel_from_fitted
from ...econometrics.normalize import _public_term
from .estimation_survey import _apply_survey_design_variance, _survey_design_declared


# ---- handler adapters (each builds its model-specific kwargs from ctx) ----
# NB: every runner call goes through the orchestrator module (`_orch.run_X`)
# so existing tests that monkeypatch `workbench.orchestrator.run_panel_ols`,
# `run_logit`, etc. continue to work. Importing the runners directly here
# would bypass those monkeypatches.


def _fit_pooled(handler, ctx, env, handles, validation_error):
    """Multiple imputation: fit every dataset and pool (stages/mi_pooling.py)."""
    from ...combinators.multiple_imputation import MultipleImputationRefusal
    from .mi_pooling import fit_multiply_imputed, kernel_resolver

    resolve = kernel_resolver(
        ctx, handler.model_type, kernel_source=_kernel_source_packet,
        recorded=recorded_inference_kernel, public_name=_public_term,
    )
    try:
        return fit_multiply_imputed(handler, ctx, env, handles, kernel_for=resolve)
    except MultipleImputationRefusal as refusal:
        raise validation_error(
            f"MI_{refusal.code}", refusal.message,
            {"model_type": handler.model_type, "imputation_count": len(handles),
             "source_artifacts": [handle.artifact_id for handle in handles]},
        ) from refusal


def _fit_groups(handler, ctx, env, request, validation_error):
    """By-group execution: one fit per group (stages/by_group_fit.py)."""
    from ...combinators.by_group import ByGroupRefusal
    from .by_group_fit import fit_by_group
    from .mi_pooling import kernel_resolver

    design_declared = _survey_design_declared(ctx) or bool(str(ctx.artifacts.get("_sampling_weight") or "").strip())
    resolve = kernel_resolver(
        ctx, handler.model_type, kernel_source=_kernel_source_packet,
        recorded=recorded_inference_kernel, public_name=_public_term,
    )
    try:
        return fit_by_group(handler, ctx, env, dict(request), design_declared=design_declared, kernel_for=resolve)
    except ByGroupRefusal as refusal:
        raise validation_error(
            f"BY_GROUP_{refusal.code}", refusal.message,
            {"model_type": handler.model_type, "by_group": dict(request)},
        ) from refusal


def _validate_model_family_weights(
    model_type: str,
    *,
    frequency_weight: str,
    analysis_weight: str,
    sampling_weight: str,
) -> None:
    """Admit weights from the declared ModelFamilyContract only.

    The ordinary Run path used to special-case ``ols``.  That was safe for
    today's registry but made the contract fields descriptive rather than
    authoritative.  Keeping this lookup at the fit boundary makes every
    future family fail closed unless it explicitly declares the weight kind.
    """

    from ...contracts.model.family import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS.get(model_type)
    allowed = frozenset(contract.allows_weights) if contract is not None else frozenset()
    provided = {
        kind: column
        for kind, column in (
            ("frequency", frequency_weight),
            ("analysis", analysis_weight),
            ("sampling", sampling_weight),
        )
        if column
    }
    unsupported = sorted(set(provided) - allowed)
    if unsupported:
        allowed_text = ", ".join(sorted(allowed)) or "none"
        raise ValueError(
            "MODEL_WEIGHT_UNSUPPORTED: "
            f"model family {model_type} does not declare support for "
            f"{', '.join(unsupported)} weight(s); allowed: {allowed_text}"
        )


def _kernel_source_packet(result: dict[str, Any]) -> dict[str, Any]:
    """The packet whose sample size and fingerprint the kernel repeats.

    Envelope-style results (model packs, LMM) carry their figures one level
    down; reading the outer object would record no sample size.
    """
    for key in ("result", "payload"):
        nested = result.get(key)
        if isinstance(nested, dict) and "nobs" in nested:
            return nested
    return result


def _result_for_downstream(model_type: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return the result shape consumed by the pre-packet engine stages.

    LMM owns a versioned PacketEnvelope on disk.  Diagnostics, recording, and
    report stages predate packets and consume the public result payload shape.
    Passing an envelope through silently makes those stages default to OLS
    labels even though the model fit itself succeeded.  LMM uses the historical
    ``payload`` envelope; model packs use a public ``result`` payload.  Both
    forms are unwrapped here so every legacy consumer reads the same
    authoritative model identity.
    """

    if model_type != "linear_mixed_effects":
        nested = result.get("result")
        if isinstance(nested, dict) and isinstance(nested.get("model_type"), str):
            if nested["model_type"] != model_type:
                raise RuntimeError("MODEL_RESULT_PAYLOAD_INVALID")
            return nested
        return result

    from ...contracts.common.envelope import PacketEnvelope

    packet = PacketEnvelope.from_dict(result)
    if packet.contract != "linear_mixed_effects.result":
        raise RuntimeError("LMM_RESULT_CONTRACT_INVALID")
    payload = packet.to_dict()["payload"]
    if payload.get("model_type") != "linear_mixed_effects":
        raise RuntimeError("LMM_RESULT_PAYLOAD_INVALID")
    return payload


def _panel_covariance_request(ctx) -> tuple[str, str | None]:
    """Covariance and cluster column for a panel or DID fit (clustered by default)."""
    from ...cleaning import normalize_column_name
    from ...contracts.model.ols import effective_panel_covariance

    covariance, cluster = effective_panel_covariance(
        ctx.artifacts.get("_covariance"), ctx.artifacts.get("_model_options") or {}
    )
    return covariance, normalize_column_name(cluster) if cluster else None


def panel_effect_columns(ctx) -> tuple[str | None, str | None]:
    """The (entity, time) columns whose fixed effects a panel fit uses (stages/routing.py)."""
    columns = ctx.artifacts.get("_panel_effect_columns")
    if columns is not None:
        return columns
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    return (id_cands[0] if id_cands else None, t_cands[0] if t_cands else None)


def _fit_panel_ols(ctx, env):
    entity, time = panel_effect_columns(ctx)
    # The panel's time order (declared, else detected) indexes the fit and its
    # diagnostics even when it adds no fixed effects.
    t_cands = ctx.artifacts.get("_time_candidates") or []
    structure_time = time or (t_cands[0] if t_cands else None)
    covariance, cluster = _panel_covariance_request(ctx)
    primary, fitted = _orch().run_panel_ols(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        entity=entity,
        time=structure_time,
        time_effects=time is not None,
        model_id="panel_ols_1",
        covariance=covariance,
        cluster_col=cluster,
    )
    # NB: today's code does NOT store panel_ols fitted; preserve that, but hand
    # the stage its kernel so post-estimation does not need the fitted object.
    kernel = kernel_from_fitted(
        fitted, model_id="panel_ols_1", model_type="panel_ols",
        nobs=int(primary.get("nobs") or 0), public_name=_public_term,
    )
    if kernel is not None:
        record_inference_kernel(ctx, kernel)
    from ..panel_diagnostics import panel_evidence
    from ..completion_evidence import publish_completion_evidence

    diagnostics, positions, definition = panel_evidence(fitted, primary, ctx.data.frame,
        y=ctx.artifacts['_normalized_y'], x=ctx.artifacts['_normalized_x'],
        entity=entity, time=structure_time if fitted.model.dependent.index.names[1] == structure_time else None,
        cluster=cluster)
    publish_completion_evidence(ctx, env, primary, point_definition=definition,
        retained_positions=positions, diagnostics={'panel': diagnostics})
    return "panel_ols_1", primary, None


def _engine_request(ctx):
    """The estimation_engine argument, passed only when a run chose a non-default engine."""
    engine = ctx.artifacts.get("_estimation_engine")
    return {"estimation_engine": engine} if engine else {}


def _fit_iv_2sls(ctx, env):
    from ..iv_spec import validate_iv_spec
    endog = ctx.artifacts.get("_iv_endog") or []
    instruments = ctx.artifacts.get("_iv_instruments") or []
    exog = ctx.artifacts["_normalized_x"]
    y = ctx.artifacts["_normalized_y"]
    validate_iv_spec(y=y, exog=exog, endog=endog, instruments=instruments)
    def fit():
        return _orch().run_iv_2sls(
            ctx.data.frame,
            y=y,
            exog=exog,
            endog=endog,
            instruments=instruments,
            model_id="iv_2sls_1",
            covariance=ctx.artifacts.get("_covariance") or "robust",
            **_engine_request(ctx),
        )
    if ctx.artifacts.get("_estimation_engine") == "fast" and env.stop_reason is not None:
        from ...checks.ar_cancellation import cancellation_scope
        from ..interruptible import run_interruptible

        def owned_fit():
            env.checkpoint()
            with cancellation_scope(env.checkpoint):
                return fit()
        primary, fitted = run_interruptible(env, owned_fit, drain_on_cancel=True)
    else:
        primary, fitted = fit()
    return "iv_2sls_1", primary, fitted   # MUST return fitted (diagnostics needs it)


def _fit_did(ctx, env):
    from ..did_spec import normalize_did_input
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    norm = normalize_did_input(
        ctx.data.frame,
        mode=ctx.artifacts.get("_did_mode") or "cohort",
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        y=ctx.artifacts["_normalized_y"],
        cohort=ctx.artifacts.get("_did_cohort_col"),
        treat=ctx.artifacts.get("_did_treat_col"),
        post=ctx.artifacts.get("_did_post_col"),
        status=ctx.artifacts.get("_did_status_col"),
    )
    ctx.artifacts["_did_normalized"] = norm
    covariance, cluster = _panel_covariance_request(ctx)
    ctx.artifacts["_panel_covariance"] = (covariance, cluster)
    # The derived binary indicator enters the fitted design as float64.
    # Use that dtype for the fit so a numeric DID can avoid formula materialization.
    fit_frame = norm.frame.copy(deep=False)
    fit_frame["_did_D"] = norm.frame["_did_D"].astype("float64")
    primary, fitted = _orch().run_did(
        fit_frame,
        y=norm.y,
        x=ctx.artifacts["_normalized_x"],
        entity=norm.entity,
        time=norm.time,
        model_id="did_1",
        covariance=covariance,
        cluster_col=cluster,
    )
    return "did_1", primary, fitted   # MUST return fitted (diagnostics needs it)


def _fit_cs_did(ctx, env):
    from ..did_spec import normalize_did_input
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    norm = normalize_did_input(
        ctx.data.frame,
        mode=ctx.artifacts.get("_did_mode") or "cohort",
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        y=ctx.artifacts["_normalized_y"],
        cohort=ctx.artifacts.get("_did_cohort_col"),
        treat=ctx.artifacts.get("_did_treat_col"),
        post=ctx.artifacts.get("_did_post_col"),
        status=ctx.artifacts.get("_did_status_col"),
    )
    ctx.artifacts["_did_normalized"] = norm
    result = _orch().run_cs_did(
        norm,
        covariates=ctx.artifacts["_normalized_x"],
        control_group=ctx.artifacts.get("_cs_control_group") or "never",
        est_method=ctx.artifacts.get("_cs_est_method") or "dr",
        base_period=ctx.artifacts.get("_cs_base_period") or "varying",
        anticipation=int(ctx.artifacts.get("_cs_anticipation") or 0),
        cluster_var=ctx.artifacts.get("_cs_cluster_var") or None,
        honest_did=ctx.artifacts.get("_honest_did", False),
        progress=lambda message: env.progress("honest_did", message),
    )
    ctx.artifacts["_cs_did_result"] = result          # Task 12 (diagnostics) reads this
    simple = result["aggregations"]["simple"]
    primary = {
        "schema_version": 1, "model_id": "cs_did_1", "model_type": "cs_did", "nobs_basis": "units", "n_rows": int(len(norm.frame)),
        "engine": "workbench", "nobs": int(result["metadata"]["n_units"]),
        "r_squared": None,
        "coefficients": {"ATT": {
            "estimate": simple["overall"], "std_error": simple["overall_se"],
            "p_value": None, **_aggregate_interval(simple),
            "source_id": "model_results.cs_did_1.coefficients.ATT"}},
        "warnings": result["warnings"],
    }
    record_single_estimate_kernel(
        ctx, model_id="cs_did_1", model_type="cs_did", name="ATT",
        estimate=simple["overall"], std_error=simple["overall_se"], nobs=primary["nobs"],
    )
    return "cs_did_1", primary, None     # no fitted object; diagnostics reads _cs_did_result


def _aggregate_interval(simple):
    """The overall ATT's pointwise interval as the coefficient row carries it.

    The aggregation document already reports it; without this the row said
    "not reported" for an interval the same run had computed.
    """
    interval = simple.get("overall_pointwise_ci")
    if (
        isinstance(interval, (list, tuple)) and len(interval) == 2
        and all(isinstance(bound, (int, float)) and math.isfinite(bound) for bound in interval)
    ):
        return {"ci_lower": float(interval[0]), "ci_upper": float(interval[1])}
    return {}


def _fit_sa_did(ctx, env):
    from ..did_spec import normalize_did_input
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    norm = normalize_did_input(
        ctx.data.frame,
        mode=ctx.artifacts.get("_did_mode") or "cohort",
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        y=ctx.artifacts["_normalized_y"],
        cohort=ctx.artifacts.get("_did_cohort_col"),
        treat=ctx.artifacts.get("_did_treat_col"),
        post=ctx.artifacts.get("_did_post_col"),
        status=ctx.artifacts.get("_did_status_col"),
    )
    ctx.artifacts["_did_normalized"] = norm
    result = _orch().run_sa_did(
        norm,
        cluster_var=ctx.artifacts.get("_cs_cluster_var") or None,   # reuse the CS cluster channel
        honest_did=ctx.artifacts.get("_honest_did", False),
        progress=lambda message: env.progress("honest_did", message),
    )
    ctx.artifacts["_sa_did_result"] = result
    simple = result["aggregations"]["simple"]
    primary = {"schema_version": 1, "model_id": "sa_did_1", "model_type": "sa_did", "nobs_basis": "units", "n_rows": int(len(norm.frame)),
        "engine": "workbench", "nobs": int(result["metadata"]["n_units"]), "r_squared": None,
        "coefficients": {"ATT": {"estimate": simple["overall"], "std_error": simple["overall_se"],
            "p_value": None, **_aggregate_interval(simple),
            "source_id": "model_results.sa_did_1.coefficients.ATT"}},
        "warnings": result["warnings"]}
    record_single_estimate_kernel(
        ctx, model_id="sa_did_1", model_type="sa_did", name="ATT",
        estimate=simple["overall"], std_error=simple["overall_se"], nobs=primary["nobs"],
    )
    return "sa_did_1", primary, None


def _fit_dcdh(ctx, env):
    from ..dcdh_spec import normalize_treatment_path
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    norm = normalize_treatment_path(
        ctx.data.frame,
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        y=ctx.artifacts["_normalized_y"],
        treatment=ctx.artifacts.get("_dcdh_treatment_col"),
    )
    ctx.artifacts["_dcdh_normalized"] = norm
    result = _orch().run_dcdh(
        norm,
        cluster_var=ctx.artifacts.get("_cs_cluster_var") or None,   # reuse cluster channel
    )
    ctx.artifacts["_dcdh_result"] = result
    oa = result["overall_att"]
    primary = {"schema_version": 1, "model_id": "dcdh_1", "model_type": "dcdh", "nobs_basis": "units", "n_rows": int(len(norm.frame)),
        "engine": "workbench", "nobs": int(result["metadata"]["n_units"]), "r_squared": None,
        "coefficients": {"ATT": {"estimate": oa["estimate"], "std_error": oa["se"],
            "p_value": None, "source_id": "model_results.dcdh_1.coefficients.ATT"}},
        "warnings": result["warnings"]}
    record_single_estimate_kernel(
        ctx, model_id="dcdh_1", model_type="dcdh", name="ATT",
        estimate=oa["estimate"], std_error=oa["se"], nobs=primary["nobs"],
    )
    return "dcdh_1", primary, None


def _ols_robust_se_decision(ctx):
    """Record the ACTUAL standard-error choice for ols_1 (v1.7 honesty fix)."""
    from ... import graph_decision_factory as dpf

    if _survey_design_declared(ctx):
        method = "replicate" if str(ctx.artifacts.get("_survey_replicate_type") or "").strip() else "linearization"
        return dpf.ols_default_robust_se(variant=f"Design-based ({method})", explicit=True)
    covariance = (ctx.artifacts.get("_covariance") or "").strip()
    if covariance == "unadjusted":
        return dpf.ols_default_robust_se(variant="nonrobust", explicit=True)
    if covariance == "clustered":
        return dpf.ols_default_robust_se(variant="clustered", explicit=True)
    if covariance == "hac":
        return dpf.ols_default_robust_se(variant="HAC", explicit=True)
    return dpf.ols_default_robust_se(variant="HC1")


def _ols_covariance_plan(ctx) -> tuple[bool, str | None]:
    """Map the requested covariance onto run_ols arguments — honestly.

    v1.7 finding: `_fit_ols` used to hardcode robust=True, silently ignoring
    an explicit `unadjusted` or `clustered` request that the editable schema,
    rerun UI, and run_inputs.json all accepted. Every accepted value must now
    change the fit or fail closed.
    """
    covariance = (ctx.artifacts.get("_covariance") or "").strip() or "robust"
    if covariance == "hac" and (ctx.artifacts.get("_entity_col") or "").strip():
        raise ValueError(
            "OLS_HAC_WITH_CLUSTERS: HAC (Newey-West) standard errors cannot be combined with "
            "clustering; that is the Driscoll-Kraay estimator, which is not implemented yet."
        )
    if covariance == "clustered":
        from ...cleaning import normalize_column_name

        entity_raw = (ctx.artifacts.get("_entity_col") or "").strip()
        entity = normalize_column_name(entity_raw) if entity_raw else ""
        if not entity or entity not in ctx.data.frame.columns:
            raise ValueError(
                "OLS_CLUSTER_FIELD_MISSING: clustered covariance for OLS requires "
                "an entity field naming the cluster column."
            )
        return True, entity
    return covariance not in {"unadjusted", "hac"}, None


def _ols_weight_spec(ctx):
    frequency_weight = str(ctx.artifacts.get("_frequency_weight") or "").strip()
    analysis_weight = str(ctx.artifacts.get("_analysis_weight") or "").strip()
    sampling_weight = str(ctx.artifacts.get("_sampling_weight") or "").strip()
    if sampling_weight:
        # A declared design is now executed by the survey engine, so the only
        # remaining refusal is an undeclared one.  The former message told the
        # user to reach for `entity_col + covariance=clustered` instead, which is
        # a category error: a clustered covariance ignores the variance reduction
        # stratification buys and produces no design degrees of freedom.
        if not _survey_design_declared(ctx):
            raise ValueError(
                "OLS_SAMPLING_WEIGHT_UNSUPPORTED: sampling_weight requires a declared "
                "complex sampling design; supply survey_strata_col and/or "
                "survey_psu_col. A clustered covariance is not a substitute."
            )
        return {"kind": "sampling", "column": sampling_weight}
    if frequency_weight and analysis_weight:
        raise ValueError(
            "OLS_WEIGHT_SEMANTICS_CONFLICT: choose one of frequency_weight or analysis_weight"
        )
    if frequency_weight:
        return {"kind": "frequency", "column": frequency_weight}
    if analysis_weight:
        return {"kind": "analysis", "column": analysis_weight}
    return None


def _fit_ols(ctx, env):
    model_id = _model_id(ctx, "ols_1")
    robust, cluster_col = _ols_covariance_plan(ctx)
    from ...lineage.run_inputs import read_run_inputs

    try:
        persisted_form = (read_run_inputs(env.run_root).get("form") or {})
    except (FileNotFoundError, OSError, ValueError):
        persisted_form = {}
    requested_covariance = (ctx.artifacts.get("_covariance") or "").strip() or "robust"
    options = ctx.artifacts.get("_model_options") or {}
    hac_time_order = None
    if requested_covariance == "hac" and options.get("time_order"):
        from ...cleaning import normalize_column_name

        hac_time_order = normalize_column_name(str(options["time_order"]))
    # The fit and its result contract are one long pure call: stop waiting on cancel.
    from ..interruptible import run_interruptible

    primary, fitted = run_interruptible(env, lambda: _orch().run_ols(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        robust=robust,
        model_id=model_id,
        categorical_x=ctx.artifacts.get("_categorical_vars"),
        cluster_col=cluster_col,
        covariance=requested_covariance,
        covariance_explicit=bool((ctx.artifacts.get("_covariance") or "").strip()),
        dataset_snapshot={
            "upload_sha256": ctx.artifacts.get("_upload_hash", ""),
            "model_input_artifact": ctx.data.artifact_id,
        },
        # The runner already derives the same IDs for an unweighted RangeIndex.
        row_ids=(None if type(ctx.data.frame.index) is RangeIndex and all(
            ctx.artifacts.get(key) in (None, "")
            for key in ("_frequency_weight", "_analysis_weight", "_sampling_weight")
        ) else [str(value) for value in ctx.data.frame.index]),
        focal_x=persisted_form.get("focal_x"),
        primary_estimand=persisted_form.get("primary_estimand"),
        weights=_ols_weight_spec(ctx),
        fitted_sink=lambda covariance_fit: _record_fitted_kernel(
            ctx, covariance_fit, model_id=model_id, model_type="ols"
        ),
        hac_time_order=hac_time_order,
        hac_lags=options.get("hac_lags") if requested_covariance == "hac" else None,
    ))
    _apply_survey_design_variance(ctx, "ols", primary)
    if primary.get("nobs_subpopulation") is not None:
        # The fitted object describes every row, not the subpopulation; residual
        # diagnostics on it would describe the wrong sample.
        return model_id, primary, None
    return model_id, primary, fitted
