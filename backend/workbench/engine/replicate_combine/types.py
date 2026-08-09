"""Immutable runtime types and JSON-safe evidence envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, ClassVar

from workbench.contracts.model.replicate_combine import (
    MAX_EVIDENCE_SCALARS,
    MAX_REQUESTED_REPLICATES,
    MAX_SEED,
    REPLICATE_COMBINE_CONTRACT_VERSION,
    REPLICATE_KINDS,
    ReplicateContractError,
    ReplicatePlan,
)
from workbench.contracts.common.envelope import freeze_json, thaw_json

from .errors import STABLE_FAILURE_REASONS, ReplicateCombineError


BATCH_CONTRACT = "replicate_combine.batch"
_BATCH_FIELDS = frozenset(
    {
        "contract",
        "contract_version",
        "kind",
        "requested_count",
        "succeeded_count",
        "failed_count",
        "seed",
        "status",
        "reason_code",
        "failure_reasons",
        "provenance",
        "digest",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "strategy_id",
        "adapter_id",
        "base_seed",
        "derived_seeds",
        "replicate_order",
        "evidence_scalar_count",
        "evidence_commitment",
        "provenance_commitment",
    }
)
_STATUS = frozenset({"completed", "completed_with_failures", "failed"})
_HEX64 = set("0123456789abcdef")
_BATCH_REASON_CODES = frozenset(
    {
        "REPLICATE_COMPLETED",
        "REPLICATE_PARTIAL_FAILURE",
        "REPLICATE_FAILURE_BUDGET_EXCEEDED",
        "REPLICATE_EVIDENCE_BUDGET_EXCEEDED",
    }
)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReplicateContractError(
            "REPLICATE_NON_JSON_EVIDENCE", "evidence is not canonical JSON"
        ) from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_hex_digest(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX64


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ReplicateContractError(
                "REPLICATE_NON_JSON_PROVENANCE", "mapping keys must be strings"
            )
        return {key: _copy_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_json(item) for item in value]
    if isinstance(value, list):
        return [_copy_json(item) for item in value]
    return value


def _require_json(value: Any, label: str) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ReplicateContractError("REPLICATE_NON_FINITE_PROVENANCE", f"{label} is not finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_json(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ReplicateContractError("REPLICATE_NON_JSON_PROVENANCE", f"{label} keys must be strings")
        for key, item in value.items():
            _require_json(item, f"{label}.{key}")
        return
    raise ReplicateContractError("REPLICATE_NON_JSON_PROVENANCE", f"{label} is not JSON-safe")


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if any(type(key) is not str for key in value):
        raise ReplicateContractError("REPLICATE_UNKNOWN_FIELD", f"{label} keys must be strings")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ReplicateContractError(
            "REPLICATE_UNKNOWN_FIELD", f"unknown {label} field: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReplicateContractError(
            "REPLICATE_MISSING_FIELD", f"missing {label} field: {', '.join(sorted(missing))}"
        )


def _require_exact_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise ReplicateContractError("REPLICATE_INVALID_BATCH_FIELD", f"{label} is invalid")
    return value


def _validate_provenance(
    value: Any,
    *,
    requested_count: int,
    status: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplicateContractError("REPLICATE_INVALID_PROVENANCE", "provenance must be a mapping")
    _require_exact_keys(value, _PROVENANCE_FIELDS, "provenance")
    _require_json(dict(value), "provenance")

    for field_name in ("strategy_id", "adapter_id"):
        field_value = value[field_name]
        if type(field_value) is not str or not field_value:
            raise ReplicateContractError("REPLICATE_INVALID_PROVENANCE", f"{field_name} is invalid")
    base_seed = _require_exact_int(value["base_seed"], "base_seed")
    if base_seed > MAX_SEED:
        raise ReplicateContractError("REPLICATE_INVALID_PROVENANCE", "base_seed exceeds the hard limit")

    derived_seeds = value["derived_seeds"]
    order = value["replicate_order"]
    if not isinstance(derived_seeds, list) or any(
        type(item) is not int
        or isinstance(item, bool)
        or item < 0
        or item > MAX_SEED
        for item in derived_seeds
    ):
        raise ReplicateContractError("REPLICATE_INVALID_PROVENANCE", "derived_seeds is invalid")
    if len(derived_seeds) not in {0, requested_count} or len(set(derived_seeds)) != len(derived_seeds):
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "derived_seeds count is inconsistent")
    if not isinstance(order, list) or any(
        type(item) is not int or isinstance(item, bool) or item < 0 for item in order
    ):
        raise ReplicateContractError("REPLICATE_INVALID_PROVENANCE", "replicate_order is invalid")
    if order:
        if order != list(range(requested_count)):
            raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "replicate_order is inconsistent")
    elif derived_seeds:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "seed/order evidence is inconsistent")

    scalar_count = _require_exact_int(value["evidence_scalar_count"], "evidence_scalar_count")
    if scalar_count > MAX_EVIDENCE_SCALARS:
        raise ReplicateContractError("REPLICATE_EVIDENCE_BUDGET_EXCEEDS_LIMIT", "evidence count exceeds limit")
    commitment = value["evidence_commitment"]
    if not _is_hex_digest(commitment) or (status == "failed" and commitment == "0" * 64):
        raise ReplicateContractError("REPLICATE_INVALID_COMMITMENT", "evidence_commitment is invalid")
    public_commitment = value["provenance_commitment"]
    if not _is_hex_digest(public_commitment) or public_commitment == "0" * 64:
        raise ReplicateContractError("REPLICATE_INVALID_COMMITMENT", "provenance_commitment is invalid")
    return {
        "strategy_id": value["strategy_id"],
        "adapter_id": value["adapter_id"],
        "base_seed": base_seed,
        "derived_seeds": list(derived_seeds),
        "replicate_order": list(order),
        "evidence_scalar_count": scalar_count,
        "evidence_commitment": commitment,
        "provenance_commitment": public_commitment,
    }


@dataclass(frozen=True)
class ReplicateEvidence:
    """Internal scalar evidence; raw values never leave the runner envelope."""

    scalars: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.scalars, Mapping):
            raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "scalars must be a mapping")
        object.__setattr__(self, "scalars", MappingProxyType(dict(self.scalars)))


class ReplicateStrategy:
    """Typed strategy interface used only through ReplicateRegistry."""

    strategy_id: ClassVar[str] = ""

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        raise NotImplementedError


class ReplicateAdapter:
    """Typed adapter interface between a strategy and a combiner."""

    adapter_id: ClassVar[str] = ""

    def adapt(
        self,
        evidence: ReplicateEvidence,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
    ) -> ReplicateEvidence:
        raise NotImplementedError


class ReplicateCombiner:
    """Typed internal combiner; its raw evidence never crosses the runner boundary."""

    combiner_id: ClassVar[str] = ""

    def combine(
        self,
        evidence: Sequence[ReplicateEvidence],
        *,
        plan: ReplicatePlan,
        batch: "ReplicateBatch",
    ) -> Mapping[str, Any]:
        raise NotImplementedError


_FORBIDDEN_COMBINED_KEYS = frozenset(
    {
        "replicate_rows",
        "replicate_values",
        "raw_data",
        "raw_rows",
        "raw_values",
        "distribution_values",
    }
)


def _validate_combined_result(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplicateCombineError(
            "REPLICATE_COMBINER_INVALID_RESULT", "combiner result must be a mapping"
        )

    def visit(node: Any, label: str) -> None:
        if isinstance(node, Mapping):
            if any(key in _FORBIDDEN_COMBINED_KEYS for key in node):
                raise ReplicateCombineError(
                    "REPLICATE_RAW_VALUES_FORBIDDEN",
                    f"combiner result contains raw replicate field at {label}",
                )
            if any(type(key) is not str for key in node):
                raise ReplicateCombineError(
                    "REPLICATE_COMBINER_INVALID_RESULT",
                    f"combiner result keys at {label} must be strings",
                )
            for key, child in node.items():
                visit(child, f"{label}.{key}")
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{label}[{index}]")
            return
        _require_json(node, label)

    visit(value, "result")
    return _copy_json(value)


@dataclass(frozen=True, init=False)
class ReplicateCombinedResult:
    """Aggregate combiner output paired with its bounded execution batch."""

    batch: "ReplicateBatch"
    _result: Mapping[str, Any]

    def __init__(self, *, batch: "ReplicateBatch", result: Mapping[str, Any]) -> None:
        if not isinstance(batch, ReplicateBatch):
            raise ReplicateCombineError(
                "REPLICATE_INVALID_BATCH", "combined result requires a ReplicateBatch"
            )
        normalized = _validate_combined_result(result)
        object.__setattr__(self, "batch", batch)
        object.__setattr__(self, "_result", freeze_json(normalized, "result"))

    @property
    def result(self) -> dict[str, Any]:
        return thaw_json(self._result)

    def to_dict(self) -> dict[str, Any]:
        return {"batch": self.batch.to_dict(), "result": self.result}


@dataclass(frozen=True, init=False)
class ReplicateBatch:
    """Bounded execution evidence; no replicate rows or scalar values."""

    kind: str
    requested_count: int
    succeeded_count: int
    failed_count: int
    seed: int
    status: str
    reason_code: str
    _failure_reasons: Mapping[str, int]
    _provenance: Mapping[str, Any]
    digest: str | None

    def __init__(
        self,
        *,
        kind: str,
        requested_count: int,
        succeeded_count: int,
        failed_count: int,
        seed: int,
        status: str,
        reason_code: str,
        failure_reasons: Mapping[str, int],
        provenance: Mapping[str, Any],
        digest: str | None,
    ) -> None:
        raw_payload = {
            "contract": BATCH_CONTRACT,
            "contract_version": REPLICATE_COMBINE_CONTRACT_VERSION,
            "kind": kind,
            "requested_count": requested_count,
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "seed": seed,
            "status": status,
            "reason_code": reason_code,
            "failure_reasons": failure_reasons,
            "provenance": provenance,
            "digest": digest,
        }
        normalized = _validate_batch_payload(raw_payload)
        object.__setattr__(self, "kind", normalized["kind"])
        object.__setattr__(self, "requested_count", normalized["requested_count"])
        object.__setattr__(self, "succeeded_count", normalized["succeeded_count"])
        object.__setattr__(self, "failed_count", normalized["failed_count"])
        object.__setattr__(self, "seed", normalized["seed"])
        object.__setattr__(self, "status", normalized["status"])
        object.__setattr__(self, "reason_code", normalized["reason_code"])
        object.__setattr__(
            self,
            "_failure_reasons",
            freeze_json(normalized["failure_reasons"], "failure_reasons"),
        )
        object.__setattr__(
            self,
            "_provenance",
            freeze_json(normalized["provenance"], "provenance"),
        )
        object.__setattr__(self, "digest", normalized["digest"])

    @property
    def failure_reasons(self) -> dict[str, int]:
        return thaw_json(self._failure_reasons)

    @property
    def provenance(self) -> dict[str, Any]:
        # Return a detached JSON copy.  The stored mapping remains deeply
        # frozen, so callers cannot mutate the batch's validated state.
        return thaw_json(self._provenance)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract": BATCH_CONTRACT,
            "contract_version": REPLICATE_COMBINE_CONTRACT_VERSION,
            "kind": self.kind,
            "requested_count": self.requested_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "seed": self.seed,
            "status": self.status,
            "reason_code": self.reason_code,
            "failure_reasons": dict(self.failure_reasons),
            "provenance": _copy_json(self.provenance),
            "digest": self.digest,
        }
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplicateBatch":
        normalized = _validate_batch_payload(value)
        return cls(**normalized)


def _validate_batch_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplicateContractError("REPLICATE_INVALID_PAYLOAD", "batch must be a mapping")
    _require_exact_keys(value, _BATCH_FIELDS, "batch")
    if value["contract"] != BATCH_CONTRACT:
        raise ReplicateContractError("REPLICATE_UNSUPPORTED_CONTRACT", "batch contract is not declared")
    if value["contract_version"] != REPLICATE_COMBINE_CONTRACT_VERSION:
        raise ReplicateContractError(
            "REPLICATE_UNSUPPORTED_CONTRACT_VERSION", "batch version is not supported"
        )
    kind = value["kind"]
    if type(kind) is not str or kind not in REPLICATE_KINDS:
        raise ReplicateContractError("REPLICATE_INVALID_KIND", "batch kind is not declared")
    requested = _require_exact_int(value["requested_count"], "requested_count", minimum=1)
    if requested > MAX_REQUESTED_REPLICATES:
        raise ReplicateContractError(
            "REPLICATE_REQUESTED_COUNT_EXCEEDS_LIMIT", "requested_count exceeds the hard limit"
        )
    succeeded = _require_exact_int(value["succeeded_count"], "succeeded_count")
    failed = _require_exact_int(value["failed_count"], "failed_count")
    seed = _require_exact_int(value["seed"], "seed")
    if seed > MAX_SEED:
        raise ReplicateContractError("REPLICATE_INVALID_BATCH_FIELD", "seed exceeds the hard limit")
    status = value["status"]
    if type(status) is not str or status not in _STATUS:
        raise ReplicateContractError("REPLICATE_INVALID_BATCH_FIELD", "status is invalid")
    reason_code = value["reason_code"]
    if type(reason_code) is not str or reason_code not in _BATCH_REASON_CODES:
        raise ReplicateContractError("REPLICATE_INVALID_REASON_CODE", "batch reason_code is not declared")
    is_evidence_budget_preflight = (
        status == "failed"
        and reason_code == "REPLICATE_EVIDENCE_BUDGET_EXCEEDED"
        and succeeded == 0
        and failed == 0
    )
    if not is_evidence_budget_preflight and succeeded + failed != requested:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "batch counts do not match requested count")
    if status == "completed" and (failed != 0 or reason_code != "REPLICATE_COMPLETED"):
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "completed status is inconsistent")
    if status == "completed_with_failures" and (
        failed == 0 or reason_code != "REPLICATE_PARTIAL_FAILURE"
    ):
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "partial status is inconsistent")
    if status == "failed" and reason_code not in {
        "REPLICATE_FAILURE_BUDGET_EXCEEDED",
        "REPLICATE_EVIDENCE_BUDGET_EXCEEDED",
    }:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "failed status is inconsistent")
    if status == "failed" and not is_evidence_budget_preflight and failed == 0:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "failed status lacks failed replicates")

    failure_reasons = value["failure_reasons"]
    if not isinstance(failure_reasons, Mapping) or any(
        type(key) is not str
        or key not in STABLE_FAILURE_REASONS
        or type(count) is not int
        or isinstance(count, bool)
        or count < 0
        for key, count in failure_reasons.items()
    ):
        raise ReplicateContractError("REPLICATE_INVALID_REASON_CODE", "failure reason is not declared")
    if sum(failure_reasons.values()) != failed:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "failure reasons do not match count")
    provenance = _validate_provenance(
        value["provenance"],
        requested_count=requested,
        status=status,
    )
    if provenance["base_seed"] != seed:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "base seed is inconsistent")
    if status != "failed" and len(provenance["derived_seeds"]) != requested:
        raise ReplicateContractError("REPLICATE_PROVENANCE_MISMATCH", "completed batch lacks seed provenance")
    digest = value["digest"]
    if status == "failed":
        if digest is not None:
            raise ReplicateContractError("REPLICATE_DIGEST_MISMATCH", "failed batches cannot publish a digest")
    else:
        if not _is_hex_digest(digest):
            raise ReplicateContractError("REPLICATE_INVALID_DIGEST", "digest is invalid")
        expected = _batch_digest(
            {
                "contract": BATCH_CONTRACT,
                "contract_version": REPLICATE_COMBINE_CONTRACT_VERSION,
                "kind": kind,
                "requested_count": requested,
                "succeeded_count": succeeded,
                "failed_count": failed,
                "seed": seed,
                "status": status,
                "reason_code": reason_code,
                "failure_reasons": dict(failure_reasons),
                "provenance": provenance,
            }
        )
        if digest != expected:
            raise ReplicateContractError("REPLICATE_DIGEST_MISMATCH", "batch digest does not match payload")
    public_fields = {
        key: value
        for key, value in provenance.items()
        if key != "provenance_commitment"
    }
    expected_public_commitment = compute_provenance_commitment(
        public_fields,
        context={
            "requested_count": requested,
            "succeeded_count": succeeded,
            "failed_count": failed,
            "status": status,
            "reason_code": reason_code,
        },
    )
    if provenance["provenance_commitment"] != expected_public_commitment:
        raise ReplicateContractError(
            "REPLICATE_PROVENANCE_MISMATCH", "provenance_commitment does not match public provenance"
        )
    return {
        "kind": kind,
        "requested_count": requested,
        "succeeded_count": succeeded,
        "failed_count": failed,
        "seed": seed,
        "status": status,
        "reason_code": reason_code,
        "failure_reasons": dict(failure_reasons),
        "provenance": provenance,
        "digest": digest,
    }


def validate_scalar_evidence(evidence: ReplicateEvidence) -> dict[str, float | int]:
    if not isinstance(evidence, ReplicateEvidence):
        raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "strategy output must be ReplicateEvidence")
    if any(type(key) is not str or not key for key in evidence.scalars):
        raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "evidence keys must be non-empty strings")
    normalized: dict[str, float | int] = {}
    for key, value in evidence.scalars.items():
        if type(value) is int and not isinstance(value, bool):
            normalized[key] = value
        elif type(value) is float and math.isfinite(value):
            normalized[key] = value
        else:
            raise ReplicateCombineError(
                "REPLICATE_NON_SCALAR_EVIDENCE", "evidence values must be finite numeric scalars"
            )
    return normalized


def evidence_commitment(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash bounded adapter evidence without exposing its scalar values."""

    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment records must be a sequence")
    if len(records) > MAX_REQUESTED_REPLICATES:
        raise ReplicateCombineError("REPLICATE_EVIDENCE_BUDGET_EXCEEDS_LIMIT", "too many commitment records")
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment record must be a mapping")
        status = record.get("status")
        if status == "evidence_budget_exceeded" and set(record) == {"status"}:
            normalized_records.append({"status": status})
            continue
        index = record.get("index")
        seed = record.get("seed")
        if (
            type(index) is not int
            or isinstance(index, bool)
            or index < 0
            or type(seed) is not int
            or isinstance(seed, bool)
            or seed < 0
        ):
            raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment index/seed is invalid")
        if status == "completed":
            if set(record) != {"index", "seed", "status", "adapter"}:
                raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment adapter record is invalid")
            adapter_values = validate_scalar_evidence(
                ReplicateEvidence(scalars=record["adapter"])
            )
            normalized_records.append(
                {"index": index, "seed": seed, "status": status, "adapter": adapter_values}
            )
        elif status == "failed":
            if set(record) != {"index", "seed", "status", "reason_code"}:
                raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment failure record is invalid")
            reason_code = record["reason_code"]
            if reason_code not in STABLE_FAILURE_REASONS:
                raise ReplicateCombineError("REPLICATE_INVALID_REASON_CODE", "commitment reason is not declared")
            normalized_records.append(
                {"index": index, "seed": seed, "status": status, "reason_code": reason_code}
            )
        else:
            raise ReplicateCombineError("REPLICATE_NON_SCALAR_EVIDENCE", "commitment record status is invalid")
    return _sha256(normalized_records)


def _batch_digest(payload_without_digest: Mapping[str, Any]) -> str:
    return _sha256(dict(payload_without_digest))


def compute_provenance_commitment(
    public_provenance: Mapping[str, Any], *, context: Mapping[str, Any] | None = None
) -> str:
    payload = dict(public_provenance)
    if context is not None:
        payload["batch_context"] = dict(context)
    return _sha256(payload)


__all__ = [
    "BATCH_CONTRACT",
    "ReplicateAdapter",
    "ReplicateBatch",
    "ReplicateCombiner",
    "ReplicateCombinedResult",
    "ReplicateEvidence",
    "ReplicateStrategy",
    "compute_provenance_commitment",
    "evidence_commitment",
    "validate_scalar_evidence",
]
