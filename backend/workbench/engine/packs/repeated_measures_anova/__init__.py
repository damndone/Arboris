"""Bounded classical repeated-measures and mixed-design ANOVA kernels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2, f as f_distribution
from statsmodels.stats.anova import AnovaRM

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.repeated_measures_anova import (
    MIXED_DESIGN_OPERATION_ID,
    REPEATED_MEASURES_ANOVA_COMPLETED,
    REPEATED_MEASURES_ANOVA_CONTRACT,
    REPEATED_MEASURES_ANOVA_CONTRACT_VERSION,
    REPEATED_MEASURES_ANOVA_CORRECTIONS,
    REPEATED_MEASURES_ANOVA_OPERATION_IDS,
    REPEATED_MEASURES_ANOVA_REASON_CODES,
    REPEATED_ONLY_OPERATION_ID,
    RepeatedMeasuresAnovaInput,
    make_result_envelope,
)


MAX_ROWS = 100_000
MAX_SUBJECTS = 2_000
MAX_FACTOR_LEVELS = 32
MAX_WITHIN_FACTORS = 1
MAX_BETWEEN_FACTORS = 1
MAX_RESULT_POSITIONS = 16
MAX_ECHOED_COLUMNS = 4


class RepeatedMeasuresAnovaPackError(ValueError):
    """Stable, machine-readable failure from the ANOVA pack boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class _PreparedDesign:
    y: np.ndarray
    subject_values: tuple[Any, ...]
    within_values: tuple[Any, ...]
    between_values: tuple[Any, ...]
    subject_group_indices: tuple[int, ...]
    working_frame: pd.DataFrame


def _fail(reason_code: str, message: str) -> None:
    raise RepeatedMeasuresAnovaPackError(reason_code, message)


