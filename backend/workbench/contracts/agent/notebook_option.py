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
- `NotebookOptionRevision@1.2` — a capability-bound successor that carries an
  immutable resolution binding reference and explicitly bounded execution mode.
- `ArtifactContract@1.0` — expected artifacts in the strict form DEC-ART-001
  allows: artifact_id + artifact_type + count + optional step. No `role`, no
  `schema_ref`; the registry persists neither, and a contract naming fields the
  system cannot check is a contract that validates nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...canonical import sha256_canonical
from ..common.envelope import ContractError, freeze_json, require_exact_keys, thaw_json

NOTEBOOK_OPTION_CONTRACT_VERSION = "1.1"
NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION = "1.0"
NOTEBOOK_OPTION_V12_CONTRACT_VERSION = "1.2"
NOTEBOOK_OPTION_V13_CONTRACT_VERSION = "1.3"
OPTION_EXECUTION_CONTRACT_VERSION = "1.1"
OPTION_EXECUTION_LEGACY_CONTRACT_VERSION = "1.0"
RECOMMENDATION_DECISION_CONTRACT_VERSION = "1.0"
FEASIBILITY_DECISION_CONTRACT_VERSION = "1.0"
RECOMMENDATION_DECISION_V11_CONTRACT_VERSION = "1.1"
MAX_RECOMMENDATION_CANDIDATES = 3
OPTION_MATERIALIZATION_CONTRACT_VERSION = "1.0"
OPTION_MATERIALIZATION_V11_CONTRACT_VERSION = "1.1"
ARTIFACT_CONTRACT_VERSION = "1.0"

LIFECYCLE_STATUSES = (
    "proposed",
    "deferred",
    "selected",
    "executing",
    "executed",
    "rejected",
    "archived",
    "materialized",
)
LEGACY_LIFECYCLE_STATUSES = tuple(
    status for status in LIFECYCLE_STATUSES if status != "materialized"
)
FRESHNESS_STATUSES = ("fresh", "stale", "revalidating")
VALIDATION_STATUSES = ("valid", "invalid", "unvalidated")
RISK_LEVELS = ("low", "medium", "high")
RECOMMENDATION_OUTCOMES = ("recommended", "tied", "insufficient_evidence")
FEASIBILITY_OUTCOMES = ("feasible", "blocked")

# DEC-ART-001: only dimensions the artifact registry actually persists.
ARTIFACT_MATCH_DIMENSIONS = ("artifact_id", "artifact_type", "count", "step")


class NotebookContractError(ContractError):
    """A notebook/option packet violated its locked contract."""


