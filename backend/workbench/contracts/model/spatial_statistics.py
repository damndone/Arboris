"""Closed contracts for global spatial-association statistics.

The contract deliberately describes a finite vector and an explicit graph.  It
does not describe coordinates, learned neighbours, local statistics, or a
spatial regression model; those are separate capabilities with different
estimands and identification assumptions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json
from workbench.contracts.model.p7_extension import P7ScopeMetadata


SPATIAL_STATISTICS_CONTRACT = "spatial_statistics.result"
SPATIAL_STATISTICS_CONTRACT_VERSION = "1.0"
SPATIAL_STATISTICS_OPERATION_IDS = frozenset(
    {"spatial.moran_i", "spatial.geary_c", "spatial.getis_ord_g"}
)
SPATIAL_STATISTICS_STATUSES = frozenset({"completed", "rejected", "failed"})
SPATIAL_STATISTICS_REASON_CODES = frozenset(
    {"SPATIAL_COMPLETED", "SPATIAL_REJECTED", "SPATIAL_FAILED"}
)
_WEIGHT_KINDS = frozenset({"matrix", "edges"})
_NORMALIZATIONS = frozenset({"none", "row_standardize"})
_SYMMETRY_POLICIES = frozenset({"require_symmetric", "allow_asymmetric"})
_ROW_SUM_POLICIES = frozenset({"require_positive", "allow_zero_islands"})
_ISLAND_POLICIES = frozenset({"reject", "keep_zero"})
_TAILS = frozenset({"two-sided", "greater", "less"})
_INPUT_FIELDS = {"operation_id", "values", "weights", "weight_policy", "permutation_policy"}
_RESULT_FIELDS = {
    "contract", "contract_version", "operation_id", "status", "reason_code",
    "n_observations", "n_edges", "result", "evidence_digest",
}
_RAW_RESULT_KEYS = frozenset({"permutation_rows", "raw_values", "raw_matrix", "matrix", "rows"})


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{field} must be finite")
    return number


def _positive_int(value: Any, field: str, *, maximum: int = 1_000_000) -> int:
    if type(value) is not int or value < 1 or value > maximum:
        raise ContractError(f"{field} must be a positive bounded integer")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{field} must be a non-empty string")
    return value


def _finite_vector(value: Any, field: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{field} must be a numeric sequence")
    values = tuple(_finite(item, f"{field}[]") for item in value)
    if len(values) < 3:
        raise ContractError(f"{field} must contain at least three observations")
    return values


@dataclass(frozen=True)
class SpatialWeightsSpec:
    """An explicit finite graph represented either as a matrix or edge list."""

    kind: str
    n_nodes: int
    matrix: tuple[tuple[float, ...], ...] | None = None
    edges: tuple[tuple[int, int, float], ...] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _WEIGHT_KINDS:
            raise ContractError("weights kind is not declared")
        if type(self.n_nodes) is not int or self.n_nodes < 3 or self.n_nodes > 100_000:
            raise ContractError("weights n_nodes is outside the supported bound")
        if self.kind == "matrix":
            if self.matrix is None or self.edges is not None:
                raise ContractError("matrix weights require only matrix representation")
            rows = tuple(tuple(_finite(v, "weights.matrix[]") for v in row) for row in self.matrix)
            if len(rows) != self.n_nodes or any(len(row) != self.n_nodes for row in rows):
                raise ContractError("weights matrix must be square with n_nodes rows")
            object.__setattr__(self, "matrix", rows)
        else:
            if self.edges is None or self.matrix is not None:
                raise ContractError("edge weights require only edge representation")
            seen: set[tuple[int, int]] = set()
            normalized: list[tuple[int, int, float]] = []
            for edge in self.edges:
                if not isinstance(edge, Sequence) or len(edge) != 3:
                    raise ContractError("each edge must be [source, target, weight]")
                source, target, weight = edge
                if type(source) is not int or type(target) is not int:
                    raise ContractError("edge endpoints must be integers")
                if not 0 <= source < self.n_nodes or not 0 <= target < self.n_nodes:
                    raise ContractError("edge endpoint is outside n_nodes")
                key = (source, target)
                if key in seen:
                    raise ContractError("duplicate directed edge is not allowed")
                seen.add(key)
                normalized.append((source, target, _finite(weight, "weights.edges.weight")))
            object.__setattr__(self, "edges", tuple(normalized))

    @classmethod
    def from_matrix(cls, matrix: Sequence[Sequence[float]]) -> "SpatialWeightsSpec":
        try:
            rows = tuple(tuple(row) for row in matrix)
        except TypeError as exc:
            raise ContractError("weights matrix must be a square sequence") from exc
        return cls(kind="matrix", n_nodes=len(rows), matrix=rows)

    @classmethod
    def from_edges(cls, n_nodes: int, edges: Sequence[Sequence[object]]) -> "SpatialWeightsSpec":
        return cls(kind="edges", n_nodes=n_nodes, edges=tuple(tuple(edge) for edge in edges))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialWeightsSpec":
        if not isinstance(value, Mapping):
            raise ContractError("weights must be a mapping")
        kind = value.get("kind")
        if kind == "matrix":
            require_exact_keys(value, {"kind", "n_nodes", "matrix"}, "matrix weights")
            return cls(kind=kind, n_nodes=value["n_nodes"], matrix=tuple(tuple(row) for row in value["matrix"]))
        if kind == "edges":
            require_exact_keys(value, {"kind", "n_nodes", "edges"}, "edge weights")
            return cls(kind=kind, n_nodes=value["n_nodes"], edges=tuple(tuple(edge) for edge in value["edges"]))
        raise ContractError("weights kind is not declared")

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "matrix":
            return {"kind": self.kind, "n_nodes": self.n_nodes, "matrix": [list(row) for row in self.matrix or ()]}
        return {"kind": self.kind, "n_nodes": self.n_nodes, "edges": [list(edge) for edge in self.edges or ()]}


@dataclass(frozen=True)
class SpatialWeightPolicy:
    normalization: str
    symmetry_policy: str
    row_sum_policy: str
    zero_diagonal_policy: str
    islands_policy: str
    negative_weight_policy: str

    def __post_init__(self) -> None:
        choices = {
            "normalization": (_NORMALIZATIONS, self.normalization),
            "symmetry_policy": (_SYMMETRY_POLICIES, self.symmetry_policy),
            "row_sum_policy": (_ROW_SUM_POLICIES, self.row_sum_policy),
            "zero_diagonal_policy": ({"require_zero"}, self.zero_diagonal_policy),
            "islands_policy": (_ISLAND_POLICIES, self.islands_policy),
            "negative_weight_policy": ({"reject"}, self.negative_weight_policy),
        }
        for field, (allowed, value) in choices.items():
            if type(value) is not str or value not in allowed:
                raise ContractError(f"{field} is not declared")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialWeightPolicy":
        require_exact_keys(value, {"normalization", "symmetry_policy", "row_sum_policy", "zero_diagonal_policy", "islands_policy", "negative_weight_policy"}, "spatial weight policy")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, str]:
        return {
            "normalization": self.normalization,
            "symmetry_policy": self.symmetry_policy,
            "row_sum_policy": self.row_sum_policy,
            "zero_diagonal_policy": self.zero_diagonal_policy,
            "islands_policy": self.islands_policy,
            "negative_weight_policy": self.negative_weight_policy,
        }


@dataclass(frozen=True)
class PermutationPolicy:
    n_permutations: int
    seed: int | None
    tail: str
    plus_one: bool

    def __post_init__(self) -> None:
        _positive_int(self.n_permutations, "n_permutations", maximum=20_000)
        if self.seed is not None and (type(self.seed) is not int or self.seed < 0):
            raise ContractError("seed must be a non-negative integer or null")
        if self.tail not in _TAILS:
            raise ContractError("tail is not declared")
        if type(self.plus_one) is not bool:
            raise ContractError("plus_one must be boolean")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PermutationPolicy":
        require_exact_keys(value, {"n_permutations", "seed", "tail", "plus_one"}, "permutation policy")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"n_permutations": self.n_permutations, "seed": self.seed, "tail": self.tail, "plus_one": self.plus_one}


@dataclass(frozen=True)
class SpatialStatisticsRequest:
    operation_id: str
    values: tuple[float, ...]
    weights: SpatialWeightsSpec
    weight_policy: SpatialWeightPolicy
    permutation_policy: PermutationPolicy

    def __post_init__(self) -> None:
        if self.operation_id not in SPATIAL_STATISTICS_OPERATION_IDS:
            raise ContractError("operation_id is not a declared spatial operation")
        values = _finite_vector(self.values, "values")
        if len(values) != self.weights.n_nodes:
            raise ContractError("values length must match weights n_nodes")
        object.__setattr__(self, "values", values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialStatisticsRequest":
        require_exact_keys(value, _INPUT_FIELDS, "spatial statistics input")
        return cls(
            operation_id=value["operation_id"],
            values=tuple(value["values"]),
            weights=SpatialWeightsSpec.from_dict(value["weights"]),
            weight_policy=SpatialWeightPolicy.from_dict(value["weight_policy"]),
            permutation_policy=PermutationPolicy.from_dict(value["permutation_policy"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "values": list(self.values),
            "weights": self.weights.to_dict(),
            "weight_policy": self.weight_policy.to_dict(),
            "permutation_policy": self.permutation_policy.to_dict(),
        }


def _reject_raw(value: Any, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _RAW_RESULT_KEYS:
                raise ContractError(f"{path}.{key} must not expose raw spatial observations")
            _reject_raw(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw(item, f"{path}[{index}]")


def _validate_scope(value: Mapping[str, Any]) -> None:
    P7ScopeMetadata.from_dict(value)


def validate_spatial_statistics_result(value: Mapping[str, Any]) -> None:
    require_exact_keys(value, _RESULT_FIELDS, "spatial statistics result envelope")
    if value["contract"] != SPATIAL_STATISTICS_CONTRACT or value["contract_version"] != SPATIAL_STATISTICS_CONTRACT_VERSION:
        raise ContractError("spatial statistics contract or version is not declared")
    if value["operation_id"] not in SPATIAL_STATISTICS_OPERATION_IDS:
        raise ContractError("operation_id is not declared")
    status = value["status"]
    reason = value["reason_code"]
    expected = {"completed": "SPATIAL_COMPLETED", "rejected": "SPATIAL_REJECTED", "failed": "SPATIAL_FAILED"}.get(status)
    if expected is None or reason != expected:
        raise ContractError("status and reason_code are inconsistent")
    if type(value["n_observations"]) is not int or value["n_observations"] < 0:
        raise ContractError("n_observations must be a non-negative integer")
    if type(value["n_edges"]) is not int or value["n_edges"] < 0:
        raise ContractError("n_edges must be a non-negative integer")
    result = value["result"]
    if not isinstance(result, Mapping):
        raise ContractError("result must be a mapping")
    _reject_raw(result)
    if status == "completed":
        if "scope" not in result:
            raise ContractError("completed spatial result requires scope")
        _validate_scope(result["scope"])
        if "observed_statistic" not in result:
            raise ContractError("completed spatial result requires observed_statistic")
        _finite(result["observed_statistic"], "result.observed_statistic")
        digest = value["evidence_digest"]
        if type(digest) is not str or digest != sha256_canonical({"operation_id": value["operation_id"], "result": result}):
            raise ContractError("evidence_digest does not match spatial result")
    elif value["evidence_digest"] is not None:
        raise ContractError("non-completed spatial result cannot publish evidence_digest")
    freeze_json(result, "result")


def make_spatial_statistics_result(*, operation_id: str, status: str, reason_code: str, n_observations: int, n_edges: int, result: Mapping[str, Any], evidence_digest: str | None) -> dict[str, Any]:
    payload = {
        "contract": SPATIAL_STATISTICS_CONTRACT,
        "contract_version": SPATIAL_STATISTICS_CONTRACT_VERSION,
        "operation_id": operation_id,
        "status": status,
        "reason_code": reason_code,
        "n_observations": n_observations,
        "n_edges": n_edges,
        "result": result,
        "evidence_digest": evidence_digest,
    }
    validate_spatial_statistics_result(payload)
    return payload


__all__ = [
    "PermutationPolicy", "SpatialStatisticsRequest", "SpatialWeightPolicy", "SpatialWeightsSpec",
    "SPATIAL_STATISTICS_CONTRACT", "SPATIAL_STATISTICS_CONTRACT_VERSION", "SPATIAL_STATISTICS_OPERATION_IDS",
    "make_spatial_statistics_result", "validate_spatial_statistics_result",
]