def _require_column_name(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        _fail(
            "REPEATED_MEASURES_ANOVA_BAD_INPUT",
            f"{field_name} must be a non-empty string",
        )
    return value


def _normalize_within_columns(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(
            "REPEATED_MEASURES_ANOVA_BAD_INPUT",
            "within_factor_columns must be an array of column names",
        )
    columns = list(value)
    if len(columns) != MAX_WITHIN_FACTORS:
        _fail(
            "REPEATED_MEASURES_ANOVA_UNSUPPORTED_WITHIN_FACTORS",
            "exactly one within factor is supported in this version",
        )
    if any(type(column) is not str or not column for column in columns):
        _fail(
            "REPEATED_MEASURES_ANOVA_BAD_INPUT",
            "within_factor_columns must contain non-empty strings",
        )
    if len(set(columns)) != len(columns):
        _fail(
            "REPEATED_MEASURES_ANOVA_DUPLICATE_COLUMN",
            "within_factor_columns must not contain duplicates",
        )
    return columns


def _validate_declaration(
    *,
    operation_id: object,
    response_column: object,
    subject_column: object,
    within_factor_columns: object,
    between_factor_column: object,
    correction: object,
    formula: object,
    eval: object,
) -> RepeatedMeasuresAnovaInput:
    if type(operation_id) is not str or operation_id not in REPEATED_MEASURES_ANOVA_OPERATION_IDS:
        _fail(
            "REPEATED_MEASURES_ANOVA_UNKNOWN_OPERATION",
            "operation_id is not a declared repeated-measures operation",
        )
    if formula is not None or eval is not None:
        _fail(
            "REPEATED_MEASURES_ANOVA_UNSUPPORTED_FORMULA",
            "formula and eval inputs are not accepted; use structured column names",
        )
    response = _require_column_name(response_column, "response_column")
    subject = _require_column_name(subject_column, "subject_column")
    within = _normalize_within_columns(within_factor_columns)
    if len({response, subject, *within}) != 2 + len(within):
        _fail(
            "REPEATED_MEASURES_ANOVA_DUPLICATE_COLUMN",
            "response, subject, and within columns must be distinct",
        )
    if type(correction) is not str or correction not in REPEATED_MEASURES_ANOVA_CORRECTIONS:
        _fail(
            "REPEATED_MEASURES_ANOVA_INVALID_CORRECTION",
            "correction must be none, greenhouse_geisser, or huynh_feldt",
        )

    between: str | None
    if isinstance(between_factor_column, (list, tuple)):
        if len(between_factor_column) != MAX_BETWEEN_FACTORS:
            _fail(
                "REPEATED_MEASURES_ANOVA_MULTIPLE_BETWEEN_FACTORS",
                "mixed design accepts exactly one between factor column",
            )
        _fail(
            "REPEATED_MEASURES_ANOVA_BAD_INPUT",
            "between_factor_column must be a column name, not an array",
        )
    if operation_id == MIXED_DESIGN_OPERATION_ID:
        if between_factor_column is None:
            _fail(
                "REPEATED_MEASURES_ANOVA_INVALID_DESIGN",
                "mixed design requires exactly one between factor column",
            )
        between = _require_column_name(between_factor_column, "between_factor_column")
        if between in {response, subject, *within}:
            _fail(
                "REPEATED_MEASURES_ANOVA_DUPLICATE_COLUMN",
                "between_factor_column must be distinct from other columns",
            )
    else:
        if between_factor_column is not None:
            _fail(
                "REPEATED_MEASURES_ANOVA_INVALID_DESIGN",
                "repeated-only operation cannot declare a between factor",
            )
        between = None

    try:
        return RepeatedMeasuresAnovaInput(
            operation_id=operation_id,
            response_column=response,
            subject_column=subject,
            within_factor_columns=tuple(within),
            between_factor_column=between,
            correction=correction,
        )
    except ContractError as exc:
        _fail("REPEATED_MEASURES_ANOVA_BAD_INPUT", str(exc))


def _is_missing(value: object) -> bool:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, (bool, np.bool_)) and bool(missing)


def _normalized_label(value: object, column: str) -> tuple[tuple[str, Any], Any]:
    if isinstance(value, np.generic):
        value = value.item()
    if _is_missing(value):
        _fail(
            "REPEATED_MEASURES_ANOVA_EMPTY_LEVEL",
            f"column {column!r} contains a missing level",
        )
    if type(value) is str:
        if not value:
            _fail(
                "REPEATED_MEASURES_ANOVA_EMPTY_LEVEL",
                f"column {column!r} contains an empty level",
            )
        return ("str", value), value
    if type(value) is bool:
        return ("bool", value), value
    if type(value) is int:
        return ("int", value), value
    if type(value) is float:
        if not math.isfinite(value):
            _fail(
                "REPEATED_MEASURES_ANOVA_EMPTY_LEVEL",
                f"column {column!r} contains a non-finite level",
            )
        return ("float", value), value
    _fail(
        "REPEATED_MEASURES_ANOVA_INVALID_LEVEL",
        f"column {column!r} contains an unsupported level type",
    )


def _require_homogeneous_label_kinds(
    keys: Sequence[tuple[str, Any]],
    column: str,
) -> None:
    kinds = {key[0] for key in keys}
    if len(kinds) > 1:
        _fail(
            "REPEATED_MEASURES_ANOVA_INVALID_LEVEL",
            f"column {column!r} contains heterogeneous label types",
        )


def _check_declared_categorical_levels(selected: pd.DataFrame, column: str) -> None:
    dtype = selected[column].dtype
    if not isinstance(dtype, pd.CategoricalDtype):
        return
    observed: set[tuple[str, Any]] = set()
    for value in selected[column].tolist():
        key, _ = _normalized_label(value, column)
        observed.add(key)
    for value in dtype.categories.tolist():
        key, _ = _normalized_label(value, column)
        if key not in observed:
            _fail(
                "REPEATED_MEASURES_ANOVA_EMPTY_LEVEL",
                f"column {column!r} declares an empty level",
            )


def _prepare_design(frame: pd.DataFrame, request: RepeatedMeasuresAnovaInput) -> _PreparedDesign:
    if not isinstance(frame, pd.DataFrame):
        _fail("REPEATED_MEASURES_ANOVA_BAD_INPUT", "frame must be a pandas DataFrame")
    if len(frame) > MAX_ROWS:
        _fail(
            "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
            f"row count exceeds the bound of {MAX_ROWS}",
        )
    if not frame.columns.is_unique:
        _fail(
            "REPEATED_MEASURES_ANOVA_DUPLICATE_COLUMN",
            "frame columns must be unique",
        )

    within_column = request.within_factor_columns[0]
    selected_columns = [request.response_column, request.subject_column, within_column]
    if request.between_factor_column is not None:
        selected_columns.append(request.between_factor_column)
    missing = [column for column in selected_columns if column not in frame.columns]
    if missing:
        _fail(
            "REPEATED_MEASURES_ANOVA_MISSING_COLUMN",
            "unknown columns: " + ", ".join(missing),
        )
    selected = frame.loc[:, selected_columns].copy()
    if selected.empty:
        _fail(
            "REPEATED_MEASURES_ANOVA_TOO_FEW_SUBJECTS",
            "at least two subjects and two within levels are required",
        )

    response_series = selected[request.response_column]
    if (
        not pd.api.types.is_numeric_dtype(response_series.dtype)
        or pd.api.types.is_bool_dtype(response_series.dtype)
        or pd.api.types.is_complex_dtype(response_series.dtype)
    ):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_NUMERIC_RESPONSE",
            "response_column must be a real numeric column",
        )
    try:
        response = response_series.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_NUMERIC_RESPONSE",
            "response_column cannot be represented as real numbers",
        )
        raise AssertionError("unreachable") from exc
    if not np.isfinite(response).all():
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESPONSE",
            "response_column contains NaN or infinite values",
        )

    for column in selected_columns[1:]:
        _check_declared_categorical_levels(selected, column)

    subject_keys: list[tuple[str, Any]] = []
    subject_public: list[Any] = []
    within_keys: list[tuple[str, Any]] = []
    within_public: list[Any] = []
    between_keys: list[tuple[str, Any]] = []
    between_public: list[Any] = []
    for value in selected[request.subject_column].tolist():
        key, public = _normalized_label(value, request.subject_column)
        subject_keys.append(key)
        subject_public.append(public)
    for value in selected[within_column].tolist():
        key, public = _normalized_label(value, within_column)
        within_keys.append(key)
        within_public.append(public)
    if request.between_factor_column is not None:
        for value in selected[request.between_factor_column].tolist():
            key, public = _normalized_label(value, request.between_factor_column)
            between_keys.append(key)
            between_public.append(public)

    _require_homogeneous_label_kinds(subject_keys, request.subject_column)
    _require_homogeneous_label_kinds(within_keys, within_column)
    if request.between_factor_column is not None:
        _require_homogeneous_label_kinds(
            between_keys,
            request.between_factor_column,
        )

    subject_order: list[tuple[str, Any]] = []
    subject_values: list[Any] = []
    subject_index: dict[tuple[str, Any], int] = {}
    within_order: list[tuple[str, Any]] = []
    within_values: list[Any] = []
    within_index: dict[tuple[str, Any], int] = {}
    between_order: list[tuple[str, Any]] = []
    between_values: list[Any] = []
    between_index: dict[tuple[str, Any], int] = {}
    for key, public in zip(subject_keys, subject_public):
        if key not in subject_index:
            subject_index[key] = len(subject_order)
            subject_order.append(key)
            subject_values.append(public)
    for key, public in zip(within_keys, within_public):
        if key not in within_index:
            within_index[key] = len(within_order)
            within_order.append(key)
            within_values.append(public)
    for key, public in zip(between_keys, between_public):
        if key not in between_index:
            between_index[key] = len(between_order)
            between_order.append(key)
            between_values.append(public)

    if len(subject_order) > MAX_SUBJECTS:
        _fail(
            "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
            f"subject count exceeds the bound of {MAX_SUBJECTS}",
        )
    if len(subject_order) < 2:
        _fail(
            "REPEATED_MEASURES_ANOVA_TOO_FEW_SUBJECTS",
            "at least two subjects are required",
        )
    if len(within_order) < 2:
        _fail(
            "REPEATED_MEASURES_ANOVA_TOO_FEW_LEVELS",
            "within factor must contain at least two observed levels",
        )
    if len(within_order) > MAX_FACTOR_LEVELS:
        _fail(
            "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
            f"within level count exceeds the bound of {MAX_FACTOR_LEVELS}",
        )
    if request.between_factor_column is not None:
        if len(between_order) < 2:
            _fail(
                "REPEATED_MEASURES_ANOVA_TOO_FEW_LEVELS",
                "between factor must contain at least two observed levels",
            )
        if len(between_order) > MAX_FACTOR_LEVELS:
            _fail(
                "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
                f"between level count exceeds the bound of {MAX_FACTOR_LEVELS}",
            )

    cell_keys = list(zip(subject_keys, within_keys))
    if len(set(cell_keys)) != len(cell_keys):
        _fail(
            "REPEATED_MEASURES_ANOVA_DUPLICATE_CELL",
            "each subject by within-factor cell must occur exactly once",
        )
    expected_cells = len(subject_order) * len(within_order)
    if len(cell_keys) != expected_cells:
        _fail(
            "REPEATED_MEASURES_ANOVA_INCOMPLETE_BALANCE",
            "every subject must contain every within-factor level",
        )

    subject_group_keys: dict[tuple[str, Any], tuple[str, Any]] = {}
    if request.between_factor_column is not None:
        for subject_key, between_key in zip(subject_keys, between_keys):
            previous = subject_group_keys.setdefault(subject_key, between_key)
            if previous != between_key:
                _fail(
                    "REPEATED_MEASURES_ANOVA_INCONSISTENT_BETWEEN_LABEL",
                    "each subject must have one stable between-factor label",
                )
        subjects_per_group = [
            sum(1 for value in subject_group_keys.values() if value == key)
            for key in between_order
        ]
        if len(set(subjects_per_group)) != 1:
            _fail(
                "REPEATED_MEASURES_ANOVA_INCOMPLETE_BALANCE",
                "between-factor groups must contain the same number of subjects",
            )

    y = np.empty((len(subject_order), len(within_order)), dtype=float)
    y.fill(np.nan)
    for value, subject_key, within_key in zip(response, subject_keys, within_keys):
        y[subject_index[subject_key], within_index[within_key]] = value
    if not np.isfinite(y).all():
        _fail(
            "REPEATED_MEASURES_ANOVA_INCOMPLETE_BALANCE",
            "the balanced subject by within matrix is incomplete",
        )

    subject_group_indices = tuple(
        between_index[subject_group_keys[key]] if between_order else 0
        for key in subject_order
    )
    working = pd.DataFrame(
        {
            request.response_column: response,
            request.subject_column: subject_public,
            within_column: within_public,
        }
    )
    working[within_column] = pd.Categorical(
        working[within_column], categories=within_values, ordered=True
    )
    if request.between_factor_column is not None:
        working[request.between_factor_column] = between_public

    return _PreparedDesign(
        y=y,
        subject_values=tuple(subject_values),
        within_values=tuple(within_values),
        between_values=tuple(between_values),
        subject_group_indices=subject_group_indices,
        working_frame=working,
    )


