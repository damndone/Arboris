from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from ....artifacts import register_artifact, write_json
from ....contracts.model.v186_model_families import (
    MultinomialResultContract,
    OrdinalDiagnosticsContract,
    OrdinalResultContract,
    QuantileRegressionResultContract,
    SurvivalEvidenceContract,
    V186_EXTERNAL_ORACLE_STATUS,
    V186_VALIDATION_LEVEL,
)
from ....contracts.model.multinomial_logit import MultinomialLogitRequest
from ....contracts.model.ordered_logit import OrderedLogitRequest
from ....contracts.model.quantile_regression import QuantileRegressionRequest
from ....contracts.model.survival import SurvivalCoxRequest
from ....contracts.common.envelope import ContractError as TypedContractError
from ....model_options import ModelOptionsContract
from ...registry import ModelHandler, ModelOptionsValidationError


MODEL_OPTIONS_VERSION = "v1.8.6"


def _options_contract(name: str) -> ModelOptionsContract:
    return ModelOptionsContract(
        producer_version=MODEL_OPTIONS_VERSION,
        input_contract_version=f"workbench.{name}.options.v1",
    )


def _validate_mapping(options: Mapping[str, Any], *, allowed: set[str], required: set[str] | None = None) -> None:
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ModelOptionsValidationError(
            "MODEL_OPTIONS_UNKNOWN_FIELD",
            f"model options contain unknown field(s): {', '.join(unknown)}",
            {"unknown_fields": unknown},
        )
    missing = sorted((required or set()) - set(options))
    if missing:
        raise ModelOptionsValidationError(
            "MODEL_OPTIONS_REQUIRED_FIELD",
            f"model options require: {', '.join(missing)}",
            {"required_fields": missing},
        )


def validate_ordinal_options(options: Mapping[str, Any]) -> None:
    _validate_mapping(options, allowed={"optimizer", "maxiter", "link", "outcome_order"})
    if "optimizer" in options and options["optimizer"] not in {"bfgs", "lbfgs"}:
        raise ModelOptionsValidationError("ORDINAL_OPTIMIZER_INVALID", "ordinal optimizer must be bfgs or lbfgs")
    if "link" in options and options["link"] not in {"logit", "probit"}:
        raise ModelOptionsValidationError("ORDINAL_LINK_INVALID", "ordinal link must be logit or probit")
    if "outcome_order" in options:
        order = options["outcome_order"]
        if (
            not isinstance(order, list)
            or len(order) < 3
            or any(not isinstance(level, str) or not level for level in order)
            or len(set(order)) != len(order)
        ):
            raise ModelOptionsValidationError(
                "ORDINAL_OUTCOME_ORDER_INVALID",
                "ordinal outcome_order must be a list of at least three unique non-empty labels",
            )
    if "maxiter" in options and (not isinstance(options["maxiter"], int) or not 50 <= options["maxiter"] <= 5000):
        raise ModelOptionsValidationError("ORDINAL_MAXITER_INVALID", "ordinal maxiter must be an integer between 50 and 5000")
    try:
        OrderedLogitRequest.from_mapping(options)
    except TypedContractError as exc:
        raise ModelOptionsValidationError("ORDINAL_REQUEST_INVALID", f"ordinal_logit request rejected: {exc}") from exc


def validate_multinomial_options(options: Mapping[str, Any]) -> None:
    _validate_mapping(options, allowed={"maxiter", "base_category"})
    if "maxiter" in options and (not isinstance(options["maxiter"], int) or not 50 <= options["maxiter"] <= 5000):
        raise ModelOptionsValidationError("MULTINOMIAL_MAXITER_INVALID", "multinomial maxiter must be an integer between 50 and 5000")
    if "base_category" in options and not isinstance(options["base_category"], str):
        raise ModelOptionsValidationError("MULTINOMIAL_BASE_CATEGORY_INVALID", "base_category must be a string label")
    try:
        MultinomialLogitRequest.from_mapping(options)
    except TypedContractError as exc:
        raise ModelOptionsValidationError("MULTINOMIAL_REQUEST_INVALID", f"multinomial_logit request rejected: {exc}") from exc


