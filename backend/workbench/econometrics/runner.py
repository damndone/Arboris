from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
import pandas as pd
import statsmodels
import statsmodels.formula.api as smf

from ..canonical import sha256_canonical
from ..analysis_loop.fingerprints import (
    analysis_sample_fingerprint,
    coefficient_schema_fingerprint,
    dataset_snapshot_fingerprint,
    inference_config_fingerprint,
    point_estimation_fingerprint,
)
from ..analysis_loop.policy import (
    cluster_declared_runtime_compatible,
    cluster_runtime_type,
    ols_cluster_policy_v1,
)
from .normalize import _json_safe_float, normalize_statsmodels_result
from .optional_deps import require_optional_dependency

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


def _python_scalar(value: Any) -> Any:
    """Make pandas/numpy scalar values safe for the canonical JSON helpers."""
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        missing = pd.isna(value)
        if type(missing) is bool and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row_id_values(
    frame: pd.DataFrame,
    row_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    def collision_safe(values: list[Any]) -> list[str]:
        original_types = [
            f"{type(value).__module__}.{type(value).__qualname__}"
            for value in values
        ]
        normalized = [_python_scalar(value) for value in values]
        rendered = [str(value) for value in normalized]
        if len(set(rendered)) == len(rendered):
            return rendered
        typed = [
            f"{original_type}:{value}"
            for original_type, value in zip(original_types, normalized, strict=True)
        ]
        return typed

    if row_ids is None:
        if frame.index.is_unique:
            return collision_safe(list(frame.index))
        return [f"position:{position}" for position in range(len(frame))]
    if len(row_ids) != len(frame):
        raise ValueError(
            "OLS_CLUSTER_ROW_ALIGNMENT: analysis row identifiers must be unique "
            "and aligned to the input frame."
        )
    values = collision_safe(list(row_ids))
    if len(set(values)) == len(values):
        return values
    if frame.index.is_unique:
        raise ValueError(
            "OLS_CLUSTER_ROW_ALIGNMENT: analysis row identifiers must be unique "
            "and aligned to the input frame."
        )
    return [f"{value}#occurrence:{position}" for position, value in enumerate(values)]


def _cluster_declared_dtype(groups: pd.Series) -> str:
    dtype = groups.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        return "category"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_string_dtype(dtype):
        return "string"
    return str(dtype)


def _validate_cluster_group_values(groups: pd.Series) -> None:
    declared = _cluster_declared_dtype(groups)
    runtime_types: set[str | None] = set()
    for position, value in enumerate(groups):
        try:
            missing = pd.isna(value)
            is_missing = type(missing) is bool and missing
        except (TypeError, ValueError):
            is_missing = False
        if is_missing:
            raise ValueError(
                "OLS_CLUSTER_VALUES_MISSING: entity_col contains null/NaN values "
                f"on analysis rows at position {position}."
            )
        runtime_types.add(cluster_runtime_type(value))

    policy = ols_cluster_policy_v1
    if (
        None in runtime_types
        or "bool" in runtime_types and policy.reject_boolean
        or "float" in runtime_types and policy.reject_float
        or any(item not in policy.allowed_cluster_types for item in runtime_types)
        or (
            len(runtime_types) == 1
            and not cluster_declared_runtime_compatible(
                declared, next(iter(runtime_types))
            )
        )
    ):
        raise ValueError(
            "OLS_CLUSTER_TYPE_UNSUPPORTED: entity_col values violate "
            "ols_cluster_policy_v1 "
            f"(declared_dtype={declared!r}, "
            f"runtime_types={sorted(str(item) for item in runtime_types)})."
        )
    if len(runtime_types) > 1 and policy.reject_mixed_object:
        raise ValueError(
            "OLS_CLUSTER_TYPE_MIXED: entity_col contains mixed runtime value types "
            f"({sorted(str(item) for item in runtime_types)})."
        )


def _analysis_row_context(
    frame: pd.DataFrame,
    row_labels: Any,
    *,
    model_index: Any = None,
    row_ids: list[str] | tuple[str, ...] | None,
    cluster_row_ids: list[str] | tuple[str, ...] | None,
) -> tuple[list[int], list[str]]:
    reference_index = list(model_index if model_index is not None else frame.index)
    labels = list(row_labels) if row_labels is not None else reference_index
    source_ids = _row_id_values(frame, row_ids)
    positions_by_label: dict[Any, list[int]] = {}
    for position, label in enumerate(reference_index):
        positions_by_label.setdefault(label, []).append(position)
    selected_positions: list[int] = []
    for label in labels:
        positions = positions_by_label.get(label)
        if not positions:
            raise ValueError(
                "OLS_CLUSTER_ROW_ALIGNMENT: model rows are not aligned to the input frame."
            )
        selected_positions.append(positions.pop(0))
    analysis_ids = [source_ids[position] for position in selected_positions]
    if cluster_row_ids is not None:
        observed_cluster_ids = [str(value) for value in cluster_row_ids]
        if observed_cluster_ids != analysis_ids:
            raise ValueError(
                "OLS_CLUSTER_ROW_ALIGNMENT: cluster vector row identifiers do not "
                "match the model analysis rows in order."
            )
    return selected_positions, analysis_ids


def _frame_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    try:
        values = json.loads(frame.to_json(orient="split", date_format="iso"))
    except (TypeError, ValueError):
        values = {
            "columns": [str(column) for column in frame.columns],
            "data": [
                [_python_scalar(value) for value in row]
                for row in frame.itertuples(index=False, name=None)
            ],
        }
    return {
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(frame[column].dtype) for column in frame.columns},
        "values": values,
    }