def _finite(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            f"{field_name} is not a finite number",
        )
        raise AssertionError("unreachable") from exc
    if not math.isfinite(number):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            f"{field_name} is not finite",
        )
    return number


def _is_effectively_zero(value: float, scale: float) -> bool:
    if not math.isfinite(value) or not math.isfinite(scale):
        return True
    relative_scale = max(abs(scale), np.finfo(float).tiny)
    return value <= np.finfo(float).eps * relative_scale


def _json_native(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_json_native(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _finite(value, "result")
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            _fail(
                "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
                "result mapping keys must be strings",
            )
        return {key: _json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(item) for item in value]
    if type(value) is float:
        return _finite(value, "result")
    return value


def _sphericity(
    y: np.ndarray,
    *,
    within_factor: str,
    correction: str,
    hf_error_df: float | None = None,
    mauchly_provenance: str = "subject_within_error_df_per_within_contrast",
) -> dict[str, Any]:
    n_subjects, n_levels = y.shape
    if n_levels == 2:
        return {
            "applicable": False,
            "within_factor": within_factor,
            "mauchly": None,
            "epsilon": {
                "greenhouse_geisser": 1.0,
                "huynh_feldt": 1.0,
                "selected": 1.0,
            },
            "reason": "two_level_within_factor",
        }

    contrasts = np.zeros((n_levels - 1, n_levels), dtype=float)
    for index in range(n_levels - 1):
        denominator = math.sqrt((index + 1) * (index + 2))
        contrasts[index, : index + 1] = 1.0 / denominator
        contrasts[index, index + 1] = -(index + 1) / denominator
    transformed = y @ contrasts.T
    covariance = np.atleast_2d(np.cov(transformed, rowvar=False, ddof=1))
    if not np.isfinite(covariance).all():
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "sphericity covariance contains a non-finite value",
        )
    eigenvalues = np.linalg.eigvalsh(covariance)
    if not np.isfinite(eigenvalues).all():
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "sphericity covariance eigenvalues contain a non-finite value",
        )
    scale = max(float(np.max(np.abs(eigenvalues))), np.finfo(float).tiny)
    if np.any(eigenvalues <= np.finfo(float).eps * scale):
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "sphericity covariance is singular",
        )
    dimension = n_levels - 1
    trace = float(np.trace(covariance))
    trace_square = float(np.trace(covariance @ covariance))
    if not math.isfinite(trace) or not math.isfinite(trace_square):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "sphericity trace calculation is not finite",
        )
    if trace <= 0.0 or trace_square <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "sphericity covariance has no positive trace",
        )
    epsilon_gg = (trace * trace) / (dimension * trace_square)
    if not math.isfinite(epsilon_gg):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Greenhouse-Geisser epsilon is not finite",
        )
    epsilon_lower = 1.0 / dimension
    epsilon_gg = min(1.0, max(epsilon_lower, epsilon_gg))
    if not math.isfinite(epsilon_gg):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "bounded Greenhouse-Geisser epsilon is not finite",
        )
    reference_error_df = (
        float((n_subjects - 1) * dimension)
        if hf_error_df is None
        else float(hf_error_df)
    )
    if not math.isfinite(reference_error_df):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Huynh-Feldt reference error degrees of freedom are not finite",
        )
    if reference_error_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "Huynh-Feldt reference error degrees of freedom are not positive",
        )
    reference_subjects = reference_error_df / dimension + 1.0
    hf_denominator = dimension * (
        reference_subjects - 1.0 - dimension * epsilon_gg
    )
    if not math.isfinite(hf_denominator):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Huynh-Feldt epsilon denominator is not finite",
        )
    if hf_denominator <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "Huynh-Feldt epsilon denominator is not positive",
        )
    epsilon_hf = (
        reference_subjects * dimension * epsilon_gg - 2.0
    ) / hf_denominator
    if not math.isfinite(epsilon_hf):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Huynh-Feldt epsilon is not finite",
        )
    epsilon_hf = min(1.0, max(epsilon_lower, epsilon_hf))
    if not math.isfinite(epsilon_hf):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "bounded Huynh-Feldt epsilon is not finite",
        )
    sign, log_determinant = np.linalg.slogdet(covariance)
    if sign <= 0.0 or not math.isfinite(float(log_determinant)):
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "Mauchly determinant is not positive",
        )
    log_w = float(log_determinant) - dimension * math.log(trace / dimension)
    if not math.isfinite(log_w):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly log determinant is not finite",
        )
    try:
        w = math.exp(log_w)
    except OverflowError as exc:
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly determinant overflows",
        )
        raise AssertionError("unreachable") from exc
    if not math.isfinite(w):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly determinant is not finite",
        )
    mauchly_effective_sample_df = reference_error_df / dimension
    if not math.isfinite(mauchly_effective_sample_df):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly effective sample df is not finite",
        )
    if mauchly_effective_sample_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "Mauchly effective sample df is not positive",
        )
    rho = 1.0 - (
        2.0 * dimension * dimension + dimension + 2.0
    ) / (6.0 * dimension * mauchly_effective_sample_df)
    if not math.isfinite(rho) or rho <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly correction rho is not positive and finite",
        )
    w2_denominator = (
        288.0
        * (mauchly_effective_sample_df * dimension * rho) ** 2
    )
    w2 = (
        (dimension + 2.0)
        * (dimension - 1.0)
        * (dimension - 2.0)
        * (
            2.0 * dimension**3
            + 6.0 * dimension**2
            + 3.0 * n_levels
            + 2.0
        )
        / w2_denominator
    )
    if not math.isfinite(w2):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly second-order correction is not finite",
        )
    mauchly_df = dimension * (dimension + 1.0) / 2.0 - 1.0
    if mauchly_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_SPHERICITY",
            "Mauchly evidence does not have positive degrees of freedom",
        )
    mauchly_chi_square = -mauchly_effective_sample_df * rho * log_w
    mauchly_p_primary = chi2.sf(mauchly_chi_square, mauchly_df)
    mauchly_p_secondary = chi2.sf(mauchly_chi_square, mauchly_df + 4.0)
    mauchly_p = mauchly_p_primary + w2 * (
        mauchly_p_secondary - mauchly_p_primary
    )
    if not all(
        math.isfinite(value)
        for value in (
            mauchly_chi_square,
            mauchly_p_primary,
            mauchly_p_secondary,
            mauchly_p,
        )
    ):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "Mauchly evidence is not finite",
        )
    selected = 1.0 if correction == "none" else (
        epsilon_gg if correction == "greenhouse_geisser" else epsilon_hf
    )
    return {
        "applicable": True,
        "within_factor": within_factor,
        "mauchly": {
            "w": _finite(w, "mauchly.w"),
            "chi_square": _finite(mauchly_chi_square, "mauchly.chi_square"),
            "df": _finite(mauchly_df, "mauchly.df"),
            "p_value": _finite(mauchly_p, "mauchly.p_value"),
            "correction": {
                "policy": "stats_mauchly_test_rho_w2",
                "provenance": mauchly_provenance,
                "residual_error_df": _finite(
                    reference_error_df,
                    "mauchly.residual_error_df",
                ),
                "effective_sample_df": _finite(
                    mauchly_effective_sample_df,
                    "mauchly.effective_sample_df",
                ),
            },
        },
        "epsilon": {
            "greenhouse_geisser": _finite(epsilon_gg, "epsilon.greenhouse_geisser"),
            "huynh_feldt": _finite(epsilon_hf, "epsilon.huynh_feldt"),
            "selected": _finite(selected, "epsilon.selected"),
        },
        "reason": "sphericity_evidence_reported",
    }