def validate_survival_options(options: Mapping[str, Any]) -> None:
    if "event_column" not in options or options.get("event_column") in (None, ""):
        raise ModelOptionsValidationError(
            "SURVIVAL_EVENT_REQUIRED",
            "survival model options require event_column",
            {"required_fields": ["event_column"]},
        )
    _validate_mapping(options, allowed={"event_column", "group_column", "entry_column", "ties"})
    for key in ("event_column", "group_column", "entry_column"):
        if key in options and (not isinstance(options[key], str) or not options[key]):
            raise ModelOptionsValidationError("SURVIVAL_COLUMN_INVALID", f"{key} must be a non-empty column name")
    if options.get("ties", "breslow") not in {"breslow", "efron"}:
        raise ModelOptionsValidationError("SURVIVAL_TIES_INVALID", "survival ties must be breslow or efron")
    try:
        SurvivalCoxRequest.from_mapping(options)
    except TypedContractError as exc:
        raise ModelOptionsValidationError("SURVIVAL_REQUEST_INVALID", f"survival_cox request rejected: {exc}") from exc


def validate_quantile_options(options: Mapping[str, Any]) -> None:
    _validate_mapping(options, allowed={"quantiles", "bootstrap_reps", "random_state"})
    quantiles = options.get("quantiles", [0.25, 0.5, 0.75])
    if not isinstance(quantiles, list) or not quantiles or any(not isinstance(q, (int, float)) or not 0 < float(q) < 1 for q in quantiles):
        raise ModelOptionsValidationError("QUANTILES_INVALID", "quantiles must be a non-empty list of values strictly between 0 and 1")
    if len(set(float(q) for q in quantiles)) != len(quantiles) or len(quantiles) > 7:
        raise ModelOptionsValidationError("QUANTILES_INVALID", "quantiles must be unique and contain at most seven values")
    reps = options.get("bootstrap_reps", 0)
    if not isinstance(reps, int) or not 0 <= reps <= 1000:
        raise ModelOptionsValidationError("QUANTILE_BOOTSTRAP_INVALID", "bootstrap_reps must be an integer between 0 and 1000")
    if "random_state" in options and (not isinstance(options["random_state"], int) or options["random_state"] < 0):
        raise ModelOptionsValidationError("QUANTILE_RANDOM_STATE_INVALID", "random_state must be a non-negative integer")
    try:
        QuantileRegressionRequest.from_mapping(options)
    except TypedContractError as exc:
        raise ModelOptionsValidationError("QUANTILE_REQUEST_INVALID", f"quantile_regression request rejected: {exc}") from exc


def _frame(ctx: Any, y: str, x: list[str], extra: list[str] | None = None) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    frame = ctx.data.frame
    extra_columns = list(extra or [])
    missing = [column for column in [y, *x, *extra_columns] if column not in frame.columns]
    if missing:
        raise ValueError(f"MODEL_INPUT_COLUMN_MISSING: {', '.join(missing)}")
    selected = frame[list(dict.fromkeys([y, *x, *extra_columns]))].copy()
    selected = selected.dropna(axis=0, how="any")
    if len(selected) < max(20, len(x) + 5):
        raise ValueError("MODEL_INPUT_TOO_SMALL_FOR_MODEL_FAMILY")
    target = selected[y]
    exog = selected[x].apply(pd.to_numeric, errors="raise")
    return selected, target, exog


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, pd.Series):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(item) for item in value.to_dict(orient="records")]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _validation_metadata() -> dict[str, str]:
    return {
        "level": V186_VALIDATION_LEVEL,
        "external_oracle": V186_EXTERNAL_ORACLE_STATUS,
    }


def _exp_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(np.exp(float(value)))
    except (TypeError, ValueError, OverflowError):
        return None
    return _json_safe(result)