def _primary_estimand(
    coefficients: dict[str, dict[str, Any]],
    *,
    focal_x: list[str] | tuple[str, ...] | str | None,
    primary_estimand: dict[str, Any] | None,
) -> dict[str, Any] | None:
    stable_ids = {
        coefficient.get("result_id")
        for coefficient in coefficients.values()
        if isinstance(coefficient, dict)
    }
    if isinstance(primary_estimand, dict):
        explicit_id = primary_estimand.get("result_id")
        if explicit_id in stable_ids:
            return {
                **primary_estimand,
                "result_id": explicit_id,
                "resolution_source": "explicit_primary_metadata",
            }
        return None
    if isinstance(focal_x, str):
        focal_values = [item.strip() for item in focal_x.split(",") if item.strip()]
    elif isinstance(focal_x, (list, tuple)):
        focal_values = [str(item) for item in focal_x]
    else:
        focal_values = []
    if len(focal_values) != 1:
        return None
    focal_term = focal_values[0]
    exact_matches = [
        coefficient
        for term, coefficient in coefficients.items()
        if term == focal_term
    ]
    if len(exact_matches) != 1:
        return None
    return {
        "result_id": exact_matches[0]["result_id"],
        "role": "primary",
        "focal_x": focal_term,
        "resolution_source": "explicit_focal_x",
    }