def _correction_for_effect(
    *,
    f_value: float,
    numerator_df: float,
    denominator_df: float,
    sphericity: Mapping[str, Any],
    correction: str,
    apply: bool,
) -> tuple[float, float, float, dict[str, Any]]:
    correction_applied = bool(
        apply
        and correction != "none"
        and bool(sphericity.get("applicable", False))
    )
    if correction_applied:
        epsilon = float(sphericity["epsilon"][correction])
    else:
        epsilon = 1.0
    corrected_num_df = numerator_df * epsilon
    corrected_den_df = denominator_df * epsilon
    if corrected_num_df <= 0.0 or corrected_den_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "corrected error degrees of freedom are not positive",
        )
    if correction_applied:
        p_value = f_distribution.sf(f_value, corrected_num_df, corrected_den_df)
    else:
        p_value = f_distribution.sf(f_value, numerator_df, denominator_df)
    return (
        _finite(corrected_num_df, "effect.df"),
        _finite(corrected_den_df, "effect.df_error"),
        _finite(p_value, "effect.p_value"),
        {
            "policy": correction,
            "applied": correction_applied,
            "epsilon": _finite(epsilon, "effect.epsilon"),
        },
    )


def _effect_row(
    *,
    term: str,
    sum_sq: float,
    numerator_df: float,
    denominator_df: float,
    f_value: float,
    error_layer: str,
    sphericity: Mapping[str, Any],
    correction: str,
    correct_sphericity: bool,
    p_value_override: float | None = None,
) -> dict[str, Any]:
    sum_sq = _finite(sum_sq, f"{term}.sum_sq")
    numerator_df = _finite(numerator_df, f"{term}.df")
    denominator_df = _finite(denominator_df, f"{term}.df_error")
    f_value = _finite(f_value, f"{term}.f")
    if numerator_df <= 0.0 or denominator_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            f"{term} does not have positive degrees of freedom",
        )
    mean_sq = _finite(sum_sq / numerator_df, f"{term}.mean_sq")
    corrected_num_df, corrected_den_df, corrected_p, correction_payload = (
        _correction_for_effect(
            f_value=f_value,
            numerator_df=numerator_df,
            denominator_df=denominator_df,
            sphericity=sphericity,
            correction=correction,
            apply=correct_sphericity,
        )
    )
    if p_value_override is not None and not correction_payload["applied"]:
        corrected_p = _finite(p_value_override, f"{term}.p_value")
    return {
        "term": term,
        "sum_sq": sum_sq,
        "df": corrected_num_df,
        "mean_sq": mean_sq,
        "f": f_value,
        "p_value": corrected_p,
        "df_error": corrected_den_df,
        "error_layer": error_layer,
        "correction": correction_payload,
    }