def _fit_stats(result: Any, names: list[str]) -> dict[str, dict[str, float | None]]:
    params = np.asarray(result.params, dtype=float).reshape(-1)
    bse = np.asarray(getattr(result, "bse", np.full_like(params, np.nan)), dtype=float).reshape(-1)
    pvalues = np.asarray(getattr(result, "pvalues", np.full_like(params, np.nan)), dtype=float).reshape(-1)
    try:
        intervals = np.asarray(result.conf_int(), dtype=float)
    except Exception:
        intervals = np.full((len(params), 2), np.nan)
    return {
        name: {
            "estimate": _json_safe(params[index]),
            "std_error": _json_safe(bse[index]) if index < len(bse) else None,
            "p_value": _json_safe(pvalues[index]) if index < len(pvalues) else None,
            "ci_lower": _json_safe(intervals[index, 0]) if index < len(intervals) else None,
            "ci_upper": _json_safe(intervals[index, 1]) if index < len(intervals) else None,
        }
        for index, name in enumerate(names)
    }


def _persist_packet(env: Any, artifact_id: str, relative: str, payload: Mapping[str, Any], *, artifact_type: str = "model_diagnostic") -> None:
    path = env.run_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, _json_safe(dict(payload)))
    register_artifact(env.run_root, artifact_id, path, artifact_type, "model_families", ["cleaned_dataset"])


