"""Versioned, fail-closed contracts for bounded replicate execution.

The contract deliberately contains declarations and budgets only.  Runtime
strategy objects stay in the engine registry; callbacks, import paths and raw
replicate payloads never cross this boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from workbench.contracts.common.envelope import ContractError


REPLICATE_COMBINE_CONTRACT = "replicate_combine.plan"
REPLICATE_COMBINE_CONTRACT_VERSION = "1.0"
REPLICATE_KINDS = frozenset(
    {"multiple_imputation", "bootstrap", "permutation", "survey_replicate"}
)
COMBINER_IDS = frozenset(
    {"rubin_pool", "distribution_ci", "permutation_null", "replicate_covariance"}
)

# These are intentionally finite protocol limits, not resource-policy knobs
# supplied by an Agent.  A later product policy may lower them per operation.
MAX_REQUESTED_REPLICATES = 10_000
MAX_FAILURES = 10_000
MAX_EVIDENCE_SCALARS = 100_000
MAX_SEED = (1 << 63) - 1

_PLAN_FIELDS = frozenset(
    {
        "contract",
        "contract_version",
        "kind",
        "requested_replicates",
        "seed",
        "strategy_id",
        "adapter_id",
        "combiner_id",
        "max_failures",
        "max_evidence_scalars",
    }
)
_UNSAFE_FIELDS = frozenset(
    {
        "callback",
        "callable",
        "formula",
        "python",
        "import_path",
        "shell",
        "command",
        "expression",
    }
)
_RAW_FIELDS = frozenset({"replicate_rows", "replicate_values", "raw_data"})
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class ReplicateContractError(ContractError):
    """Raised when a replicate plan or batch violates its public contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplicateContractError("REPLICATE_INVALID_PAYLOAD", f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise ReplicateContractError("REPLICATE_INVALID_PAYLOAD", f"{label} keys must be strings")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
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


def _validate_id(value: Any, field_name: str) -> str:
    if type(value) is not str or not _ID_PATTERN.fullmatch(value):
        raise ReplicateContractError("REPLICATE_INVALID_ID", f"{field_name} is not a valid id")
    return value


def _validate_non_negative_int(value: Any, field_name: str, reason_code: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ReplicateContractError(reason_code, f"{field_name} must be a non-negative integer")
    return value


def _validate_budget(value: Any, field_name: str, limit: int, invalid_reason: str, limit_reason: str) -> int:
    result = _validate_non_negative_int(value, field_name, invalid_reason)
    if result > limit:
        raise ReplicateContractError(limit_reason, f"{field_name} exceeds the hard limit")
    return result


@dataclass(frozen=True)
class ReplicatePlan:
    """Immutable declaration of one bounded replicate execution."""

    kind: str
    requested_replicates: int
    seed: int
    strategy_id: str
    adapter_id: str
    combiner_id: str
    max_failures: int
    max_evidence_scalars: int

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in REPLICATE_KINDS:
            raise ReplicateContractError("REPLICATE_INVALID_KIND", "kind is not declared")
        if (
            type(self.requested_replicates) is not int
            or isinstance(self.requested_replicates, bool)
            or self.requested_replicates < 1
        ):
            raise ReplicateContractError(
                "REPLICATE_INVALID_REQUESTED_COUNT",
                "requested_replicates must be a positive integer",
            )
        if self.requested_replicates > MAX_REQUESTED_REPLICATES:
            raise ReplicateContractError(
                "REPLICATE_REQUESTED_COUNT_EXCEEDS_LIMIT",
                "requested_replicates exceeds the hard limit",
            )
        if (
            type(self.seed) is not int
            or isinstance(self.seed, bool)
            or self.seed < 0
            or self.seed > MAX_SEED
        ):
            raise ReplicateContractError(
                "REPLICATE_INVALID_SEED", "seed must be a non-negative bounded integer"
            )
        _validate_id(self.strategy_id, "strategy_id")
        _validate_id(self.adapter_id, "adapter_id")
        _validate_id(self.combiner_id, "combiner_id")
        if self.combiner_id not in COMBINER_IDS:
            raise ReplicateContractError(
                "REPLICATE_UNKNOWN_COMBINER", "combiner_id is not declared"
            )
        _validate_budget(
            self.max_failures,
            "max_failures",
            MAX_FAILURES,
            "REPLICATE_INVALID_FAILURE_BUDGET",
            "REPLICATE_FAILURE_BUDGET_EXCEEDS_LIMIT",
        )
        _validate_budget(
            self.max_evidence_scalars,
            "max_evidence_scalars",
            MAX_EVIDENCE_SCALARS,
            "REPLICATE_INVALID_EVIDENCE_BUDGET",
            "REPLICATE_EVIDENCE_BUDGET_EXCEEDS_LIMIT",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": REPLICATE_COMBINE_CONTRACT,
            "contract_version": REPLICATE_COMBINE_CONTRACT_VERSION,
            "kind": self.kind,
            "requested_replicates": self.requested_replicates,
            "seed": self.seed,
            "strategy_id": self.strategy_id,
            "adapter_id": self.adapter_id,
            "combiner_id": self.combiner_id,
            "max_failures": self.max_failures,
            "max_evidence_scalars": self.max_evidence_scalars,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplicatePlan":
        payload = _require_mapping(value, "plan")
        # Diagnose fields that would otherwise be accepted as generic unknown
        # keys with a more actionable security reason.
        unsafe = _UNSAFE_FIELDS.intersection(payload)
        if unsafe:
            raise ReplicateContractError(
                "REPLICATE_UNSAFE_EXECUTION_FIELD",
                f"executable field is forbidden: {sorted(unsafe)[0]}",
            )
        raw = _RAW_FIELDS.intersection(payload)
        if raw:
            raise ReplicateContractError(
                "REPLICATE_RAW_VALUES_FORBIDDEN",
                f"raw replicate field is forbidden: {sorted(raw)[0]}",
            )
        _require_exact_keys(payload, _PLAN_FIELDS, "plan")
        if payload["contract"] != REPLICATE_COMBINE_CONTRACT:
            raise ReplicateContractError("REPLICATE_UNSUPPORTED_CONTRACT", "contract is not declared")
        if payload["contract_version"] != REPLICATE_COMBINE_CONTRACT_VERSION:
            raise ReplicateContractError(
                "REPLICATE_UNSUPPORTED_CONTRACT_VERSION", "contract_version is not supported"
            )
        return cls(
            kind=payload["kind"],
            requested_replicates=payload["requested_replicates"],
            seed=payload["seed"],
            strategy_id=payload["strategy_id"],
            adapter_id=payload["adapter_id"],
            combiner_id=payload["combiner_id"],
            max_failures=payload["max_failures"],
            max_evidence_scalars=payload["max_evidence_scalars"],
        )


__all__ = [
    "COMBINER_IDS",
    "MAX_EVIDENCE_SCALARS",
    "MAX_FAILURES",
    "MAX_REQUESTED_REPLICATES",
    "MAX_SEED",
    "REPLICATE_COMBINE_CONTRACT",
    "REPLICATE_COMBINE_CONTRACT_VERSION",
    "REPLICATE_KINDS",
    "ReplicateContractError",
    "ReplicatePlan",
]
