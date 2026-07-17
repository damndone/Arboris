"""Domain-separated deterministic fingerprints for OLS analysis inputs."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json_v1, sha256_canonical


def _fingerprint(kind: str, value: Any) -> str:
    return sha256_canonical({"fingerprint_type": kind, "value": value})


def dataset_snapshot_fingerprint(
    snapshot: Any = None,
    *,
    dataset: Any = None,
) -> str:
    if snapshot is not None and dataset is not None:
        raise TypeError("provide snapshot or dataset, not both")
    if snapshot is None:
        snapshot = dataset
    return _fingerprint("dataset_snapshot_v1", snapshot)


def analysis_sample_fingerprint(
    row_set: Any,
    row_order: Any,
) -> str:
    """Fingerprint membership and the order in which rows enter estimation."""

    row_set_value = sorted(
        row_set,
        key=lambda item: canonical_json_v1(item),
    )
    return _fingerprint(
        "analysis_sample_v1",
        {"row_set": row_set_value, "row_order": row_order},
    )


def point_estimation_fingerprint(
    *,
    y: Any,
    X: Any,
    weights: Any,
    intercept: bool,
    categorical_encoding: Any,
    missing_policy: Any,
    rows: Any,
    solver_options: Any,
) -> str:
    """Fingerprint only inputs that can change the point estimate."""

    return _fingerprint(
        "point_estimation_v1",
        {
            "y": y,
            "X": X,
            "weights": weights,
            "intercept": intercept,
            "categorical_encoding": categorical_encoding,
            "missing_policy": missing_policy,
            "rows": rows,
            "solver_options": solver_options,
        },
    )


def coefficient_schema_fingerprint(
    schema: Any = None,
    *,
    coefficients: Any = None,
) -> str:
    if schema is not None and coefficients is not None:
        raise TypeError("provide schema or coefficients, not both")
    if schema is None:
        schema = coefficients
    return _fingerprint("coefficient_schema_v1", schema)


def inference_config_fingerprint(
    *,
    covariance: Any,
    cluster_var: Any,
    cluster_group_vector: Any = None,
    cluster_group_vector_fingerprint: str | None = None,
    cluster_count: Any,
    corrections: Any,
    df: Any,
    use_t: Any,
    confidence_level: Any,
    engine: Any,
    version: Any = None,
    engine_version: Any = None,
) -> str:
    if version is not None and engine_version is not None:
        raise TypeError("provide version or engine_version, not both")
    vector_value = (
        cluster_group_vector_fingerprint
        if cluster_group_vector_fingerprint is not None
        else cluster_group_vector
    )
    return _fingerprint(
        "inference_config_v1",
        {
            "covariance": covariance,
            "cluster_var": cluster_var,
            "cluster_group_vector": vector_value,
            "cluster_count": cluster_count,
            "corrections": corrections,
            "df": df,
            "use_t": use_t,
            "confidence_level": confidence_level,
            "engine": engine,
            "version": version if version is not None else engine_version,
        },
    )
