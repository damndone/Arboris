"""Standalone categorical-count statistical kernels."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import chi2_contingency
from statsmodels.stats.contingency_tables import mcnemar

from workbench.contracts.model.categorical import (
    CATEGORICAL_CONTRACT,
    CATEGORICAL_CONTRACT_VERSION,
    CATEGORICAL_OPERATION_IDS,
    make_result_envelope,
)


MAX_TABLE_ROWS = 64
MAX_TABLE_COLUMNS = 64
MAX_TABLE_CELLS = 4096
_MAX_INTEGER_COUNT = np.iinfo(np.int64).max
_FLOAT64_SIGNIFICAND_BITS = 53


class CategoricalPackError(ValueError):
    """Stable, machine-readable categorical input or policy failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _reject(reason_code: str, message: str) -> None:
    raise CategoricalPackError(reason_code, message)


def _require_bool(value: Any, name: str) -> None:
    if type(value) is not bool:
        _reject("CATEGORICAL_INVALID_OPTION", f"{name} must be an explicit boolean")


def _is_exact_float64_integer(value: int) -> bool:
    """Check binary64 integer representability without converting the value."""

    if value <= 2**_FLOAT64_SIGNIFICAND_BITS:
        return True
    spacing_exponent = value.bit_length() - _FLOAT64_SIGNIFICAND_BITS
    return value % (1 << spacing_exponent) == 0


def _rows_from_table(table: Any) -> list[list[Any]]:
    if isinstance(table, np.ndarray):
        if table.ndim != 2:
            _reject("CATEGORICAL_INVALID_DIMENSIONS", "table must be two-dimensional")
        rows = table.tolist()
    elif isinstance(table, (list, tuple)):
        rows = list(table)
    else:
        _reject(
            "CATEGORICAL_BAD_TABLE",
            "table must be a nested list/tuple or a two-dimensional numpy array",
        )

    if not rows:
        _reject("CATEGORICAL_INVALID_DIMENSIONS", "table must not be empty")
    if len(rows) > MAX_TABLE_ROWS:
        _reject("CATEGORICAL_TABLE_TOO_LARGE", f"table has more than {MAX_TABLE_ROWS} rows")

    normalized_rows: list[list[Any]] = []
    for row in rows:
        if isinstance(row, np.ndarray):
            if row.ndim != 1:
                _reject("CATEGORICAL_INVALID_DIMENSIONS", "each table row must be one-dimensional")
            normalized_row = row.tolist()
        elif isinstance(row, (list, tuple)):
            normalized_row = list(row)
        else:
            _reject("CATEGORICAL_BAD_TABLE", "table rows must be arrays")
        normalized_rows.append(normalized_row)

    width = len(normalized_rows[0])
    if width == 0 or any(len(row) != width for row in normalized_rows):
        _reject("CATEGORICAL_INVALID_DIMENSIONS", "table must be rectangular")
    if width > MAX_TABLE_COLUMNS or len(normalized_rows) * width > MAX_TABLE_CELLS:
        _reject(
            "CATEGORICAL_TABLE_TOO_LARGE",
            f"table dimensions are bounded at {MAX_TABLE_ROWS}x{MAX_TABLE_COLUMNS}",
        )
    return normalized_rows


def _validate_count_table(
    table: Any, *, exact_dimensions: tuple[int, int] | None = None
) -> tuple[np.ndarray, tuple[tuple[int, ...], ...], int, int, int]:
    rows = _rows_from_table(table)
    n_rows = len(rows)
    n_columns = len(rows[0])
    if exact_dimensions is not None and (n_rows, n_columns) != exact_dimensions:
        _reject(
            "CATEGORICAL_INVALID_DIMENSIONS",
            f"table must have shape {exact_dimensions[0]}x{exact_dimensions[1]}",
        )
    if n_rows < 2 or n_columns < 2:
        _reject(
            "CATEGORICAL_INVALID_DIMENSIONS",
            "table must have at least two rows and two columns",
        )

    normalized: list[list[int]] = []
    for row in rows:
        normalized_row: list[int] = []
        for value in row:
            if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
                _reject("CATEGORICAL_NONFINITE_COUNT", "counts must be finite")
            if type(value) is bool or not (type(value) is int or isinstance(value, np.integer)):
                _reject("CATEGORICAL_NON_INTEGER_COUNT", "counts must already be integers")
            count = int(value)
            if count < 0:
                _reject("CATEGORICAL_NEGATIVE_COUNT", "counts must be non-negative")
            if count > _MAX_INTEGER_COUNT:
                _reject("CATEGORICAL_COUNT_TOO_LARGE", "counts exceed the supported integer range")
            if not _is_exact_float64_integer(count):
                _reject(
                    "CATEGORICAL_COUNT_NOT_EXACT",
                    "counts must be exactly representable by the float64 backend",
                )
            normalized_row.append(count)
        normalized.append(normalized_row)

    exact_table = tuple(tuple(row) for row in normalized)
    values = np.asarray(normalized, dtype=np.float64)
    if not np.isfinite(values).all():
        _reject("CATEGORICAL_NONFINITE_COUNT", "counts must be finite")
    sample_size = int(sum(sum(row) for row in normalized))
    return values, exact_table, n_rows, n_columns, sample_size


