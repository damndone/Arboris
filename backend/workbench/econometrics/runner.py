from __future__ import annotations

from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from .normalize import _json_safe_float, normalize_statsmodels_result
from .optional_deps import require_optional_dependency

# honest-DID (Rambachan-Roth ΔRM) production config. Module-level so tests can
# monkeypatch to a small grid for speed; run_cs_did reads them as globals.
HONEST_MBAR_GRID = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_GRID_POINTS = 1000
HONEST_SD_M_MULT = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_SD_SCALE_FLOOR = 1e-8


def _formula_term(column: str, categorical: bool = False) -> str:
    quoted = f"Q({column!r})"
    if categorical:
        return f"C({quoted})"
    return quoted


def _ols_formula(y: str, terms: list[str]) -> str:
    return f"{_formula_term(y)} ~ {' + '.join(terms)}"


def _linearmodels_term(column: str) -> str:
    if column.isidentifier():
        return column
    return f"`{column.replace('`', '``')}`"


def _ensure_numeric_y(frame: pd.DataFrame, y: str) -> pd.DataFrame:
    series = frame[y]
    if pd.api.types.is_numeric_dtype(series):
        return frame
    converted = pd.to_numeric(series, errors="coerce")
    if converted.isna().all():
        cleaned = series.astype(str).str.replace(r"[$,€£¥\s%]", "", regex=True)
        converted = pd.to_numeric(cleaned, errors="coerce")
    if converted.isna().all():
        raise ValueError(
            f"Column '{y}' is non-numeric and could not be converted. "
            f"Check that the correct sheet, column, and transpose setting are selected."
        )
    frame[y] = converted
    return frame


def _ensure_numeric_x(frame: pd.DataFrame, x: list[str]) -> pd.DataFrame:
    for col in x:
        if col not in frame.columns:
            continue
        series = frame[col]
        if pd.api.types.is_numeric_dtype(series):
            continue
        converted = pd.to_numeric(series, errors="coerce")
        if converted.notna().sum() > 0:
            frame[col] = converted
    return frame


def _add_engine(result: dict[str, Any], *, engine: str = "statsmodels") -> dict[str, Any]:
    result["engine"] = engine
    return result


def _normalize_linearmodels_result(
    fitted: Any,
    model_id: str,
    model_type: str,
) -> dict[str, Any]:
    params = getattr(fitted, "params", {})
    std_errors = getattr(fitted, "std_errors", {})
    pvalues = getattr(fitted, "pvalues", {})
    coefficients: dict[str, dict[str, Any]] = {}

    items = params.items() if hasattr(params, "items") else enumerate(params)
    for label, estimate in items:
        term = str(label)
        p_value = _json_safe_float(
            pvalues.get(label) if hasattr(pvalues, "get") else None
        )
        coefficients[term] = {
            "estimate": _json_safe_float(estimate),
            "std_error": _json_safe_float(
                std_errors.get(label) if hasattr(std_errors, "get") else None
            ),
            "p_value": round(p_value, 6) if p_value is not None else None,
            "source_id": f"model_results.{model_id}.coefficients.{term}",
        }

    return {
        "schema_version": 1,
        "model_id": model_id,
        "model_type": model_type,
        "engine": "linearmodels",
        "nobs": int(getattr(fitted, "nobs")),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "coefficients": coefficients,
        "warnings": [],
    }


