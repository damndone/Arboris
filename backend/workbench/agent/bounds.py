"""Bounded projections of result values for the Agent.

What reaches the Agent leaves the machine (egress control v1), so every value
is cut to a fixed size and stripped to finite numbers and short labels. An
unbounded probability or survival table would turn a result summary into a
data-export channel.

Moved out of ``context_tools`` in v1.8.10 so the per-family evidence projection
can use them without importing the whole tool provider.
"""

from __future__ import annotations

import math
from typing import Any


def _public_stat_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(float(value)) else None
    except OverflowError:
        return None


def _public_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _bounded_label(value: Any) -> str | None:
    return value[:128] if isinstance(value, str) else None


def _bounded_labels(value: Any, *, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item[:128] for item in value[:limit] if isinstance(item, str)]


def _bounded_numeric_list(value: Any, *, limit: int) -> list[int | float]:
    if not isinstance(value, list):
        return []
    return [number for item in value[:limit] if (number := _public_stat_number(item)) is not None]


def _bounded_numeric_fields(
    value: Any,
    *,
    fields: tuple[str, ...],
    string_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for field in fields:
        number = _public_stat_number(value.get(field))
        if number is not None:
            result[field] = number
    for field in string_fields:
        label = _bounded_label(value.get(field))
        if label is not None:
            result[field] = label
    for field in list_fields:
        result[field] = _bounded_labels(value.get(field))
    return result


def _bounded_numeric_map(value: Any, *, fields: tuple[str, ...]) -> dict[str, dict[str, int | float]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, int | float]] = {}
    for key, cell in list(value.items())[:64]:
        if not isinstance(key, str) or not isinstance(cell, dict):
            continue
        bounded = _bounded_numeric_fields(cell, fields=fields)
        if bounded:
            result[key[:128]] = bounded
    return result


def _bounded_ordinal_marginal_effects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for row in value[:16]:
        if not isinstance(row, dict):
            continue
        effects = row.get("average_effect_by_category")
        result.append({
            "variable": _bounded_label(row.get("variable")),
            "average_effect_by_category": {},
        })
        if isinstance(effects, dict):
            result[-1]["average_effect_by_category"] = {
                str(key)[:128]: number
                for key, item in list(effects.items())[:16]
                if (number := _public_stat_number(item)) is not None
            }
    return result


