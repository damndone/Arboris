from __future__ import annotations

from .fit_support import (
    _formula_term,
    _ols_formula,
    _ensure_numeric_y,
    _ensure_numeric_x,
    _add_engine,
)
# Callers import every estimator from this module: the binary/count packs, the panel and IV
# estimators, and the OLS row helpers are re-exported here (F401 by design).
from ..engine.packs.binary_models.runner import run_logit, run_probit
from ..engine.packs.count_regression.runner import run_poisson, run_negative_binomial, run_glm

import os
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from .collinearity import dependent_columns, unidentified_columns, whole_terms
from .normalize import _json_safe_float, _public_term, normalize_statsmodels_result
from .optional_deps import require_optional_dependency
from .panel_design import panel_ols_model
from .ols_contract import (
    _linearmodels_term,
    _normalize_linearmodels_result,
    _python_scalar,
    _python_values,
    _row_id_values,
    _validate_cluster_group_values,
    _aligned_positions,
    _analysis_row_context,
    _attach_ols_result_contract,
)
from .ols_covariance import (
    _require_hac_time_order,
    _hac_plan,
    apply_ols_covariance,
    _normalize_ols_weight_spec,
    _frequency_weight_counts,
    _expand_rows_by_frequency,
)
from .panel_iv import (
    run_fixed_effects,
    _panel_covariance,
    _panel_covariance_warnings,
    _panel_estimation_rows,
    _cluster_panel_fit,
    run_panel_ols,
    run_iv_2sls,
)

# honest-DID (Rambachan-Roth ΔRM) production config. Module-level so tests can
# monkeypatch to a small grid for speed; run_cs_did reads them as globals.
HONEST_MBAR_GRID = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_GRID_POINTS = 1000
HONEST_SD_M_MULT = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_SD_SCALE_FLOOR = 1e-8
# Honest-DID's per-target LP/SLSQP paths are independent. Keep the production
# fan-out bounded so a long sensitivity run uses available CPU without creating
# an unbounded thread storm; tests may monkeypatch this module-level value.
HONEST_DID_WORKERS = max(1, min(4, os.cpu_count() or 1))


#: One indicator per level, held densely: 4,741 levels on 9,166 rows took 2.2 GB for one fit.
MAX_OLS_INDICATOR_COLUMNS = 1_000


def _refuse_oversized_dummies(frame: pd.DataFrame, x: list[str], categorical: set[str]) -> None:
    levels = {
        column: int(frame[column].nunique())
        for column in x
        if column in frame.columns and (column in categorical or not pd.api.types.is_numeric_dtype(frame[column]))
    }
    if sum(levels.values()) > MAX_OLS_INDICATOR_COLUMNS:
        named = ", ".join(f"{column} ({count})" for column, count in sorted(levels.items(), key=lambda item: -item[1]))
        raise ValueError(
            f"OLS_TOO_MANY_CATEGORY_LEVELS: these predictors would add {sum(levels.values())} indicator columns, above the "
            f"limit of {MAX_OLS_INDICATOR_COLUMNS}: {named}. Drop the column, group rare levels first, or absorb it as a panel fixed effect."
        )


def _columns_the_fit_reads(frame: pd.DataFrame, y: str, x: list[str], *optional: str | None) -> list[str]:
    """The formula's columns plus the weight and time-order columns, in frame order.

    A column the frame lacks is left for the formula to report, as before.
    """
    wanted = {y, *x, *(column for column in optional if column)}
    return [column for column in frame.columns if column in wanted]


