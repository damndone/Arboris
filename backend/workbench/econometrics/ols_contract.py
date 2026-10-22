"""OLS result contract: linearmodels normalization, row identities, sample and point fingerprints."""

from __future__ import annotations

import json
from typing import Any
import numpy as np
import pandas as pd
import statsmodels

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
from .normalize import _json_safe_float


def _linearmodels_term(column: str) -> str:
    if column.isidentifier():
        return column
    return f"`{column.replace('`', '``')}`"


def _normalize_linearmodels_result(
    fitted: Any,
    model_id: str,
    model_type: str,
    *,
    y_column: str | None = None,
    covariance: str | None = None,
    entity_col: str | None = None,
    time_col: str | None = None,
    clustered_on_entity: bool = False,
    inference: Any = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    params = getattr(fitted, "params", {})
    std_errors = getattr(fitted, "std_errors", {})
    pvalues = getattr(fitted, "pvalues", {})
    confidence_intervals = getattr(fitted, "conf_int", lambda: None)()
    coefficients: dict[str, dict[str, Any]] = {}

    items = list(params.items() if hasattr(params, "items") else enumerate(params))
    for label, estimate in items:
        term = str(label)
        interval = None
        if hasattr(confidence_intervals, "loc"):
            try:
                interval = confidence_intervals.loc[label]
            except (KeyError, TypeError):
                interval = None
        ci_lower = (
            _json_safe_float(interval.get("lower"))
            if hasattr(interval, "get")
            else None
        )
        ci_upper = (
            _json_safe_float(interval.get("upper"))
            if hasattr(interval, "get")
            else None
        )
        p_value = _json_safe_float(
            pvalues.get(label) if hasattr(pvalues, "get") else None
        )
        coefficients[term] = {
            "estimate": _json_safe_float(estimate),
            "std_error": _json_safe_float(
                std_errors.get(label) if hasattr(std_errors, "get") else None
            ),
            "p_value": round(p_value, 6) if p_value is not None else None,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "source_id": f"model_results.{model_id}.coefficients.{term}",
        }

    result = {
        "schema_version": 1,
        "model_id": model_id,
        "model_type": model_type,
        "engine": "linearmodels",
        "y_column": y_column,
        "nobs": int(getattr(fitted, "nobs")),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "r_squared_adj": _json_safe_float(getattr(fitted, "rsquared_adj", None)),
        "df_model": _json_safe_float(getattr(fitted, "df_model", None)),
        "df_resid": _json_safe_float(getattr(fitted, "df_resid", None)),
        "coefficients": coefficients,
        "warnings": list(warnings or []),
    }
    if inference is not None:
        # Clustered by panel_inference: CR1, Stata's finite-sample rule, t(G - 1).
        result.update(
            {
                "covariance": "clustered",
                "covariance_estimator": (
                    "clustered_entity" if inference.cluster_variable == entity_col else "clustered"
                ),
                "entity_col": entity_col,
                "time_col": time_col,
                "x_columns": [str(label) for label, _ in items],
                "covariance_evidence": {
                    "covariance": "clustered",
                    "covariance_estimator": "CR1",
                    "cluster_variable": inference.cluster_variable,
                    "cluster_entity": inference.cluster_variable == entity_col,
                    "cluster_count": inference.n_clusters,
                    "small_sample_correction": True,
                    "degrees_of_freedom_correction": True,
                    "finite_sample_factor": "G/(G-1) * (N-1)/(N-K)",
                    "parameters_counted": inference.parameters_counted,
                    "use_t": True,
                    "inference_version": INFERENCE_ENGINE_VERSION,
                    "df_method": "clusters_minus_one",
                    "inference_distribution": "t",
                    "effective_df": inference.df,
                    "confidence_level": 0.95,
                    "df_resid": _json_safe_float(getattr(fitted, "df_resid", None)),
                    "reference": "Stata xtreg, fe vce(cluster)",
                },
            }
        )
        return result
    if covariance is not None:
        cluster_count = None
        if clustered_on_entity and entity_col is not None:
            entities = getattr(fitted.model, "dependent", None)
            entity_ids = getattr(entities, "entity_ids", None)
            if entity_ids is not None:
                cluster_count = len({str(value) for value in entity_ids.ravel()})
        result.update(
            {
                "covariance": covariance,
                "covariance_estimator": (
                    "clustered_entity" if clustered_on_entity else covariance
                ),
                "entity_col": entity_col,
                "time_col": time_col,
                "x_columns": [str(label) for label, _ in items],
                "covariance_evidence": {
                    "covariance": covariance,
                    "cluster_variable": entity_col if clustered_on_entity else None,
                    "cluster_entity": clustered_on_entity,
                    "cluster_count": cluster_count,
                    "confidence_level": 0.95,
                    "df_resid": _json_safe_float(getattr(fitted, "df_resid", None)),
                    "inference_version": INFERENCE_ENGINE_VERSION,
                    "inference_distribution": "t" if getattr(fitted, "debiased", False) else "z",
                },
            }
        )
    return result


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


_PLAIN_KINDS = frozenset("biuf")  # bool, signed/unsigned int, float numpy dtypes


def _python_values(values: Any) -> list[Any]:
    """``[_python_scalar(v) for v in values]`` for a column, in one pass where possible.

    For a plain numpy bool/int/float column, ``tolist()`` gives the same
    Python scalars as ``.item()`` on each value, and a missing float is NaN,
    which ``_python_scalar`` maps to None. Other columns (dates, objects,
    nullable extension types) keep the per-value path. Converting six
    million values one by one was about 2 s of a 1,000,000-row OLS.
    """
    dtype = getattr(values, "dtype", None)
    if isinstance(dtype, np.dtype) and dtype.kind in _PLAIN_KINDS:
        array = np.asarray(values)
        out = array.tolist()
        if dtype.kind == "f":
            missing = np.flatnonzero(np.isnan(array))
            for position in missing.tolist():
                out[position] = None
        return out
    return [_python_scalar(value) for value in values]


def _row_id_values(
    frame: pd.DataFrame,
    row_ids: list[str] | tuple[str, ...] | None,
) -> list[str]:
    def collision_safe(values: list[Any]) -> list[str]:
        if set(map(type, values)) <= {str} and len(set(values)) == len(values):
            # Distinct strings convert and render to themselves; the typed
            # rendering below is needed only when renderings collide.
            return list(values)
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
            index = frame.index
            if isinstance(index.dtype, np.dtype) and index.dtype.kind in "iu":
                # Distinct integers render to distinct decimal strings, so the
                # collision check always takes the plain branch.
                return [str(value) for value in index.tolist()]
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


def _aligned_positions(reference_index: list[Any], labels: list[Any]) -> list[int]:
    """Each label's position in the reference, taking a repeated label's occurrences in order.

    Equal sequences map to 0..n-1 (that is what taking each label's next
    occurrence gives); unique labels on a unique reference use one vectorized
    lookup. Anything else keeps the per-label path, which also raises for a
    missing label or one used more often than it occurs.
    """
    if labels is reference_index or labels == reference_index:
        return list(range(len(reference_index)))
    reference = pd.Index(reference_index)
    if reference.is_unique and not reference.hasnans and pd.Index(labels).is_unique:
        found = reference.get_indexer(labels)
        if (found < 0).any():
            raise ValueError(
                "OLS_CLUSTER_ROW_ALIGNMENT: model rows are not aligned to the input frame."
            )
        return found.tolist()
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
    return selected_positions


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
    selected_positions = _aligned_positions(reference_index, labels)
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
    hac: dict[str, Any] | None = None,
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
        y=_python_values(selected[y]),
        X={
            column: _python_values(selected[column])
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
    # Where the inference degrees of freedom come from. Results written before
    # inference engine v2 carry no `inference_version`: their robust and
    # clustered p-values used the normal distribution.
    df_method = (
        ("clusters_minus_one" if covariance == "clustered" else "residual") if use_t else "asymptotic"
    )
    evidence = {
        "covariance": covariance,
        "covariance_estimator": {"clustered": "cluster", "robust": "HC1", "hac": "HAC"}.get(
            covariance, "nonrobust"
        ),
        "engine": "statsmodels",
        "library": "statsmodels",
        "library_version": statsmodels.__version__,
        # HC1 and CR1 both scale the sandwich for finite samples (N/(N-K);
        # G/(G-1) * (N-1)/(N-K)).
        "small_sample_correction": covariance in {"clustered", "robust", "hac"},
        "degrees_of_freedom_correction": covariance == "clustered",
        "use_t": use_t,
        "inference_version": INFERENCE_ENGINE_VERSION,
        "df_method": df_method,
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
        # Newey-West: the kernel, the lag and the rule that chose it, and the
        # column that ordered the rows.
        **({"hac": dict(hac)} if hac is not None else {}),
    }
    inference_kwargs: dict[str, Any] = {
        "covariance": covariance,
        "cluster_var": cluster_col,
        "cluster_count": cluster_count,
        "corrections": {
            "small_sample_correction": covariance == "clustered",
            "degrees_of_freedom_correction": covariance == "clustered",
            **({"hac": {key: hac[key] for key in ("kernel", "lags", "time_order")}} if hac is not None else {}),
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


#: Inference engine v2 (v1.8.10): robust and clustered OLS use Stata's
#: finite-sample reference distributions instead of the normal.
INFERENCE_ENGINE_VERSION = "workbench.inference.v2"