def _repeated_only_stats(
    prepared: _PreparedDesign,
    request: RepeatedMeasuresAnovaInput,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    y = prepared.y
    n_subjects, n_levels = y.shape
    grand_mean = float(np.mean(y))
    subject_means = np.mean(y, axis=1)
    within_means = np.mean(y, axis=0)
    sum_sq = float(np.sum((y - grand_mean) ** 2))
    subject_sum_sq = float(n_levels * np.sum((subject_means - grand_mean) ** 2))
    within_sum_sq = float(n_subjects * np.sum((within_means - grand_mean) ** 2))
    error_residual = (
        y
        - subject_means[:, None]
        - within_means[None, :]
        + grand_mean
    )
    error_sum_sq = float(np.sum(error_residual**2))
    numerator_df = float(n_levels - 1)
    denominator_df = float((n_subjects - 1) * (n_levels - 1))
    if denominator_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "subject:within error layer is singular or degenerate",
        )
    if not all(
        math.isfinite(value)
        for value in (sum_sq, subject_sum_sq, within_sum_sq, error_sum_sq)
    ):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "repeated-measures sums of squares are not finite",
        )
    error_scale = max(
        abs(sum_sq),
        abs(subject_sum_sq),
        abs(within_sum_sq),
        abs(error_sum_sq),
        np.finfo(float).tiny,
    )
    if _is_effectively_zero(error_sum_sq, error_scale):
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "subject:within error layer is singular or degenerate",
        )
    error_mean_sq = error_sum_sq / denominator_df
    if not math.isfinite(error_mean_sq) or error_mean_sq <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "subject:within mean square is not positive",
        )

    try:
        statsmodels_table = AnovaRM(
            prepared.working_frame,
            depvar=request.response_column,
            subject=request.subject_column,
            within=[request.within_factor_columns[0]],
            aggregate_func=None,
        ).fit().anova_table
    except (ValueError, np.linalg.LinAlgError, TypeError) as exc:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            f"statsmodels.AnovaRM could not fit the validated design: {exc}",
        )
    statsmodels_row = statsmodels_table.iloc[0]
    statsmodels_f = _finite(statsmodels_row["F Value"], "AnovaRM.F Value")
    statsmodels_p = _finite(statsmodels_row["Pr > F"], "AnovaRM.Pr > F")
    sphericity = _sphericity(
        y,
        within_factor=request.within_factor_columns[0],
        correction=request.correction,
        hf_error_df=denominator_df,
        mauchly_provenance=(
            "repeated_only_subject_within_error_df_per_within_contrast"
        ),
    )
    effect = _effect_row(
        term=request.within_factor_columns[0],
        sum_sq=within_sum_sq,
        numerator_df=numerator_df,
        denominator_df=denominator_df,
        f_value=statsmodels_f,
        error_layer="subject:within",
        sphericity=sphericity,
        correction=request.correction,
        correct_sphericity=True,
        p_value_override=statsmodels_p,
    )
    error_layer = {
        "name": "subject:within",
        "sum_sq": _finite(error_sum_sq, "subject:within.sum_sq"),
        "df": _finite(denominator_df, "subject:within.df"),
        "mean_sq": _finite(error_mean_sq, "subject:within.mean_sq"),
    }
    return [effect], [error_layer], sphericity


