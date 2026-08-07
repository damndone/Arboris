"""Transparent internal-consistency reliability diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native, prepare_numeric_frame


def _validate_item_options(
    items: Sequence[str],
    reverse_scored: Sequence[str] | None,
    reverse_bounds: Mapping[str, Sequence[float]] | None,
) -> tuple[frozenset[str], dict[str, tuple[float, float]]]:
    item_set = frozenset(items)
    reverse_values = () if reverse_scored is None else tuple(reverse_scored)
    if any(type(item) is not str or not item for item in reverse_values):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "reverse_scored must contain item names"
        )
    if len(set(reverse_values)) != len(reverse_values):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION", "reverse_scored must not contain duplicates"
        )
    reverse_set = frozenset(reverse_values)
    unknown_reverse = reverse_set - item_set
    if unknown_reverse:
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "reverse_scored contains items outside the requested item order",
        )
    if reverse_bounds is None:
        bounds: Mapping[str, Sequence[float]] = {}
    else:
        if not isinstance(reverse_bounds, Mapping):
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION", "reverse_bounds must be a mapping"
            )
        bounds = reverse_bounds
    if set(bounds) - set(reverse_set) or reverse_set - set(bounds):
        raise MultivariatePackError(
            "MULTIVARIATE_INVALID_OPTION",
            "reverse_bounds must contain exactly the explicitly reverse-scored items",
        )
    normalized: dict[str, tuple[float, float]] = {}
    for item in reverse_values:
        raw_bounds = bounds[item]
        if (
            isinstance(raw_bounds, (str, bytes))
            or not isinstance(raw_bounds, Sequence)
            or len(raw_bounds) != 2
            or any(type(bound) not in (int, float) for bound in raw_bounds)
        ):
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                f"reverse bounds for {item!r} must be two finite numbers",
            )
        minimum, maximum = float(raw_bounds[0]), float(raw_bounds[1])
        if not np.isfinite(minimum) or not np.isfinite(maximum) or minimum >= maximum:
            raise MultivariatePackError(
                "MULTIVARIATE_INVALID_OPTION",
                f"reverse bounds for {item!r} must satisfy finite minimum < maximum",
            )
        normalized[item] = (minimum, maximum)
    return reverse_set, normalized


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if np.var(left, ddof=1) <= 0.0 or np.var(right, ddof=1) <= 0.0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if np.isfinite(value) else None


def _alpha_for_values(values: np.ndarray) -> float | None:
    if values.shape[1] < 2:
        return None
    total = values.sum(axis=1)
    total_variance = float(np.var(total, ddof=1))
    if total_variance <= 0.0 or not np.isfinite(total_variance):
        return None
    item_variance_sum = float(np.var(values, axis=0, ddof=1).sum())
    return float(values.shape[1] / (values.shape[1] - 1) * (1.0 - item_variance_sum / total_variance))


def cronbach_alpha(
    frame: pd.DataFrame,
    items: Sequence[str],
    *,
    reverse_scored: Sequence[str] | None = None,
    reverse_bounds: Mapping[str, Sequence[float]] | None = None,
    missing_policy: str = "complete_case_v1",
) -> dict[str, object]:
    """Compute alpha plus item-level diagnostics with explicit reverse scoring.

    Column names never trigger reverse scoring.  A reverse transformation is
    applied only when the caller supplies both the item name and its declared
    minimum/maximum scale bounds.
    """

    if isinstance(items, (str, bytes)):
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "items must be an array of item names"
        )
    try:
        normalized_items = tuple(items)
    except TypeError as exc:
        raise MultivariatePackError(
            "MULTIVARIATE_BAD_INPUT", "items must be an array of item names"
        ) from exc
    reverse_set, bounds = _validate_item_options(
        normalized_items,
        reverse_scored,
        reverse_bounds,
    )
    prepared = prepare_numeric_frame(
        frame,
        list(normalized_items),
        missing_policy=missing_policy,
    )
    values = prepared.frame.to_numpy(dtype=float, copy=True)
    item_indices = {item: index for index, item in enumerate(normalized_items)}
    for item in normalized_items:
        if item in reverse_set:
            minimum, maximum = bounds[item]
            index = item_indices[item]
            values[:, index] = maximum + minimum - values[:, index]

    total = values.sum(axis=1)
    total_variance = float(np.var(total, ddof=1))
    if total_variance <= 0.0 or not np.isfinite(total_variance):
        raise MultivariatePackError(
            "MULTIVARIATE_INSUFFICIENT_VARIANCE",
            "total score variance must be positive for Cronbach alpha",
        )
    alpha = _alpha_for_values(values)
    if alpha is None:
        raise MultivariatePackError(
            "MULTIVARIATE_INSUFFICIENT_VARIANCE",
            "Cronbach alpha is undefined for this item set",
        )

    diagnostics: list[dict[str, object]] = []
    for index, item in enumerate(normalized_items):
        rest = total - values[:, index]
        deleted = np.delete(values, index, axis=1)
        diagnostics.append(
            {
                "item": item,
                "corrected_item_total_correlation": _safe_correlation(
                    values[:, index], rest
                ),
                "alpha_if_deleted": _alpha_for_values(deleted),
            }
        )

    reverse_manifest = [
        {
            "item": item,
            "minimum": bounds[item][0],
            "maximum": bounds[item][1],
        }
        for item in normalized_items
        if item in reverse_set
    ]
    result = {
        "item_order": list(normalized_items),
        "missing_policy": prepared.missing_policy,
        "reverse_scoring": reverse_manifest,
        "alpha": alpha,
        "item_diagnostics": diagnostics,
        "retained_positions": list(prepared.retained_positions),
    }
    return make_result_envelope(
        operation_id="multivariate.cronbach_alpha",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=prepared.n_observations,
        columns=prepared.columns,
        result=json_native(result),
    )


__all__ = ["cronbach_alpha"]