def _fit_ols_formula(formula: str, data: pd.DataFrame, weight_kind: str | None, weight_column: str | None) -> Any:
    if weight_kind == "sampling":
        # A sampling weight means "this row represents w population units", so
        # the point estimate is weighted least squares -- the same arithmetic an
        # analysis weight produces.  What differs is the variance (see run_ols).
        sampling_weights = pd.to_numeric(data[weight_column], errors="coerce")
        return smf.wls(formula=formula, data=data, weights=sampling_weights).fit()
    if weight_kind == "analysis":
        # An analysis weight stays weighted least squares: it rescales each
        # row's contribution without claiming the row was observed more than
        # once, so nobs remains the row count.
        analysis_weights = pd.to_numeric(data[weight_column], errors="coerce")
        if (analysis_weights == 1).all():
            # Keep the unweighted numerical path byte-for-byte stable for the
            # identity case while still exposing that the declared weight was
            # validated and executed.
            return smf.ols(formula=formula, data=data).fit()
        return smf.wls(formula=formula, data=data, weights=analysis_weights).fit()
    # Unweighted, or a frequency weight already executed by expanding the
    # analysis rows.
    return smf.ols(formula=formula, data=data).fit()


def run_ols(
    frame: pd.DataFrame, y: str, x: list[str], robust: bool, model_id: str,
    categorical_x: set[str] | None = None,
    cluster_col: str | None = None,
    *,
    covariance: str | None = None,
    covariance_explicit: bool | None = None,
    dataset_snapshot: Any = None,
    row_ids: list[str] | tuple[str, ...] | None = None,
    cluster_row_ids: list[str] | tuple[str, ...] | None = None,
    focal_x: list[str] | tuple[str, ...] | str | None = None,
    primary_estimand: dict[str, Any] | None = None,
    weights: Any = None,
    intercept: bool = True,
    missing_policy: str = "statsmodels_patsy_drop_rows",
    solver_options: Any = None,
    fitted_sink: Any = None,
    hac_time_order: str | None = None,
    hac_lags: int | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    _refuse_oversized_dummies(frame, x, cat)
    weight_kind, weight_column, weight_values = _normalize_ols_weight_spec(frame, weights)
    frequency_counts: Any = None
    if weight_kind == "frequency":
        # A frequency weight declares "this row was observed w times".  The
        # only faithful execution is the dataset with each row physically
        # repeated w times: it makes nobs, residual degrees of freedom and
        # every covariance estimator correct by construction instead of
        # requiring a per-estimator correction factor.
        frequency_counts = _frequency_weight_counts(weight_values, weight_column)
        frame, row_ids, cluster_row_ids = _expand_rows_by_frequency(
            frame, frequency_counts, row_ids=row_ids, cluster_row_ids=cluster_row_ids
        )
    if cluster_col is not None and (cluster_col == y or cluster_col in x):
        raise ValueError(
            "OLS_CLUSTER_FIELD_CONFLICT: entity_col cannot be y or an OLS X/formula column."
        )
    if cluster_col is not None and cluster_col not in frame.columns:
        raise ValueError(
            "OLS_CLUSTER_FIELD_MISSING: clustered covariance for OLS requires "
            f"an entity field naming an existing cluster column (got {cluster_col!r})."
        )
    if covariance is None:
        covariance = "clustered" if cluster_col is not None else (
            "robust" if robust else "unadjusted"
        )
        if covariance_explicit is None:
            covariance_explicit = cluster_col is not None
    else:
        covariance = covariance.strip().lower()
        if covariance not in {"robust", "unadjusted", "clustered", "hac"}:
            raise ValueError(f"OLS_COVARIANCE_UNSUPPORTED: unsupported covariance {covariance!r}.")
        if covariance_explicit is None:
            covariance_explicit = True
        if covariance == "clustered" and cluster_col is None:
            raise ValueError(
                "OLS_CLUSTER_FIELD_MISSING: clustered covariance for OLS requires "
                "an entity field naming the cluster column."
            )
        robust = covariance == "robust"
    if cluster_col is not None and covariance == "hac":
        raise ValueError(
            "OLS_HAC_WITH_CLUSTERS: HAC (Newey-West) standard errors cannot be combined with "
            "clustering; that is the Driscoll-Kraay estimator, which is not implemented yet."
        )
    if cluster_col is not None and covariance != "clustered":
        raise ValueError(
            "OLS_CLUSTER_COVARIANCE_CONFLICT: entity_col requires covariance=clustered."
        )
    if covariance == "hac":
        _require_hac_time_order(frame, hac_time_order, y, x, weight_kind)
    if covariance == "clustered":
        robust = False
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    if covariance == "clustered":
        _validate_cluster_group_values(frame[cluster_col])
    model_frame = frame.loc[:, _columns_the_fit_reads(frame, y, x, weight_column, hac_time_order)].copy()
    if not frame.index.is_unique:
        # Patsy/statsmodels uses row labels for its model data. A positional
        # index makes duplicate input labels unambiguous without changing any
        # values, columns, formula, sample order, or point estimate.
        model_frame.index = pd.RangeIndex(len(model_frame), name="__ols_position__")
    if covariance == "hac":
        # Newey-West weights residual autocovariances by lag, so the rows must be
        # in time order. Sorting keeps the row labels, so every mapping back to
        # the input rows is unchanged; the point estimate does not depend on it.
        order_key = model_frame[hac_time_order]
        if not pd.api.types.is_numeric_dtype(order_key):
            order_key = pd.to_datetime(order_key, format="mixed", errors="coerce")
        model_frame = model_frame.iloc[np.argsort(order_key.to_numpy(), kind="mergesort")]
    normalized_weights: dict[str, Any] | None = None
    if weight_kind is not None:
        normalized_weights = {"kind": weight_kind, "column": weight_column, "executed": True}
    if weight_kind == "sampling":
        # The design-variance engine owns a sampling weight's variance, because
        # getting it right needs the strata and PSU structure this function never sees.
        normalized_weights["variance_owner"] = "survey_design_engine"
    original = _fit_ols_formula(formula, model_frame, weight_kind, weight_column)
    omitted_terms, not_identified_terms = [], []
    dependent = dependent_columns(original.model)
    if dependent:
        # Stata's rule: a term that adds nothing to the terms before it is
        # omitted and the rest is fitted on the same rows, instead of printing
        # pseudo-inverse numbers for terms the rows cannot identify.
        column_by_term = {_formula_term(column, column in cat): column for column in x}
        slices = original.model.data.design_info.term_name_slices
        for term in whole_terms(original.model, dependent):
            if term in column_by_term:
                constant = np.ptp(original.model.exog[:, slices[term]], axis=0).max() == 0
                omitted_terms.append({
                    "variable": column_by_term[term],
                    "term": _public_term(term),
                    "reason": "zero_variance" if constant else "perfect_collinearity",
                })
        omitted = {entry["variable"] for entry in omitted_terms}
        if omitted:
            rows = original.model.data.row_labels
            formula = _ols_formula(
                y, [_formula_term(column, column in cat) for column in x if column not in omitted] or ["1"]
            )
            original = _fit_ols_formula(formula, model_frame.loc[rows], weight_kind, weight_column)
    if dependent is None or dependent_columns(original.model):
        # What is left is a set of category levels that other terms determine;
        # Stata omits one level, which a formula term cannot, so every
        # coefficient the rows cannot pin down is named instead.
        names = list(original.model.exog_names)
        not_identified_terms = [_public_term(names[index]) for index in unidentified_columns(original.model)]
    hac: dict[str, Any] | None = None
    if covariance == "clustered":
        row_labels = getattr(original.model.data, "row_labels", None)
        row_positions, _ = _analysis_row_context(
            frame,
            row_labels,
            model_index=model_frame.index,
            row_ids=row_ids,
            cluster_row_ids=cluster_row_ids,
        )
        groups = frame.iloc[row_positions][cluster_col]
        group_values = [_python_scalar(value) for value in groups]
        if any(value is None for value in group_values):
            raise ValueError(
                "OLS_CLUSTER_VALUES_MISSING: entity_col contains null/NaN values "
                "on analysis rows."
            )
        _validate_cluster_group_values(groups)
        fitted = apply_ols_covariance(
            original, "clustered", groups=groups.to_numpy(copy=True)
        )
        model_type = "ols_clustered"
    elif covariance == "hac":
        hac = _hac_plan(original, model_frame, hac_time_order, hac_lags)
        fitted = apply_ols_covariance(original, "hac", hac_lags=hac["lags"])
        model_type = "ols_hac"
    elif robust:
        fitted = apply_ols_covariance(original, "robust")
        model_type = "ols_robust"
    else:
        fitted = original
        model_type = "ols"
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = model_type
    if omitted_terms:
        result["omitted_terms"] = omitted_terms
    if not_identified_terms:
        result["not_identified_terms"] = not_identified_terms
    result = _attach_ols_result_contract(
        result,
        fitted=fitted,
        original=original,
        frame=frame,
        y=y,
        x=x,
        categorical_x=cat,
        model_id=model_id,
        covariance=covariance,
        covariance_explicit=bool(covariance_explicit),
        cluster_col=cluster_col if covariance == "clustered" else None,
        hac=hac,
        model_index=model_frame.index,
        dataset_snapshot=dataset_snapshot,
        row_ids=row_ids,
        cluster_row_ids=cluster_row_ids,
        focal_x=focal_x,
        primary_estimand=primary_estimand,
        weights=normalized_weights,
        intercept=intercept,
        missing_policy=missing_policy,
        solver_options=solver_options or {"engine": "statsmodels", "method": "ols"},
    )
    if fitted_sink is not None:
        # The caller keeps receiving the plain fit (diagnostics need it); the
        # fit that carries the reported covariance goes to whoever records the
        # inference kernel, so post-estimation uses the same variance as the
        # standard errors on screen.
        fitted_sink(fitted)
    return _add_engine(result), original


def run_did(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    model_id: str,
    covariance: str = "clustered",
    cluster_col: str | None = None,
) -> tuple[dict[str, Any], Any]:
    """TWFE DID: y ~ 1 + _did_D + x... + EntityEffects + TimeEffects. The
    coefficient on _did_D is the ATT. Expects the canonical cohort frame from
    normalize_did_input (must contain _did_D). Standard errors cluster by
    unit unless another covariance is chosen (panel_inference)."""
    panel_module = require_optional_dependency(
        "linearmodels.panel", extra="panel", engine="linearmodels", model_type="did",
    )
    covariance = _panel_covariance(covariance, cluster_col)
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    cluster_source = cluster_col or entity
    if covariance == "clustered":
        data = _panel_estimation_rows(data, [y, "_did_D", *x], cluster_source)
    data = data.set_index([entity, time])

    model = panel_ols_model(panel_module, data, y=y, regressors=["_did_D", *x],
                            entity_effects=True, time_effects=True)
    if covariance == "clustered":
        fitted = model.fit(cov_type="unadjusted")
        fitted = _cluster_panel_fit(
            fitted, data, y=y, regressors=["_did_D", *x], entity_effects=True, time_effects=True,
            cluster_source=cluster_source,
        )
    else:
        fitted = model.fit(cov_type=covariance)
    return _normalize_linearmodels_result(
        fitted, model_id, "did", y_column=y, covariance=covariance, entity_col=entity, time_col=time,
        inference=getattr(fitted, "inference", None), warnings=_panel_covariance_warnings(covariance),
    ), fitted


def run_event_study(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    event_time_col: str,
    ref_period: int = -1,
    covariance: str = "clustered",
    cluster_col: str | None = None,
) -> dict[str, Any]:
    """Dynamic DID: regress y on event-time dummies (reference period omitted)
    under two-way FE. Returns the coefficient path keyed by event_time. Never-
    treated rows (NaN event_time) contribute to the FE baseline only."""
    panel_module = require_optional_dependency(
        "linearmodels.panel", extra="panel", engine="linearmodels", model_type="did",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    evt = data[event_time_col]
    distinct = evt.dropna().unique()
    if any(not float(v).is_integer() for v in distinct):
        raise ValueError(
            "DID_EVENT_TIME_NONINTEGER: event times must be whole periods; got "
            "fractional values"
        )
    event_values = sorted(int(v) for v in distinct if int(v) != ref_period)

    dummy_terms = []
    for k in event_values:
        col = f"_evt_{'m' if k < 0 else 'p'}{abs(k)}"
        data[col] = (evt == k).astype(float)
        dummy_terms.append(col)

    covariance = _panel_covariance(covariance, cluster_col)
    cluster_source = cluster_col or entity
    if covariance == "clustered":
        data = _panel_estimation_rows(data, [y, *dummy_terms, *x], cluster_source)
    data = data.set_index([entity, time])
    try:
        fitted = panel_ols_model(panel_module, data, y=y, regressors=[*dummy_terms, *x],
                                 entity_effects=True, time_effects=True).fit(
            cov_type="unadjusted" if covariance == "clustered" else covariance
        )
        if covariance == "clustered":
            fitted = _cluster_panel_fit(
                fitted, data, y=y, regressors=[*dummy_terms, *x], entity_effects=True, time_effects=True,
                cluster_source=cluster_source,
            )
    except Exception as exc:
        # A single treatment cohort (no timing variation) makes the event-time
        # indicators collinear with the time fixed effects, so PanelOLS reports
        # the event dummies as absorbed. Surface this as a structured, catchable
        # DID_ error so callers can skip the (unidentified) event study while
        # still reporting the ATT — rather than crashing the whole run.
        if "absorb" in str(exc).lower() or type(exc).__name__ == "AbsorbingEffectError":
            raise ValueError(
                "DID_EVENT_STUDY_UNIDENTIFIED: event-time indicators are collinear "
                "with the time fixed effects (e.g. a single treatment cohort, or the "
                "reference period is absent from the data); the dynamic event study "
                "is not identified."
            ) from exc
        raise

    coef, se, ci_lo, ci_hi = [], [], [], []
    conf = fitted.conf_int()
    for k in event_values:
        col = f"_evt_{'m' if k < 0 else 'p'}{abs(k)}"
        coef.append(_json_safe_float(fitted.params.get(col)))
        se.append(_json_safe_float(fitted.std_errors.get(col)))
        ci_lo.append(_json_safe_float(conf.loc[col, "lower"]))
        ci_hi.append(_json_safe_float(conf.loc[col, "upper"]))
    leads = [f"_evt_m{abs(k)}" for k in event_values if k < 0]
    inference = getattr(fitted, "inference", None)
    return {
        "event_time": event_values,
        "coef": coef, "se": se, "ci_lower": ci_lo, "ci_upper": ci_hi,
        "ref_period": ref_period,
        "covariance": covariance,
        "cluster_variable": inference.cluster_variable if inference is not None else None,
        "n_clusters": inference.n_clusters if inference is not None else None,
        "inference_distribution": "t" if inference is not None else "z",
        "effective_df": inference.df if inference is not None else None,
        # The pre-period leads' joint test needs their covariance, not only
        # their standard errors.
        "pre_period_terms": leads,
        "pre_period_estimates": [_json_safe_float(fitted.params.get(term)) for term in leads],
        "pre_period_covariance": (
            [[_json_safe_float(value) for value in row] for row in fitted.cov.loc[leads, leads].to_numpy()]
            if leads else []
        ),
    }


def _finalize_did_bundle(bundle, *, seed, B, alpha, honest_did, extra_metadata, progress=None):
    """Estimator-agnostic downstream for a DID EffectEstimateBundle: att_gt cell
    table, four aggregations + multiplier-bootstrap sup-t bands, warnings,
    metadata, opt-in honest-DID (ΔRM + ΔSD/FLCI), and the assembled result dict.
    Shared by run_cs_did and run_sa_did — the bundle is the seam, so this contains
    NO estimator-specific branch. estimator-specific metadata arrives via
    `extra_metadata` and is merged into `metadata`."""
    from ..engine.cs_aggregate import aggregate, _se
    from ..engine.cs_inference import multiplier_bootstrap
    import numpy as np

    G = bundle.influence_func.shape[0]
    row_cluster = bundle.aux["row_cluster"]
    n_clusters = int(np.unique(row_cluster).size)

    # --- per-cell att_gt table (se from the cell's IF column for valid cells) ---
    att_gt = []
    for k, m in enumerate(bundle.cell_metadata):
        col = bundle.influence_func[:, k]
        se = float(_se(col, row_cluster, G)) if m["valid"] else None
        att_gt.append({"g": float(m["g"]), "t": float(m["t"]),
            "event_time": float(m["event_time"]), "att": (float(bundle.estimates[k])
            if m["valid"] else None), "se": se, "n_treated": m["n_treated"],
            "n_control": m["n_control"], "valid": bool(m["valid"]),
            "warning": m.get("warning")})

    # --- four aggregations, each with bootstrap bands ---
    aggregations = {}
    agg_by_kind = {}
    for kind in ("simple", "dynamic", "group", "calendar"):
        agg = aggregate(bundle, kind)
        agg_by_kind[kind] = agg
        out = {"overall": agg["overall"], "overall_se": agg["overall_se"]}
        # overall band (single component)
        if agg["overall"] is not None and agg["overall_if"] is not None:
            ob = multiplier_bootstrap(np.asarray(agg["overall_if"]).reshape(G, 1),
                B=B, alpha=alpha, seed=seed, estimates=np.array([agg["overall"]]),
                clusters=row_cluster)
            out["overall_pointwise_ci"] = ob["pointwise_ci"][0].tolist()
            out["overall_uniform_band"] = ob["uniform_band"][0].tolist()
        # per-label estimates + simultaneous band over the labels
        labels = [float(x) for x in agg["label"]]
        if labels:
            lb = multiplier_bootstrap(agg["component_if"], B=B, alpha=alpha, seed=seed,
                estimates=np.asarray(agg["estimate"], dtype=float), clusters=row_cluster)
            out.update({
                "label_kind": {"simple": "none", "dynamic": "event_time",
                    "group": "cohort", "calendar": "period"}[kind],
                ("event_time" if kind == "dynamic" else "label"): labels,
                "estimate": [float(x) for x in agg["estimate"]],
                "se": [float(x) for x in agg["se"]],
                "pointwise_ci": lb["pointwise_ci"].tolist(),
                "uniform_band": lb["uniform_band"].tolist(),
                "uniform_crit": lb["uniform_crit"]})
        else:
            out.update({"label_kind": "none", "label": [], "estimate": [], "se": []})
        aggregations[kind] = out

    # --- unbalanced-panel aggregation-weight characterization (qualitative) ---
    # Estimator-agnostic: keys off diagnostics["balanced"] (set only by SA, and only
    # to False when some entity is missing some period). CS bundles never set the key
    # (.get returns None, `is False` → False), so CS stays golden 0-drift; SA balanced
    # bundles set True. Purely characterizes the boundary — NO quantified difference.
    if bundle.diagnostics.get("balanced") is False:
        aggregations["dynamic"]["interpretation_restrictions"] = [
            "This event-study uses did-style cohort-size (n_g) aggregation weights. "
            "In unbalanced panels this may differ from fixest::sunab's aggregation "
            "(which weights by observed counts per relative period)."
        ]

    # --- warnings ---
    warnings = []
    for oc in bundle.diagnostics.get("omitted_cells", []):
        warnings.append(f"Cell (g={oc['g']}, t={oc['t']}) omitted: {oc.get('warning')}")
    # single-cohort event times in the dynamic aggregation (thin support)
    dyn = agg_by_kind["dynamic"]
    for lab in dyn["label"]:
        cells = dyn["weights_used"][lab]["cells"]
        if len(cells) == 1:
            warnings.append(f"Event time {lab} is supported by a single cohort.")

    cohorts = sorted({m["g"] for m in bundle.cell_metadata})
    metadata = {**extra_metadata,
        "n_units": int(G), "n_clusters": n_clusters,
        "cluster_level": bundle.vcov_config.get("cluster_level", "entity"),
        "n_cohorts": len(cohorts),
        "n_valid_cells": int(sum(1 for m in bundle.cell_metadata if m["valid"])),
        "n_cells": len(bundle.cell_metadata), "B": B, "alpha": alpha, "seed": seed,
        "confidence_level": 1 - alpha, "band_type": "simultaneous"}

    # --- honest-DID (Rambachan-Roth ΔRM) sensitivity: opt-in, degrade-not-fail ---
    result_honest = None
    if honest_did:
        from ..engine.honest_did_adapter import honest_did_from_cs_dynamic
        try:
            hd = honest_did_from_cs_dynamic(
                agg_by_kind["dynamic"], row_cluster=row_cluster, n_total=G,
                mbar_grid=HONEST_MBAR_GRID, alpha=alpha,
                grid_points=HONEST_GRID_POINTS,
                m_mult=HONEST_SD_M_MULT, scale_floor=HONEST_SD_SCALE_FLOOR,
                progress=progress, workers=HONEST_DID_WORKERS)
        except Exception as exc:            # honest-DID must NEVER fail the run
            reason = f"HONEST_INTERNAL_ERROR: {exc}"
            hd = {"rm": {"status": "degraded", "reason": reason},
                  "sd": {"status": "degraded", "reason": reason}}
        # strip the _debug_* keys from the shipped artifact (test-only in engine layer)
        result_honest = {k: v for k, v in hd.items() if not k.startswith("_debug_")}

    return {"att_gt": att_gt, "aggregations": aggregations,
        "diagnostics": bundle.diagnostics, "warnings": warnings, "metadata": metadata,
        **({"honest_did": result_honest} if result_honest is not None else {})}


def run_cs_did(norm, *, covariates, control_group, est_method, base_period,
               anticipation, cluster_var, seed=20260615, B=1000, alpha=0.05,
               honest_did=False, progress=None):
    """Callaway-Sant'Anna group-time ATT end to end. Returns a structured dict:
    att_gt cell table, four aggregations (each with point estimates + analytical SE +
    multiplier-bootstrap pointwise/uniform bands), diagnostics, warnings, metadata.
    Pure (no I/O). Seed-deterministic."""
    from ..engine.cs_attgt import estimate_att_gt

    # v1.5.6 hardening — Fix #2: coerce/validate the outcome to numeric, mirroring
    # the other runners' `_ensure_numeric_y`. A string/object y otherwise reaches
    # a bare `dtype 'str' does not support operation 'mean'` TypeError that escapes
    # to WORKFLOW_FAILED; this raises the structured numeric-y ValueError instead
    # (caught by the estimation stage → MODEL_FIT_FAILED).
    norm.frame = _ensure_numeric_y(norm.frame, norm.y)

    bundle = estimate_att_gt(norm, control_group=control_group, est_method=est_method,
        base_period=base_period, anticipation=anticipation,
        covariates=list(covariates), cluster_var=cluster_var)
    md = {"control_group": control_group, "est_method": est_method,
          "base_period": base_period, "anticipation": anticipation,
          "covariates": list(covariates), "cluster_var": cluster_var}
    return _finalize_did_bundle(bundle, seed=seed, B=B, alpha=alpha,
                                honest_did=honest_did, extra_metadata=md,
                                progress=progress)


def run_sa_did(norm, *, cluster_var, seed=20260615, B=1000, alpha=0.05,
               honest_did=False, progress=None):
    """Sun-Abraham interaction-weighted event study end to end. Constructs the SA
    bundle then defers ENTIRELY to _finalize_did_bundle (estimator-slot validation)."""
    from ..engine.sa_attgt import estimate_sa
    norm.frame = _ensure_numeric_y(norm.frame, norm.y)
    bundle = estimate_sa(norm, cluster_var=cluster_var)
    md = {"estimator": "sun_abraham", "cluster_var": cluster_var}
    return _finalize_did_bundle(bundle, seed=seed, B=B, alpha=alpha,
                                honest_did=honest_did, extra_metadata=md,
                                progress=progress)


def _json_safe_dcdh(obj):
    """Recursively replace non-finite floats with None so the dCDH result dict is
    strictly JSON-serializable (json.dumps allow_nan=False)."""
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe_dcdh(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe_dcdh(v) for v in obj]
    return obj


def run_dcdh(norm, *, cluster_var, seed=20260622, B=1000, alpha=0.05):
    """de Chaisemartin-D'Haultfoeuille dynamic DID (binary non-absorbing, first-up
    switchers). Emits an EventStudyBundle; reuses multiplier_bootstrap for sup-t
    bands. Does NOT go through _finalize_did_bundle (that is (g,t)-bundle-specific)."""
    import numpy as np

    from ..engine.dcdh_estimator import estimate_dcdh
    from ..engine.cs_inference import multiplier_bootstrap
    from ..engine.cs_aggregate import _se

    norm.frame = _ensure_numeric_y(norm.frame, norm.y)
    b = estimate_dcdh(norm, cluster_var=cluster_var)
    N = int(b.aux["n_total"])
    row_cluster = b.aux["row_cluster"]
    est = np.asarray(b.estimates, dtype=float)

    boot = multiplier_bootstrap(b.influence_func, B=B, alpha=alpha, seed=seed,
                                estimates=est, clusters=row_cluster)
    se = [float(_se(b.influence_func[:, k], row_cluster, N)) for k in range(est.size)]

    ev = [float(e) for e in b.event_times]
    event_study = {
        "label_kind": "event_time",
        "event_time": ev,
        "estimate": [float(x) for x in est],
        "se": se,
        "pointwise_ci": boot["pointwise_ci"].tolist(),
        "uniform_band": boot["uniform_band"].tolist(),
        "uniform_crit": boot["uniform_crit"],
        "kind": list(b.labels),
        "n_switchers": [int(x) for x in b.n_switchers],
    }
    # overall ATT (secondary / experimental) = switcher-weighted mean of effect cols
    eff_idx = [k for k, e in enumerate(ev) if e >= 0]
    if eff_idx:
        w = np.array([b.n_switchers[k] for k in eff_idx], dtype=float)
        w = w / w.sum() if w.sum() else np.full(len(eff_idx), 1.0 / len(eff_idx))
        overall = float(np.dot(w, est[eff_idx]))
        overall_if = b.influence_func[:, eff_idx] @ w
        overall_se = float(_se(overall_if, row_cluster, N))
    else:
        overall, overall_se = None, None

    result = {
        "estimator": "dcdh",
        "event_study": event_study,
        "overall_att": {"estimate": overall, "se": overall_se, "experimental": True},
        "diagnostics": b.diagnostics,
        "honest_did": None,
        "honest_did_supported": False,
        "interpretation_restrictions": [
            "Non-absorbing binary treatment; event origin = first 0->1 switch. "
            "Units may switch back to 0 after the first up-switch (still included).",
            "baseline=1 units are excluded from both treatment and control in this version.",
        ],
        "warnings": [],
        "metadata": {"n_units": N, "estimator": "dcdh", "cluster_var": cluster_var},
    }
    return _json_safe_dcdh(result)


def run_time_series_diagnostics(
    frame: pd.DataFrame, y: str, time: str
) -> dict[str, float | None]:
    ordered = frame.sort_values(time)
    series = pd.to_numeric(ordered[y], errors="coerce")
    autocorrelation = series.autocorr(lag=1)
    if pd.isna(autocorrelation):
        autocorrelation = None
    return {
        "lag1_autocorrelation": None
        if autocorrelation is None
        else float(autocorrelation)
    }
