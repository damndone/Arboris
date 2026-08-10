"""Fail-closed structured-term MANOVA using the installed statsmodels kernel."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from patsy import PatsyError, dmatrices
from statsmodels.multivariate.manova import MANOVA

from workbench.contracts.model.multivariate import make_result_envelope

from .common import MultivariatePackError, json_native


MANOVA_STATISTICS = frozenset(
    {
        "wilks_lambda",
        "pillai_trace",
        "hotelling_lawley_trace",
        "roy_greatest_root",
    }
)
MANOVA_MAX_RETAINED_POSITIONS = 500

_STATISTIC_LABELS = (
    ("wilks_lambda", "Wilks' lambda"),
    ("pillai_trace", "Pillai's trace"),
    ("hotelling_lawley_trace", "Hotelling-Lawley trace"),
    ("roy_greatest_root", "Roy's greatest root"),
)
def _error(reason_code: str, message: str) -> MultivariatePackError:
    return MultivariatePackError(reason_code, message)


def _normalize_column_names(value: object, field_name: str, *, minimum: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _error("MULTIVARIATE_BAD_INPUT", f"{field_name} must be an array of column names")
    normalized = list(value)
    if len(normalized) < minimum or any(type(item) is not str or not item for item in normalized):
        raise _error(
            "MULTIVARIATE_BAD_INPUT",
            f"{field_name} must contain at least {minimum} non-empty strings",
        )
    if len(set(normalized)) != len(normalized):
        raise _error("MULTIVARIATE_DUPLICATE_COLUMN", f"{field_name} must not contain duplicates")
    return normalized


def _normalize_interactions(
    interaction_terms: object,
    factor_columns: list[str],
) -> list[list[str]]:
    if isinstance(interaction_terms, (str, bytes)) or not isinstance(interaction_terms, Sequence):
        raise _error(
            "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
            "interaction_terms must be an array of factor-column arrays",
        )
    factor_order = {column: index for index, column in enumerate(factor_columns)}
    normalized: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_term in interaction_terms:
        if (
            isinstance(raw_term, (str, bytes))
            or not isinstance(raw_term, Sequence)
        ):
            raise _error(
                "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
                "each interaction must contain at least two factor columns",
            )
        term = list(raw_term)
        if len(term) < 2 or any(type(item) is not str or not item for item in term):
            raise _error(
                "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
                "each interaction must contain at least two factor columns",
            )
        if len(set(term)) != len(term):
            raise _error(
                "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
                "interaction factors must be unique",
            )
        unknown = [item for item in term if item not in factor_order]
        if unknown:
            raise _error(
                "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
                "interactions may reference factor columns only",
            )
        canonical = tuple(sorted(term, key=factor_order.__getitem__))
        if canonical in seen:
            raise _error(
                "MULTIVARIATE_INVALID_FACTOR_INTERACTION",
                "interaction_terms must not contain duplicates",
            )
        seen.add(canonical)
        normalized.append(list(canonical))
    return normalized


def _quote(column: str) -> str:
    """Quote a validated column name for Patsy without accepting formula text."""

    return f"Q({json.dumps(column, ensure_ascii=False)})"


def _factor_expression(column: str) -> str:
    return f"C({_quote(column)})"


def _build_formula(
    response_columns: list[str],
    factor_columns: list[str],
    covariate_columns: list[str],
    interaction_terms: list[list[str]],
    intercept: bool,
) -> str:
    lhs = " + ".join(_quote(column) for column in response_columns)
    rhs: list[str] = ["1" if intercept else "0"]
    rhs.extend(_factor_expression(column) for column in factor_columns)
    rhs.extend(_quote(column) for column in covariate_columns)
    rhs.extend(
        ":".join(_factor_expression(column) for column in interaction)
        for interaction in interaction_terms
    )
    return f"{lhs} ~ {' + '.join(rhs)}"


def _factor_label(value: object, column: str) -> str:
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is str:
        if not value:
            raise _error(
                "MULTIVARIATE_INVALID_CATEGORY_LABEL",
                f"factor {column!r} contains an empty category label",
            )
        return value
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not np.isfinite(value):
            raise _error(
                "MULTIVARIATE_INVALID_CATEGORY",
                f"factor {column!r} contains a non-finite category",
            )
        return repr(value)
    raise _error(
        "MULTIVARIATE_INVALID_CATEGORY",
        f"factor {column!r} contains an unsupported category value",
    )


def _prepare_frame(
    frame: pd.DataFrame,
    response_columns: list[str],
    factor_columns: list[str],
    covariate_columns: list[str],
    missing_policy: str,
    retained_positions_limit: int,
) -> tuple[pd.DataFrame, tuple[int, ...], int, bool, dict[str, list[str]]]:
    if not isinstance(frame, pd.DataFrame):
        raise _error("MULTIVARIATE_BAD_INPUT", "frame must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise _error("MULTIVARIATE_DUPLICATE_COLUMN", "frame columns must be unique")
    if missing_policy != "complete_case_v1":
        raise _error(
            "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
            "only complete_case_v1 is currently declared",
        )

    all_columns = [*response_columns, *factor_columns, *covariate_columns]
    if len(set(all_columns)) != len(all_columns):
        raise _error(
            "MULTIVARIATE_DUPLICATE_COLUMN",
            "response, factor, and covariate columns must be disjoint",
        )
    missing = [column for column in all_columns if column not in frame.columns]
    if missing:
        raise _error("MULTIVARIATE_MISSING_COLUMN", "unknown columns: " + ", ".join(missing))

    selected = frame.loc[:, all_columns].copy()
    for column, role in [
        *[(column, "responses") for column in response_columns],
        *[(column, "covariates") for column in covariate_columns],
    ]:
        dtype = selected[column].dtype
        if (
            not pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_complex_dtype(dtype)
        ):
            raise _error(
                "MULTIVARIATE_NON_NUMERIC_COLUMN",
                f"{role[:-1]} column {column!r} is not a real numeric column",
            )

    complete_mask = selected.notna().all(axis=1)
    all_retained_positions = np.flatnonzero(complete_mask.to_numpy())
    retained_positions_count = int(all_retained_positions.size)
    retained_positions = tuple(
        all_retained_positions[:retained_positions_limit].tolist()
    )
    retained_positions_truncated = retained_positions_count > retained_positions_limit
    complete = selected.loc[complete_mask].reset_index(drop=True)
    if complete.empty:
        raise _error("MULTIVARIATE_NO_COMPLETE_CASES", "no complete-case observations remain")
    if len(complete) < 2:
        raise _error(
            "MULTIVARIATE_TOO_FEW_OBSERVATIONS",
            "at least two complete-case observations are required",
        )

    numeric_columns = [*response_columns, *covariate_columns]
    try:
        numeric_values = complete.loc[:, numeric_columns].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise _error(
            "MULTIVARIATE_NON_NUMERIC_COLUMN",
            "numeric response and covariate columns cannot be represented as real numbers",
        ) from exc
    if not np.isfinite(numeric_values).all():
        raise _error(
            "MULTIVARIATE_NON_FINITE_VALUE",
            "numeric responses and covariates contain non-finite values",
        )
    complete.loc[:, numeric_columns] = numeric_values

    factor_levels: dict[str, list[str]] = {}
    for column in factor_columns:
        labels = [_factor_label(value, column) for value in complete[column].tolist()]
        if len(set(labels)) != len(set(complete[column].tolist())):
            raise _error(
                "MULTIVARIATE_INVALID_CATEGORY_LABEL",
                f"factor {column!r} has ambiguous category identities",
            )
        levels = sorted(set(labels))
        if len(levels) < 2:
            raise _error(
                "MULTIVARIATE_TOO_FEW_CATEGORIES",
                f"factor {column!r} must contain at least two complete-case levels",
            )
        factor_levels[column] = levels
        complete[column] = pd.Categorical(labels, categories=levels, ordered=True)
    return (
        complete,
        retained_positions,
        retained_positions_count,
        retained_positions_truncated,
        factor_levels,
    )


def _term_names(
    intercept: bool,
    factor_columns: list[str],
    covariate_columns: list[str],
    interaction_terms: list[list[str]],
) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    if intercept:
        terms.append(("Intercept", "Intercept"))
    terms.extend((f"C({column})", _factor_expression(column)) for column in factor_columns)
    terms.extend((column, _quote(column)) for column in covariate_columns)
    terms.extend(
        (
            ":".join(f"C({column})" for column in interaction),
            ":".join(_factor_expression(column) for column in interaction),
        )
        for interaction in interaction_terms
    )
    return terms


def _finite_statistic(value: object, field_name: str, term: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise _error(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            f"MANOVA {field_name} for {term!r} is not numeric",
        ) from exc
    if not np.isfinite(number):
        raise _error(
            "MULTIVARIATE_NON_FINITE_VALUE",
            f"MANOVA {field_name} for {term!r} is non-finite",
        )
    return number


def _extract_tests(
    results: dict[str, Any],
    terms: list[tuple[str, str]],
    response_dimension: int,
) -> dict[str, dict[str, dict[str, float]]]:
    extracted: dict[str, dict[str, dict[str, float]]] = {}
    for public_term, statsmodels_term in terms:
        if statsmodels_term not in results:
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"MANOVA did not return the declared term {public_term!r}",
            )
        stat_table = results[statsmodels_term].get("stat")
        if not isinstance(stat_table, pd.DataFrame):
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"MANOVA returned no statistics for {public_term!r}",
            )
        contrast = results[statsmodels_term].get("contrast_L")
        if contrast is None:
            hypothesis_rank: int | None = None
        else:
            try:
                contrast_values = np.asarray(contrast, dtype=float)
                if contrast_values.ndim != 2 or not np.isfinite(contrast_values).all():
                    raise ValueError("contrast is not finite two-dimensional data")
                hypothesis_rank = int(np.linalg.matrix_rank(contrast_values))
            except (TypeError, ValueError, np.linalg.LinAlgError) as exc:
                raise _error(
                    "MULTIVARIATE_NUMERIC_DEGENERACY",
                    f"MANOVA contrast for {public_term!r} is invalid",
                ) from exc
            if hypothesis_rank < 1:
                raise _error(
                    "MULTIVARIATE_NUMERIC_DEGENERACY",
                    f"MANOVA contrast for {public_term!r} has zero rank",
                )
        term_statistics: dict[str, dict[str, float]] = {}
        for public_statistic, statsmodels_label in _STATISTIC_LABELS:
            if statsmodels_label not in stat_table.index:
                raise _error(
                    "MULTIVARIATE_NUMERIC_DEGENERACY",
                    f"MANOVA omitted {statsmodels_label} for {public_term!r}",
                )
            row = stat_table.loc[statsmodels_label]
            statistic = _finite_statistic(row["Value"], "statistic", public_term)
            numerator_df = _finite_statistic(row["Num DF"], "numerator df", public_term)
            denominator_df = _finite_statistic(row["Den DF"], "denominator df", public_term)
            f_value = _finite_statistic(row["F Value"], "F value", public_term)
            p_value = _finite_statistic(row["Pr > F"], "p value", public_term)
            if numerator_df <= 0.0 or denominator_df <= 0.0 or f_value < -1e-10 or not 0.0 <= p_value <= 1.0:
                raise _error(
                    "MULTIVARIATE_NUMERIC_DEGENERACY",
                    f"MANOVA returned invalid inference values for {public_term!r}",
                )
            term_statistics[public_statistic] = {
                "statistic": statistic,
                "numerator_df": numerator_df,
                "denominator_df": denominator_df,
                "f": max(f_value, 0.0),
                "p_value": p_value,
            }
        wilks = term_statistics["wilks_lambda"]["statistic"]
        pillai = term_statistics["pillai_trace"]["statistic"]
        hotelling_lawley = term_statistics["hotelling_lawley_trace"]["statistic"]
        roy = term_statistics["roy_greatest_root"]["statistic"]
        if hypothesis_rank is None:
            hypothesis_rank = max(
                1,
                int(
                    np.ceil(
                        term_statistics["wilks_lambda"]["numerator_df"]
                        / response_dimension
                    )
                ),
            )
        pillai_upper = min(response_dimension, hypothesis_rank)
        if not 0.0 < wilks <= 1.0:
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"Wilks lambda for {public_term!r} is outside (0, 1]",
            )
        if not 0.0 <= pillai <= float(pillai_upper):
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"Pillai trace for {public_term!r} exceeds its response-dimension bound",
            )
        if hotelling_lawley < 0.0:
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"Hotelling-Lawley trace for {public_term!r} is negative",
            )
        if not 0.0 <= roy <= hotelling_lawley:
            raise _error(
                "MULTIVARIATE_NUMERIC_DEGENERACY",
                f"Roy greatest root for {public_term!r} exceeds Hotelling-Lawley trace",
            )
        extracted[public_term] = term_statistics
    return extracted


def fit_manova(
    frame: pd.DataFrame,
    response_columns: Sequence[str],
    *,
    factor_columns: Sequence[str],
    covariate_columns: Sequence[str],
    interaction_terms: Sequence[Sequence[str]],
    intercept: bool,
    missing_policy: str,
    max_retained_positions: int = MANOVA_MAX_RETAINED_POSITIONS,
) -> dict[str, object]:
    """Fit MANOVA from validated structured terms and an explicit data policy."""

    normalized_responses = _normalize_column_names(response_columns, "response_columns", minimum=2)
    normalized_factors = _normalize_column_names(factor_columns, "factor_columns", minimum=0)
    normalized_covariates = _normalize_column_names(covariate_columns, "covariate_columns", minimum=0)
    if type(intercept) is not bool:
        raise _error("MULTIVARIATE_INVALID_OPTION", "intercept must be a boolean")
    if (
        type(max_retained_positions) is not int
        or not 1 <= max_retained_positions <= MANOVA_MAX_RETAINED_POSITIONS
    ):
        raise _error(
            "MULTIVARIATE_INVALID_OPTION",
            f"max_retained_positions must be an integer in [1, {MANOVA_MAX_RETAINED_POSITIONS}]",
        )
    normalized_interactions = _normalize_interactions(interaction_terms, normalized_factors)
    if not intercept and not (normalized_factors or normalized_covariates):
        raise _error(
            "MULTIVARIATE_INVALID_OPTION",
            "a no-intercept MANOVA requires at least one declared design term",
        )

    (
        prepared,
        retained_positions,
        retained_positions_count,
        retained_positions_truncated,
        factor_levels,
    ) = _prepare_frame(
        frame,
        normalized_responses,
        normalized_factors,
        normalized_covariates,
        missing_policy,
        max_retained_positions,
    )
    formula = _build_formula(
        normalized_responses,
        normalized_factors,
        normalized_covariates,
        normalized_interactions,
        intercept,
    )
    try:
        _, design = dmatrices(formula, data=prepared, return_type="dataframe")
    except (PatsyError, TypeError, ValueError) as exc:
        raise _error(
            "MULTIVARIATE_SINGULAR_DESIGN",
            "validated MANOVA terms could not produce a finite design matrix",
        ) from exc
    design_values = design.to_numpy(dtype=float)
    if not np.isfinite(design_values).all():
        raise _error("MULTIVARIATE_NON_FINITE_VALUE", "MANOVA design matrix is non-finite")
    design_columns = int(design_values.shape[1])
    design_rank = int(np.linalg.matrix_rank(design_values))
    if design_columns == 0 or design_rank != design_columns:
        raise _error(
            "MULTIVARIATE_SINGULAR_DESIGN",
            "MANOVA design matrix is singular",
        )
    residual_df = int(len(prepared) - design_rank)
    if residual_df < len(normalized_responses):
        raise _error(
            "MULTIVARIATE_INSUFFICIENT_RESIDUAL_DF",
            "MANOVA requires residual degrees of freedom at least equal to the response count",
        )

    terms = _term_names(
        intercept,
        normalized_factors,
        normalized_covariates,
        normalized_interactions,
    )
    public_term_ids = [public_term for public_term, _ in terms]
    if len(set(public_term_ids)) != len(public_term_ids):
        raise _error(
            "MULTIVARIATE_INVALID_OPTION",
            "declared terms produce ambiguous public term IDs",
        )

    try:
        fitted = MANOVA.from_formula(formula, data=prepared)
        test_results = fitted.mv_test().results
    except (PatsyError, TypeError, ValueError, np.linalg.LinAlgError) as exc:
        raise _error(
            "MULTIVARIATE_NUMERIC_DEGENERACY",
            "statsmodels could not fit a finite MANOVA",
        ) from exc

    tests = _extract_tests(test_results, terms, len(normalized_responses))
    result = {
        "model_specification": {
            "response_columns": normalized_responses,
            "factor_columns": normalized_factors,
            "covariate_columns": normalized_covariates,
            "interaction_terms": normalized_interactions,
            "intercept": intercept,
            "missing_policy": missing_policy,
            "formula": formula,
        },
        "factor_levels": factor_levels,
        "design": {
            "n_rows": len(prepared),
            "n_columns": design_columns,
            "rank": design_rank,
            "residual_degrees_of_freedom": residual_df,
        },
        "term_tests": tests,
        "missing_policy": missing_policy,
        "retained_positions": list(retained_positions),
        "retained_positions_count": retained_positions_count,
        "retained_positions_limit": max_retained_positions,
        "retained_positions_truncated": retained_positions_truncated,
    }
    return make_result_envelope(
        operation_id="multivariate.manova",
        status="completed",
        reason_code=(
            "MULTIVARIATE_OUTPUT_TOO_LARGE"
            if retained_positions_truncated
            else "ANALYSIS_COMPLETED"
        ),
        n_observations=len(prepared),
        columns=[*normalized_responses, *normalized_factors, *normalized_covariates],
        result=json_native(result),
    )


__all__ = ["MANOVA_MAX_RETAINED_POSITIONS", "MANOVA_STATISTICS", "fit_manova"]
