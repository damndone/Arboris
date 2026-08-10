"""Rubin's rules for pooling aligned model estimates across imputations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from scipy import stats

from workbench.canonical import sha256_canonical
from workbench.contracts.model.missing_data import make_missing_data_result

from .errors import MissingDataPackError


MAX_IMPUTATIONS = 1_000
MAX_COEFFICIENTS = 10_000


def _reject(reason_code: str, message: str) -> None:
    raise MissingDataPackError(reason_code, message)


def _finite(value: Any, label: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _reject("MISSING_DATA_INVALID_INPUT", f"{label} must be finite")
    number = float(value)
    if not math.isfinite(number):
        _reject("MISSING_DATA_INVALID_INPUT", f"{label} must be finite")
    return number


def _alpha(value: Any) -> float:
    alpha = _finite(value, "alpha")
    if not 0.0 < alpha < 1.0:
        _reject("MISSING_DATA_INVALID_INPUT", "alpha must be between 0 and 1")
    return alpha


def _coefficient_names(result: Mapping[str, Any]) -> list[str]:
    coefficients = result.get("coefficients")
    if not isinstance(coefficients, Mapping) or not coefficients:
        _reject("MISSING_DATA_INVALID_INPUT", "coefficients must be a non-empty mapping")
    names = list(coefficients)
    if any(type(name) is not str or not name for name in names):
        _reject("MISSING_DATA_INVALID_INPUT", "coefficient names must be non-empty strings")
    if len(names) > MAX_COEFFICIENTS:
        _reject("MISSING_DATA_INVALID_INPUT", "coefficient count exceeds the hard limit")
    return names


def _estimate_and_variance(
    coefficient: Mapping[str, Any], name: str
) -> tuple[float, float, float | None]:
    if not isinstance(coefficient, Mapping):
        _reject("MISSING_DATA_INVALID_INPUT", f"coefficient {name!r} must be a mapping")
    estimate = _finite(coefficient.get("estimate"), f"coefficient {name!r} estimate")
    if "variance" in coefficient:
        variance = _finite(coefficient["variance"], f"coefficient {name!r} variance")
        if variance <= 0.0:
            _reject(
                "MISSING_DATA_INVALID_VARIANCE",
                f"coefficient {name!r} variance must be positive",
            )
    elif "std_error" in coefficient:
        standard_error = _finite(
            coefficient["std_error"], f"coefficient {name!r} standard error"
        )
        if standard_error <= 0.0:
            _reject(
                "MISSING_DATA_INVALID_VARIANCE",
                f"coefficient {name!r} standard error must be positive",
            )
        variance = standard_error * standard_error
        if not math.isfinite(variance):
            _reject(
                "MISSING_DATA_INVALID_VARIANCE",
                f"coefficient {name!r} variance must be finite",
            )
    else:
        _reject(
            "MISSING_DATA_INVALID_VARIANCE",
            f"coefficient {name!r} requires variance or std_error",
        )

    complete_df: float | None = None
    if "degrees_of_freedom" in coefficient:
        complete_df = _finite(
            coefficient["degrees_of_freedom"],
            f"coefficient {name!r} degrees of freedom",
        )
        if complete_df <= 0.0:
            _reject(
                "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                f"coefficient {name!r} degrees of freedom must be positive and finite",
            )
    return estimate, variance, complete_df


def _sample_variance(values: Sequence[float], mean: float) -> float:
    divisor = len(values) - 1
    return sum((value - mean) ** 2 for value in values) / divisor


def rubin_pool(
    model_results: Sequence[Mapping[str, Any]],
    *,
    alpha: float = 0.05,
    null_value: float = 0.0,
    complete_data_degrees_of_freedom: float | None = None,
) -> dict[str, Any]:
    """Pool unrounded coefficient estimates and complete-data variances.

    ``model_results`` must contain one aligned coefficient block per
    imputation.  The implementation never pools already-rounded p-values or
    confidence limits.
    """

    if isinstance(model_results, (str, bytes)) or not isinstance(model_results, Sequence):
        _reject("MISSING_DATA_INVALID_INPUT", "model_results must be a sequence")
    m = len(model_results)
    if m < 2:
        _reject(
            "MISSING_DATA_TOO_FEW_IMPUTATIONS",
            "Rubin pooling requires at least 2 imputations",
        )
    if m > MAX_IMPUTATIONS:
        _reject("MISSING_DATA_INVALID_INPUT", "imputation count exceeds the hard limit")
    alpha_value = _alpha(alpha)
    null = _finite(null_value, "null_value")
    if complete_data_degrees_of_freedom is not None:
        fallback_df = _finite(
            complete_data_degrees_of_freedom, "complete-data degrees of freedom"
        )
        if fallback_df <= 0.0:
            _reject(
                "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                "complete-data degrees of freedom must be positive and finite",
            )
    else:
        fallback_df = None

    if any(not isinstance(result, Mapping) for result in model_results):
        _reject("MISSING_DATA_INVALID_INPUT", "each model result must be a mapping")
    names = _coefficient_names(model_results[0])
    if len(names) > MAX_COEFFICIENTS:
        _reject("MISSING_DATA_INVALID_INPUT", "coefficient count exceeds the hard limit")

    estimates: dict[str, list[float]] = {name: [] for name in names}
    variances: dict[str, list[float]] = {name: [] for name in names}
    supplied_df: dict[str, list[float]] = {name: [] for name in names}
    for result in model_results:
        result_names = _coefficient_names(result)
        if result_names != names and set(result_names) != set(names):
            _reject(
                "MISSING_DATA_COEFFICIENT_MISMATCH",
                "coefficient names must match across imputations",
            )
        if set(result_names) != set(names):
            _reject(
                "MISSING_DATA_COEFFICIENT_MISMATCH",
                "coefficient names must match across imputations",
            )
        coefficients = result["coefficients"]
        for name in names:
            estimate, variance, complete_df = _estimate_and_variance(coefficients[name], name)
            estimates[name].append(estimate)
            variances[name].append(variance)
            if complete_df is not None:
                supplied_df[name].append(complete_df)

    pooled_coefficients: dict[str, dict[str, Any]] = {}
    for name in names:
        q_values = estimates[name]
        u_values = variances[name]
        q_bar = sum(q_values) / m
        u_bar = sum(u_values) / m
        between = _sample_variance(q_values, q_bar)
        total = u_bar + (1.0 + 1.0 / m) * between
        if not math.isfinite(total) or total <= 0.0:
            _reject(
                "MISSING_DATA_INVALID_VARIANCE",
                f"coefficient {name!r} total variance must be positive and finite",
            )

        if between == 0.0:
            candidate_df = fallback_df
            if candidate_df is None and supplied_df[name]:
                if len(supplied_df[name]) != m or len(set(supplied_df[name])) != 1:
                    _reject(
                        "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                        f"coefficient {name!r} degrees of freedom are not aligned",
                    )
                candidate_df = supplied_df[name][0]
            if candidate_df is None or not math.isfinite(candidate_df) or candidate_df <= 0.0:
                _reject(
                    "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                    f"coefficient {name!r} Rubin degrees of freedom are undefined",
                )
            relative_increase = 0.0
            fraction_missing = 0.0
        else:
            relative_increase = (1.0 + 1.0 / m) * between / u_bar
            degrees_of_freedom = (m - 1.0) * (1.0 + 1.0 / relative_increase) ** 2
            if not math.isfinite(degrees_of_freedom) or degrees_of_freedom <= 0.0:
                _reject(
                    "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                    f"coefficient {name!r} Rubin degrees of freedom are invalid",
                )
            candidate_df = degrees_of_freedom
            fraction_missing = relative_increase / (1.0 + relative_increase)

        standard_error = math.sqrt(total)
        t_statistic = (q_bar - null) / standard_error
        critical = float(stats.t.ppf(1.0 - alpha_value / 2.0, candidate_df))
        if not math.isfinite(critical):
            _reject(
                "MISSING_DATA_INVALID_DEGREES_OF_FREEDOM",
                f"coefficient {name!r} t critical value is not finite",
            )
        p_value = float(2.0 * stats.t.sf(abs(t_statistic), candidate_df))
        pooled_coefficients[name] = {
            "estimate": q_bar,
            "within_variance": u_bar,
            "between_variance": between,
            "total_variance": total,
            "standard_error": standard_error,
            "degrees_of_freedom": candidate_df,
            "relative_increase_in_variance": relative_increase,
            "fraction_missing_information": fraction_missing,
            "t_statistic": t_statistic,
            "p_value": p_value,
            "confidence_level": 1.0 - alpha_value,
            "confidence_interval_method": "rubin_t",
            "confidence_interval": [
                q_bar - critical * standard_error,
                q_bar + critical * standard_error,
            ],
            "Qbar": q_bar,
            "Ubar": u_bar,
            "B": between,
            "T": total,
        }

    input_digest = sha256_canonical(
        {
            "m": m,
            "coefficients": {
                name: {
                    "estimates": estimates[name],
                    "variances": variances[name],
                }
                for name in names
            },
        }
    )
    evidence_digest = sha256_canonical(
        {
            "m": m,
            "alpha": alpha_value,
            "coefficients": pooled_coefficients,
        }
    )
    return make_missing_data_result(
        operation_id="missing_data.rubin_pool",
        status="completed",
        reason_code="MISSING_DATA_RUBIN_COMPLETED",
        m=m,
        alpha=alpha_value,
        confidence_level=1.0 - alpha_value,
        pooling_method="rubin_t",
        coefficients=pooled_coefficients,
        provenance={
            "imputation_count": m,
            "coefficient_names": list(names),
            "input_digest": input_digest,
        },
        evidence_digest=evidence_digest,
    )


__all__ = ["MAX_COEFFICIENTS", "MAX_IMPUTATIONS", "rubin_pool"]