def _bounded_ordinal_probabilities(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        probabilities = row.get("probabilities")
        result.append({
            "row": _public_positive_int(row.get("row")),
            "probabilities": {
                str(key)[:128]: number
                for key, item in list(probabilities.items())[:16]
                if isinstance(key, str) and (number := _public_stat_number(item)) is not None
            } if isinstance(probabilities, dict) else {},
        })
    return result


def _bounded_parallel_lines(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = _bounded_numeric_fields(value, fields=(), string_fields=("status", "method"))
    result["slope_ranges"] = {}
    if isinstance(value.get("slope_ranges"), dict):
        result["slope_ranges"] = {
            str(key)[:128]: number
            for key, item in list(value["slope_ranges"].items())[:16]
            if (number := _public_stat_number(item)) is not None
        }
    comparisons: list[dict[str, Any]] = []
    for row in (value.get("comparisons") if isinstance(value.get("comparisons"), list) else [])[:8]:
        if not isinstance(row, dict):
            continue
        coefficients = row.get("coefficients")
        comparisons.append({
            "threshold": _public_positive_int(row.get("threshold")),
            "coefficients": {
                str(key)[:128]: number
                for key, item in list(coefficients.items())[:16]
                if isinstance(key, str) and (number := _public_stat_number(item)) is not None
            } if isinstance(coefficients, dict) else {},
        })
    result["comparisons"] = comparisons
    return result


def _bounded_multinomial_marginal_effects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    numeric_fields = ("dy/dx", "Std. Err.", "z", "Pr(>|z|)", "Conf. Int. Low", "Cont. Int. Hi.")
    result: list[dict[str, Any]] = []
    for row in value[:16]:
        if not isinstance(row, dict):
            continue
        bounded = _bounded_numeric_fields(row, fields=numeric_fields, string_fields=("endog", "exog"))
        result.append(bounded)
    return result


def _bounded_probability_map(value: Any, *, limit: int = 8) -> dict[str, list[int | float]]:
    if not isinstance(value, dict):
        return {}
    return {
        key[:128]: _bounded_numeric_list(item, limit=limit)
        for key, item in list(value.items())[:16]
        if isinstance(key, str) and isinstance(item, list)
    }


def _bounded_anova_rows(value: Any, *, limit: int = 24) -> list[dict[str, Any]]:
    """An ANOVA table, bounded like every other agent-facing projection.

    A factorial design with many levels can produce a long table; the limit
    keeps this a summary rather than a data-export channel.
    """
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        rows.append(
            _bounded_numeric_fields(
                row,
                fields=("sum_sq", "df", "f", "p_value", "partial_eta_squared"),
                string_fields=("term",),
            )
        )
    return rows


def _bounded_survival_rows(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        bounded = _bounded_numeric_fields(
            row,
            fields=("time", "survival", "n_at_risk", "at_risk", "events", "censored"),
            string_fields=("group",),
        )
        result.append(bounded)
    return result


def _bounded_schoenfeld(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(_bounded_numeric_fields(
            row,
            fields=("time_correlation",),
            string_fields=("variable", "status"),
        ))
    return result


def _bounded_quantile_fits(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    numeric_fields = ("estimate", "std_error", "p_value", "ci_lower", "ci_upper")
    for quantile, fit in list(value.items())[:7]:
        if not isinstance(quantile, str) or not isinstance(fit, dict):
            continue
        coefficients = fit.get("coefficients")
        result[quantile[:32]] = {
            "quantile": _public_stat_number(fit.get("quantile")),
            "coefficients": {
                str(term)[:128]: _bounded_numeric_fields(cell, fields=numeric_fields)
                for term, cell in list(coefficients.items())[:32]
                if isinstance(term, str) and isinstance(cell, dict)
            } if isinstance(coefficients, dict) else {},
        }
    return result


def _bounded_quantile_intervals(value: Any) -> dict[str, dict[str, list[int | float]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, list[int | float]]] = {}
    for quantile, terms in list(value.items())[:7]:
        if not isinstance(quantile, str) or not isinstance(terms, dict):
            continue
        result[quantile[:32]] = {}
        for term, interval in list(terms.items())[:32]:
            if not isinstance(term, str) or not isinstance(interval, list) or len(interval) != 2:
                continue
            numbers = [_public_stat_number(item) for item in interval]
            if all(item is not None for item in numbers):
                result[quantile[:32]][term[:128]] = [numbers[0], numbers[1]]  # type: ignore[list-item]
    return result


def _bounded_bootstrap(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = _bounded_numeric_fields(value, fields=("repetitions", "random_state"))
    successful = value.get("successful_repetitions")
    if isinstance(successful, dict):
        result["successful_repetitions"] = {
            str(key)[:32]: number
            for key, item in list(successful.items())[:7]
            if (number := _public_positive_int(item)) is not None
        }
    result["intervals"] = _bounded_quantile_intervals(value.get("intervals"))
    return result


def _bounded_cross_quantile_comparisons(value: Any, *, limit: int = 32) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    numeric_fields = ("lower_quantile", "upper_quantile", "difference", "std_error", "p_value")
    result: list[dict[str, Any]] = []
    for row in value[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(_bounded_numeric_fields(row, fields=numeric_fields, string_fields=("term",)))
    return result


def _bounded_interval(value: Any) -> list[int | float] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    numbers = [_public_stat_number(item) for item in value]
    return numbers if all(number is not None for number in numbers) else None  # type: ignore[return-value]


def _bounded_effect_aggregate(value: Any) -> dict[str, Any] | None:
    """An aggregated treatment effect: estimate, standard error, intervals."""
    if not isinstance(value, dict):
        return None
    estimate = _public_stat_number(value.get("overall"))
    if estimate is None:
        return None
    result: dict[str, Any] = {
        "estimate": estimate,
        "std_error": _public_stat_number(value.get("overall_se")),
    }
    ci = _bounded_interval(value.get("overall_pointwise_ci"))
    if ci is not None:
        result["ci"] = ci
    band = _bounded_interval(value.get("overall_uniform_band"))
    if band is not None:
        result["uniform_band"] = band
    return result


def _bounded_effect_series(value: Any, *, limit: int = 24) -> dict[str, Any] | None:
    """Effects by event time, cohort or period, cut to ``limit`` rows.

    Rows keep their own interval and the simultaneous band, so an Agent asked
    whether pre-treatment effects are zero reads the same numbers the plot shows.
    """
    if not isinstance(value, dict):
        return None
    label_kind = _bounded_label(value.get("label_kind")) or "label"
    labels = value.get("event_time") if isinstance(value.get("event_time"), list) else value.get("label")
    estimates = value.get("estimate")
    if not isinstance(labels, list) or not isinstance(estimates, list):
        return None
    errors = value.get("se") if isinstance(value.get("se"), list) else []
    cis = value.get("pointwise_ci") if isinstance(value.get("pointwise_ci"), list) else []
    bands = value.get("uniform_band") if isinstance(value.get("uniform_band"), list) else []
    rows: list[dict[str, Any]] = []
    for position, label in enumerate(labels[:limit]):
        estimate = _public_stat_number(estimates[position]) if position < len(estimates) else None
        if estimate is None:
            continue
        row: dict[str, Any] = {
            "source_index": position,
            "label": label if _public_stat_number(label) is not None else _bounded_label(str(label)),
            "estimate": estimate,
            "std_error": _public_stat_number(errors[position]) if position < len(errors) else None,
        }
        ci = _bounded_interval(cis[position]) if position < len(cis) else None
        if ci is not None:
            row["ci"] = ci
        band = _bounded_interval(bands[position]) if position < len(bands) else None
        if band is not None:
            row["uniform_band"] = band
        rows.append(row)
    result: dict[str, Any] = {
        "label_kind": label_kind,
        "rows": rows,
        "rows_omitted": max(len(labels) - limit, 0),
    }
    overall = _bounded_effect_aggregate(value)
    if overall is not None:
        result["overall"] = overall
    return result


def _bounded_effect_point(value: Any) -> dict[str, Any] | None:
    """A headline effect reported as an estimate and a standard error only."""
    if not isinstance(value, dict):
        return None
    estimate = _public_stat_number(value.get("estimate"))
    if estimate is None:
        return None
    result: dict[str, Any] = {
        "estimate": estimate,
        "std_error": _public_stat_number(value.get("se", value.get("std_error"))),
    }
    if isinstance(value.get("experimental"), bool):
        result["experimental"] = value["experimental"]
    return result


def _bounded_tree(value: Any, *, depth: int = 3, width: int = 16) -> Any:
    """A nested result cut to finite numbers, short labels and few branches."""
    if isinstance(value, bool):
        return value
    number = _public_stat_number(value)
    if number is not None:
        return number
    if isinstance(value, str):
        return value[:256]
    if depth <= 0:
        return None
    if isinstance(value, list):
        return [_bounded_tree(item, depth=depth - 1, width=width) for item in value[:width]]
    if isinstance(value, dict):
        return {
            str(key)[:64]: _bounded_tree(item, depth=depth - 1, width=width)
            for key, item in list(value.items())[:width]
            if not str(key).startswith("_")
        }
    return None


def _bounded_honest_did(value: Any) -> dict[str, Any] | None:
    """Honest-DID sensitivity: each restriction's status and its intervals."""
    if not isinstance(value, dict):
        return None
    return {
        str(track)[:16]: _bounded_tree(block, depth=4, width=12)
        for track, block in list(value.items())[:4]
        if isinstance(block, dict) and not str(track).startswith("_")
    }
