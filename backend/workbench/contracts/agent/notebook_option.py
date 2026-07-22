"""v1.8.1 Contract Sprint — the Notebook/Option packets (ADR-PD-001 §5).

Integration-owned. Feature lanes consume these definitions read-only; a lane
that finds them unable to express a needed fact must stop and raise a Contract
Change Request rather than adding a field on its branch (ADR §6).

Three packets are locked here:

- `NotebookOptionRevision@1.0` — an immutable snapshot of one proposed analysis
  path. Pins BOTH hashes from spec §4.0: `generation_context_hash` records what
  the agent saw, `freshness_dependency_fingerprint` is the only one that gates
  execution. Merging them is self-referential (the compiled context contains the
  notebook's existing options, so a new option would stale itself).
- `OptionExecution@1.0` — the five-tuple execution pins, so a user confirming
  revision 2 cannot execute revision 3.
- `ArtifactContract@1.0` — expected artifacts in the strict form DEC-ART-001
  allows: artifact_id + artifact_type + count + optional step. No `role`, no
  `schema_ref`; the registry persists neither, and a contract naming fields the
  system cannot check is a contract that validates nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json

NOTEBOOK_OPTION_CONTRACT_VERSION = "1.0"
OPTION_EXECUTION_CONTRACT_VERSION = "1.0"
ARTIFACT_CONTRACT_VERSION = "1.0"

LIFECYCLE_STATUSES = (
    "proposed",
    "deferred",
    "selected",
    "executing",
    "executed",
    "rejected",
    "archived",
)
FRESHNESS_STATUSES = ("fresh", "stale", "revalidating")
VALIDATION_STATUSES = ("valid", "invalid", "unvalidated")
RISK_LEVELS = ("low", "medium", "high")

# DEC-ART-001: only dimensions the artifact registry actually persists.
ARTIFACT_MATCH_DIMENSIONS = ("artifact_id", "artifact_type", "count", "step")


class NotebookContractError(ContractError):
    """A notebook/option packet violated its locked contract."""


def _require_str(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise NotebookContractError(f"{field} must be a non-empty string")
    return value


def _require_choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    text = _require_str(value, field)
    if text not in allowed:
        raise NotebookContractError(f"{field} must be one of {list(allowed)}, got {text!r}")
    return text


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise NotebookContractError(f"{field} must be an int >= {minimum}")
    return value


@dataclass(frozen=True)
class ExpectedArtifact:
    """One required or optional product of executing an option."""

    artifact_id: str
    artifact_type: str
    required: bool = True
    count: int = 1
    step: str | None = None

    def __post_init__(self) -> None:
        _require_str(self.artifact_id, "artifact_id")
        _require_str(self.artifact_type, "artifact_type")
        _require_int(self.count, "count", minimum=0)
        if self.step is not None:
            _require_str(self.step, "step")
        if type(self.required) is not bool:
            raise NotebookContractError("required must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "required": self.required,
            "count": self.count,
            "step": self.step,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExpectedArtifact":
        require_exact_keys(
            value,
            {"artifact_id", "artifact_type", "required", "count", "step"},
            "expected_artifact",
        )
        return cls(
            artifact_id=value["artifact_id"],
            artifact_type=value["artifact_type"],
            required=value["required"],
            count=value["count"],
            step=value["step"],
        )


@dataclass(frozen=True)
class ArtifactContract:
    """What executing an option must produce for the result to count.

    `checked_dimensions` / `not_evaluated_dimensions` are part of the packet so a
    consumer can never mistake "we did not look at payload schemas" for "payload
    schemas were valid" (DEC-ART-001).
    """

    expected: tuple[ExpectedArtifact, ...]
    contract_version: str = ARTIFACT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != ARTIFACT_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {ARTIFACT_CONTRACT_VERSION}"
            )
        ids = [item.artifact_id for item in self.expected]
        if len(ids) != len(set(ids)):
            raise NotebookContractError("expected artifacts must have unique artifact_id")

    @property
    def required_ids(self) -> tuple[str, ...]:
        return tuple(item.artifact_id for item in self.expected if item.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "expected": [item.to_dict() for item in self.expected],
            "checked_dimensions": list(ARTIFACT_MATCH_DIMENSIONS),
            "not_evaluated_dimensions": ["payload_schema"],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactContract":
        require_exact_keys(
            value,
            {
                "contract_version",
                "expected",
                "checked_dimensions",
                "not_evaluated_dimensions",
            },
            "artifact_contract",
        )
        return cls(
            contract_version=value["contract_version"],
            expected=tuple(ExpectedArtifact.from_dict(item) for item in value["expected"]),
        )


@dataclass(frozen=True)
class NotebookOptionRevision:
    """An immutable snapshot of one proposed analysis path."""

    option_id: str
    option_revision: int
    notebook_id: str
    run_family_id: str
    generation_context_id: str
    generation_context_hash: str
    freshness_dependency_fingerprint: str
    typed_proposal_id: str
    typed_proposal_revision: int
    artifact_contract: ArtifactContract
    rationale: str
    assumptions: tuple[str, ...]
    risk_level: str
    lifecycle_status: str
    freshness_status: str
    validation_status: str
    rank: int
    batch_id: str
    created_at: str
    supersedes_option_revision: int | None = None
    contract_version: str = NOTEBOOK_OPTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != NOTEBOOK_OPTION_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {NOTEBOOK_OPTION_CONTRACT_VERSION}"
            )
        for field in (
            "option_id",
            "notebook_id",
            "run_family_id",
            "generation_context_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "typed_proposal_id",
            "batch_id",
            "created_at",
        ):
            _require_str(getattr(self, field), field)
        _require_int(self.option_revision, "option_revision", minimum=1)
        _require_int(self.typed_proposal_revision, "typed_proposal_revision", minimum=1)
        _require_int(self.rank, "rank", minimum=1)
        _require_choice(self.lifecycle_status, LIFECYCLE_STATUSES, "lifecycle_status")
        _require_choice(self.freshness_status, FRESHNESS_STATUSES, "freshness_status")
        _require_choice(self.validation_status, VALIDATION_STATUSES, "validation_status")
        _require_choice(self.risk_level, RISK_LEVELS, "risk_level")
        # The two hashes must be distinguishable: a producer that computed one
        # value and stored it in both fields would silently reintroduce the
        # self-reference bug that spec §4.0 exists to prevent.
        if self.generation_context_hash == self.freshness_dependency_fingerprint:
            raise NotebookContractError(
                "generation_context_hash and freshness_dependency_fingerprint must not "
                "be the same value; they answer different questions (spec §4.0)"
            )
        if not self.generation_context_hash.startswith("sha256:"):
            raise NotebookContractError("generation_context_hash must be sha256-prefixed")
        if not self.freshness_dependency_fingerprint.startswith("fresh1:"):
            raise NotebookContractError(
                "freshness_dependency_fingerprint must be fresh1-prefixed"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "notebook_id": self.notebook_id,
            "run_family_id": self.run_family_id,
            "generation_context_id": self.generation_context_id,
            "generation_context_hash": self.generation_context_hash,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "typed_proposal_id": self.typed_proposal_id,
            "typed_proposal_revision": self.typed_proposal_revision,
            "artifact_contract": self.artifact_contract.to_dict(),
            "rationale": self.rationale,
            "assumptions": list(self.assumptions),
            "risk_level": self.risk_level,
            "lifecycle_status": self.lifecycle_status,
            "freshness_status": self.freshness_status,
            "validation_status": self.validation_status,
            "rank": self.rank,
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "supersedes_option_revision": self.supersedes_option_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NotebookOptionRevision":
        payload = dict(value)
        return cls(
            option_id=payload["option_id"],
            option_revision=payload["option_revision"],
            notebook_id=payload["notebook_id"],
            run_family_id=payload["run_family_id"],
            generation_context_id=payload["generation_context_id"],
            generation_context_hash=payload["generation_context_hash"],
            freshness_dependency_fingerprint=payload["freshness_dependency_fingerprint"],
            typed_proposal_id=payload["typed_proposal_id"],
            typed_proposal_revision=payload["typed_proposal_revision"],
            artifact_contract=ArtifactContract.from_dict(payload["artifact_contract"]),
            rationale=payload.get("rationale", ""),
            assumptions=tuple(payload.get("assumptions", ())),
            risk_level=payload["risk_level"],
            lifecycle_status=payload["lifecycle_status"],
            freshness_status=payload["freshness_status"],
            validation_status=payload["validation_status"],
            rank=payload["rank"],
            batch_id=payload["batch_id"],
            created_at=payload["created_at"],
            supersedes_option_revision=payload.get("supersedes_option_revision"),
            contract_version=payload.get(
                "contract_version", NOTEBOOK_OPTION_CONTRACT_VERSION
            ),
        )


@dataclass(frozen=True)
class OptionExecution:
    """The pins that make "confirm" refer to exactly one revision."""

    option_id: str
    option_revision: int
    proposal_id: str
    proposal_revision: int
    freshness_dependency_fingerprint: str
    generation_context_id: str
    run_id: str | None = None
    contract_version: str = OPTION_EXECUTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != OPTION_EXECUTION_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {OPTION_EXECUTION_CONTRACT_VERSION}"
            )
        for field in (
            "option_id",
            "proposal_id",
            "freshness_dependency_fingerprint",
            "generation_context_id",
        ):
            _require_str(getattr(self, field), field)
        _require_int(self.option_revision, "option_revision", minimum=1)
        _require_int(self.proposal_revision, "proposal_revision", minimum=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "generation_context_id": self.generation_context_id,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionExecution":
        require_exact_keys(
            value,
            {
                "contract_version",
                "option_id",
                "option_revision",
                "proposal_id",
                "proposal_revision",
                "freshness_dependency_fingerprint",
                "generation_context_id",
                "run_id",
            },
            "option_execution",
        )
        return cls(
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            proposal_id=value["proposal_id"],
            proposal_revision=value["proposal_revision"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            generation_context_id=value["generation_context_id"],
            run_id=value["run_id"],
            contract_version=value["contract_version"],
        )


__all__ = [
    "ARTIFACT_CONTRACT_VERSION",
    "ARTIFACT_MATCH_DIMENSIONS",
    "ArtifactContract",
    "ExpectedArtifact",
    "FRESHNESS_STATUSES",
    "LIFECYCLE_STATUSES",
    "NOTEBOOK_OPTION_CONTRACT_VERSION",
    "NotebookContractError",
    "NotebookOptionRevision",
    "OPTION_EXECUTION_CONTRACT_VERSION",
    "OptionExecution",
    "RISK_LEVELS",
    "VALIDATION_STATUSES",
    "freeze_json",
    "thaw_json",
]