def _root_cause_suffix(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = type(exc).__name__
    return f" Root cause: {message[:200]}"


def run_ols(
    frame: pd.DataFrame, y: str, x: list[str], robust: bool, model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    original = smf.ols(formula=formula, data=frame).fit()
    fitted = original.get_robustcov_results(cov_type="HC1") if robust else original
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "ols_robust" if robust else "ols"
    return _add_engine(result), original


def run_logit(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.logit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"Logit model {model_id} failed to fit (possible perfect separation). "
            f"Try OLS (Linear Probability Model) instead."
        ) from exc
    if not getattr(fitted, "converged", True):
        raise ValueError(
            f"Logit model {model_id} did not converge. "
            f"Try OLS (Linear Probability Model) instead."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "logit"
    return _add_engine(result), fitted


def run_probit(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.probit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"Probit model {model_id} failed to fit. "
            f"Check binary outcome values and predictors.{_root_cause_suffix(exc)}"
        ) from exc
    if not getattr(fitted, "converged", True):
        raise ValueError(f"Probit model {model_id} did not converge.")
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "probit"
    return _add_engine(result), fitted


def run_poisson(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str,
    exposure_col: str | None = None,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    series = frame[y].dropna()
    if (series < 0).any():
        raise ValueError(
            f"Poisson model requires non-negative y, "
            f"but column '{y}' has negative values."
        )
    if not pd.api.types.is_numeric_dtype(series):
        raise ValueError(
            f"Poisson model requires numeric y, "
            f"but column '{y}' is non-numeric."
        )
    if not (series == series.astype(int)).all():
        raise ValueError(
            f"Poisson model requires integer y (counts), "
            f"but column '{y}' has non-integer values."
        )

    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])

    exposure_actually_used = False
    if exposure_col is not None and exposure_col in frame.columns:
        exposure_vals = frame[exposure_col].values
        if (exposure_vals <= 0).any():
            import warnings
            warnings.warn(
                f"Exposure column '{exposure_col}' contains non-positive values "
                f"(zeros or negatives). Falling back to standard Poisson "
                f"without exposure adjustment."
            )
            fitted = smf.poisson(formula=formula, data=frame).fit(disp=False, maxiter=100)
        else:
            from statsmodels.genmod.families import Poisson
            fitted = smf.glm(
                formula=formula, data=frame,
                family=Poisson(),
                exposure=exposure_vals,
            ).fit(disp=False, maxiter=100)
            exposure_actually_used = True
    else:
        fitted = smf.poisson(formula=formula, data=frame).fit(disp=False, maxiter=100)

    if not getattr(fitted, "converged", True):
        raise ValueError(
            f"Poisson model {model_id} did not converge."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    if exposure_actually_used:
        result["model_type"] = "poisson_rate"
        result["exposure_col"] = exposure_col
    else:
        result["model_type"] = "poisson"
    return _add_engine(result), fitted


def run_negative_binomial(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    series = frame[y].dropna()
    if (series < 0).any():
        raise ValueError(
            f"Negative Binomial model requires non-negative y, but '{y}' has negative values."
        )
    if not (series == series.astype(int)).all():
        raise ValueError(
            f"Negative Binomial model requires integer count y, but '{y}' has non-integer values."
        )
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.negativebinomial(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"Negative Binomial model {model_id} failed to fit.{_root_cause_suffix(exc)}"
        ) from exc
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "negative_binomial"
    return _add_engine(result), fitted


def run_glm(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    family_name: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    from statsmodels.genmod import families

    family_map = {
        "binomial": families.Binomial,
        "poisson": families.Poisson,
        "negative_binomial": families.NegativeBinomial,
    }
    family_cls = family_map.get(family_name)
    if family_cls is None:
        raise ValueError(f"Unsupported GLM family: {family_name}")
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.glm(formula=formula, data=frame, family=family_cls()).fit(maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"GLM model {model_id} failed to fit.{_root_cause_suffix(exc)}"
        ) from exc
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "glm"
    result["glm_family"] = family_name
    return _add_engine(result), fitted


def run_fixed_effects(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str | None,
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    cat = categorical_x or set()
    terms = [_formula_term(column, column in cat) for column in x]
    terms.append(f"C({_formula_term(entity)})")
    if time is not None:
        terms.append(f"C({_formula_term(time)})")
    fitted = smf.ols(formula=_ols_formula(y, terms), data=frame).fit()
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "fixed_effects"
    return _add_engine(result), fitted


def run_panel_ols(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str | None,
    time: str | None,
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    if entity is None and time is None:
        raise ValueError(
            "PANEL_FIELDS_MISSING: PanelOLS requires at least an entity or time field."
        )

    panel_module = require_optional_dependency(
        "linearmodels.panel",
        extra="panel",
        engine="linearmodels",
        model_type="panel_ols",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)

    index_cols: list[str] = []
    if entity is None:
        entity = "_panel_entity"
        data[entity] = "entity"
    index_cols.append(entity)
    if time is None:
        time = "_panel_time"
        data[time] = range(len(data))
    index_cols.append(time)
    data = data.set_index(index_cols)

    terms = ["1", *[_linearmodels_term(column) for column in x]]
    if index_cols[0] != "_panel_entity":
        terms.append("EntityEffects")
    if index_cols[1] != "_panel_time":
        terms.append("TimeEffects")
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(
        cov_type=covariance
    )
    return _normalize_linearmodels_result(fitted, model_id, "panel_ols"), fitted


def run_iv_2sls(
    frame: pd.DataFrame,
    y: str,
    exog: list[str],
    endog: list[str],
    instruments: list[str],
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    if not endog or not instruments:
        raise ValueError(
            "IV_SPEC_INCOMPLETE: IV2SLS requires endogenous variables and instruments."
        )

    iv_module = require_optional_dependency(
        "linearmodels.iv",
        extra="panel",
        engine="linearmodels",
        model_type="iv_2sls",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, [*exog, *endog, *instruments])

    rhs_terms = ["1", *[_linearmodels_term(column) for column in exog]]
    iv_terms = " + ".join(_linearmodels_term(column) for column in endog)
    instrument_terms = " + ".join(
        _linearmodels_term(column) for column in instruments
    )
    formula = (
        f"{_linearmodels_term(y)} ~ {' + '.join(rhs_terms)} "
        f"[{iv_terms} ~ {instrument_terms}]"
    )
    fitted = iv_module.IV2SLS.from_formula(formula, data=data).fit(
        cov_type=covariance
    )
    return _normalize_linearmodels_result(fitted, model_id, "iv_2sls"), fitted


def run_did(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    """TWFE DID: y ~ 1 + _did_D + x... + EntityEffects + TimeEffects. The
    coefficient on _did_D is the ATT. Expects the canonical cohort frame from
    normalize_did_input (must contain _did_D)."""
    panel_module = require_optional_dependency(
        "linearmodels.panel", extra="panel", engine="linearmodels", model_type="did",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    data = data.set_index([entity, time])

    terms = ["1", "_did_D", *[_linearmodels_term(c) for c in x],
             "EntityEffects", "TimeEffects"]
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(cov_type=covariance)
    return _normalize_linearmodels_result(fitted, model_id, "did"), fitted


def run_event_study(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    event_time_col: str,
    ref_period: int = -1,
    covariance: str = "robust",
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

    data = data.set_index([entity, time])
    terms = ["1", *dummy_terms, *[_linearmodels_term(c) for c in x],
             "EntityEffects", "TimeEffects"]
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    try:
        fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(
            cov_type=covariance
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
    return {
        "event_time": event_values,
        "coef": coef, "se": se, "ci_lower": ci_lo, "ci_upper": ci_hi,
        "ref_period": ref_period,
    }


def run_cs_did(norm, *, covariates, control_group, est_method, base_period,
               anticipation, cluster_var, seed=20260615, B=1000, alpha=0.05,
               honest_did=False):
    """Callaway-Sant'Anna group-time ATT end to end. Returns a structured dict:
    att_gt cell table, four aggregations (each with point estimates + analytical SE +
    multiplier-bootstrap pointwise/uniform bands), diagnostics, warnings, metadata.
    Pure (no I/O). Seed-deterministic."""
    from ..engine.cs_attgt import estimate_att_gt
    from ..engine.cs_aggregate import aggregate, _se
    from ..engine.cs_inference import multiplier_bootstrap
    import numpy as np

    # v1.5.6 hardening — Fix #2: coerce/validate the outcome to numeric, mirroring
    # the other runners' `_ensure_numeric_y`. A string/object y otherwise reaches
    # a bare `dtype 'str' does not support operation 'mean'` TypeError that escapes
    # to WORKFLOW_FAILED; this raises the structured numeric-y ValueError instead
    # (caught by the estimation stage → MODEL_FIT_FAILED).
    norm.frame = _ensure_numeric_y(norm.frame, norm.y)

    bundle = estimate_att_gt(norm, control_group=control_group, est_method=est_method,
        base_period=base_period, anticipation=anticipation,
        covariates=list(covariates), cluster_var=cluster_var)
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
    metadata = {"control_group": control_group, "est_method": est_method,
        "base_period": base_period, "anticipation": anticipation,
        "covariates": list(covariates), "cluster_var": cluster_var,
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
                m_mult=HONEST_SD_M_MULT, scale_floor=HONEST_SD_SCALE_FLOOR)
        except Exception as exc:            # honest-DID must NEVER fail the run
            reason = f"HONEST_INTERNAL_ERROR: {exc}"
            hd = {"rm": {"status": "degraded", "reason": reason},
                  "sd": {"status": "degraded", "reason": reason}}
        # strip the _debug_* keys from the shipped artifact (test-only in engine layer)
        result_honest = {k: v for k, v in hd.items() if not k.startswith("_debug_")}

    return {"att_gt": att_gt, "aggregations": aggregations,
        "diagnostics": bundle.diagnostics, "warnings": warnings, "metadata": metadata,
        **({"honest_did": result_honest} if result_honest is not None else {})}


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