def _mixed_stats(
    prepared: _PreparedDesign,
    request: RepeatedMeasuresAnovaInput,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    y = prepared.y
    n_subjects, n_levels = y.shape
    n_groups = len(prepared.between_values)
    group_indices = np.asarray(prepared.subject_group_indices, dtype=int)
    subjects_per_group = np.bincount(group_indices, minlength=n_groups)
    if len(set(subjects_per_group.tolist())) != 1:
        _fail(
            "REPEATED_MEASURES_ANOVA_INCOMPLETE_BALANCE",
            "between-factor groups must contain the same number of subjects",
        )
    subjects_per_group_value = int(subjects_per_group[0])
    grand_mean = float(np.mean(y))
    subject_means = np.mean(y, axis=1)
    within_means = np.mean(y, axis=0)
    group_means = np.asarray(
        [np.mean(y[group_indices == group_index, :]) for group_index in range(n_groups)]
    )
    group_within_means = np.asarray(
        [
            np.mean(y[group_indices == group_index, :], axis=0)
            for group_index in range(n_groups)
        ]
    )
    between_sum_sq = float(
        subjects_per_group_value
        * n_levels
        * np.sum((group_means - grand_mean) ** 2)
    )
    subject_between_sum_sq = float(
        n_levels
        * np.sum(
            [
                (subject_means[index] - group_means[group_indices[index]]) ** 2
                for index in range(n_subjects)
            ]
        )
    )
    within_sum_sq = float(
        n_subjects * np.sum((within_means - grand_mean) ** 2)
    )
    interaction_sum_sq = float(
        subjects_per_group_value
        * np.sum(
            (
                group_within_means
                - group_means[:, None]
                - within_means[None, :]
                + grand_mean
            )
            ** 2
        )
    )
    error_residual = np.empty_like(y)
    for subject_index in range(n_subjects):
        group_index = group_indices[subject_index]
        error_residual[subject_index, :] = (
            y[subject_index, :]
            - subject_means[subject_index]
            - group_within_means[group_index, :]
            + group_means[group_index]
        )
    subject_within_sum_sq = float(np.sum(error_residual**2))
    if not all(
        math.isfinite(value)
        for value in (
            between_sum_sq,
            subject_between_sum_sq,
            within_sum_sq,
            interaction_sum_sq,
            subject_within_sum_sq,
        )
    ):
        _fail(
            "REPEATED_MEASURES_ANOVA_NON_FINITE_RESULT",
            "mixed-design sums of squares are not finite",
        )
    between_df = float(n_groups - 1)
    subject_between_df = float(n_groups * (subjects_per_group_value - 1))
    within_df = float(n_levels - 1)
    subject_within_df = float(
        n_groups * (subjects_per_group_value - 1) * (n_levels - 1)
    )
    interaction_df = float((n_groups - 1) * (n_levels - 1))
    if subject_between_df <= 0.0 or subject_within_df <= 0.0:
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "mixed-design error layers do not have positive degrees of freedom",
        )
    subject_between_mean_sq = subject_between_sum_sq / subject_between_df
    subject_within_mean_sq = subject_within_sum_sq / subject_within_df
    subject_between_scale = max(
        abs(between_sum_sq),
        abs(subject_between_sum_sq),
        np.finfo(float).tiny,
    )
    subject_within_scale = max(
        abs(within_sum_sq),
        abs(interaction_sum_sq),
        abs(subject_within_sum_sq),
        np.finfo(float).tiny,
    )
    if (
        not math.isfinite(subject_between_mean_sq)
        or not math.isfinite(subject_within_mean_sq)
        or _is_effectively_zero(subject_between_sum_sq, subject_between_scale)
        or _is_effectively_zero(subject_within_sum_sq, subject_within_scale)
    ):
        _fail(
            "REPEATED_MEASURES_ANOVA_SINGULAR_ERROR_LAYER",
            "mixed-design subject error layer is singular or degenerate",
        )
    sphericity_residual = y - group_within_means[group_indices, :]
    sphericity = _sphericity(
        sphericity_residual,
        within_factor=request.within_factor_columns[0],
        correction=request.correction,
        hf_error_df=subject_within_df,
        mauchly_provenance=(
            "mixed_subject_within_error_df_per_within_contrast"
        ),
    )
    between_f = between_sum_sq / between_df / subject_between_mean_sq
    within_f = within_sum_sq / within_df / subject_within_mean_sq
    interaction_f = interaction_sum_sq / interaction_df / subject_within_mean_sq
    effects = [
        _effect_row(
            term=request.between_factor_column or "between",
            sum_sq=between_sum_sq,
            numerator_df=between_df,
            denominator_df=subject_between_df,
            f_value=between_f,
            error_layer="subject:between",
            sphericity=sphericity,
            correction=request.correction,
            correct_sphericity=False,
        ),
        _effect_row(
            term=request.within_factor_columns[0],
            sum_sq=within_sum_sq,
            numerator_df=within_df,
            denominator_df=subject_within_df,
            f_value=within_f,
            error_layer="subject:within",
            sphericity=sphericity,
            correction=request.correction,
            correct_sphericity=True,
        ),
        _effect_row(
            term=f"{request.between_factor_column}:{request.within_factor_columns[0]}",
            sum_sq=interaction_sum_sq,
            numerator_df=interaction_df,
            denominator_df=subject_within_df,
            f_value=interaction_f,
            error_layer="subject:within",
            sphericity=sphericity,
            correction=request.correction,
            correct_sphericity=True,
        ),
    ]
    error_layers = [
        {
            "name": "subject:between",
            "sum_sq": _finite(subject_between_sum_sq, "subject:between.sum_sq"),
            "df": _finite(subject_between_df, "subject:between.df"),
            "mean_sq": _finite(subject_between_mean_sq, "subject:between.mean_sq"),
        },
        {
            "name": "subject:within",
            "sum_sq": _finite(subject_within_sum_sq, "subject:within.sum_sq"),
            "df": _finite(subject_within_df, "subject:within.df"),
            "mean_sq": _finite(subject_within_mean_sq, "subject:within.mean_sq"),
        },
    ]
    return effects, error_layers, sphericity


