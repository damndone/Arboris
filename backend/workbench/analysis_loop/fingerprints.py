"""Domain-separated deterministic fingerprints for OLS analysis inputs."""

from __future__ import annotations

from typing import Any

from .canonical import canonical_json_v1, sha256_canonical


_OMITTED = object()


def _fingerprint(kind: str, value: Any) -> str:
    return sha256_canonical({"fingerprint_type": kind, "value": value})


def dataset_snapshot_fingerprint(
    snapshot: Any = _OMITTED,
    *,
    dataset: Any = _OMITTED,
) -> str:
    """Fingerprint a dataset source; omitted and explicit ``None`` differ.

    ``snapshot`` and ``dataset`` are aliases. Supplying neither omits the
    source key, while supplying either as ``None`` preserves a JSON null.
    """

    if snapshot is not _OMITTED and dataset is not _OMITTED:
        raise TypeError("provide snapshot or dataset, not both")
    source = snapshot if snapshot is not _OMITTED else dataset
    value = {} if source is _OMITTED else {"source": source}
    return _fingerprint("dataset_snapshot_v1", value)


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
    schema: Any = _OMITTED,
    *,
    coefficients: Any = _OMITTED,
) -> str:
    """Fingerprint a coefficient schema; omitted and explicit ``None`` differ."""

    if schema is not _OMITTED and coefficients is not _OMITTED:
        raise TypeError("provide schema or coefficients, not both")
    source = schema if schema is not _OMITTED else coefficients
    value = {} if source is _OMITTED else {"source": source}
    return _fingerprint("coefficient_schema_v1", value)


def inference_config_fingerprint(
    *,
    covariance: Any,
    cluster_var: Any,
    cluster_group_vector: Any = _OMITTED,
    cluster_group_vector_fingerprint: Any = _OMITTED,
    cluster_count: Any,
    corrections: Any,
    df: Any,
    use_t: Any,
    confidence_level: Any,
    engine: Any,
    version: Any = _OMITTED,
    engine_version: Any = _OMITTED,
    inference_distribution: Any = _OMITTED,
    p_value_method: Any = _OMITTED,
    confidence_interval_method: Any = _OMITTED,
) -> str:
    """Fingerprint inference settings with sentinel-preserved aliases.

    Omitted cluster-vector/version aliases leave their keys absent; explicit
    ``None`` emits JSON null. The raw/fingerprint and version/engine-version
    names are aliases and cannot be supplied together.
    """

    if version is not _OMITTED and engine_version is not _OMITTED:
        raise TypeError("provide version or engine_version, not both")
    if (
        cluster_group_vector is not _OMITTED
        and cluster_group_vector_fingerprint is not _OMITTED
    ):
        raise TypeError("provide cluster_group_vector or its fingerprint, not both")
    vector_value = (
        cluster_group_vector
        if cluster_group_vector is not _OMITTED
        else cluster_group_vector_fingerprint
    )
    version_value = version if version is not _OMITTED else engine_version
    value = {
        "covariance": covariance,
        "cluster_var": cluster_var,
        "cluster_count": cluster_count,
        "corrections": corrections,
        "df": df,
        "use_t": use_t,
        "confidence_level": confidence_level,
        "engine": engine,
    }
    if vector_value is not _OMITTED:
        value["cluster_group_vector"] = vector_value
    if version_value is not _OMITTED:
        value["version"] = version_value
    for key, item in (
        ("inference_distribution", inference_distribution),
        ("p_value_method", p_value_method),
        ("confidence_interval_method", confidence_interval_method),
    ):
        if item is not _OMITTED:
            value[key] = item
    return _fingerprint(
        "inference_config_v1",
        value,
    )