def _require_str(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise NotebookContractError(f"{field} must be a non-empty string")
    return value


def _require_digest(value: Any, field: str) -> str:
    text = _require_str(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise NotebookContractError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _require_choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    text = _require_str(value, field)
    if text not in allowed:
        raise NotebookContractError(f"{field} must be one of {list(allowed)}, got {text!r}")
    return text


def _require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise NotebookContractError(f"{field} must be an int >= {minimum}")
    return value


def _require_string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise NotebookContractError(f"{field} must be a tuple or list of strings")
    items = tuple(value)
    for item in items:
        _require_str(item, field)
    return items


def _require_mapping(value: Any, packet: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NotebookContractError(f"{packet} must be a mapping")
    return value


def _require_optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field)


def _require_optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field, minimum=1)


def _candidate_cohort_hash(option_ids: tuple[str, ...]) -> str:
    return sha256_canonical({"candidate_option_ids": sorted(option_ids)})


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
        if not self.expected:
            raise NotebookContractError(
                "artifact_contract must contain at least one expected artifact"
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


_OPTION_BASE_REQUIRED_KEYS = frozenset(
    {
        "option_id",
        "option_revision",
        "notebook_id",
        "run_family_id",
        "generation_context_id",
        "generation_context_hash",
        "freshness_dependency_fingerprint",
        "typed_proposal_id",
        "typed_proposal_revision",
        "artifact_contract",
        "risk_level",
        "lifecycle_status",
        "freshness_status",
        "validation_status",
        "rank",
        "batch_id",
        "created_at",
    }
)
_OPTION_BASE_OPTIONAL_KEYS = frozenset(
    {"rationale", "assumptions", "supersedes_option_revision", "contract_version"}
)


def _validate_option_fields(option: Any, allowed_lifecycle_statuses: tuple[str, ...]) -> None:
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
        _require_str(getattr(option, field), field)
    _require_int(option.option_revision, "option_revision", minimum=1)
    _require_int(option.typed_proposal_revision, "typed_proposal_revision", minimum=1)
    _require_int(option.rank, "rank", minimum=1)
    _require_choice(option.lifecycle_status, allowed_lifecycle_statuses, "lifecycle_status")
    _require_choice(option.freshness_status, FRESHNESS_STATUSES, "freshness_status")
    _require_choice(option.validation_status, VALIDATION_STATUSES, "validation_status")
    _require_choice(option.risk_level, RISK_LEVELS, "risk_level")
    if option.generation_context_hash == option.freshness_dependency_fingerprint:
        raise NotebookContractError(
            "generation_context_hash and freshness_dependency_fingerprint must not "
            "be the same value; they answer different questions (spec §4.0)"
        )
    if not option.generation_context_hash.startswith("sha256:"):
        raise NotebookContractError("generation_context_hash must be sha256-prefixed")
    if not option.freshness_dependency_fingerprint.startswith("fresh1:"):
        raise NotebookContractError("freshness_dependency_fingerprint must be fresh1-prefixed")


def _option_wire_dict(option: Any) -> dict[str, Any]:
    return {
        "contract_version": option.contract_version,
        "option_id": option.option_id,
        "option_revision": option.option_revision,
        "notebook_id": option.notebook_id,
        "run_family_id": option.run_family_id,
        "generation_context_id": option.generation_context_id,
        "generation_context_hash": option.generation_context_hash,
        "freshness_dependency_fingerprint": option.freshness_dependency_fingerprint,
        "typed_proposal_id": option.typed_proposal_id,
        "typed_proposal_revision": option.typed_proposal_revision,
        "artifact_contract": option.artifact_contract.to_dict(),
        "rationale": option.rationale,
        "assumptions": list(option.assumptions),
        "risk_level": option.risk_level,
        "lifecycle_status": option.lifecycle_status,
        "freshness_status": option.freshness_status,
        "validation_status": option.validation_status,
        "rank": option.rank,
        "batch_id": option.batch_id,
        "created_at": option.created_at,
        "supersedes_option_revision": option.supersedes_option_revision,
    }


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    result_hash: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_str(self.evidence_id, "evidence_id")
        _require_str(self.result_hash, "result_hash")
        object.__setattr__(self, "source_refs", _require_string_tuple(self.source_refs, "source_refs"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "result_hash": self.result_hash,
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRef":
        require_exact_keys(value, {"evidence_id", "result_hash", "source_refs"}, "evidence_ref")
        return cls(
            evidence_id=value["evidence_id"],
            result_hash=value["result_hash"],
            source_refs=value["source_refs"],
        )


@dataclass(frozen=True)
class MemoryDefaultSource:
    """Immutable provenance for one server-applied Draft default."""

    memory_id: str
    revision: int
    target_ref: str

    def __post_init__(self) -> None:
        _require_str(self.memory_id, "memory_default_source.memory_id")
        _require_int(self.revision, "memory_default_source.revision", minimum=1)
        _require_str(self.target_ref, "memory_default_source.target_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "target_ref": self.target_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MemoryDefaultSource":
        require_exact_keys(
            value,
            {"memory_id", "revision", "target_ref"},
            "memory_default_source",
        )
        return cls(
            memory_id=value["memory_id"],
            revision=value["revision"],
            target_ref=value["target_ref"],
        )


@dataclass(frozen=True)
class NotebookOptionRevision:
    """NotebookOptionRevision@1.0 public write shape and version dispatcher."""

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
    contract_version: str = NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION}"
            )
        _validate_option_fields(self, LEGACY_LIFECYCLE_STATUSES)

    @property
    def lifecycle_projection(self) -> str:
        return "legacy_unverified"

    @property
    def materializable(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return _option_wire_dict(self)

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "NotebookOptionRevision | NotebookOptionRevisionV11 | NotebookOptionRevisionV12 | NotebookOptionRevisionV13":
        payload = _require_mapping(value, "notebook_option_revision")
        version = payload.get("contract_version", NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION)
        if version == NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION:
            return cls._from_v10_dict(payload)
        if version == NOTEBOOK_OPTION_CONTRACT_VERSION:
            return NotebookOptionRevisionV11.from_dict(payload)
        if version == NOTEBOOK_OPTION_V12_CONTRACT_VERSION:
            return NotebookOptionRevisionV12.from_dict(payload)
        if version == NOTEBOOK_OPTION_V13_CONTRACT_VERSION:
            return NotebookOptionRevisionV13.from_dict(payload)
        raise NotebookContractError(
            f"NotebookOptionRevision contract_version must be one of "
            f"[{NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION!r}, {NOTEBOOK_OPTION_CONTRACT_VERSION!r}, "
            f"{NOTEBOOK_OPTION_V12_CONTRACT_VERSION!r}, {NOTEBOOK_OPTION_V13_CONTRACT_VERSION!r}], "
            f"got {version!r}"
        )

    @classmethod
    def _from_v10_dict(cls, value: Mapping[str, Any]) -> "NotebookOptionRevision":
        payload = dict(value)
        unknown = sorted(set(payload) - _OPTION_BASE_REQUIRED_KEYS - _OPTION_BASE_OPTIONAL_KEYS)
        if unknown:
            raise NotebookContractError(
                f"notebook_option_revision has unknown field(s): {', '.join(unknown)}; "
                "unversioned fields are refused, not silently dropped (ADR §11)"
            )
        missing = sorted(_OPTION_BASE_REQUIRED_KEYS - set(payload))
        if missing:
            raise NotebookContractError(
                f"notebook_option_revision is missing required field(s): {', '.join(missing)}"
            )
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
            assumptions=_require_string_tuple(payload.get("assumptions", ()), "assumptions"),
            risk_level=payload["risk_level"],
            lifecycle_status=payload["lifecycle_status"],
            freshness_status=payload["freshness_status"],
            validation_status=payload["validation_status"],
            rank=payload["rank"],
            batch_id=payload["batch_id"],
            created_at=payload["created_at"],
            supersedes_option_revision=payload.get("supersedes_option_revision"),
            contract_version=payload.get("contract_version", NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION),
        )


@dataclass(frozen=True)
class NotebookOptionRevisionV11:
    """NotebookOptionRevision@1.1, the evidence-bearing successor shape."""

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
    evidence_refs: tuple[EvidenceRef, ...]
    comparative_claims: tuple[str, ...]
    recommendation_decision_id: str
    recommendation_status: str
    supersedes_option_revision: int | None = None
    contract_version: str = NOTEBOOK_OPTION_CONTRACT_VERSION

    _V11_KEYS = _OPTION_BASE_REQUIRED_KEYS | frozenset(
        {
            "contract_version",
            "rationale",
            "assumptions",
            "supersedes_option_revision",
            "evidence_refs",
            "comparative_claims",
            "recommendation_decision_id",
            "recommendation_status",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != NOTEBOOK_OPTION_CONTRACT_VERSION:
            raise NotebookContractError(f"contract_version must be {NOTEBOOK_OPTION_CONTRACT_VERSION}")
        _validate_option_fields(self, LIFECYCLE_STATUSES)
        _require_str(self.rationale, "rationale")
        object.__setattr__(self, "assumptions", _require_string_tuple(self.assumptions, "assumptions"))
        if not isinstance(self.evidence_refs, (tuple, list)):
            raise NotebookContractError("evidence_refs must be a tuple or list")
        evidence_refs = tuple(self.evidence_refs)
        if any(not isinstance(item, EvidenceRef) for item in evidence_refs):
            raise NotebookContractError("evidence_refs must contain EvidenceRef records")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(
            self, "comparative_claims", _require_string_tuple(self.comparative_claims, "comparative_claims")
        )
        _require_str(self.recommendation_decision_id, "recommendation_decision_id")
        _require_choice(self.recommendation_status, RECOMMENDATION_OUTCOMES, "recommendation_status")
        _require_optional_int(self.supersedes_option_revision, "supersedes_option_revision")

    @property
    def lifecycle_projection(self) -> str:
        return self.lifecycle_status

    @property
    def materializable(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        payload = _option_wire_dict(self)
        payload.update(
            {
                "evidence_refs": [item.to_dict() for item in self.evidence_refs],
                "comparative_claims": list(self.comparative_claims),
                "recommendation_decision_id": self.recommendation_decision_id,
                "recommendation_status": self.recommendation_status,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NotebookOptionRevisionV11":
        require_exact_keys(value, cls._V11_KEYS, "notebook_option_revision")
        evidence_refs = value["evidence_refs"]
        if not isinstance(evidence_refs, (tuple, list)):
            raise NotebookContractError("evidence_refs must be a tuple or list")
        return cls(
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            notebook_id=value["notebook_id"],
            run_family_id=value["run_family_id"],
            generation_context_id=value["generation_context_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            typed_proposal_id=value["typed_proposal_id"],
            typed_proposal_revision=value["typed_proposal_revision"],
            artifact_contract=ArtifactContract.from_dict(value["artifact_contract"]),
            rationale=value["rationale"],
            assumptions=_require_string_tuple(value["assumptions"], "assumptions"),
            risk_level=value["risk_level"],
            lifecycle_status=value["lifecycle_status"],
            freshness_status=value["freshness_status"],
            validation_status=value["validation_status"],
            rank=value["rank"],
            batch_id=value["batch_id"],
            created_at=value["created_at"],
            evidence_refs=tuple(EvidenceRef.from_dict(item) for item in evidence_refs),
            comparative_claims=_require_string_tuple(
                value["comparative_claims"], "comparative_claims"
            ),
            recommendation_decision_id=value["recommendation_decision_id"],
            recommendation_status=value["recommendation_status"],
            supersedes_option_revision=value["supersedes_option_revision"],
            contract_version=value["contract_version"],
        )


@dataclass(frozen=True)
class NotebookOptionRevisionV12(NotebookOptionRevisionV11):
    """NotebookOptionRevision@1.2 for an admitted capability binding.

    ``materialize_only`` remains the default. A server may additionally declare
    ``confirm_and_execute`` for a low-risk option or the explicitly experimental
    ``experimental_confirm_and_execute`` for the high-risk ``model.custom``
    option. Either declaration is only a capability of the option contract: it
    is not an execution grant. The separate server-owned authorization receipt,
    containment profile, and existing Run gates remain mandatory.
    """

    capability_resolution_binding_ref: str | None = None
    execution_modes: tuple[str, ...] = ("materialize_only",)
    contract_version: str = NOTEBOOK_OPTION_V12_CONTRACT_VERSION

    _V12_KEYS = NotebookOptionRevisionV11._V11_KEYS | frozenset(
        {"capability_resolution_binding_ref", "execution_modes"}
    )

    def __post_init__(self) -> None:
        if self.contract_version != NOTEBOOK_OPTION_V12_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {NOTEBOOK_OPTION_V12_CONTRACT_VERSION}"
            )
        _validate_option_fields(self, LIFECYCLE_STATUSES)
        _require_str(self.rationale, "rationale")
        object.__setattr__(self, "assumptions", _require_string_tuple(self.assumptions, "assumptions"))
        object.__setattr__(
            self,
            "capability_resolution_binding_ref",
            _require_digest(
                self.capability_resolution_binding_ref,
                "capability_resolution_binding_ref",
            ),
        )
        modes = _require_string_tuple(self.execution_modes, "execution_modes")
        if (
            not modes
            or modes[0] != "materialize_only"
            or len(set(modes)) != len(modes)
            or any(
                mode
                not in {
                    "materialize_only",
                    "confirm_and_execute",
                    "experimental_confirm_and_execute",
                }
                for mode in modes
            )
        ):
            raise NotebookContractError(
                "execution_modes must start with materialize_only and may optionally "
                "include confirm_and_execute or experimental_confirm_and_execute"
            )
        object.__setattr__(self, "execution_modes", modes)
        object.__setattr__(
            self,
            "comparative_claims",
            _require_string_tuple(self.comparative_claims, "comparative_claims"),
        )
        _require_str(self.recommendation_decision_id, "recommendation_decision_id")
        _require_choice(self.recommendation_status, RECOMMENDATION_OUTCOMES, "recommendation_status")
        _require_optional_int(self.supersedes_option_revision, "supersedes_option_revision")

    @property
    def execution_allowed(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        payload = _option_wire_dict(self)
        payload.update(
            {
                "evidence_refs": [item.to_dict() for item in self.evidence_refs],
                "comparative_claims": list(self.comparative_claims),
                "recommendation_decision_id": self.recommendation_decision_id,
                "recommendation_status": self.recommendation_status,
                "capability_resolution_binding_ref": self.capability_resolution_binding_ref,
                "execution_modes": list(self.execution_modes),
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NotebookOptionRevisionV12":
        require_exact_keys(value, cls._V12_KEYS, "notebook_option_revision")
        evidence_refs = value["evidence_refs"]
        if not isinstance(evidence_refs, (tuple, list)):
            raise NotebookContractError("evidence_refs must be a tuple or list")
        return cls(
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            notebook_id=value["notebook_id"],
            run_family_id=value["run_family_id"],
            generation_context_id=value["generation_context_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            typed_proposal_id=value["typed_proposal_id"],
            typed_proposal_revision=value["typed_proposal_revision"],
            artifact_contract=ArtifactContract.from_dict(value["artifact_contract"]),
            rationale=value["rationale"],
            assumptions=_require_string_tuple(value["assumptions"], "assumptions"),
            risk_level=value["risk_level"],
            lifecycle_status=value["lifecycle_status"],
            freshness_status=value["freshness_status"],
            validation_status=value["validation_status"],
            rank=value["rank"],
            batch_id=value["batch_id"],
            created_at=value["created_at"],
            evidence_refs=tuple(EvidenceRef.from_dict(item) for item in evidence_refs),
            comparative_claims=_require_string_tuple(value["comparative_claims"], "comparative_claims"),
            recommendation_decision_id=value["recommendation_decision_id"],
            recommendation_status=value["recommendation_status"],
            supersedes_option_revision=value["supersedes_option_revision"],
            capability_resolution_binding_ref=value["capability_resolution_binding_ref"],
            execution_modes=_require_string_tuple(value["execution_modes"], "execution_modes"),
            contract_version=value["contract_version"],
        )


@dataclass(frozen=True)
class NotebookOptionRevisionV13(NotebookOptionRevisionV11):
    """NotebookOptionRevision@1.3 with visible memory-default provenance."""

    memory_default_sources: tuple[MemoryDefaultSource, ...] = ()
    contract_version: str = NOTEBOOK_OPTION_V13_CONTRACT_VERSION

    _V13_KEYS = NotebookOptionRevisionV11._V11_KEYS | frozenset({"memory_default_sources"})

    def __post_init__(self) -> None:
        if self.contract_version != NOTEBOOK_OPTION_V13_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {NOTEBOOK_OPTION_V13_CONTRACT_VERSION}"
            )
        _validate_option_fields(self, LIFECYCLE_STATUSES)
        _require_str(self.rationale, "rationale")
        object.__setattr__(self, "assumptions", _require_string_tuple(self.assumptions, "assumptions"))
        if not isinstance(self.evidence_refs, (tuple, list)):
            raise NotebookContractError("evidence_refs must be a tuple or list")
        evidence_refs = tuple(self.evidence_refs)
        if any(not isinstance(item, EvidenceRef) for item in evidence_refs):
            raise NotebookContractError("evidence_refs must contain EvidenceRef records")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(
            self, "comparative_claims", _require_string_tuple(self.comparative_claims, "comparative_claims")
        )
        _require_str(self.recommendation_decision_id, "recommendation_decision_id")
        _require_choice(self.recommendation_status, RECOMMENDATION_OUTCOMES, "recommendation_status")
        _require_optional_int(self.supersedes_option_revision, "supersedes_option_revision")
        if not isinstance(self.memory_default_sources, (tuple, list)) or not self.memory_default_sources:
            raise NotebookContractError("memory_default_sources must be a non-empty tuple or list")
        sources = tuple(self.memory_default_sources)
        if any(not isinstance(item, MemoryDefaultSource) for item in sources):
            raise NotebookContractError("memory_default_sources must contain MemoryDefaultSource records")
        if len({(item.memory_id, item.revision, item.target_ref) for item in sources}) != len(sources):
            raise NotebookContractError("memory_default_sources must be unique")
        object.__setattr__(self, "memory_default_sources", sources)

    def to_dict(self) -> dict[str, Any]:
        payload = _option_wire_dict(self)
        payload.update(
            {
                "evidence_refs": [item.to_dict() for item in self.evidence_refs],
                "comparative_claims": list(self.comparative_claims),
                "recommendation_decision_id": self.recommendation_decision_id,
                "recommendation_status": self.recommendation_status,
                "memory_default_sources": [item.to_dict() for item in self.memory_default_sources],
            }
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NotebookOptionRevisionV13":
        require_exact_keys(value, cls._V13_KEYS, "notebook_option_revision")
        evidence_refs = value["evidence_refs"]
        sources = value["memory_default_sources"]
        if not isinstance(evidence_refs, (tuple, list)):
            raise NotebookContractError("evidence_refs must be a tuple or list")
        if not isinstance(sources, (tuple, list)):
            raise NotebookContractError("memory_default_sources must be a tuple or list")
        return cls(
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            notebook_id=value["notebook_id"],
            run_family_id=value["run_family_id"],
            generation_context_id=value["generation_context_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            typed_proposal_id=value["typed_proposal_id"],
            typed_proposal_revision=value["typed_proposal_revision"],
            artifact_contract=ArtifactContract.from_dict(value["artifact_contract"]),
            rationale=value["rationale"],
            assumptions=_require_string_tuple(value["assumptions"], "assumptions"),
            risk_level=value["risk_level"],
            lifecycle_status=value["lifecycle_status"],
            freshness_status=value["freshness_status"],
            validation_status=value["validation_status"],
            rank=value["rank"],
            batch_id=value["batch_id"],
            created_at=value["created_at"],
            evidence_refs=tuple(EvidenceRef.from_dict(item) for item in evidence_refs),
            comparative_claims=_require_string_tuple(value["comparative_claims"], "comparative_claims"),
            recommendation_decision_id=value["recommendation_decision_id"],
            recommendation_status=value["recommendation_status"],
            supersedes_option_revision=value["supersedes_option_revision"],
            memory_default_sources=tuple(MemoryDefaultSource.from_dict(item) for item in sources),
            contract_version=value["contract_version"],
        )


LegacyNotebookOptionRevision = NotebookOptionRevision


@dataclass(frozen=True)
class RecommendationDecision:
    recommendation_decision_id: str
    batch_id: str
    generation_context_hash: str
    freshness_dependency_fingerprint: str
    evidence_pack_hashes: tuple[str, ...]
    comparison_protocol_refs: tuple[str, ...]
    candidate_option_ids: tuple[str, ...]
    outcome: str
    recommended_option_id: str | None
    reason_refs: tuple[str, ...]
    contract_version: str = RECOMMENDATION_DECISION_CONTRACT_VERSION

    _KEYS = frozenset(
        {
            "contract_version",
            "recommendation_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "evidence_pack_hashes",
            "comparison_protocol_refs",
            "candidate_option_ids",
            "outcome",
            "recommended_option_id",
            "reason_refs",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != RECOMMENDATION_DECISION_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {RECOMMENDATION_DECISION_CONTRACT_VERSION}"
            )
        for field in (
            "recommendation_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
        ):
            _require_str(getattr(self, field), field)
        for field in (
            "evidence_pack_hashes",
            "comparison_protocol_refs",
            "candidate_option_ids",
            "reason_refs",
        ):
            object.__setattr__(self, field, _require_string_tuple(getattr(self, field), field))
        _require_choice(self.outcome, RECOMMENDATION_OUTCOMES, "outcome")
        if len(set(self.candidate_option_ids)) != len(self.candidate_option_ids):
            raise NotebookContractError("candidate_option_ids must be unique")
        if self.outcome == "recommended":
            selected = _require_str(self.recommended_option_id, "recommended_option_id")
            if selected not in self.candidate_option_ids:
                raise NotebookContractError("recommended_option_id must name a candidate option")
        elif self.recommended_option_id is not None:
            raise NotebookContractError(
                "recommended_option_id must be null for tied or insufficient_evidence outcomes"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "recommendation_decision_id": self.recommendation_decision_id,
            "batch_id": self.batch_id,
            "generation_context_hash": self.generation_context_hash,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "evidence_pack_hashes": list(self.evidence_pack_hashes),
            "comparison_protocol_refs": list(self.comparison_protocol_refs),
            "candidate_option_ids": list(self.candidate_option_ids),
            "outcome": self.outcome,
            "recommended_option_id": self.recommended_option_id,
            "reason_refs": list(self.reason_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecommendationDecision":
        require_exact_keys(value, cls._KEYS, "recommendation_decision")
        return cls(
            recommendation_decision_id=value["recommendation_decision_id"],
            batch_id=value["batch_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            evidence_pack_hashes=value["evidence_pack_hashes"],
            comparison_protocol_refs=value["comparison_protocol_refs"],
            candidate_option_ids=value["candidate_option_ids"],
            outcome=value["outcome"],
            recommended_option_id=value["recommended_option_id"],
            reason_refs=value["reason_refs"],
            contract_version=value["contract_version"],
        )


@dataclass(frozen=True)
class FeasibilityCandidateDecision:
    """One server-owned feasibility result for a complete option cohort."""

    option_id: str
    protocol_id: str
    protocol_version: str
    inspection_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    outcome: str
    reason_code: str

    _KEYS = frozenset(
        {
            "option_id",
            "protocol_id",
            "protocol_version",
            "inspection_refs",
            "evidence_refs",
            "outcome",
            "reason_code",
        }
    )

    def __post_init__(self) -> None:
        _require_str(self.option_id, "option_id")
        _require_str(self.protocol_id, "protocol_id")
        _require_str(self.protocol_version, "protocol_version")
        inspection_refs = _require_string_tuple(self.inspection_refs, "inspection_refs")
        evidence_refs = _require_string_tuple(self.evidence_refs, "evidence_refs")
        if not inspection_refs or not evidence_refs:
            raise NotebookContractError(
                "feasibility candidates require inspection and evidence references"
            )
        object.__setattr__(self, "inspection_refs", inspection_refs)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        _require_choice(self.outcome, FEASIBILITY_OUTCOMES, "outcome")
        _require_str(self.reason_code, "reason_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "inspection_refs": list(self.inspection_refs),
            "evidence_refs": list(self.evidence_refs),
            "outcome": self.outcome,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeasibilityCandidateDecision":
        require_exact_keys(value, cls._KEYS, "feasibility_candidate")
        return cls(
            option_id=value["option_id"],
            protocol_id=value["protocol_id"],
            protocol_version=value["protocol_version"],
            inspection_refs=value["inspection_refs"],
            evidence_refs=value["evidence_refs"],
            outcome=value["outcome"],
            reason_code=value["reason_code"],
        )


@dataclass(frozen=True)
class FeasibilityDecision:
    """Server-owned evidence that covers every candidate in one batch.

    Agent payloads never populate this record.  A registered feasibility
    protocol creates it after validating the complete cohort and its evidence.
    """

    feasibility_decision_id: str
    batch_id: str
    generation_context_hash: str
    freshness_dependency_fingerprint: str
    evidence_pack_hashes: tuple[str, ...]
    candidate_option_ids: tuple[str, ...]
    candidate_cohort_hash: str
    candidates: tuple[FeasibilityCandidateDecision, ...]
    validator_revision: str
    contract_version: str = FEASIBILITY_DECISION_CONTRACT_VERSION

    _KEYS = frozenset(
        {
            "contract_version",
            "feasibility_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "evidence_pack_hashes",
            "candidate_option_ids",
            "candidate_cohort_hash",
            "candidates",
            "validator_revision",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != FEASIBILITY_DECISION_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {FEASIBILITY_DECISION_CONTRACT_VERSION}"
            )
        for field in (
            "feasibility_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "validator_revision",
        ):
            _require_str(getattr(self, field), field)
        evidence_pack_hashes = _require_string_tuple(
            self.evidence_pack_hashes, "evidence_pack_hashes"
        )
        candidate_option_ids = _require_string_tuple(
            self.candidate_option_ids, "candidate_option_ids"
        )
        if not evidence_pack_hashes:
            raise NotebookContractError("evidence_pack_hashes must not be empty")
        if not candidate_option_ids:
            raise NotebookContractError("candidate_option_ids must not be empty")
        if len(candidate_option_ids) > MAX_RECOMMENDATION_CANDIDATES:
            raise NotebookContractError("candidate_option_ids allow at most 3 options")
        if len(set(candidate_option_ids)) != len(candidate_option_ids):
            raise NotebookContractError("candidate_option_ids must be unique")
        _require_digest(self.candidate_cohort_hash, "candidate_cohort_hash")
        if self.candidate_cohort_hash != _candidate_cohort_hash(candidate_option_ids):
            raise NotebookContractError(
                "candidate_cohort_hash does not cover the complete candidate cohort"
            )
        if not isinstance(self.candidates, (tuple, list)):
            raise NotebookContractError("candidates must be a tuple or list")
        candidates = tuple(self.candidates)
        if not candidates or any(not isinstance(item, FeasibilityCandidateDecision) for item in candidates):
            raise NotebookContractError("candidates must contain feasibility decisions")
        if tuple(item.option_id for item in candidates) != candidate_option_ids:
            raise NotebookContractError(
                "candidates must cover candidate_option_ids in the same order"
            )
        object.__setattr__(self, "evidence_pack_hashes", evidence_pack_hashes)
        object.__setattr__(self, "candidate_option_ids", candidate_option_ids)
        object.__setattr__(self, "candidates", candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "feasibility_decision_id": self.feasibility_decision_id,
            "batch_id": self.batch_id,
            "generation_context_hash": self.generation_context_hash,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "evidence_pack_hashes": list(self.evidence_pack_hashes),
            "candidate_option_ids": list(self.candidate_option_ids),
            "candidate_cohort_hash": self.candidate_cohort_hash,
            "candidates": [item.to_dict() for item in self.candidates],
            "validator_revision": self.validator_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeasibilityDecision":
        require_exact_keys(value, cls._KEYS, "feasibility_decision")
        candidates = value["candidates"]
        if not isinstance(candidates, (tuple, list)):
            raise NotebookContractError("candidates must be a tuple or list")
        return cls(
            feasibility_decision_id=value["feasibility_decision_id"],
            batch_id=value["batch_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            evidence_pack_hashes=value["evidence_pack_hashes"],
            candidate_option_ids=value["candidate_option_ids"],
            candidate_cohort_hash=value["candidate_cohort_hash"],
            candidates=tuple(FeasibilityCandidateDecision.from_dict(item) for item in candidates),
            validator_revision=value["validator_revision"],
            contract_version=value["contract_version"],
        )


@dataclass(frozen=True)
class RecommendationDecisionV11:
    """Recommendation successor with a server-owned decision reference."""

    recommendation_decision_id: str
    batch_id: str
    generation_context_hash: str
    freshness_dependency_fingerprint: str
    evidence_pack_hashes: tuple[str, ...]
    candidate_option_ids: tuple[str, ...]
    candidate_cohort_hash: str
    outcome: str
    recommended_option_id: str | None
    feasibility_decision_ref: str | None
    comparison_decision_ref: str | None
    reason_refs: tuple[str, ...]
    contract_version: str = RECOMMENDATION_DECISION_V11_CONTRACT_VERSION

    _KEYS = frozenset(
        {
            "contract_version",
            "recommendation_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "evidence_pack_hashes",
            "candidate_option_ids",
            "candidate_cohort_hash",
            "outcome",
            "recommended_option_id",
            "feasibility_decision_ref",
            "comparison_decision_ref",
            "reason_refs",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != RECOMMENDATION_DECISION_V11_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {RECOMMENDATION_DECISION_V11_CONTRACT_VERSION}"
            )
        for field in (
            "recommendation_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
        ):
            _require_str(getattr(self, field), field)
        for field in ("evidence_pack_hashes", "candidate_option_ids", "reason_refs"):
            object.__setattr__(self, field, _require_string_tuple(getattr(self, field), field))
        if not self.evidence_pack_hashes or not self.candidate_option_ids:
            raise NotebookContractError("v1.1 decisions require evidence and candidates")
        if len(self.candidate_option_ids) > MAX_RECOMMENDATION_CANDIDATES:
            raise NotebookContractError("candidate_option_ids allow at most 3 options")
        if len(set(self.candidate_option_ids)) != len(self.candidate_option_ids):
            raise NotebookContractError("candidate_option_ids must be unique")
        _require_digest(self.candidate_cohort_hash, "candidate_cohort_hash")
        if self.candidate_cohort_hash != _candidate_cohort_hash(self.candidate_option_ids):
            raise NotebookContractError("candidate_cohort_hash does not match candidates")
        _require_choice(self.outcome, RECOMMENDATION_OUTCOMES, "outcome")
        if self.outcome == "recommended":
            selected = _require_str(self.recommended_option_id, "recommended_option_id")
            if selected not in self.candidate_option_ids:
                raise NotebookContractError("recommended_option_id must name a candidate option")
        elif self.recommended_option_id is not None:
            raise NotebookContractError(
                "recommended_option_id must be null for tied or insufficient_evidence outcomes"
            )
        feasibility_ref = self.feasibility_decision_ref
        comparison_ref = self.comparison_decision_ref
        if feasibility_ref is not None:
            _require_str(feasibility_ref, "feasibility_decision_ref")
        if comparison_ref is not None:
            _require_str(comparison_ref, "comparison_decision_ref")
        if (feasibility_ref is None) == (comparison_ref is None):
            raise NotebookContractError(
                "exactly one of feasibility_decision_ref or comparison_decision_ref is required"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "recommendation_decision_id": self.recommendation_decision_id,
            "batch_id": self.batch_id,
            "generation_context_hash": self.generation_context_hash,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "evidence_pack_hashes": list(self.evidence_pack_hashes),
            "candidate_option_ids": list(self.candidate_option_ids),
            "candidate_cohort_hash": self.candidate_cohort_hash,
            "outcome": self.outcome,
            "recommended_option_id": self.recommended_option_id,
            "feasibility_decision_ref": self.feasibility_decision_ref,
            "comparison_decision_ref": self.comparison_decision_ref,
            "reason_refs": list(self.reason_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecommendationDecisionV11":
        require_exact_keys(value, cls._KEYS, "recommendation_decision_v11")
        return cls(
            recommendation_decision_id=value["recommendation_decision_id"],
            batch_id=value["batch_id"],
            generation_context_hash=value["generation_context_hash"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            evidence_pack_hashes=value["evidence_pack_hashes"],
            candidate_option_ids=value["candidate_option_ids"],
            candidate_cohort_hash=value["candidate_cohort_hash"],
            outcome=value["outcome"],
            recommended_option_id=value["recommended_option_id"],
            feasibility_decision_ref=value["feasibility_decision_ref"],
            comparison_decision_ref=value["comparison_decision_ref"],
            reason_refs=value["reason_refs"],
            contract_version=value["contract_version"],
        )


@dataclass(frozen=True)
class OptionMaterialization:
    materialization_id: str
    option_id: str
    option_revision: int
    proposal_id: str
    proposal_revision: int
    freshness_dependency_fingerprint: str
    generation_context_id: str
    draft_id: str
    draft_hash: str
    draft_execution_mode: str
    source_run_id: str | None
    source_model_node_id: str | None
    source_op_node_id: str | None
    source_node_hash: str | None
    source_forest_node_key: str | None
    source_context_fingerprint: str | None
    dataset_upload_sha256: str | None
    run_family_id: str
    contract_version: str = OPTION_MATERIALIZATION_CONTRACT_VERSION

    _SOURCE_PIN_FIELDS = (
        "source_run_id",
        "source_model_node_id",
        "source_op_node_id",
        "source_node_hash",
        "source_forest_node_key",
        "source_context_fingerprint",
    )
    _KEYS = frozenset(
        {
            "contract_version",
            "materialization_id",
            "option_id",
            "option_revision",
            "proposal_id",
            "proposal_revision",
            "freshness_dependency_fingerprint",
            "generation_context_id",
            "draft_id",
            "draft_hash",
            "draft_execution_mode",
            "source_run_id",
            "source_model_node_id",
            "source_op_node_id",
            "source_node_hash",
            "source_forest_node_key",
            "source_context_fingerprint",
            "dataset_upload_sha256",
            "run_family_id",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != OPTION_MATERIALIZATION_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {OPTION_MATERIALIZATION_CONTRACT_VERSION}"
            )
        self._validate_fields()

    def _validate_fields(self) -> None:
        for field in (
            "materialization_id",
            "option_id",
            "proposal_id",
            "freshness_dependency_fingerprint",
            "generation_context_id",
            "draft_id",
            "draft_hash",
            "run_family_id",
        ):
            _require_str(getattr(self, field), field)
        _require_int(self.option_revision, "option_revision", minimum=1)
        _require_int(self.proposal_revision, "proposal_revision", minimum=1)
        _require_choice(self.draft_execution_mode, ("rerun_child", "genesis"), "draft_execution_mode")
        for field in self._SOURCE_PIN_FIELDS:
            _require_optional_str(getattr(self, field), field)
        _require_optional_str(self.dataset_upload_sha256, "dataset_upload_sha256")
        if self.draft_execution_mode == "rerun_child":
            if self.dataset_upload_sha256 is not None:
                raise NotebookContractError("rerun_child forbids dataset_upload_sha256")
            if any(getattr(self, field) is None for field in self._SOURCE_PIN_FIELDS):
                raise NotebookContractError("rerun_child requires every run/node source pin")
        else:
            if self.dataset_upload_sha256 is None:
                raise NotebookContractError("genesis requires dataset_upload_sha256")
            if any(getattr(self, field) is not None for field in self._SOURCE_PIN_FIELDS):
                raise NotebookContractError("genesis forbids all run/node source pins")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "materialization_id": self.materialization_id,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "generation_context_id": self.generation_context_id,
            "draft_id": self.draft_id,
            "draft_hash": self.draft_hash,
            "draft_execution_mode": self.draft_execution_mode,
            "source_run_id": self.source_run_id,
            "source_model_node_id": self.source_model_node_id,
            "source_op_node_id": self.source_op_node_id,
            "source_node_hash": self.source_node_hash,
            "source_forest_node_key": self.source_forest_node_key,
            "source_context_fingerprint": self.source_context_fingerprint,
            "dataset_upload_sha256": self.dataset_upload_sha256,
            "run_family_id": self.run_family_id,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "OptionMaterialization | OptionMaterializationV11":
        if (
            isinstance(value, Mapping)
            and value.get("contract_version")
            == OPTION_MATERIALIZATION_V11_CONTRACT_VERSION
        ):
            return OptionMaterializationV11.from_dict(value)
        require_exact_keys(value, cls._KEYS, "option_materialization")
        return cls(**{key: value[key] for key in cls._KEYS})


@dataclass(frozen=True)
class OptionMaterializationV11(OptionMaterialization):
    """OptionMaterialization@1.1 with an immutable capability binding pin.

    The legacy materialization remains the wire contract for native/unbound
    options.  A capability-bound option must use this successor so a later
    Draft or replay cannot silently detach from the binding that produced it.
    """

    capability_resolution_binding_ref: str = ""
    contract_version: str = OPTION_MATERIALIZATION_V11_CONTRACT_VERSION

    _V11_KEYS = OptionMaterialization._KEYS | frozenset(
        {"capability_resolution_binding_ref"}
    )

    def __post_init__(self) -> None:
        if self.contract_version != OPTION_MATERIALIZATION_V11_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {OPTION_MATERIALIZATION_V11_CONTRACT_VERSION}"
            )
        self._validate_fields()
        _require_digest(
            self.capability_resolution_binding_ref,
            "capability_resolution_binding_ref",
        )

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["contract_version"] = self.contract_version
        payload["capability_resolution_binding_ref"] = self.capability_resolution_binding_ref
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionMaterializationV11":
        require_exact_keys(value, cls._V11_KEYS, "option_materialization_v11")
        payload = {key: value[key] for key in OptionMaterialization._KEYS}
        payload["capability_resolution_binding_ref"] = value[
            "capability_resolution_binding_ref"
        ]
        return cls(**payload)


@dataclass(frozen=True)
class OptionExecution:
    """OptionExecution@1.0 public write shape and version dispatcher."""

    option_id: str
    option_revision: int
    proposal_id: str
    proposal_revision: int
    freshness_dependency_fingerprint: str
    generation_context_id: str
    run_id: str | None = None
    contract_version: str = OPTION_EXECUTION_LEGACY_CONTRACT_VERSION

    _KEYS = frozenset(
        {
            "contract_version",
            "option_id",
            "option_revision",
            "proposal_id",
            "proposal_revision",
            "freshness_dependency_fingerprint",
            "generation_context_id",
            "run_id",
        }
    )

    def __post_init__(self) -> None:
        if self.contract_version != OPTION_EXECUTION_LEGACY_CONTRACT_VERSION:
            raise NotebookContractError(
                f"contract_version must be {OPTION_EXECUTION_LEGACY_CONTRACT_VERSION}"
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
        _require_optional_str(self.run_id, "run_id")

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
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionExecution | OptionExecutionV11":
        payload = _require_mapping(value, "option_execution")
        version = payload.get("contract_version")
        if version == OPTION_EXECUTION_LEGACY_CONTRACT_VERSION:
            return cls._from_v10_dict(payload)
        if version == OPTION_EXECUTION_CONTRACT_VERSION:
            return OptionExecutionV11.from_dict(payload)
        raise NotebookContractError(
            f"OptionExecution contract_version must be one of "
            f"[{OPTION_EXECUTION_LEGACY_CONTRACT_VERSION!r}, {OPTION_EXECUTION_CONTRACT_VERSION!r}], "
            f"got {version!r}"
        )

    @classmethod
    def _from_v10_dict(cls, value: Mapping[str, Any]) -> "OptionExecution":
        require_exact_keys(value, cls._KEYS, "option_execution")
        return cls(**{key: value[key] for key in cls._KEYS})


@dataclass(frozen=True)
class OptionExecutionV11:
    """OptionExecution@1.1, pinned to one materialized draft and child run."""

    option_id: str
    option_revision: int
    proposal_id: str
    proposal_revision: int
    freshness_dependency_fingerprint: str
    generation_context_id: str
    materialization_id: str
    draft_id: str
    draft_hash: str
    source_run_id: str
    run_id: str
    contract_version: str = OPTION_EXECUTION_CONTRACT_VERSION

    _KEYS = OptionExecution._KEYS | frozenset(
        {"materialization_id", "draft_id", "draft_hash", "source_run_id"}
    )

    def __post_init__(self) -> None:
        if self.contract_version != OPTION_EXECUTION_CONTRACT_VERSION:
            raise NotebookContractError(f"contract_version must be {OPTION_EXECUTION_CONTRACT_VERSION}")
        for field in (
            "option_id",
            "proposal_id",
            "freshness_dependency_fingerprint",
            "generation_context_id",
            "materialization_id",
            "draft_id",
            "draft_hash",
            "source_run_id",
            "run_id",
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
            "materialization_id": self.materialization_id,
            "draft_id": self.draft_id,
            "draft_hash": self.draft_hash,
            "source_run_id": self.source_run_id,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionExecutionV11":
        require_exact_keys(value, cls._KEYS, "option_execution")
        return cls(**{key: value[key] for key in cls._KEYS})


LegacyOptionExecution = OptionExecution


__all__ = [
    "ARTIFACT_CONTRACT_VERSION",
    "ARTIFACT_MATCH_DIMENSIONS",
    "ArtifactContract",
    "EvidenceRef",
    "ExpectedArtifact",
    "FEASIBILITY_DECISION_CONTRACT_VERSION",
    "FEASIBILITY_OUTCOMES",
    "FRESHNESS_STATUSES",
    "FeasibilityCandidateDecision",
    "FeasibilityDecision",
    "LEGACY_LIFECYCLE_STATUSES",
    "MAX_RECOMMENDATION_CANDIDATES",
    "LegacyNotebookOptionRevision",
    "LegacyOptionExecution",
    "LIFECYCLE_STATUSES",
    "MemoryDefaultSource",
    "NOTEBOOK_OPTION_CONTRACT_VERSION",
    "NOTEBOOK_OPTION_LEGACY_CONTRACT_VERSION",
    "NOTEBOOK_OPTION_V12_CONTRACT_VERSION",
    "NOTEBOOK_OPTION_V13_CONTRACT_VERSION",
    "NotebookContractError",
    "NotebookOptionRevision",
    "NotebookOptionRevisionV11",
    "NotebookOptionRevisionV12",
    "NotebookOptionRevisionV13",
    "OPTION_EXECUTION_LEGACY_CONTRACT_VERSION",
    "OPTION_EXECUTION_CONTRACT_VERSION",
    "OPTION_MATERIALIZATION_CONTRACT_VERSION",
    "OptionMaterialization",
    "OptionExecution",
    "OptionExecutionV11",
    "RECOMMENDATION_DECISION_CONTRACT_VERSION",
    "RECOMMENDATION_DECISION_V11_CONTRACT_VERSION",
    "RECOMMENDATION_OUTCOMES",
    "RecommendationDecision",
    "RecommendationDecisionV11",
    "RISK_LEVELS",
    "VALIDATION_STATUSES",
    "freeze_json",
    "thaw_json",
]