def _marginal_probability_effects(model: Any, params: Any, exog: pd.DataFrame, names: list[str], categories: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in names:
        step = max(float(exog[name].std()) * 0.01, 1e-4)
        plus = exog.copy()
        minus = exog.copy()
        plus[name] += step
        minus[name] -= step
        effect = (np.asarray(model.predict(params, exog=plus)) - np.asarray(model.predict(params, exog=minus))) / (2 * step)
        rows.append({"variable": name, "average_effect_by_category": {category: float(effect[:, index].mean()) for index, category in enumerate(categories)}})
    return rows


def _ordered_categories(target: pd.Series, options: Mapping[str, Any]) -> list[str]:
    raw = target.astype(str)
    observed = set(raw.unique().tolist())
    requested = options.get("outcome_order")
    if requested is not None:
        order = [str(level) for level in requested]
        if set(order) != observed:
            raise ModelOptionsValidationError(
                "ORDINAL_OUTCOME_ORDER_MISMATCH",
                "outcome_order must contain every observed ordered outcome level exactly once",
                {"outcome_order": order, "observed_levels": sorted(observed)},
            )
        return order
    if isinstance(target.dtype, pd.CategoricalDtype) and target.dtype.ordered:
        return [str(level) for level in target.cat.categories if str(level) in observed]
    numeric = pd.to_numeric(target, errors="coerce")
    if numeric.notna().all():
        return [str(value) for value in sorted(numeric.unique().tolist())]
    return sorted(observed)


def fit_ordinal(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    from statsmodels.miscmodels.ordinal_model import OrderedModel

    frame, target, exog = _frame(ctx, ctx.artifacts["_normalized_y"], ctx.artifacts["_normalized_x"])
    options = dict(ctx.artifacts.get("_model_options") or {})
    categories = _ordered_categories(target, options)
    if len(categories) < 3:
        raise ValueError("ORDINAL_OUTCOME_REQUIRES_AT_LEAST_THREE_ORDERED_LEVELS")
    codes = pd.Categorical(target.astype(str), categories=categories, ordered=True).codes
    link = str(options.get("link", "logit"))
    model = OrderedModel(codes, exog, distr=link)
    fitted = model.fit(method=str(options.get("optimizer", "bfgs")), maxiter=int(options.get("maxiter", 500)), disp=False)
    names = [str(name) for name in fitted.params.index]
    # statsmodels names the cutpoints from the internal 0-based codes, which
    # would report a boundary against an outcome level the user never declared.
    # Relabel them with the declared levels while preserving their order.
    threshold_labels = [
        f"{categories[position]}/{categories[position + 1]}"
        for position in range(len(categories) - 1)
    ]
    threshold_positions = [
        position for position, name in enumerate(names) if name not in exog.columns
    ]
    if len(threshold_positions) == len(threshold_labels):
        for label, position in zip(threshold_labels, threshold_positions, strict=True):
            names[position] = label
    coefficient_map = _fit_stats(fitted, names)
    slope_names = [name for name in names if name in exog.columns]
    odds_ratios = (
        {
            name: {
                "odds_ratio": _exp_or_none(coefficient_map[name]["estimate"]),
                "ci_lower": _exp_or_none(coefficient_map[name]["ci_lower"]),
                "ci_upper": _exp_or_none(coefficient_map[name]["ci_upper"]),
            }
            for name in slope_names
        }
        if link == "logit"
        else None
    )
    probabilities = np.asarray(model.predict(fitted.params, exog=exog), dtype=float)
    parallel = _parallel_lines(codes, exog, categories, link=link)
    diagnostic = {
        "contract": "workbench.ordinal_logit.diagnostics.v1",
        "model_type": "ordinal_logit",
        "parallel_lines": parallel,
        "nobs": int(len(frame)),
        "validation": _validation_metadata(),
    }
    OrdinalDiagnosticsContract.from_dict(diagnostic)
    _persist_packet(env, "diagnostics_ordinal_logit_1", "model_results/diagnostics_ordinal_logit_1.json", diagnostic)
    primary = {
        "contract": "workbench.ordinal_logit.result.v1",
        "schema_version": 1,
        "model_id": "ordinal_logit_1",
        "model_type": "ordinal_logit",
        "engine": "statsmodels",
        "nobs": int(len(frame)),
        "outcome_levels": categories,
        "link": link,
        "coefficients": coefficient_map,
        "odds_ratios": odds_ratios,
        "predicted_probabilities": [{"row": int(index), "probabilities": {category: _json_safe(probabilities[index, pos]) for pos, category in enumerate(categories)}} for index in range(len(probabilities))],
        "marginal_effects": _marginal_probability_effects(model, fitted.params, exog, slope_names, categories),
        "diagnostic_artifacts": ["diagnostics_ordinal_logit_1"],
        "validation": _validation_metadata(),
    }
    OrdinalResultContract.from_dict(primary)
    return "ordinal_logit_1", primary, None


def _parallel_lines(
    codes: np.ndarray,
    exog: pd.DataFrame,
    categories: list[str],
    *,
    link: str,
) -> dict[str, Any]:
    slopes: list[dict[str, Any]] = []
    model_class = sm.Logit if link == "logit" else sm.Probit
    for threshold in range(1, len(categories)):
        binary = (codes >= threshold).astype(int)
        if len(np.unique(binary)) < 2:
            continue
        try:
            result = model_class(binary, sm.add_constant(exog, has_constant="add")).fit(disp=False)
            slopes.append({"threshold": threshold, "coefficients": {str(name): _json_safe(value) for name, value in zip(result.params.index, result.params)}})
        except Exception:
            continue
    if len(slopes) < 2:
        return {"status": "insufficient_support", "method": f"cumulative_{link}_slope_range", "comparisons": slopes}
    names = list(exog.columns)
    ranges = {name: _json_safe(max(float(row["coefficients"].get(name, np.nan)) for row in slopes) - min(float(row["coefficients"].get(name, np.nan)) for row in slopes)) for name in names}
    return {"status": "computed", "method": f"cumulative_{link}_slope_range", "slope_ranges": ranges, "comparisons": slopes}


def fit_multinomial(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    from statsmodels.discrete.discrete_model import MNLogit

    frame, target, exog_raw = _frame(ctx, ctx.artifacts["_normalized_y"], ctx.artifacts["_normalized_x"])
    outcome_levels = sorted(target.astype(str).unique().tolist())
    if len(outcome_levels) < 3:
        raise ValueError("MULTINOMIAL_OUTCOME_REQUIRES_AT_LEAST_THREE_LEVELS")
    options = dict(ctx.artifacts.get("_model_options") or {})
    requested_base = options.get("base_category")
    base_category = str(requested_base) if requested_base is not None else outcome_levels[-1]
    if base_category not in outcome_levels:
        raise ModelOptionsValidationError(
            "MULTINOMIAL_BASE_CATEGORY_UNKNOWN",
            f"base_category must match an observed outcome level: {base_category}",
            {"base_category": base_category, "outcome_levels": outcome_levels},
        )
    # statsmodels' MNLogit uses the first coded level as the reference category.
    # Keep the public outcome order stable, but put the declared reference first
    # in the private coding order so coefficient labels and probabilities agree.
    model_categories = [base_category] + [category for category in outcome_levels if category != base_category]
    category_codes = pd.Categorical(target.astype(str), categories=model_categories, ordered=False).codes
    exog = sm.add_constant(exog_raw, has_constant="add")
    fitted = MNLogit(category_codes, exog).fit(disp=False, maxiter=int(options.get("maxiter", 500)))
    params = np.asarray(fitted.params, dtype=float)
    standard_errors = np.asarray(fitted.bse, dtype=float)
    p_values = np.asarray(fitted.pvalues, dtype=float)
    confidence_intervals = np.asarray(fitted.conf_int(), dtype=float)
    names = [str(name) for name in exog.columns]
    non_base = model_categories[1:]
    coefficients: dict[str, Any] = {}
    rrr: dict[str, Any] = {}
    for category_index, category in enumerate(non_base):
        for term_index, name in enumerate(names):
            estimate = float(params[term_index, category_index])
            if confidence_intervals.ndim == 3:
                ci_lower = float(confidence_intervals[category_index, term_index, 0])
                ci_upper = float(confidence_intervals[category_index, term_index, 1])
            elif confidence_intervals.ndim == 2 and confidence_intervals.shape[0] == len(non_base) * len(names):
                interval_index = category_index * len(names) + term_index
                ci_lower = float(confidence_intervals[interval_index, 0])
                ci_upper = float(confidence_intervals[interval_index, 1])
            else:
                standard_error = float(standard_errors[term_index, category_index])
                ci_lower = estimate - 1.959963984540054 * standard_error
                ci_upper = estimate + 1.959963984540054 * standard_error
            key = f"{category}:{name}"
            coefficients[key] = {
                "estimate": _json_safe(estimate),
                "std_error": _json_safe(standard_errors[term_index, category_index]),
                "p_value": _json_safe(p_values[term_index, category_index]),
                "ci_lower": _json_safe(ci_lower),
                "ci_upper": _json_safe(ci_upper),
            }
            rrr[key] = {
                "relative_risk_ratio": _exp_or_none(estimate),
                "ci_lower": _exp_or_none(ci_lower),
                "ci_upper": _exp_or_none(ci_upper),
            }
    probabilities = np.asarray(fitted.predict(exog), dtype=float)
    margeff = fitted.get_margeff(at="overall").summary_frame()
    marginal_effects = _json_safe(margeff.reset_index().to_dict(orient="records"))
    primary = {
        "contract": "workbench.multinomial_logit.result.v1",
        "schema_version": 1,
        "model_id": "multinomial_logit_1",
        "model_type": "multinomial_logit",
        "engine": "statsmodels",
        "nobs": int(len(frame)),
        "outcome_levels": outcome_levels,
        "base_category": base_category,
        "coefficients": coefficients,
        "relative_risk_ratios": rrr,
        "predicted_probabilities": {
            category: [_json_safe(row[model_categories.index(category)]) for row in probabilities]
            for category in outcome_levels
        },
        "marginal_effects": marginal_effects,
        "diagnostic_artifacts": ["diagnostics_multinomial_logit_1"],
        "validation": _validation_metadata(),
    }
    MultinomialResultContract.from_dict(primary)
    _persist_packet(
        env,
        "diagnostics_multinomial_logit_1",
        "model_results/diagnostics_multinomial_logit_1.json",
        {
            "contract": "workbench.multinomial_logit.diagnostics.v1",
            "model_type": "multinomial_logit",
            "outcome_levels": outcome_levels,
            "base_category": base_category,
            "nobs": int(len(frame)),
            "validation": _validation_metadata(),
        },
    )
    return "multinomial_logit_1", primary, None


def _survival_curve(
    time: np.ndarray,
    status: np.ndarray,
    group: np.ndarray | None = None,
    entry: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    from statsmodels.duration.survfunc import SurvfuncRight

    if group is None:
        groups = [("all", np.ones(len(time), dtype=bool))]
    else:
        groups = [(str(value), group == value) for value in np.unique(group)]
    curves: list[dict[str, Any]] = []
    for label, mask in groups:
        group_entry = entry[mask] if entry is not None else None
        curve = SurvfuncRight(time[mask], status[mask], entry=group_entry)
        for index, point in enumerate(np.asarray(curve.surv_times)):
            at_risk = (time[mask] >= point)
            if group_entry is not None:
                at_risk &= group_entry <= point
            curves.append({"group": label, "time": _json_safe(point), "survival": _json_safe(np.asarray(curve.surv_prob)[index]), "n_at_risk": int(np.sum(at_risk))})
    return curves


def fit_survival(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    from statsmodels.duration.hazard_regression import PHReg
    from statsmodels.duration.survfunc import survdiff

    options = dict(ctx.artifacts.get("_model_options") or {})
    validate_survival_options(options)
    event_column = str(options["event_column"])
    extra_columns = [event_column]
    if options.get("group_column"):
        extra_columns.append(str(options["group_column"]))
    if options.get("entry_column"):
        extra_columns.append(str(options["entry_column"]))
    frame, _target, exog = _frame(ctx, ctx.artifacts["_normalized_y"], ctx.artifacts["_normalized_x"], extra_columns)
    duration = pd.to_numeric(frame[ctx.artifacts["_normalized_y"]], errors="raise").to_numpy(dtype=float)
    raw_status = pd.to_numeric(frame[event_column], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(duration).all() or (duration <= 0).any():
        raise ValueError("SURVIVAL_DURATION_MUST_BE_FINITE_AND_POSITIVE")
    if not np.isfinite(raw_status).all() or not np.isin(raw_status, [0, 1]).all() or not raw_status.any():
        raise ValueError("SURVIVAL_EVENT_COLUMN_MUST_BE_BINARY_WITH_AN_EVENT")
    status = raw_status.astype(int)
    group = None
    group_column = options.get("group_column")
    if group_column:
        if str(group_column) not in frame.columns:
            raise ValueError(f"SURVIVAL_GROUP_COLUMN_MISSING: {group_column}")
        group = frame[str(group_column)].to_numpy()
    entry = None
    if options.get("entry_column"):
        entry = pd.to_numeric(frame[str(options["entry_column"])], errors="raise").to_numpy(dtype=float)
        if (
            not np.isfinite(entry).all()
            or (entry < 0).any()
            or (entry >= duration).any()
        ):
            raise ValueError("SURVIVAL_ENTRY_MUST_BE_FINITE_NONNEGATIVE_AND_BEFORE_DURATION")
    fitted = PHReg(duration, exog, status=status, entry=entry, ties=str(options.get("ties", "breslow"))).fit()
    names = [str(name) for name in exog.columns]
    coefficient_map = _fit_stats(fitted, names)
    for name, values in coefficient_map.items():
        values["hazard_ratio"] = _json_safe(np.exp(float(values["estimate"]))) if values["estimate"] is not None else None
    event_times = sorted(set(float(value) for value in duration[status == 1]))
    risk_set = []
    for point in event_times:
        at_risk_mask = duration >= point
        if entry is not None:
            at_risk_mask &= entry <= point
        risk_set.append({
            "time": _json_safe(point),
            "at_risk": int(np.sum(at_risk_mask)),
            "events": int(np.sum((duration == point) & (status == 1))),
            "censored": int(np.sum((duration == point) & (status == 0))),
        })
    log_rank: dict[str, Any] = {"status": "not_requested"}
    if group is not None and len(np.unique(group)) == 2:
        chisq, pvalue = survdiff(duration, status, group, entry=entry)
        log_rank = {"status": "computed", "statistic": _json_safe(chisq), "p_value": _json_safe(pvalue), "groups": [str(value) for value in np.unique(group)]}
    residuals = np.asarray(getattr(fitted, "schoenfeld_residuals", np.empty((0, len(names)))), dtype=float)
    event_axis = np.asarray(duration[status == 1], dtype=float)
    schoenfeld: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        if residuals.ndim == 2 and residuals.shape[1] > index:
            values = (
                residuals[status == 1, index]
                if residuals.shape[0] == len(duration)
                else residuals[:, index]
            )
        else:
            values = np.array([])
        finite = np.isfinite(values) & np.isfinite(event_axis[: len(values)])
        finite_values = values[finite]
        finite_times = event_axis[: len(values)][finite]
        corr = stats.pearsonr(finite_times, finite_values)[0] if len(finite_values) > 2 and np.std(finite_values) > 0 else np.nan
        schoenfeld.append({"variable": name, "residuals": _json_safe(values), "time_correlation": _json_safe(corr), "status": "computed" if len(finite_values) > 2 else "insufficient_support"})
    evidence = {
        "contract": "workbench.survival.v1",
        "model_type": "survival_cox",
        "duration_column": ctx.artifacts["_normalized_y"],
        "event_column": event_column,
        "entry_column": str(options["entry_column"]) if options.get("entry_column") else None,
        "nobs": int(len(frame)),
        "censoring": {"events": int(status.sum()), "censored": int((status == 0).sum())},
        "time_to_event": {
            "duration_column": ctx.artifacts["_normalized_y"],
            "event_column": event_column,
            "entry_column": str(options["entry_column"]) if options.get("entry_column") else None,
        },
        "kaplan_meier": _survival_curve(duration, status, group, entry),
        "log_rank": log_rank,
        "risk_set": risk_set,
        "schoenfeld": schoenfeld,
        "validation": _validation_metadata(),
    }
    SurvivalEvidenceContract.from_dict(evidence)
    _persist_packet(env, "survival_evidence", "survival/evidence.json", evidence, artifact_type="survival_evidence")
    primary = {
        "schema_version": 1,
        "model_id": "survival_cox_1",
        "model_type": "survival_cox",
        "engine": "statsmodels",
        "nobs": int(len(frame)),
        "coefficients": coefficient_map,
        "hazard_ratios": {name: values.get("hazard_ratio") for name, values in coefficient_map.items()},
        "survival_evidence_artifact": "survival_evidence",
    }
    return "survival_cox_1", primary, None


def fit_quantile(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    from statsmodels.regression.quantile_regression import QuantReg

    frame, target, exog_raw = _frame(ctx, ctx.artifacts["_normalized_y"], ctx.artifacts["_normalized_x"])
    options = dict(ctx.artifacts.get("_model_options") or {})
    quantiles = sorted(float(q) for q in options.get("quantiles", [0.25, 0.5, 0.75]))
    exog = sm.add_constant(exog_raw, has_constant="add")
    fits: dict[str, Any] = {}
    confidence_intervals: dict[str, Any] = {}
    fitted_by_q: dict[float, Any] = {}
    names = [str(name) for name in exog.columns]
    for quantile in quantiles:
        fitted = QuantReg(target.to_numpy(dtype=float), exog).fit(q=quantile)
        fitted_by_q[quantile] = fitted
        fits[str(quantile)] = {"quantile": quantile, "coefficients": _fit_stats(fitted, names)}
        confidence_intervals[str(quantile)] = {
            name: [
                fits[str(quantile)]["coefficients"][name]["ci_lower"],
                fits[str(quantile)]["coefficients"][name]["ci_upper"],
            ]
            for name in names
        }
    bootstrap_reps = int(options.get("bootstrap_reps", 0))
    bootstrap: dict[str, Any] = {
        "repetitions": bootstrap_reps,
        "random_state": int(options.get("random_state", 0)),
        "successful_repetitions": {},
        "intervals": {},
    }
    if bootstrap_reps:
        rng = np.random.default_rng(int(options.get("random_state", 0)))
        estimates = {str(q): {name: [] for name in names} for q in quantiles}
        for _ in range(bootstrap_reps):
            indices = rng.integers(0, len(target), len(target))
            for quantile in quantiles:
                try:
                    fitted = QuantReg(target.to_numpy(dtype=float)[indices], exog.iloc[indices]).fit(q=quantile)
                    for index, name in enumerate(names):
                        estimates[str(quantile)][name].append(float(fitted.params.iloc[index]))
                except Exception:
                    continue
        for q_key, term_values in estimates.items():
            successful = min((len(values) for values in term_values.values()), default=0)
            bootstrap["successful_repetitions"][q_key] = successful
            bootstrap["intervals"][q_key] = {name: ([float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))] if values else [None, None]) for name, values in term_values.items()}
    else:
        bootstrap["successful_repetitions"] = {str(q): 0 for q in quantiles}
    comparisons: list[dict[str, Any]] = []
    for lower, upper in zip(quantiles, quantiles[1:]):
        lower_result = fitted_by_q[lower]
        upper_result = fitted_by_q[upper]
        for index, name in enumerate(names):
            difference = float(upper_result.params.iloc[index] - lower_result.params.iloc[index])
            se = float(np.sqrt(upper_result.bse.iloc[index] ** 2 + lower_result.bse.iloc[index] ** 2))
            z_value = difference / se if se > 0 else np.nan
            comparisons.append({"term": name, "lower_quantile": lower, "upper_quantile": upper, "difference": _json_safe(difference), "std_error": _json_safe(se), "p_value": _json_safe(2 * stats.norm.sf(abs(z_value))) if np.isfinite(z_value) else None})
    reference_quantile = min(quantiles, key=lambda q: abs(q - 0.5))
    median = fitted_by_q[reference_quantile]
    primary = {
        "contract": "workbench.quantile_regression.result.v1",
        "schema_version": 1,
        "model_id": "quantile_regression_1",
        "model_type": "quantile_regression",
        "engine": "statsmodels",
        "nobs": int(len(frame)),
        "quantiles": quantiles,
        "fits": fits,
        "coefficients": fits[str(reference_quantile)]["coefficients"],
        "reference_quantile": reference_quantile,
        "confidence_intervals": confidence_intervals,
        "bootstrap": bootstrap,
        "cross_quantile_comparisons": comparisons,
        "validation": _validation_metadata(),
    }
    QuantileRegressionResultContract.from_dict(primary)
    return "quantile_regression_1", primary, median


def model_handlers() -> dict[str, ModelHandler]:
    return {
        "ordinal_logit": ModelHandler("ordinal_logit", "ordinal_logit_1", ("ordinal",), fit_ordinal, validate_ordinal_options, _options_contract("ordinal_logit")),
        "multinomial_logit": ModelHandler("multinomial_logit", "multinomial_logit_1", ("nominal",), fit_multinomial, validate_multinomial_options, _options_contract("multinomial_logit")),
        "survival_cox": ModelHandler("survival_cox", "survival_cox_1", ("survival",), fit_survival, validate_survival_options, _options_contract("survival")),
        "quantile_regression": ModelHandler("quantile_regression", "quantile_regression_1", ("continuous",), fit_quantile, validate_quantile_options, _options_contract("quantile_regression")),
    }