def _attach_ols_result_contract(
    result: dict[str, Any],
    *,
    fitted: Any,
    original: Any,
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    categorical_x: set[str],
    model_id: str,
    covariance: str,
    covariance_explicit: bool,
    cluster_col: str | None,
    model_index: Any,
    dataset_snapshot: Any,
    row_ids: list[str] | tuple[str, ...] | None,
    cluster_row_ids: list[str] | tuple[str, ...] | None,
    focal_x: list[str] | tuple[str, ...] | str | None,
    primary_estimand: dict[str, Any] | None,
    weights: Any,
    intercept: bool,
    missing_policy: str,
    solver_options: Any,
) -> dict[str, Any]:
    row_positions, analysis_ids = _analysis_row_context(
        frame,
        getattr(original.model.data, "row_labels", None),
        model_index=model_index,
        row_ids=row_ids,
        cluster_row_ids=cluster_row_ids,
    )
    if dataset_snapshot is None:
        dataset_snapshot = _frame_snapshot(frame)
    dataset_fp = dataset_snapshot_fingerprint(dataset_snapshot)
    sample_fp = analysis_sample_fingerprint(
        row_set=analysis_ids,
        row_order=analysis_ids,
    )
    selected = frame.iloc[row_positions][[y, *x]]
    point_fp = point_estimation_fingerprint(
        y=[_python_scalar(value) for value in selected[y]],
        X={
            column: [_python_scalar(value) for value in selected[column]]
            for column in x
        },
        weights=weights,
        intercept=intercept,
        categorical_encoding={
            column: ("categorical" if column in categorical_x else "numeric")
            for column in x
        },
        missing_policy=missing_policy,
        rows=analysis_ids,
        solver_options=solver_options,
    )

    coefficients = result.get("coefficients", {})
    result_id_by_source_id: dict[str, str] = {}
    schema: list[dict[str, Any]] = []
    for position, (term, coefficient) in enumerate(coefficients.items()):
        identity = {
            "model": "ols",
            "model_id": model_id,
            "term": term,
        }
        stable_id = "coef:" + sha256_canonical(identity)
        coefficient["result_id"] = stable_id
        coefficient["candidate_result_id"] = stable_id
        coefficient["coefficient_id"] = stable_id
        coefficient["coefficient_identity"] = f"ols:{model_id}:{term}"
        coefficient["coefficient_term"] = term
        source_id = coefficient.get("source_id")
        if isinstance(source_id, str):
            result_id_by_source_id[source_id] = stable_id
        schema.append({"result_id": stable_id, "term": term, "position": position})
    stable_result_ids = [entry["result_id"] for entry in schema]

    group_vector: list[Any] | None = None
    group_vector_dtype: str | None = None
    group_vector_fp: str | None = None
    cluster_count = 0
    if cluster_col is not None:
        groups = frame.iloc[row_positions][cluster_col]
        group_vector_dtype = str(groups.dtype)
        group_vector = [_python_scalar(value) for value in groups]
        missing_positions = [
            position
            for position, value in enumerate(group_vector)
            if value is None
        ]
        if missing_positions:
            raise ValueError(
                "OLS_CLUSTER_VALUES_MISSING: entity_col contains null/NaN values "
                f"on analysis rows at positions {missing_positions}."
            )
        group_vector_fp = sha256_canonical(
            {
                "entity_col": cluster_col,
                "row_order": analysis_ids,
                "dtype": group_vector_dtype,
                "values": group_vector,
            }
        )
        cluster_count = len({json.dumps(value, sort_keys=True) for value in group_vector})

    use_t = bool(getattr(fitted, "use_t", False))
    inference_df = getattr(fitted, "df_resid_inference", None)
    effective_df = _json_safe_float(inference_df)
    if effective_df is None:
        effective_df = _json_safe_float(getattr(fitted, "df_resid", None))
    inference_distribution = "t" if use_t else "normal"
    p_value_method = "t" if use_t else "normal_z"
    confidence_interval_method = "t" if use_t else "normal_z"
    evidence = {
        "covariance": covariance,
        "covariance_estimator": "cluster" if covariance == "clustered" else (
            "HC1" if covariance == "robust" else "nonrobust"
        ),
        "engine": "statsmodels",
        "library": "statsmodels",
        "library_version": statsmodels.__version__,
        "small_sample_correction": covariance == "clustered",
        "degrees_of_freedom_correction": covariance == "clustered",
        "use_t": use_t,
        "inference_distribution": inference_distribution,
        "p_value_method": p_value_method,
        "confidence_interval_method": confidence_interval_method,
        "confidence_level": 0.95,
        "alpha": 0.05,
        "effective_df": effective_df,
        "cluster_variable": cluster_col,
        "entity_col": cluster_col,
        "cluster_count": cluster_count,
        "group_vector_dtype": group_vector_dtype,
        "group_vector_fingerprint": group_vector_fp,
    }
    inference_kwargs: dict[str, Any] = {
        "covariance": covariance,
        "cluster_var": cluster_col,
        "cluster_count": cluster_count,
        "corrections": {
            "small_sample_correction": covariance == "clustered",
            "degrees_of_freedom_correction": covariance == "clustered",
        },
        "df": effective_df,
        "use_t": use_t,
        "confidence_level": evidence["confidence_level"],
        "engine": "statsmodels",
        "version": statsmodels.__version__,
        "inference_distribution": inference_distribution,
        "p_value_method": p_value_method,
        "confidence_interval_method": confidence_interval_method,
    }
    if group_vector_fp is not None:
        inference_kwargs["cluster_group_vector_fingerprint"] = group_vector_fp
    inference_fp = inference_config_fingerprint(**inference_kwargs)
    result.update(
        {
            "contract_version": "ols_result_contract_v1",
            "model": "ols",
            "covariance": covariance,
            "covariance_wire": covariance,
            "covariance_explicit": covariance_explicit,
            "covariance_estimator": evidence["covariance_estimator"],
            "source_eligible": covariance == "unadjusted" and covariance_explicit,
            "formula": original.model.formula,
            "y_column": y,
            "x_columns": list(x),
            "intercept": intercept,
            "weights": weights,
            "missing_policy": missing_policy,
            "analysis_sample": {
                "row_set": sorted(analysis_ids),
                "row_order": analysis_ids,
                "fingerprint": sample_fp,
            },
            "dataset_snapshot_fingerprint": dataset_fp,
            "analysis_sample_fingerprint": sample_fp,
            "point_estimation_fingerprint": point_fp,
            "coefficient_schema_fingerprint": coefficient_schema_fingerprint(schema),
            "inference_config_fingerprint": inference_fp,
            "stable_result_ids": stable_result_ids,
            "candidate_result_ids": list(stable_result_ids),
            "result_id_by_source_id": result_id_by_source_id,
            "primary_estimand": _primary_estimand(
                coefficients,
                focal_x=focal_x,
                primary_estimand=primary_estimand,
            ),
            "covariance_evidence": evidence,
            "inference_config": evidence,
            "entity_col": cluster_col,
        }
    )
    return result


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
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
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
        if covariance not in {"robust", "unadjusted", "clustered"}:
            raise ValueError(f"OLS_COVARIANCE_UNSUPPORTED: unsupported covariance {covariance!r}.")
        if covariance_explicit is None:
            covariance_explicit = True
        if covariance == "clustered" and cluster_col is None:
            raise ValueError(
                "OLS_CLUSTER_FIELD_MISSING: clustered covariance for OLS requires "
                "an entity field naming the cluster column."
            )
        robust = covariance == "robust"
    if cluster_col is not None and covariance != "clustered":
        raise ValueError(
            "OLS_CLUSTER_COVARIANCE_CONFLICT: entity_col requires covariance=clustered."
        )
    if covariance == "clustered":
        robust = False
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    if covariance == "clustered":
        _validate_cluster_group_values(frame[cluster_col])
    model_frame = frame.copy()
    if not frame.index.is_unique:
        # Patsy/statsmodels uses row labels for its model data. A positional
        # index makes duplicate input labels unambiguous without changing any
        # values, columns, formula, sample order, or point estimate.
        model_frame.index = pd.RangeIndex(len(model_frame), name="__ols_position__")
    original = smf.ols(formula=formula, data=model_frame).fit()
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
        fitted = original.get_robustcov_results(
            cov_type="cluster",
            groups=groups.to_numpy(copy=True),
            use_correction=True,
            df_correction=True,
            use_t=False,
        )
        model_type = "ols_clustered"
    elif robust:
        fitted = original.get_robustcov_results(cov_type="HC1", use_t=False)
        model_type = "ols_robust"
    else:
        fitted = original
        model_type = "ols"
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = model_type
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
        model_index=model_frame.index,
        dataset_snapshot=dataset_snapshot,
        row_ids=row_ids,
        cluster_row_ids=cluster_row_ids,
        focal_x=focal_x,
        primary_estimand=primary_estimand,
        weights=weights,
        intercept=intercept,
        missing_policy=missing_policy,
        solver_options=solver_options or {"engine": "statsmodels", "method": "ols"},
    )
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