def _result_payload(
    *,
    prepared: _PreparedDesign,
    request: RepeatedMeasuresAnovaInput,
    effects: list[dict[str, Any]],
    error_layers: list[dict[str, Any]],
    sphericity: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    if len(effects) > MAX_RESULT_POSITIONS:
        _fail(
            "REPEATED_MEASURES_ANOVA_BOUND_EXCEEDED",
            f"effect result count exceeds the bound of {MAX_RESULT_POSITIONS}",
        )
    n_subjects, n_levels = prepared.y.shape
    between_count = len(prepared.between_values)
    subjects_per_between_level = (
        len(prepared.subject_values) // between_count if between_count else None
    )
    counts = {
        "n_rows": int(len(prepared.working_frame)),
        "n_subjects": int(n_subjects),
        "n_within_levels": int(n_levels),
        "n_between_levels": int(between_count),
        "subjects_per_between_level": subjects_per_between_level,
        "observations_per_subject": int(n_levels),
    }
    effects = _json_native(effects)
    error_layers = _json_native(error_layers)
    payload = {
        "design_metadata": {
            "design": (
                "mixed_design"
                if request.operation_id == MIXED_DESIGN_OPERATION_ID
                else "repeated_only"
            ),
            "response_column": request.response_column,
            "subject_column": request.subject_column,
            "within_factor_columns": list(request.within_factor_columns),
            "between_factor_column": request.between_factor_column,
            "correction_policy": request.correction,
            "formula_policy": "structured_columns_only",
            "level_order_policy": "first_observed_order",
            "method": method,
        },
        "counts": counts,
        "levels": {
            "within": list(prepared.within_values),
            "between": list(prepared.between_values),
        },
        "effects": effects,
        "anova_table": effects,
        "error_layers": error_layers,
        "sphericity": _json_native(sphericity),
        "result_positions": [item["term"] for item in effects],
        "result_positions_limit": MAX_RESULT_POSITIONS,
    }
    return _json_native(payload)


def fit_repeated_measures_anova(
    frame: pd.DataFrame,
    *,
    operation_id: str,
    response_column: str,
    subject_column: str,
    within_factor_columns: Sequence[str],
    between_factor_column: str | None = None,
    correction: str,
    formula: object = None,
    eval: object = None,
) -> dict[str, Any]:
    """Fit one bounded repeated-measures or mixed-design ANOVA.

    Invalid declarations and data raise ``RepeatedMeasuresAnovaPackError``.
    ``run_repeated_measures_anova`` is the envelope-safe alternative.
    """

    request = _validate_declaration(
        operation_id=operation_id,
        response_column=response_column,
        subject_column=subject_column,
        within_factor_columns=within_factor_columns,
        between_factor_column=between_factor_column,
        correction=correction,
        formula=formula,
        eval=eval,
    )
    prepared = _prepare_design(frame, request)
    if request.operation_id == REPEATED_ONLY_OPERATION_ID:
        effects, error_layers, sphericity = _repeated_only_stats(prepared, request)
        method = "statsmodels.AnovaRM_with_explicit_sums_of_squares"
    else:
        effects, error_layers, sphericity = _mixed_stats(prepared, request)
        method = "balanced_classical_error_layer_decomposition"
    payload = _result_payload(
        prepared=prepared,
        request=request,
        effects=effects,
        error_layers=error_layers,
        sphericity=sphericity,
        method=method,
    )
    columns = [request.response_column, request.subject_column, *request.within_factor_columns]
    if request.between_factor_column is not None:
        columns.append(request.between_factor_column)
    return make_result_envelope(
        operation_id=request.operation_id,
        status="completed",
        reason_code=REPEATED_MEASURES_ANOVA_COMPLETED,
        n_observations=len(frame),
        columns=columns,
        result=payload,
    )


def _safe_declared_columns(kwargs: dict[str, Any]) -> list[str]:
    columns: list[str] = []

    def add(value: object) -> bool:
        if type(value) is str and value and value not in columns:
            columns.append(value)
        return len(columns) >= MAX_ECHOED_COLUMNS

    if add(kwargs.get("response_column")):
        return columns
    if add(kwargs.get("subject_column")):
        return columns
    within = kwargs.get("within_factor_columns")
    if isinstance(within, Sequence) and not isinstance(within, (str, bytes)):
        for value in within:
            if add(value):
                return columns
    add(kwargs.get("between_factor_column"))
    return columns


def run_repeated_measures_anova(
    frame: pd.DataFrame,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the kernel while converting pack rejections into an envelope."""

    operation_id = kwargs.get("operation_id")
    safe_operation_id = (
        operation_id
        if type(operation_id) is str and operation_id in REPEATED_MEASURES_ANOVA_OPERATION_IDS
        else REPEATED_ONLY_OPERATION_ID
    )
    n_observations = int(len(frame)) if isinstance(frame, pd.DataFrame) else 0
    try:
        return fit_repeated_measures_anova(frame, **kwargs)
    except RepeatedMeasuresAnovaPackError as exc:
        reason_code = exc.reason_code
        message = str(exc)
    except (TypeError, ValueError) as exc:
        reason_code = "REPEATED_MEASURES_ANOVA_BAD_INPUT"
        message = f"invalid structured declaration: {exc}"

    if reason_code not in REPEATED_MEASURES_ANOVA_REASON_CODES:
        reason_code = "REPEATED_MEASURES_ANOVA_BAD_INPUT"
    return make_result_envelope(
        operation_id=safe_operation_id,
        status="rejected",
        reason_code=reason_code,
        n_observations=n_observations,
        columns=_safe_declared_columns(kwargs),
        result={
            "error": {
                "reason_code": reason_code,
                "message": message,
            }
        },
    )


fit_repeated_measures = fit_repeated_measures_anova
run_repeated_measures = run_repeated_measures_anova


__all__ = [
    "MAX_BETWEEN_FACTORS",
    "MAX_ECHOED_COLUMNS",
    "MAX_FACTOR_LEVELS",
    "MAX_RESULT_POSITIONS",
    "MAX_ROWS",
    "MAX_SUBJECTS",
    "MAX_WITHIN_FACTORS",
    "MIXED_DESIGN_OPERATION_ID",
    "REPEATED_MEASURES_ANOVA_COMPLETED",
    "REPEATED_MEASURES_ANOVA_CONTRACT",
    "REPEATED_MEASURES_ANOVA_CONTRACT_VERSION",
    "REPEATED_MEASURES_ANOVA_CORRECTIONS",
    "REPEATED_MEASURES_ANOVA_OPERATION_IDS",
    "REPEATED_MEASURES_ANOVA_REASON_CODES",
    "REPEATED_ONLY_OPERATION_ID",
    "RepeatedMeasuresAnovaPackError",
    "fit_repeated_measures",
    "fit_repeated_measures_anova",
    "run_repeated_measures",
    "run_repeated_measures_anova",
]