def _validate_positive_sample_and_margins(
    values: np.ndarray, sample_size: int, *, require_positive_margins: bool
) -> None:
    if sample_size <= 0:
        _reject("CATEGORICAL_EMPTY_TABLE", "table must contain at least one count")
    if require_positive_margins and (
        np.any(values.sum(axis=1) <= 0) or np.any(values.sum(axis=0) <= 0)
    ):
        _reject("CATEGORICAL_ZERO_MARGIN", "every row and column margin must be positive")


def _finite_float(value: Any, name: str) -> float:
    converted = float(value)
    if not math.isfinite(converted):
        _reject("CATEGORICAL_NONFINITE_RESULT", f"{name} is not finite")
    return converted


def fit_cramers_v(table: Any, *, correction: bool) -> dict[str, Any]:
    """Fit Pearson's chi-square test and Cramér's V for a count table."""

    _require_bool(correction, "correction")
    values, _, n_rows, n_columns, sample_size = _validate_count_table(table)
    _validate_positive_sample_and_margins(
        values, sample_size, require_positive_margins=True
    )
    if correction and (n_rows, n_columns) != (2, 2):
        _reject(
            "CATEGORICAL_UNSUPPORTED_CORRECTION",
            "Yates correction is declared only for a 2x2 table; refusing to ignore it",
        )

    try:
        result = chi2_contingency(values, correction=correction)
    except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
        raise CategoricalPackError(
            "CATEGORICAL_NUMERICAL_FAILURE", "scipy chi2_contingency could not evaluate the table"
        ) from exc

    chi_square = _finite_float(result.statistic, "chi_square")
    p_value = _finite_float(result.pvalue, "p_value")
    expected_counts = [
        [_finite_float(value, "expected_count") for value in row]
        for row in np.asarray(result.expected_freq).tolist()
    ]
    denominator = sample_size * min(n_rows - 1, n_columns - 1)
    cramers_v = _finite_float(math.sqrt(chi_square / denominator), "cramers_v")
    if not 0.0 <= cramers_v <= 1.0:
        _reject("CATEGORICAL_NONFINITE_RESULT", "cramers_v is outside its bounded range")

    expected_array = np.asarray(expected_counts, dtype=float)
    cells_total = int(expected_array.size)
    cells_below_5 = int(np.count_nonzero(expected_array < 5.0))
    diagnostics = {
        "cells_below_5": cells_below_5,
        "cells_total": cells_total,
        "fraction_below_5": _finite_float(cells_below_5 / cells_total, "fraction_below_5"),
        "maximum": _finite_float(expected_array.max(), "expected_count_maximum"),
        "minimum": _finite_float(expected_array.min(), "expected_count_minimum"),
    }
    payload = {
        "chi_square": chi_square,
        "degrees_of_freedom": int(result.dof),
        "p_value": p_value,
        "sample_size": sample_size,
        "cramers_v": cramers_v,
        "expected_counts": expected_counts,
        "expected_count_diagnostics": diagnostics,
        "method": "pearson_chi_square",
        "correction": correction,
        "correction_policy": "yates_2x2" if correction else "uncorrected",
    }
    return make_result_envelope(
        operation_id="categorical.cramers_v", result=payload
    )


def fit_mcnemar(
    table: Any, *, exact: bool, correction: bool
) -> dict[str, Any]:
    """Fit an explicitly selected exact or asymptotic McNemar test."""

    _require_bool(exact, "exact")
    _require_bool(correction, "correction")
    values, exact_table, _, _, sample_size = _validate_count_table(
        table, exact_dimensions=(2, 2)
    )
    _validate_positive_sample_and_margins(
        values, sample_size, require_positive_margins=False
    )

    b = exact_table[0][1]
    c = exact_table[1][0]
    discordant_total = b + c
    if discordant_total == 0:
        _reject(
            "CATEGORICAL_NO_DISCORDANCE",
            "McNemar requires at least one discordant pair",
        )
    if exact and correction:
        _reject(
            "CATEGORICAL_UNSUPPORTED_CORRECTION",
            "statsmodels exact McNemar does not apply continuity correction",
        )

    try:
        result = mcnemar(
            np.asarray(exact_table, dtype=np.int64),
            exact=exact,
            correction=correction,
        )
    except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
        raise CategoricalPackError(
            "CATEGORICAL_NUMERICAL_FAILURE", "statsmodels mcnemar could not evaluate the table"
        ) from exc

    statistic = _finite_float(result.statistic, "statistic")
    p_value = _finite_float(result.pvalue, "p_value")
    effect = {
        "discordant_total": discordant_total,
        "discordance_rate": _finite_float(
            discordant_total / sample_size, "discordance_rate"
        ),
        "directional_discordance": _finite_float(
            (b - c) / discordant_total, "directional_discordance"
        ),
    }
    payload = {
        "discordant_counts": {"b": b, "c": c},
        "statistic": statistic,
        "p_value": p_value,
        "method": "exact_binomial" if exact else "chi_square_asymptotic",
        "exact": exact,
        "correction": correction,
        "correction_policy": (
            "not_applicable_exact"
            if exact
            else ("yates_continuity" if correction else "uncorrected")
        ),
        "paired_effect": effect,
    }
    return make_result_envelope(operation_id="categorical.mcnemar", result=payload)


__all__ = [
    "CATEGORICAL_CONTRACT",
    "CATEGORICAL_CONTRACT_VERSION",
    "CATEGORICAL_OPERATION_IDS",
    "CategoricalPackError",
    "MAX_TABLE_CELLS",
    "MAX_TABLE_COLUMNS",
    "MAX_TABLE_ROWS",
    "fit_cramers_v",
    "fit_mcnemar",
]
