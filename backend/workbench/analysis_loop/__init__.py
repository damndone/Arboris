"""Deterministic contracts for the Agent Analysis Loop."""

from .canonical import (
    CanonicalJSONError,
    canonical_json_v1,
    numeric_equal,
    numbers_equal,
    sha256_canonical,
)
from .contracts import (
    ComparePayload,
    PacketConflictError,
    PacketEnvelope,
    ensure_packet_idempotent,
)
from .fingerprints import (
    analysis_sample_fingerprint,
    coefficient_schema_fingerprint,
    dataset_snapshot_fingerprint,
    inference_config_fingerprint,
    point_estimation_fingerprint,
)
from .policy import OLS_CLUSTER_POLICY_V1, ols_cluster_policy_v1

__all__ = [
    "CanonicalJSONError",
    "ComparePayload",
    "OLS_CLUSTER_POLICY_V1",
    "PacketConflictError",
    "PacketEnvelope",
    "analysis_sample_fingerprint",
    "canonical_json_v1",
    "coefficient_schema_fingerprint",
    "dataset_snapshot_fingerprint",
    "ensure_packet_idempotent",
    "inference_config_fingerprint",
    "numbers_equal",
    "numeric_equal",
    "ols_cluster_policy_v1",
    "point_estimation_fingerprint",
    "sha256_canonical",
]
