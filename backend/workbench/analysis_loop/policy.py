"""Immutable policy contract for the OLS clustered covariance golden flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


_EXPECTED_POLICY_VALUES: dict[str, Any] = {
    "allowed_model": "ols",
    "allowed_covariance": "clustered",
    "allowed_cluster_types": ("integer", "string", "category"),
    "reject_boolean": True,
    "reject_float": True,
    "reject_mixed_object": True,
    "reject_null_or_nan": True,
    "hard_min_cluster_count": 2,
    "warning_cluster_count_below": 30,
    "one_way_only": True,
    "allow_singleton_clusters": True,
    "all_singleton_clusters": "warning",
    "small_sample_correction": True,
    "degrees_of_freedom_correction": True,
    "use_t": False,
    "confidence_level": 0.95,
    "alpha": 0.05,
    "inference_distribution": "normal",
    "p_value_method": "normal_z",
    "confidence_interval_method": "normal_z",
    "effective_degrees_of_freedom": "record_per_target",
    "engine": "statsmodels",
    "minimum_engine_version": 0.14,
}


@dataclass(frozen=True)
class OLSClusterPolicyV1:
    allowed_model: str
    allowed_covariance: str
    allowed_cluster_types: tuple[str, ...]
    reject_boolean: bool
    reject_float: bool
    reject_mixed_object: bool
    reject_null_or_nan: bool
    hard_min_cluster_count: int
    warning_cluster_count_below: int
    one_way_only: bool
    allow_singleton_clusters: bool
    all_singleton_clusters: str
    small_sample_correction: bool
    degrees_of_freedom_correction: bool
    use_t: bool
    confidence_level: float
    alpha: float
    inference_distribution: str
    p_value_method: str
    confidence_interval_method: str
    effective_degrees_of_freedom: str
    engine: str
    minimum_engine_version: float

    def __post_init__(self) -> None:
        _validate_policy_instance(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OLSClusterPolicyV1":
        if not isinstance(value, Mapping):
            raise TypeError("policy must be a mapping")
        fields = set(_EXPECTED_POLICY_VALUES)
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        if missing:
            raise ValueError(
                "missing field(s) for exact v1 contract: " + ", ".join(missing)
            )
        if extra:
            raise ValueError(
                "extra field(s) for exact v1 contract: " + ", ".join(extra)
            )
        candidate_values = dict(value)
        cluster_types = candidate_values["allowed_cluster_types"]
        if not isinstance(cluster_types, (list, tuple)):
            raise TypeError(
                "allowed_cluster_types: expected list or tuple, "
                f"actual {type(cluster_types).__name__}"
            )
        candidate_values["allowed_cluster_types"] = tuple(cluster_types)
        return cls(**candidate_values)


def _validate_policy_instance(policy: OLSClusterPolicyV1) -> None:
    for field, expected in _EXPECTED_POLICY_VALUES.items():
        actual = getattr(policy, field)
        if field == "allowed_cluster_types":
            if type(actual) is not tuple:
                raise TypeError(
                    f"{field}: expected tuple[str, ...], actual {type(actual).__name__}"
                )
            if any(type(item) is not str for item in actual):
                raise TypeError(
                    f"{field}: expected tuple[str, ...], actual item types"
                )
        elif type(expected) is bool and type(actual) is not bool:
            raise TypeError(
                f"{field}: expected bool, actual {type(actual).__name__}"
            )
        elif type(expected) is int and type(actual) is not int:
            raise TypeError(
                f"{field}: expected int, actual {type(actual).__name__}"
            )
        elif type(expected) is float and type(actual) is not float:
            raise TypeError(
                f"{field}: expected float, actual {type(actual).__name__}"
            )
        elif type(expected) is str and type(actual) is not str:
            raise TypeError(
                f"{field}: expected str, actual {type(actual).__name__}"
            )
        if actual != expected:
            raise ValueError(f"{field}: expected {expected!r}, actual {actual!r}")


ols_cluster_policy_v1 = OLSClusterPolicyV1(**_EXPECTED_POLICY_VALUES)

OLS_CLUSTER_POLICY_V1 = ols_cluster_policy_v1
