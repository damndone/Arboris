"""Immutable policy contract for the OLS clustered covariance golden flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OLSClusterPolicyV1":
        return cls(
            allowed_model=str(value["allowed_model"]),
            allowed_covariance=str(value["allowed_covariance"]),
            allowed_cluster_types=tuple(value["allowed_cluster_types"]),
            reject_boolean=bool(value["reject_boolean"]),
            reject_float=bool(value["reject_float"]),
            reject_mixed_object=bool(value["reject_mixed_object"]),
            reject_null_or_nan=bool(value["reject_null_or_nan"]),
            hard_min_cluster_count=int(value["hard_min_cluster_count"]),
            warning_cluster_count_below=int(value["warning_cluster_count_below"]),
            one_way_only=bool(value["one_way_only"]),
            allow_singleton_clusters=bool(value["allow_singleton_clusters"]),
            all_singleton_clusters=str(value["all_singleton_clusters"]),
            small_sample_correction=bool(value["small_sample_correction"]),
            degrees_of_freedom_correction=bool(value["degrees_of_freedom_correction"]),
            use_t=bool(value["use_t"]),
            confidence_level=float(value["confidence_level"]),
            alpha=float(value["alpha"]),
            inference_distribution=str(value["inference_distribution"]),
            p_value_method=str(value["p_value_method"]),
            confidence_interval_method=str(value["confidence_interval_method"]),
            effective_degrees_of_freedom=str(value["effective_degrees_of_freedom"]),
            engine=str(value["engine"]),
            minimum_engine_version=float(value["minimum_engine_version"]),
        )


ols_cluster_policy_v1 = OLSClusterPolicyV1(
    allowed_model="ols",
    allowed_covariance="clustered",
    allowed_cluster_types=("integer", "string", "category"),
    reject_boolean=True,
    reject_float=True,
    reject_mixed_object=True,
    reject_null_or_nan=True,
    hard_min_cluster_count=2,
    warning_cluster_count_below=30,
    one_way_only=True,
    allow_singleton_clusters=True,
    all_singleton_clusters="warning",
    small_sample_correction=True,
    degrees_of_freedom_correction=True,
    use_t=False,
    confidence_level=0.95,
    alpha=0.05,
    inference_distribution="normal",
    p_value_method="normal_z",
    confidence_interval_method="normal_z",
    effective_degrees_of_freedom="record_per_target",
    engine="statsmodels",
    minimum_engine_version=0.14,
)

OLS_CLUSTER_POLICY_V1 = ols_cluster_policy_v1
