"""Standalone, fail-closed study-level meta-analysis kernels. (combine)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any
from scipy import stats
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.meta_analysis import META_ANALYSIS_COMPLETED, MetaAnalysisResultEnvelope, make_meta_analysis_envelope
from .rows import (
    MAX_NUMERIC_INPUT,
    MAX_OUTPUT_ROWS,
    MAX_PM_ITERATIONS,
    PM_TOLERANCE,
    _canonical_ci_method,
    _canonical_effect_measure,
    _canonical_method,
    _converted_rows,
    _evidence_rows,
    _reject,
    _resolve_continuity_correction,
    _safe_product,
    _safe_sqrt,
    _safe_sum,
    _validate_alpha,
    _validate_correction_applicability,
    _validate_evidence_correction,
)


def _weights(variances: Sequence[float], tau2: float) -> list[float]:
    weights: list[float] = []
    for variance in variances:
        try:
            weight = 1.0 / (variance + tau2)
        except (OverflowError, ZeroDivisionError):
            _reject("META_NUMERIC_OVERFLOW", "inverse-variance weight could not be evaluated")
        if not math.isfinite(weight) or weight <= 0.0:
            _reject("META_NUMERIC_OVERFLOW", "inverse-variance weight is not finite")
        weights.append(weight)
    return weights


def _weighted_mean(effects: Sequence[float], weights: Sequence[float]) -> float:
    numerator = _safe_sum(
        [_safe_product(effect, weight, "weighted effect") for effect, weight in zip(effects, weights)],
        "weighted effect sum",
    )
    denominator = _safe_sum(weights, "weight sum")
    if denominator <= 0.0:
        _reject("META_NUMERIC_OVERFLOW", "weight sum must be positive")
    value = numerator / denominator
    if not math.isfinite(value):
        _reject("META_NUMERIC_OVERFLOW", "pooled effect is not finite")
    return value


def _q_statistic(effects: Sequence[float], variances: Sequence[float]) -> tuple[float, float, list[float]]:
    weights = _weights(variances, 0.0)
    pooled = _weighted_mean(effects, weights)
    q = _safe_sum(
        [
            _safe_product(weight, (effect - pooled) ** 2, "Q contribution")
            for effect, weight in zip(effects, weights)
        ],
        "Q",
    )
    return q, pooled, weights


def _der_simonian_laird_tau2(q: float, df: int, weights: Sequence[float]) -> tuple[float, float]:
    sum_weights = _safe_sum(weights, "fixed weight sum")
    sum_squared_weights = _safe_sum([weight * weight for weight in weights], "squared weight sum")
    c = sum_weights - sum_squared_weights / sum_weights
    if not math.isfinite(c) or c <= 0.0:
        _reject("META_NUMERIC_OVERFLOW", "DerSimonian-Laird denominator is not positive")
    raw = (q - df) / c
    if not math.isfinite(raw):
        _reject("META_NUMERIC_OVERFLOW", "DerSimonian-Laird estimate is not finite")
    return max(0.0, raw), raw


def _pm_q(effects: Sequence[float], variances: Sequence[float], tau2: float) -> float:
    weights = _weights(variances, tau2)
    pooled = _weighted_mean(effects, weights)
    return _safe_sum(
        [
            _safe_product(weight, (effect - pooled) ** 2, "Paule-Mandel Q contribution")
            for effect, weight in zip(effects, weights)
        ],
        "Paule-Mandel Q",
    )


def _paule_mandel_tau2(
    effects: Sequence[float], variances: Sequence[float], df: int, q_at_zero: float
) -> float:
    if q_at_zero <= df:
        return 0.0
    lower = 0.0
    upper = max(max(variances), 1.0)
    for _ in range(MAX_PM_ITERATIONS):
        if _pm_q(effects, variances, upper) <= df:
            break
        upper *= 2.0
        if not math.isfinite(upper) or upper > MAX_NUMERIC_INPUT:
            _reject("META_NUMERIC_OVERFLOW", "Paule-Mandel bracket exceeded the numeric bound")
    else:
        _reject("META_PM_NOT_CONVERGED", "Paule-Mandel bracket could not be found")

    for _ in range(MAX_PM_ITERATIONS):
        midpoint = (lower + upper) / 2.0
        q_mid = _pm_q(effects, variances, midpoint)
        if abs(q_mid - df) <= PM_TOLERANCE * max(1.0, float(df)):
            return midpoint
        if q_mid > df:
            lower = midpoint
        else:
            upper = midpoint
        if upper - lower <= PM_TOLERANCE * max(1.0, upper):
            return (lower + upper) / 2.0
    _reject("META_PM_NOT_CONVERGED", "Paule-Mandel iterations did not converge")


def _critical_value(ci_method: str, alpha: float, df: int) -> tuple[float, str]:
    if ci_method == "normal_z":
        critical = float(stats.norm.isf(alpha / 2.0))
        distribution = "normal"
    else:
        critical = float(stats.t.isf(alpha / 2.0, df))
        distribution = "student_t"
    if not math.isfinite(critical):
        _reject("META_NUMERIC_OVERFLOW", "confidence critical value is not finite")
    return critical, distribution


def _combine_core(
    normalized: Sequence[Mapping[str, Any]],
    *,
    effect_measure: str,
    method: str,
    alpha: float,
    ci_method: str,
    conversion: Mapping[str, Any],
) -> dict[str, Any]:
    effects = [float(row["effect"]) for row in normalized]
    variances = [float(row["variance"]) for row in normalized]
    study_ids = [str(row["study_id"]) for row in normalized]
    k = len(normalized)
    df = k - 1

    q, fixed_effect, fixed_weights = _q_statistic(effects, variances)
    fixed_sum_weights = _safe_sum(fixed_weights, "fixed weight sum")
    fixed_se = _safe_sqrt(1.0 / fixed_sum_weights, "fixed standard error")
    dl_tau2, dl_tau2_raw = _der_simonian_laird_tau2(q, df, fixed_weights)
    if method == "fixed_effect":
        tau2 = 0.0
    elif method == "derSimonian_laird":
        tau2 = dl_tau2
    else:
        tau2 = _paule_mandel_tau2(effects, variances, df, q)
    selected_weights = _weights(variances, tau2)
    selected_sum_weights = _safe_sum(selected_weights, "selected weight sum")
    pooled_effect = _weighted_mean(effects, selected_weights)

    scale_estimate = 1.0
    if ci_method == "hksj":
        scale_estimate = _safe_sum(
            [
                _safe_product(weight, (effect - pooled_effect) ** 2, "HKSJ scale contribution")
                for effect, weight in zip(effects, selected_weights)
            ],
            "HKSJ scale numerator",
        ) / df
        if scale_estimate < 0.0 or not math.isfinite(scale_estimate):
            _reject("META_NUMERIC_OVERFLOW", "HKSJ scale is not finite")
    pooled_se = _safe_sqrt(scale_estimate / selected_sum_weights, "pooled standard error")
    critical, distribution = _critical_value(ci_method, alpha, df)
    ci_half_width = _safe_product(critical, pooled_se, "confidence interval half-width")
    ci = {"lower": pooled_effect - ci_half_width, "upper": pooled_effect + ci_half_width}

    prediction_se = _safe_sqrt(
        scale_estimate / selected_sum_weights + tau2,
        "prediction standard error",
    )
    prediction_half_width = _safe_product(
        critical, prediction_se, "prediction interval half-width"
    )
    prediction_interval = {
        "lower": pooled_effect - prediction_half_width,
        "upper": pooled_effect + prediction_half_width,
        "standard_error": prediction_se,
        "critical_value": critical,
        "distribution": distribution,
        "tau2_included": tau2,
    }

    relative_fixed = [weight / fixed_sum_weights for weight in fixed_weights]
    relative_selected = [weight / selected_sum_weights for weight in selected_weights]
    study_evidence = []
    for row, fixed_weight, selected_weight, fixed_relative, selected_relative in zip(
        normalized,
        fixed_weights,
        selected_weights,
        relative_fixed,
        relative_selected,
    ):
        study_evidence.append(
            {
                "study_id": row["study_id"],
                "effect_measure": effect_measure,
                "effect": row["effect"],
                "variance": row["variance"],
                "standard_error": row["standard_error"],
                "fixed_weight": fixed_weight,
                "random_weight": selected_weight,
                "fixed_relative_weight": fixed_relative,
                "relative_weight": selected_relative,
                "contribution": selected_relative * row["effect"],
            }
        )

    p_value = float(stats.chi2.sf(q, df))
    i2 = 0.0 if q <= 0.0 else max(0.0, (q - df) / q)
    h2 = q / df
    method_semantics = {
        "fixed_effect": "inverse_variance_fixed_effect",
        "derSimonian_laird": "inverse_variance_random_effects_dl",
        "paule_mandel": "inverse_variance_random_effects_pm",
    }[method]
    result: dict[str, Any] = {
        "effect_measure": effect_measure,
        "method": method,
        "method_semantics": method_semantics,
        "alpha": alpha,
        "ci_method": ci_method,
        "ci_semantics": {
            "method": ci_method,
            "distribution": distribution,
            "alpha": alpha,
            "confidence_level": 1.0 - alpha,
            "degrees_of_freedom": df if distribution == "student_t" else None,
            "scale_estimator": "hksj" if ci_method == "hksj" else "unit",
            "scale": scale_estimate,
        },
        "study_count": k,
        "studies": study_evidence,
        "weights": {
            "study_ids": study_ids,
            "fixed": fixed_weights,
            "random": selected_weights,
            "selected": selected_weights,
            "relative_fixed": relative_fixed,
            "relative_selected": relative_selected,
        },
        "pooled_effect": pooled_effect,
        "pooled_se": pooled_se,
        "pooled": {"effect": pooled_effect, "se": pooled_se, "ci": ci},
        "ci": ci,
        "ci_lower": ci["lower"],
        "ci_upper": ci["upper"],
        "q": q,
        "Q": q,
        "df": df,
        "p_value": p_value,
        "p": p_value,
        "tau2": tau2,
        "tau2_raw": dl_tau2_raw,
        "i2": i2,
        "I2": i2,
        "h2": h2,
        "H2": h2,
        "heterogeneity": {
            "Q": q,
            "q": q,
            "df": df,
            "p": p_value,
            "p_value": p_value,
            "tau2": tau2,
            "tau2_raw_dl": dl_tau2_raw,
            "I2": i2,
            "i2": i2,
            "H2": h2,
            "h2": h2,
        },
        "prediction_interval": prediction_interval,
        "conversion": dict(conversion),
    }
    return result


def _leave_one_out_evidence(
    normalized: Sequence[Mapping[str, Any]],
    *,
    effect_measure: str,
    method: str,
    alpha: float,
    ci_method: str,
    conversion: Mapping[str, Any],
    full_pooled_effect: float,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for excluded_index, excluded in enumerate(normalized):
        subset = [row for index, row in enumerate(normalized) if index != excluded_index]
        summary = _combine_core(
            subset,
            effect_measure=effect_measure,
            method=method,
            alpha=alpha,
            ci_method=ci_method,
            conversion=conversion,
        )
        evidence.append(
            {
                "excluded_study_id": excluded["study_id"],
                "effect_measure": effect_measure,
                "method": method,
                "ci_method": ci_method,
                "study_count": len(subset),
                "pooled_effect": summary["pooled_effect"],
                "pooled_se": summary["pooled_se"],
                "ci": summary["ci"],
                "q": summary["q"],
                "df": summary["df"],
                "p_value": summary["p_value"],
                "tau2": summary["tau2"],
                "i2": summary["i2"],
                "h2": summary["h2"],
                "prediction_interval": summary["prediction_interval"],
                "delta_pooled_effect": summary["pooled_effect"] - full_pooled_effect,
            }
        )
    return evidence


def _source_payload(studies: Any) -> tuple[Any, Mapping[str, Any] | None]:
    if isinstance(studies, Mapping) and "operation_id" in studies:
        try:
            envelope = MetaAnalysisResultEnvelope.from_dict(studies)
        except ContractError as exc:
            _reject("META_INVALID_INPUT_ENVELOPE", str(exc))
        if envelope.operation_id != "meta.effect_size":
            _reject("META_INVALID_INPUT_ENVELOPE", "combine accepts meta.effect_size evidence only")
        payload = envelope.to_dict()["result"]
        return payload["studies"], payload["conversion"]
    if isinstance(studies, Mapping) and "studies" in studies:
        return studies["studies"], None
    return studies, None


def _source_rows(studies: Any) -> Any:
    return _source_payload(studies)[0]


def _prepare_effects(
    studies: Any,
    *,
    effect_measure: str,
    continuity_correction: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_rows, source_conversion = _source_payload(studies)
    if source_conversion is not None:
        _validate_evidence_correction(
            source_conversion,
            effect_measure=effect_measure,
            correction=continuity_correction,
        )
        normalized = _evidence_rows(source_rows, effect_measure=effect_measure)
        conversion = dict(source_conversion)
        conversion["input"] = "meta.effect_size_evidence"
        return normalized, conversion
    return _converted_rows(
        source_rows,
        effect_measure=effect_measure,
        continuity_correction=continuity_correction,
    )


def convert_effect_size(
    studies: Any = None,
    *,
    effect_measure: str | None = None,
    alpha: float | int | None = None,
    continuity_correction: float | None = None,
    zero_correction: float | None = None,
) -> dict[str, Any]:
    """Convert study summaries into a declared effect/variance scale."""

    measure = _canonical_effect_measure(effect_measure)
    alpha_value = _validate_alpha(alpha)
    correction = _resolve_continuity_correction(continuity_correction, zero_correction)
    _validate_correction_applicability(measure, correction)
    source_rows, source_conversion = _source_payload(studies)
    if source_conversion is not None:
        _reject("META_INVALID_INPUT_ENVELOPE", "effect-size conversion cannot re-convert evidence")
    normalized, conversion = _converted_rows(
        source_rows,
        effect_measure=measure,
        continuity_correction=correction,
    )
    public_studies = [
        {**row, "yi": row["effect"], "vi": row["variance"]}
        for row in normalized
    ]
    result = {
        "effect_measure": measure,
        "alpha": alpha_value,
        "study_count": len(normalized),
        "studies": public_studies,
        "conversion": conversion,
    }
    return make_meta_analysis_envelope(
        operation_id="meta.effect_size",
        status="completed",
        reason_code=META_ANALYSIS_COMPLETED,
        result=result,
    )


def combine_effects(
    studies: Any = None,
    *,
    effect_measure: str | None = None,
    method: str | None = None,
    alpha: float | int | None = None,
    ci_method: str | None = None,
    use_t: bool | None = None,
    leave_one_out: bool = False,
    max_leave_one_out: int | None = None,
    continuity_correction: float | None = None,
    zero_correction: float | None = None,
    effects: Sequence[Any] | None = None,
    variances: Sequence[Any] | None = None,
    study_ids: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Combine study-level effects using one explicitly selected method."""

    measure = _canonical_effect_measure(effect_measure)
    method_value = _canonical_method(method)
    alpha_value = _validate_alpha(alpha)
    ci_method_value = _canonical_ci_method(ci_method, use_t=use_t)
    if type(leave_one_out) is not bool:
        _reject("META_INVALID_OPTION", "leave_one_out must be an explicit boolean")
    if max_leave_one_out is not None and (
        type(max_leave_one_out) is not int
        or isinstance(max_leave_one_out, bool)
        or not 1 <= max_leave_one_out <= MAX_OUTPUT_ROWS
    ):
        _reject(
            "META_OUTPUT_COUNT_EXCEEDED",
            f"max_leave_one_out must be an integer in [1, {MAX_OUTPUT_ROWS}]",
        )
    correction = _resolve_continuity_correction(continuity_correction, zero_correction)
    _validate_correction_applicability(measure, correction)

    supplied_vectors = any(value is not None for value in (effects, variances, study_ids))
    if supplied_vectors:
        if studies is not None or effects is None or variances is None or study_ids is None:
            _reject(
                "META_INVALID_STUDIES",
                "effects, variances, and study_ids must be supplied together",
            )
        if not (
            isinstance(effects, Sequence)
            and isinstance(variances, Sequence)
            and isinstance(study_ids, Sequence)
        ):
            _reject("META_INVALID_STUDIES", "effects, variances, and study_ids must be arrays")
        if not (len(effects) == len(variances) == len(study_ids)):
            _reject("META_INVALID_STUDIES", "effect arrays must have equal lengths")
        studies = [
            {"study_id": identifier, "yi": effect, "vi": variance}
            for identifier, effect, variance in zip(study_ids, effects, variances)
        ]
    elif studies is None:
        _reject("META_INVALID_STUDIES", "studies must be supplied")

    if supplied_vectors and measure != "direct":
        _reject("META_INVALID_STUDIES", "effect vectors are accepted only on the direct scale")
    normalized, conversion = _prepare_effects(
        studies,
        effect_measure=measure,
        continuity_correction=correction,
    )
    result = _combine_core(
        normalized,
        effect_measure=measure,
        method=method_value,
        alpha=alpha_value,
        ci_method=ci_method_value,
        conversion=conversion,
    )
    if leave_one_out:
        if len(normalized) <= 2:
            _reject(
                "META_LOO_TOO_FEW_STUDIES",
                "leave-one-out requires at least three input studies",
            )
        loo_limit = MAX_OUTPUT_ROWS if max_leave_one_out is None else max_leave_one_out
        if len(normalized) > loo_limit:
            _reject(
                "META_OUTPUT_COUNT_EXCEEDED",
                "leave-one-out output would exceed its explicit bound",
            )
        result["leave_one_out"] = _leave_one_out_evidence(
            normalized,
            effect_measure=measure,
            method=method_value,
            alpha=alpha_value,
            ci_method=ci_method_value,
            conversion=conversion,
            full_pooled_effect=result["pooled_effect"],
        )
        result["influence"] = {
            "kind": "leave_one_out",
            "bounded": True,
            "row_count": len(result["leave_one_out"]),
            "leave_one_out": result["leave_one_out"],
        }
    if len(result["studies"]) > MAX_OUTPUT_ROWS:
        _reject("META_OUTPUT_COUNT_EXCEEDED", "study evidence exceeds the output bound")
    return make_meta_analysis_envelope(
        operation_id="meta.combine",
        status="completed",
        reason_code=META_ANALYSIS_COMPLETED,
        result=result,
    )


combine_meta_analysis = combine_effects
convert_meta_effect_size = convert_effect_size
