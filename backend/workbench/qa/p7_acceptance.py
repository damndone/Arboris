"""Fail-closed, declaration-driven P7 browser acceptance records.

This module does not execute a provider or confirm an Agent proposal.  It
builds immutable work packets for a visible Workbench browser path and later
validates evidence collected from that path.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
import subprocess
from typing import Any, Literal, Mapping, Protocol

from workbench.agent.p7_pack_registry import p7_pack_registry
from workbench.qa.witness import (
    BrowserWitnessAttestation,
    WitnessChallenge,
    WitnessError,
    WitnessVerification,
    WitnessVerifier,
    WITNESS_CHALLENGE_TTL_SECONDS,
    verify_witness_attestation,
)


FixtureStatus = Literal["ready", "blocked"]
AcceptanceRunMode = Literal["operation", "family_batch"]
MANIFEST_SCHEMA_VERSION = 1


class P7AcceptanceError(ValueError):
    """Base class for acceptance-control failures."""


class ManifestConflictError(P7AcceptanceError):
    """Raised when a write-once path already contains different bytes."""


class ManifestDriftError(P7AcceptanceError):
    """Raised when frozen manifest authority no longer matches live state."""


class AttemptLedgerError(P7AcceptanceError):
    """Raised when an append-only attempt ledger is invalid or unsafe."""


class CompletionEvidenceError(P7AcceptanceError):
    """Raised when a completed claim lacks the real Agent/browser chain."""


class RateLimitError(AttemptLedgerError):
    """Raised when a caller tries to start before the next admission time."""

    def __init__(self, next_admission_at: float) -> None:
        self.next_admission_at = float(next_admission_at)
        super().__init__(
            f"rate policy denies this attempt until {self.next_admission_at:.6f}"
        )


class RegistryLike(Protocol):
    """Small registry surface used for live projection and test injection."""

    def operation_ids(self) -> tuple[str, ...]: ...

    def get(self, operation_id: str) -> object: ...


@dataclass(frozen=True)
class FixtureProfile:
    """Execution fixture state; absent fixtures are explicit blockers."""

    fixture_id: str
    status: FixtureStatus
    source: str
    input_mode: str
    required_bindings: tuple[str, ...]
    required_options: tuple[str, ...]
    blocker_code: str | None = None
    blocker_detail: str | None = None


@dataclass(frozen=True)
class ExpectedParentChildContract:
    """The minimum real-chain contract that a completed row must prove."""

    parent_operation_id: str
    child_operation_id: str
    requires_visible_user_confirmation: bool = True
    requires_durable_parent_terminal: bool = True
    requires_durable_child_terminal: bool = True
    requires_completed_nested_result: bool = True
    requires_artifact_provenance_identity: bool = True


@dataclass(frozen=True)
class AcceptanceMatrixRow:
    operation_id: str
    pack_family: str
    prompt: str
    fixture_profile: FixtureProfile
    expected_contract: ExpectedParentChildContract


@dataclass(frozen=True)
class AcceptanceBatch:
    """One browser-visible proposal covering every operation in one live family."""

    batch_id: str
    pack_family: str
    operation_ids: tuple[str, ...]
    prompt: str
    status: FixtureStatus
    fixture_id: str | None
    source: str | None
    blocker_code: str | None = None
    blocker_detail: str | None = None


@dataclass(frozen=True)
class RatePolicy:
    """Token-bucket policy frozen into an acceptance manifest."""

    capacity: int
    refill_per_second: float
    cost_per_attempt: float = 1.0

    def __post_init__(self) -> None:
        if type(self.capacity) is not int or self.capacity <= 0:
            raise ValueError("rate capacity must be a positive integer")
        if type(self.refill_per_second) not in {int, float}:
            raise ValueError("rate refill_per_second must be numeric")
        if not math.isfinite(float(self.refill_per_second)):
            raise ValueError("rate refill_per_second must be finite")
        if self.refill_per_second <= 0:
            raise ValueError("rate refill_per_second must be positive")
        if type(self.cost_per_attempt) not in {int, float}:
            raise ValueError("rate cost_per_attempt must be numeric")
        if not math.isfinite(float(self.cost_per_attempt)):
            raise ValueError("rate cost_per_attempt must be finite")
        if self.cost_per_attempt <= 0:
            raise ValueError("rate cost_per_attempt must be positive")
        if self.cost_per_attempt > self.capacity:
            raise ValueError("rate cost_per_attempt cannot exceed capacity")

    def to_dict(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "refill_per_second": float(self.refill_per_second),
            "cost_per_attempt": float(self.cost_per_attempt),
        }

    @classmethod
    def from_dict(cls, value: object) -> "RatePolicy":
        data = _exact_mapping(
            value,
            "rate_policy",
            {"capacity", "refill_per_second", "cost_per_attempt"},
        )
        return cls(
            capacity=data["capacity"],
            refill_per_second=data["refill_per_second"],
            cost_per_attempt=data["cost_per_attempt"],
        )


@dataclass(frozen=True)
class AcceptanceManifest:
    """Write-once authority for one complete live-registry acceptance run."""

    schema_version: int
    created_at: str
    registry_digest: str
    git_head: str
    dirty_digest: str
    provider: str
    model: str
    rate_policy: RatePolicy
    rows: tuple[AcceptanceMatrixRow, ...]
    manifest_digest: str

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "registry_digest": self.registry_digest,
            "git_head": self.git_head,
            "dirty_digest": self.dirty_digest,
            "provider": self.provider,
            "model": self.model,
            "rate_policy": self.rate_policy.to_dict(),
            "rows": [_row_to_dict(row) for row in self.rows],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "manifest_digest": self.manifest_digest}


@dataclass(frozen=True)
class AcceptanceRunControl:
    """Write-once execution mode and registry-derived scope for one ledger."""

    schema_version: int
    manifest_digest: str
    mode: AcceptanceRunMode
    scope_ids: tuple[str, ...]
    control_digest: str

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_digest": self.manifest_digest,
            "mode": self.mode,
            "scope_ids": list(self.scope_ids),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "control_digest": self.control_digest}


@dataclass(frozen=True)
class LegacyLedgerMigration:
    """Immutable provenance for one explicit import of a legacy ledger."""

    schema_version: int
    manifest_digest: str
    ledger_sha256: str
    event_count: int
    mode: AcceptanceRunMode
    control_digest: str
    migrated_at: float
    migration_digest: str

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_digest": self.manifest_digest,
            "ledger_sha256": self.ledger_sha256,
            "event_count": self.event_count,
            "mode": self.mode,
            "control_digest": self.control_digest,
            "migrated_at": float(self.migrated_at),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "migration_digest": self.migration_digest}


@dataclass(frozen=True)
class CompletionEvidence:
    """Identities required to prove one real, user-confirmed Agent chain."""

    evidence_kind: str
    manifest_digest: str
    submission_id: str
    attempt_no: int
    attempt_started_at: float
    fixture_id: str
    prompt_sha256: str
    provider: str
    model: str
    submission_operation_ids_digest: str
    project_root: str
    source_run_id: str
    source_node_ref: str
    source_artifact_id: str
    source_artifact_sha256: str
    option_revision_recorded_at: str
    confirmation_recorded_at: str
    workflow_plan_fingerprint: str
    agent_session_id: str
    parent_operation_id: str
    parent_record_id: str
    parent_record_status: str
    parent_record_durable: bool
    child_operation_id: str
    child_record_id: str
    child_parent_record_id: str
    child_record_status: str
    child_record_durable: bool
    confirmation_id: str
    confirmation_surface: str
    confirmation_actor: str
    confirmation_session_id: str
    confirmation_parent_record_id: str
    nested_result_status: str
    nested_result_parent_record_id: str
    nested_result_child_record_id: str
    nested_artifact_id: str
    artifact_id: str
    artifact_sha256: str
    artifact_provenance_id: str
    artifact_producer_record_id: str
    durable_chain_sha256: str | None = None
    witness_attestation: Mapping[str, object] | None = None
    witness_trust_level: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            field_name: getattr(self, field_name)
            for field_name in _COMPLETION_EVIDENCE_FIELDS
        }


_COMPLETION_EVIDENCE_FIELDS = (
    "evidence_kind",
    "manifest_digest",
    "submission_id",
    "attempt_no",
    "attempt_started_at",
    "fixture_id",
    "prompt_sha256",
    "provider",
    "model",
    "submission_operation_ids_digest",
    "project_root",
    "source_run_id",
    "source_node_ref",
    "source_artifact_id",
    "source_artifact_sha256",
    "option_revision_recorded_at",
    "confirmation_recorded_at",
    "workflow_plan_fingerprint",
    "agent_session_id",
    "parent_operation_id",
    "parent_record_id",
    "parent_record_status",
    "parent_record_durable",
    "child_operation_id",
    "child_record_id",
    "child_parent_record_id",
    "child_record_status",
    "child_record_durable",
    "confirmation_id",
    "confirmation_surface",
    "confirmation_actor",
    "confirmation_session_id",
    "confirmation_parent_record_id",
    "nested_result_status",
    "nested_result_parent_record_id",
    "nested_result_child_record_id",
    "nested_artifact_id",
    "artifact_id",
    "artifact_sha256",
    "artifact_provenance_id",
    "artifact_producer_record_id",
    "durable_chain_sha256",
    "witness_attestation",
    "witness_trust_level",
)


@dataclass(frozen=True)
class CompletionAuthority:
    """Frozen submission context that durable evidence must causally match."""

    manifest_digest: str
    submission_id: str
    attempt_no: int
    attempt_started_at: float
    fixture_id: str
    prompt: str
    prompt_sha256: str
    provider: str
    model: str
    operation_ids: tuple[str, ...]
    operation_ids_digest: str
    project_root: str


AttemptStatus = Literal[
    "awaiting_confirmation",
    "running",
    "completed",
    "failed",
    "blocked",
    "rejected",
    "cancelled",
]
ACTIVE_ATTEMPT_STATUSES = frozenset({"awaiting_confirmation", "running"})
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {"completed", "failed", "blocked", "rejected", "cancelled"}
)


@dataclass(frozen=True)
class AttemptEvent:
    schema_version: int
    sequence_no: int
    manifest_digest: str
    operation_id: str
    attempt_no: int
    retry_of: int | None
    submission_id: str
    event_type: str
    status: AttemptStatus
    occurred_at: float
    reason_code: str | None
    reason_detail: str | None
    evidence: CompletionEvidence | None
    previous_hash: str | None
    record_hash: str

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence_no": self.sequence_no,
            "manifest_digest": self.manifest_digest,
            "operation_id": self.operation_id,
            "attempt_no": self.attempt_no,
            "retry_of": self.retry_of,
            "submission_id": self.submission_id,
            "event_type": self.event_type,
            "status": self.status,
            "occurred_at": float(self.occurred_at),
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "previous_hash": self.previous_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "record_hash": self.record_hash}


@dataclass(frozen=True)
class OperationAcceptanceState:
    operation_id: str
    status: str
    attempt_no: int | None
    retry_of: int | None
    submission_id: str | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    trust_level: str = "none"
    verification_status: str = "NOT VERIFIED"


@dataclass(frozen=True)
class RateAdmission:
    admitted: bool
    next_admission_at: float
    tokens_after: float


@dataclass(frozen=True)
class NextAdmission:
    row: AcceptanceMatrixRow | None
    rate: RateAdmission
    action: Literal[
        "submit", "wait", "reopen_confirmation", "reconcile_running"
    ] | None
    attempt_no: int | None
    requires_provider_admission: bool


@dataclass(frozen=True)
class NextBatchAdmission:
    batch: AcceptanceBatch | None
    rate: RateAdmission
    action: Literal[
        "submit", "wait", "reopen_confirmation", "reconcile_running"
    ] | None
    attempt_no: int | None
    submission_id: str | None
    requires_provider_admission: bool


def _ordinary_user_prompt(operation_id: str, pack_family: str) -> str:
    title = operation_id.replace(".", " ").replace("_", " ")
    family = pack_family.replace("_", " ")
    return (
        f"请根据这份数据做一次 {title} 分析（{family}），"
        "选择与问题相符的变量，检查方法是否适用，并用通俗语言说明"
        "主要结果、限制和可复核依据。"
    )


def _ordinary_family_prompt(
    pack_family: str,
    operation_ids: tuple[str, ...],
) -> str:
    methods = "、".join(
        operation_id.replace(".", " ").replace("_", " ")
        for operation_id in operation_ids
    )
    family = pack_family.replace("_", " ")
    return (
        f"请根据这份数据一次完成 {family} 方法家族中的这些分析：{methods}。"
        "请为每种方法选择合适变量并检查适用条件，分别给出主要结果、限制和"
        "可复核依据；若某种方法不适用，请明确说明，不能悄悄跳过。"
    )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _update_digest_frame(digest: Any, label: bytes, payload: bytes) -> None:
    digest.update(len(label).to_bytes(4, "big"))
    digest.update(label)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _git_output(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ManifestDriftError(
            "cannot freeze the Git workspace state"
        ) from error
    return completed.stdout


def _untracked_entry_bytes(root: Path, relative_raw: bytes) -> bytes:
    relative_text = os.fsdecode(relative_raw)
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ManifestDriftError("Git returned an unsafe untracked path")
    path = root / relative
    try:
        info = os.lstat(path)
    except OSError as error:
        raise ManifestDriftError(
            f"cannot inspect untracked path {relative_text!r}"
        ) from error
    mode = stat.S_IFMT(info.st_mode).to_bytes(4, "big")
    if stat.S_ISLNK(info.st_mode):
        return mode + os.fsencode(os.readlink(path))
    if not stat.S_ISREG(info.st_mode):
        raise ManifestDriftError(
            f"untracked path must be a regular file or symlink: {relative_text!r}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ManifestDriftError(
            f"cannot open untracked path safely: {relative_text!r}"
        ) from error
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return mode + b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def workspace_dirty_digest(root: str | os.PathLike[str]) -> str:
    """Hash tracked diffs and untracked bytes, not only porcelain path names."""

    repository = Path(root).resolve()
    if not repository.is_dir():
        raise ManifestDriftError("workspace root must be a directory")
    status = _git_output(
        repository,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
    )
    tracked_diff = _git_output(
        repository,
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
    )
    untracked_output = _git_output(
        repository,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    untracked_paths = tuple(
        path for path in untracked_output.split(b"\0") if path
    )
    digest = hashlib.sha256()
    _update_digest_frame(digest, b"status", status)
    _update_digest_frame(digest, b"tracked-diff", tracked_diff)
    for relative_raw in sorted(untracked_paths):
        _update_digest_frame(digest, b"untracked-path", relative_raw)
        _update_digest_frame(
            digest,
            b"untracked-bytes",
            _untracked_entry_bytes(repository, relative_raw),
        )
    return digest.hexdigest()


def _exact_mapping(
    value: object,
    label: str,
    expected_keys: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestDriftError(f"{label} must be an object")
    actual = set(value)
    if actual != expected_keys:
        missing = expected_keys - actual
        extra = actual - expected_keys
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unknown " + ", ".join(sorted(extra)))
        raise ManifestDriftError(f"{label} fields drifted: " + "; ".join(detail))
    return value


def _registry_projection(registry: RegistryLike) -> list[dict[str, object]]:
    operation_ids = tuple(registry.operation_ids())
    if len(set(operation_ids)) != len(operation_ids):
        raise ManifestDriftError("registry contains duplicate operation IDs")
    projected: list[dict[str, object]] = []
    for operation_id in sorted(operation_ids):
        operation = registry.get(operation_id)
        if operation.operation_id != operation_id:
            raise ManifestDriftError(
                f"registry key {operation_id!r} returned {operation.operation_id!r}"
            )
        schema = operation.request_schema
        projected.append(
            {
                "operation_id": operation_id,
                "pack_family": operation.pack_family,
                "input_mode": operation.input_mode,
                "request_schema": {
                    "required_bindings": list(schema.required_bindings),
                    "binding_shapes": dict(sorted(schema.binding_shapes.items())),
                    "required_options": list(schema.required_options),
                    "option_shapes": dict(sorted(schema.option_shapes.items())),
                    "option_enums": {
                        key: list(values)
                        for key, values in sorted(schema.option_enums.items())
                    },
                },
            }
        )
    return projected


def registry_digest(registry: RegistryLike = p7_pack_registry) -> str:
    """Hash the live operation declarations, including their request shapes."""

    return _sha256(_registry_projection(registry))


def _fixture_to_dict(profile: FixtureProfile) -> dict[str, object]:
    return {
        "fixture_id": profile.fixture_id,
        "status": profile.status,
        "source": profile.source,
        "input_mode": profile.input_mode,
        "required_bindings": list(profile.required_bindings),
        "required_options": list(profile.required_options),
        "blocker_code": profile.blocker_code,
        "blocker_detail": profile.blocker_detail,
    }


def _fixture_from_dict(value: object) -> FixtureProfile:
    data = _exact_mapping(
        value,
        "fixture_profile",
        {
            "fixture_id",
            "status",
            "source",
            "input_mode",
            "required_bindings",
            "required_options",
            "blocker_code",
            "blocker_detail",
        },
    )
    for key in ("required_bindings", "required_options"):
        if not isinstance(data[key], list) or any(
            not isinstance(item, str) for item in data[key]
        ):
            raise ManifestDriftError(f"fixture_profile {key} must be a string list")
    if data["status"] not in {"ready", "blocked"}:
        raise ManifestDriftError("fixture_profile status drifted")
    return FixtureProfile(
        fixture_id=_required_text(data["fixture_id"], "fixture_id"),
        status=data["status"],
        source=_required_text(data["source"], "fixture source"),
        input_mode=_required_text(data["input_mode"], "fixture input_mode"),
        required_bindings=tuple(data["required_bindings"]),
        required_options=tuple(data["required_options"]),
        blocker_code=_optional_text(data["blocker_code"], "blocker_code"),
        blocker_detail=_optional_text(data["blocker_detail"], "blocker_detail"),
    )


def _contract_to_dict(contract: ExpectedParentChildContract) -> dict[str, object]:
    return {
        "parent_operation_id": contract.parent_operation_id,
        "child_operation_id": contract.child_operation_id,
        "requires_visible_user_confirmation": contract.requires_visible_user_confirmation,
        "requires_durable_parent_terminal": contract.requires_durable_parent_terminal,
        "requires_durable_child_terminal": contract.requires_durable_child_terminal,
        "requires_completed_nested_result": contract.requires_completed_nested_result,
        "requires_artifact_provenance_identity": contract.requires_artifact_provenance_identity,
    }


def _contract_from_dict(value: object) -> ExpectedParentChildContract:
    fields = {
        "parent_operation_id",
        "child_operation_id",
        "requires_visible_user_confirmation",
        "requires_durable_parent_terminal",
        "requires_durable_child_terminal",
        "requires_completed_nested_result",
        "requires_artifact_provenance_identity",
    }
    data = _exact_mapping(value, "expected_contract", fields)
    for field_name in fields - {"parent_operation_id", "child_operation_id"}:
        if data[field_name] is not True:
            raise ManifestDriftError(
                f"expected_contract {field_name} must remain true"
            )
    return ExpectedParentChildContract(
        parent_operation_id=_required_text(
            data["parent_operation_id"], "parent_operation_id"
        ),
        child_operation_id=_required_text(
            data["child_operation_id"], "child_operation_id"
        ),
    )


def _row_to_dict(row: AcceptanceMatrixRow) -> dict[str, object]:
    return {
        "operation_id": row.operation_id,
        "pack_family": row.pack_family,
        "prompt": row.prompt,
        "fixture_profile": _fixture_to_dict(row.fixture_profile),
        "expected_contract": _contract_to_dict(row.expected_contract),
    }


def _row_from_dict(value: object) -> AcceptanceMatrixRow:
    data = _exact_mapping(
        value,
        "acceptance row",
        {
            "operation_id",
            "pack_family",
            "prompt",
            "fixture_profile",
            "expected_contract",
        },
    )
    row = AcceptanceMatrixRow(
        operation_id=_required_text(data["operation_id"], "operation_id"),
        pack_family=_required_text(data["pack_family"], "pack_family"),
        prompt=_required_text(data["prompt"], "prompt"),
        fixture_profile=_fixture_from_dict(data["fixture_profile"]),
        expected_contract=_contract_from_dict(data["expected_contract"]),
    )
    forbidden = ("operation.multi_step", "model.genesis", "capability_id")
    if any(token in row.prompt.casefold() for token in forbidden):
        raise ManifestDriftError("acceptance row prompt contains protocol vocabulary")
    if row.expected_contract.child_operation_id != row.operation_id:
        raise ManifestDriftError("acceptance row child contract identity drifted")
    if row.expected_contract.parent_operation_id != "operation.multi_step":
        raise ManifestDriftError("acceptance row parent contract identity drifted")
    return row


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestDriftError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _completion_evidence_from_mapping(value: Mapping[str, object]) -> CompletionEvidence:
    if value.get("evidence_kind") not in {
        "browser_visible_agent",
        "browser_witness_attested",
    }:
        raise CompletionEvidenceError(
            "completed evidence must come from a browser-visible Agent session"
        )
    actual = set(value)
    expected = set(_COMPLETION_EVIDENCE_FIELDS)
    accepted_fields = (
        expected,
        expected - {"durable_chain_sha256"},
        expected - {"witness_attestation"},
        expected - {"witness_trust_level"},
        expected - {"witness_attestation", "witness_trust_level"},
        expected - {"durable_chain_sha256", "witness_attestation"},
        expected - {"durable_chain_sha256", "witness_trust_level"},
        expected - {"durable_chain_sha256", "witness_attestation", "witness_trust_level"},
    )
    if actual not in accepted_fields:
        missing = expected - actual
        extra = actual - expected
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unknown " + ", ".join(sorted(extra)))
        raise CompletionEvidenceError(
            "completed evidence fields are incomplete: " + "; ".join(detail)
        )
    normalized = {
        key: value[key]
        for key in _COMPLETION_EVIDENCE_FIELDS
        if key in value
    }
    normalized.setdefault("witness_attestation", None)
    normalized.setdefault("witness_trust_level", None)
    normalized.setdefault("durable_chain_sha256", None)
    return CompletionEvidence(**normalized)


def validate_completion_evidence(
    row: AcceptanceMatrixRow,
    evidence: CompletionEvidence | Mapping[str, object],
) -> CompletionEvidence:
    """Require the complete visible Agent -> parent -> child -> artifact chain."""

    if isinstance(evidence, Mapping):
        evidence = _completion_evidence_from_mapping(evidence)
    if not isinstance(evidence, CompletionEvidence):
        raise CompletionEvidenceError("completed evidence has an unsupported shape")
    if evidence.evidence_kind not in {
        "browser_visible_agent",
        "browser_witness_attested",
    }:
        raise CompletionEvidenceError(
            "completed evidence must come from a browser-visible Agent session"
        )
    if evidence.evidence_kind == "browser_witness_attested":
        if not isinstance(evidence.witness_attestation, Mapping):
            raise CompletionEvidenceError(
                "witness-attested evidence requires a signed witness envelope"
            )
        if not isinstance(evidence.durable_chain_sha256, str):
            raise CompletionEvidenceError(
                "witness-attested evidence requires an independently collected durable result chain"
            )
        if (
            len(evidence.durable_chain_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in evidence.durable_chain_sha256.casefold()
            )
        ):
            raise CompletionEvidenceError(
                "independently collected durable result chain is not a SHA-256 digest"
            )
        try:
            BrowserWitnessAttestation.from_mapping(evidence.witness_attestation)
        except WitnessError as error:
            raise CompletionEvidenceError(str(error)) from error
        if evidence.witness_trust_level not in {
            None,
            "witness_attested",
            "human_identity_verified",
        }:
            raise CompletionEvidenceError(
                "witness trust level is not a supported provider claim"
            )
    elif evidence.witness_attestation is not None:
        raise CompletionEvidenceError(
            "coordinator-only evidence cannot carry a witness envelope"
        )
    elif evidence.witness_trust_level is not None:
        raise CompletionEvidenceError(
            "coordinator-only evidence cannot carry a witness trust level"
        )
    elif evidence.durable_chain_sha256 is not None:
        raise CompletionEvidenceError(
            "coordinator-only evidence cannot carry a witness result chain"
        )
    for field_name in _COMPLETION_EVIDENCE_FIELDS:
        if field_name in {
            "parent_record_durable",
            "child_record_durable",
            "attempt_no",
            "attempt_started_at",
            "durable_chain_sha256",
            "witness_attestation",
            "witness_trust_level",
        }:
            continue
        value = getattr(evidence, field_name)
        if not isinstance(value, str) or not value:
            raise CompletionEvidenceError(
                f"completed evidence {field_name} identity is invalid"
            )
    if type(evidence.attempt_no) is not int or evidence.attempt_no <= 0:
        raise CompletionEvidenceError("completed evidence attempt_no is invalid")
    if (
        type(evidence.attempt_started_at) not in {int, float}
        or not math.isfinite(float(evidence.attempt_started_at))
        or evidence.attempt_started_at < 0
    ):
        raise CompletionEvidenceError(
            "completed evidence attempt_started_at is invalid"
        )
    try:
        revision_at = datetime.fromisoformat(
            evidence.option_revision_recorded_at.replace("Z", "+00:00")
        )
        confirmation_at = datetime.fromisoformat(
            evidence.confirmation_recorded_at.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise CompletionEvidenceError(
            "completed evidence timestamps are not ISO-8601"
        ) from error
    if revision_at.tzinfo is None or confirmation_at.tzinfo is None:
        raise CompletionEvidenceError(
            "completed evidence timestamps must include a timezone"
        )
    revision_seconds = revision_at.astimezone(timezone.utc).timestamp()
    confirmation_seconds = confirmation_at.astimezone(timezone.utc).timestamp()
    if revision_seconds < float(evidence.attempt_started_at):
        raise CompletionEvidenceError(
            "completed evidence option revision predates its submission"
        )
    if confirmation_seconds < revision_seconds:
        raise CompletionEvidenceError(
            "completed evidence confirmation predates its option revision"
        )
    if (
        evidence.parent_operation_id
        != row.expected_contract.parent_operation_id
        or evidence.parent_record_status != "completed"
    ):
        raise CompletionEvidenceError("parent operation terminal identity is invalid")
    if (
        evidence.child_operation_id != row.operation_id
        or evidence.child_parent_record_id != evidence.parent_record_id
        or evidence.child_record_status != "completed"
    ):
        raise CompletionEvidenceError("child operation terminal identity is invalid")
    if (
        evidence.confirmation_surface != "browser"
        or evidence.confirmation_actor != "user"
        or evidence.confirmation_session_id != evidence.agent_session_id
        or evidence.confirmation_parent_record_id != evidence.parent_record_id
    ):
        raise CompletionEvidenceError(
            "visible user confirmation identity is invalid"
        )
    if evidence.parent_record_durable is not True or evidence.child_record_durable is not True:
        raise CompletionEvidenceError(
            "parent and child terminal records must both be durable"
        )
    if (
        evidence.nested_result_status != "completed"
        or evidence.nested_result_parent_record_id != evidence.parent_record_id
        or evidence.nested_result_child_record_id != evidence.child_record_id
        or not evidence.nested_artifact_id
    ):
        raise CompletionEvidenceError("completed nested result identity is invalid")
    sha = evidence.artifact_sha256
    if (
        not evidence.artifact_id
        or evidence.artifact_id != evidence.nested_artifact_id
        or not isinstance(sha, str)
        or len(sha) != 64
        or any(character not in "0123456789abcdef" for character in sha.casefold())
        or not evidence.artifact_provenance_id
        or evidence.artifact_producer_record_id != evidence.child_record_id
    ):
        raise CompletionEvidenceError("artifact/provenance identity is invalid")
    for field_name in (
        "manifest_digest",
        "prompt_sha256",
        "submission_operation_ids_digest",
        "source_artifact_sha256",
    ):
        digest = getattr(evidence, field_name)
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.casefold())
        ):
            raise CompletionEvidenceError(
                f"completed evidence {field_name} is not a SHA-256 digest"
            )
    return evidence


def _validate_completion_event_time(
    evidence: CompletionEvidence,
    *,
    occurred_at: float,
) -> None:
    confirmation_at = datetime.fromisoformat(
        evidence.confirmation_recorded_at.replace("Z", "+00:00")
    ).astimezone(timezone.utc).timestamp()
    if confirmation_at > float(occurred_at):
        raise CompletionEvidenceError(
            "completed evidence confirmation is later than completion event"
        )


def validate_completion_authority(
    evidence: CompletionEvidence,
    authority: CompletionAuthority,
) -> CompletionEvidence:
    """Reject evidence collected for another manifest, submission, or fixture."""

    expected = (
        authority.manifest_digest,
        authority.submission_id,
        authority.attempt_no,
        float(authority.attempt_started_at),
        authority.fixture_id,
        authority.prompt_sha256,
        authority.provider,
        authority.model,
        authority.operation_ids_digest,
        authority.project_root,
    )
    actual = (
        evidence.manifest_digest,
        evidence.submission_id,
        evidence.attempt_no,
        float(evidence.attempt_started_at),
        evidence.fixture_id,
        evidence.prompt_sha256,
        evidence.provider,
        evidence.model,
        evidence.submission_operation_ids_digest,
        evidence.project_root,
    )
    if actual != expected:
        raise CompletionEvidenceError(
            "completed evidence does not match the active submission authority"
        )
    return evidence


def _witness_challenge_for(
    authority: CompletionAuthority,
    attestation: BrowserWitnessAttestation,
) -> WitnessChallenge:
    """Rebuild the coordinator challenge from durable submission authority."""

    return build_witness_challenge(
        authority,
        notebook_id=attestation.notebook_id,
        option_id=attestation.option_id,
        option_revision=attestation.option_revision,
    )


def build_witness_challenge(
    authority: CompletionAuthority,
    *,
    notebook_id: str,
    option_id: str,
    option_revision: int,
) -> WitnessChallenge:
    """Create the challenge an external witness must sign for one option."""

    if not isinstance(authority, CompletionAuthority):
        raise CompletionEvidenceError("completion authority is required")
    return WitnessChallenge.create(
        manifest_digest=authority.manifest_digest,
        submission_id=authority.submission_id,
        attempt_no=authority.attempt_no,
        operation_ids_digest=authority.operation_ids_digest,
        notebook_id=notebook_id,
        option_id=option_id,
        option_revision=option_revision,
        attempt_started_at=authority.attempt_started_at,
        issued_at=authority.attempt_started_at,
        expires_at=authority.attempt_started_at + WITNESS_CHALLENGE_TTL_SECONDS,
    )


def _validate_witness_completion(
    evidence: CompletionEvidence,
    authority: CompletionAuthority,
    *,
    verifier: WitnessVerifier | None,
    occurred_at: float,
) -> WitnessVerification | None:
    if evidence.evidence_kind != "browser_witness_attested":
        return None
    if not isinstance(evidence.witness_attestation, Mapping):
        raise CompletionEvidenceError(
            "witness-attested evidence requires a signed witness envelope"
        )
    try:
        attestation = BrowserWitnessAttestation.from_mapping(
            evidence.witness_attestation
        )
        return verify_witness_attestation(
            _witness_challenge_for(authority, attestation),
            attestation,
            verifier=verifier,
            now=occurred_at,
            expected_durable_chain_sha256=evidence.durable_chain_sha256,
        )
    except WitnessError as error:
        raise CompletionEvidenceError(str(error)) from error


def _normalize_witness_trust(
    evidence: CompletionEvidence,
    authority: CompletionAuthority,
    *,
    verifier: WitnessVerifier | None,
    occurred_at: float,
) -> CompletionEvidence:
    """Verify a new witness claim once and persist its provider trust level."""

    verification = _validate_witness_completion(
        evidence,
        authority,
        verifier=verifier,
        occurred_at=occurred_at,
    )
    if verification is None:
        return evidence
    if (
        evidence.witness_trust_level is not None
        and evidence.witness_trust_level != verification.trust_level
    ):
        raise CompletionEvidenceError(
            "witness trust level does not match the provider verification"
        )
    return replace(evidence, witness_trust_level=verification.trust_level)


def token_bucket_admission(
    policy: RatePolicy,
    *,
    admitted_at: tuple[float, ...] | list[float],
    now: float,
) -> RateAdmission:
    """Compute one admission without sleeping, persisting, or retrying."""

    if type(now) not in {int, float}:
        raise ValueError("rate admission time must be numeric")
    current = float(now)
    times = tuple(float(value) for value in admitted_at)
    if any(value < 0 for value in times) or current < 0:
        raise ValueError("rate admission times cannot be negative")
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise ValueError("rate admission history must be ordered")
    if times and current < times[-1]:
        raise ValueError("rate admission time precedes recorded history")

    tokens = float(policy.capacity)
    last = times[0] if times else current
    for admitted in times:
        tokens = min(
            float(policy.capacity),
            tokens + (admitted - last) * float(policy.refill_per_second),
        )
        if tokens + 1e-12 < float(policy.cost_per_attempt):
            raise AttemptLedgerError("attempt history violates the frozen rate policy")
        tokens -= float(policy.cost_per_attempt)
        last = admitted
    tokens = min(
        float(policy.capacity),
        tokens + (current - last) * float(policy.refill_per_second),
    )
    if tokens + 1e-12 >= float(policy.cost_per_attempt):
        return RateAdmission(
            admitted=True,
            next_admission_at=current,
            tokens_after=max(0.0, tokens - float(policy.cost_per_attempt)),
        )
    wait = (float(policy.cost_per_attempt) - tokens) / float(
        policy.refill_per_second
    )
    return RateAdmission(
        admitted=False,
        next_admission_at=current + wait,
        tokens_after=tokens,
    )


def _fixture_profile(
    operation: object,
    supplied: Mapping[str, object] | FixtureProfile | None,
) -> FixtureProfile:
    schema = operation.request_schema
    required_bindings = tuple(schema.required_bindings)
    required_options = tuple(schema.required_options)
    if isinstance(supplied, FixtureProfile):
        return supplied
    if supplied is None:
        return FixtureProfile(
            fixture_id=f"unresolved:{operation.operation_id}",
            status="blocked",
            source="registry_schema",
            input_mode=operation.input_mode,
            required_bindings=required_bindings,
            required_options=required_options,
            blocker_code="missing_fixture",
            blocker_detail="No executable browser fixture profile was supplied.",
        )
    status = supplied.get("status")
    if status not in {"ready", "blocked"}:
        raise ValueError(
            f"fixture profile for {operation.operation_id!r} must be ready or blocked"
        )
    fixture_id = supplied.get("fixture_id")
    source = supplied.get("source")
    if not isinstance(fixture_id, str) or not fixture_id:
        raise ValueError(
            f"fixture profile for {operation.operation_id!r} needs fixture_id"
        )
    if not isinstance(source, str) or not source:
        raise ValueError(
            f"fixture profile for {operation.operation_id!r} needs source"
        )
    blocker_code = supplied.get("blocker_code")
    blocker_detail = supplied.get("blocker_detail")
    if status == "ready" and (blocker_code is not None or blocker_detail is not None):
        raise ValueError("a ready fixture profile cannot carry a blocker")
    if status == "blocked" and (
        not isinstance(blocker_code, str) or not blocker_code
    ):
        raise ValueError("a blocked fixture profile needs blocker_code")
    return FixtureProfile(
        fixture_id=fixture_id,
        status=status,
        source=source,
        input_mode=operation.input_mode,
        required_bindings=required_bindings,
        required_options=required_options,
        blocker_code=blocker_code if isinstance(blocker_code, str) else None,
        blocker_detail=blocker_detail if isinstance(blocker_detail, str) else None,
    )


def resolve_fixture_catalog(
    *,
    registry: RegistryLike = p7_pack_registry,
    catalog: Mapping[str, object] | None,
) -> dict[str, Mapping[str, object] | FixtureProfile]:
    """Expand family-scoped fixture declarations through live registry membership.

    The preferred catalog shape has ``families`` and optional ``operations``
    objects.  The latter is an explicit override for a genuinely different
    fixture.  A legacy operation-keyed object remains accepted so existing
    manifests do not silently change meaning.
    """

    if catalog is None:
        return {}
    if not isinstance(catalog, Mapping):
        raise ValueError("fixture catalog must be an object")
    live_ids = tuple(registry.operation_ids())
    live_set = set(live_ids)
    family_members: dict[str, list[str]] = {}
    for operation_id in live_ids:
        operation = registry.get(operation_id)
        family_members.setdefault(operation.pack_family, []).append(operation_id)

    structured = "families" in catalog or "operations" in catalog
    if not structured:
        unknown = set(catalog) - live_set
        if unknown:
            raise ValueError(
                "fixture profiles name unregistered operation(s): "
                + ", ".join(sorted(unknown))
            )
        return dict(catalog)  # type: ignore[return-value]

    unknown_sections = set(catalog) - {"families", "operations"}
    if unknown_sections:
        raise ValueError(
            "fixture catalog contains unknown section(s): "
            + ", ".join(sorted(unknown_sections))
        )
    families = catalog.get("families", {})
    operations = catalog.get("operations", {})
    if not isinstance(families, Mapping):
        raise ValueError("fixture catalog families must be an object")
    if not isinstance(operations, Mapping):
        raise ValueError("fixture catalog operations must be an object")

    unknown_families = set(families) - set(family_members)
    if unknown_families:
        raise ValueError(
            "fixture catalog names unregistered pack family/families: "
            + ", ".join(sorted(unknown_families))
        )
    unknown_operations = set(operations) - live_set
    if unknown_operations:
        raise ValueError(
            "fixture profiles name unregistered operation(s): "
            + ", ".join(sorted(unknown_operations))
        )

    expanded: dict[str, Mapping[str, object] | FixtureProfile] = {}
    for pack_family, supplied in families.items():
        if not isinstance(supplied, (Mapping, FixtureProfile)):
            raise ValueError(
                f"fixture profile for family {pack_family!r} must be an object"
            )
        for operation_id in family_members[pack_family]:
            expanded[operation_id] = supplied
    for operation_id, supplied in operations.items():
        if not isinstance(supplied, (Mapping, FixtureProfile)):
            raise ValueError(
                f"fixture profile for operation {operation_id!r} must be an object"
            )
        expanded[operation_id] = supplied
    return expanded


def build_acceptance_batches(
    rows: tuple[AcceptanceMatrixRow, ...],
) -> tuple[AcceptanceBatch, ...]:
    """Group frozen operation rows by their declaration-owned pack family."""

    by_family: dict[str, list[AcceptanceMatrixRow]] = {}
    seen: set[str] = set()
    for row in rows:
        if row.operation_id in seen:
            raise ValueError("P7 acceptance rows contain duplicate operation IDs")
        seen.add(row.operation_id)
        by_family.setdefault(row.pack_family, []).append(row)

    batches: list[AcceptanceBatch] = []
    for pack_family in sorted(by_family):
        family_rows = sorted(
            by_family[pack_family], key=lambda candidate: candidate.operation_id
        )
        operation_ids = tuple(row.operation_id for row in family_rows)
        blocked = [
            row for row in family_rows if row.fixture_profile.status != "ready"
        ]
        fixture_identities = {
            (row.fixture_profile.fixture_id, row.fixture_profile.source)
            for row in family_rows
            if row.fixture_profile.status == "ready"
        }
        if blocked:
            status: FixtureStatus = "blocked"
            fixture_id = None
            source = None
            blocker_code = "incomplete_family_fixture"
            blocker_detail = "Missing executable fixture for: " + ", ".join(
                row.operation_id for row in blocked
            )
        elif len(fixture_identities) != 1:
            status = "blocked"
            fixture_id = None
            source = None
            blocker_code = "inconsistent_family_fixture"
            blocker_detail = (
                "A family batch requires one shared browser fixture source; got "
                + ", ".join(
                    f"{fixture}:{fixture_source}"
                    for fixture, fixture_source in sorted(fixture_identities)
                )
            )
        else:
            status = "ready"
            fixture_id, source = next(iter(fixture_identities))
            blocker_code = None
            blocker_detail = None
        batches.append(
            AcceptanceBatch(
                batch_id=f"family:{pack_family}",
                pack_family=pack_family,
                operation_ids=operation_ids,
                prompt=_ordinary_family_prompt(pack_family, operation_ids),
                status=status,
                fixture_id=fixture_id,
                source=source,
                blocker_code=blocker_code,
                blocker_detail=blocker_detail,
            )
        )
    return tuple(batches)


def build_acceptance_matrix(
    *,
    registry: RegistryLike = p7_pack_registry,
    fixture_profiles: Mapping[
        str, Mapping[str, object] | FixtureProfile
    ] | None = None,
) -> tuple[AcceptanceMatrixRow, ...]:
    """Project one acceptance row for every operation in ``registry``.

    A missing fixture is represented by a blocked row.  It is never dropped
    from the denominator and never converted into a test skip.
    """

    profiles = dict(fixture_profiles or {})
    live_ids = tuple(registry.operation_ids())
    unknown_profiles = set(profiles) - set(live_ids)
    if unknown_profiles:
        raise ValueError(
            "fixture profiles name unregistered operation(s): "
            + ", ".join(sorted(unknown_profiles))
        )
    rows: list[AcceptanceMatrixRow] = []
    for operation_id in live_ids:
        operation = registry.get(operation_id)
        if operation.operation_id != operation_id:
            raise ValueError(
                f"registry key {operation_id!r} returned {operation.operation_id!r}"
            )
        rows.append(
            AcceptanceMatrixRow(
                operation_id=operation_id,
                pack_family=operation.pack_family,
                prompt=_ordinary_user_prompt(operation_id, operation.pack_family),
                fixture_profile=_fixture_profile(operation, profiles.get(operation_id)),
                expected_contract=ExpectedParentChildContract(
                    parent_operation_id="operation.multi_step",
                    child_operation_id=operation_id,
                ),
            )
        )
    if len({row.operation_id for row in rows}) != len(live_ids):
        raise ValueError("P7 acceptance matrix contains duplicate operation IDs")
    return tuple(rows)


def build_acceptance_manifest(
    *,
    registry: RegistryLike = p7_pack_registry,
    git_head: str,
    dirty_digest: str,
    provider: str,
    model: str,
    rate_policy: RatePolicy,
    created_at: str,
    fixture_profiles: Mapping[
        str, Mapping[str, object] | FixtureProfile
    ] | None = None,
) -> AcceptanceManifest:
    """Freeze one registry-derived matrix and its execution authority."""

    for value, label in (
        (git_head, "git_head"),
        (dirty_digest, "dirty_digest"),
        (provider, "provider"),
        (model, "model"),
        (created_at, "created_at"),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")
    if not isinstance(rate_policy, RatePolicy):
        raise ValueError("rate_policy must be a RatePolicy")
    rows = build_acceptance_matrix(
        registry=registry,
        fixture_profiles=fixture_profiles,
    )
    unsigned = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": created_at,
        "registry_digest": registry_digest(registry),
        "git_head": git_head,
        "dirty_digest": dirty_digest,
        "provider": provider,
        "model": model,
        "rate_policy": rate_policy.to_dict(),
        "rows": [_row_to_dict(row) for row in rows],
    }
    return AcceptanceManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        created_at=created_at,
        registry_digest=unsigned["registry_digest"],
        git_head=git_head,
        dirty_digest=dirty_digest,
        provider=provider,
        model=model,
        rate_policy=rate_policy,
        rows=rows,
        manifest_digest=_sha256(unsigned),
    )


def _manifest_from_dict(value: object) -> AcceptanceManifest:
    keys = {
        "schema_version",
        "created_at",
        "registry_digest",
        "git_head",
        "dirty_digest",
        "provider",
        "model",
        "rate_policy",
        "rows",
        "manifest_digest",
    }
    data = _exact_mapping(value, "manifest", keys)
    if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestDriftError("manifest schema version drifted")
    if not isinstance(data["rows"], list) or not data["rows"]:
        raise ManifestDriftError("manifest rows must be a non-empty list")
    rows = tuple(_row_from_dict(item) for item in data["rows"])
    if len({row.operation_id for row in rows}) != len(rows):
        raise ManifestDriftError("manifest rows contain duplicate operation IDs")
    manifest = AcceptanceManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        created_at=_required_text(data["created_at"], "created_at"),
        registry_digest=_required_text(
            data["registry_digest"], "registry_digest"
        ),
        git_head=_required_text(data["git_head"], "git_head"),
        dirty_digest=_required_text(data["dirty_digest"], "dirty_digest"),
        provider=_required_text(data["provider"], "provider"),
        model=_required_text(data["model"], "model"),
        rate_policy=RatePolicy.from_dict(data["rate_policy"]),
        rows=rows,
        manifest_digest=_required_text(
            data["manifest_digest"], "manifest_digest"
        ),
    )
    if _sha256(manifest._unsigned_dict()) != manifest.manifest_digest:
        raise ManifestDriftError("manifest content digest does not match")
    return manifest


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestDriftError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _read_regular_bytes(path: Path) -> bytes:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise ManifestDriftError(f"cannot inspect manifest: {error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ManifestDriftError("manifest path must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ManifestDriftError(f"cannot open manifest safely: {error}") from error
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _publish_write_once_bytes(
    target: Path,
    expected: bytes,
    *,
    label: str,
    error_type: type[P7AcceptanceError],
) -> None:
    """Publish complete bytes with no partially visible target path."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        actual = _read_regular_bytes(target)
        if actual != expected:
            raise error_type(f"write-once {label} already contains different content")
        return

    temporary = target.with_name(f".{target.name}.{secrets.token_hex(16)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except OSError as error:
        raise error_type(f"cannot stage write-once {label}: {error}") from error
    try:
        view = memoryview(expected)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    else:
        os.close(descriptor)

    try:
        os.link(temporary, target, follow_symlinks=False)
    except FileExistsError:
        actual = _read_regular_bytes(target)
        if actual != expected:
            raise error_type(f"write-once {label} already contains different content")
    except OSError as error:
        raise error_type(f"cannot publish write-once {label}: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory = os.open(target.parent, directory_flags)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_once_manifest(
    path: str | os.PathLike[str],
    manifest: AcceptanceManifest,
) -> AcceptanceManifest:
    """Create ``path`` once; any different existing content fails closed."""

    target = Path(path)
    expected = _canonical_json(manifest.to_dict())
    _publish_write_once_bytes(
        target,
        expected,
        label="manifest path",
        error_type=ManifestConflictError,
    )
    return load_acceptance_manifest(target, verify_registry=False)


def load_acceptance_manifest(
    path: str | os.PathLike[str],
    *,
    registry: RegistryLike = p7_pack_registry,
    expected_git_head: str | None = None,
    expected_dirty_digest: str | None = None,
    verify_registry: bool = True,
) -> AcceptanceManifest:
    """Load and verify self-digest plus current registry and caller context."""

    raw = _read_regular_bytes(Path(path))
    try:
        parsed = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestDriftError("manifest is not strict UTF-8 JSON") from error
    manifest = _manifest_from_dict(parsed)
    if verify_registry:
        live_digest = registry_digest(registry)
        if live_digest != manifest.registry_digest:
            raise ManifestDriftError(
                "live registry digest does not match the frozen manifest"
            )
        live_ids = set(registry.operation_ids())
        row_ids = {row.operation_id for row in manifest.rows}
        if live_ids != row_ids:
            raise ManifestDriftError("manifest row denominator drifted from registry")
    if expected_git_head is not None and manifest.git_head != expected_git_head:
        raise ManifestDriftError("git HEAD does not match the frozen manifest")
    if (
        expected_dirty_digest is not None
        and manifest.dirty_digest != expected_dirty_digest
    ):
        raise ManifestDriftError("dirty digest does not match the frozen manifest")
    return manifest


def _event_from_dict(value: object) -> AttemptEvent:
    keys = {
        "schema_version",
        "sequence_no",
        "manifest_digest",
        "operation_id",
        "attempt_no",
        "retry_of",
        "submission_id",
        "event_type",
        "status",
        "occurred_at",
        "reason_code",
        "reason_detail",
        "evidence",
        "previous_hash",
        "record_hash",
    }
    try:
        data = _exact_mapping(value, "attempt event", keys)
    except ManifestDriftError as error:
        raise AttemptLedgerError(str(error)) from error
    for key in ("sequence_no", "attempt_no"):
        if type(data[key]) is not int or data[key] <= 0:
            raise AttemptLedgerError(f"attempt event {key} must be positive")
    retry_of = data["retry_of"]
    if retry_of is not None and (type(retry_of) is not int or retry_of <= 0):
        raise AttemptLedgerError("attempt event retry_of must be positive or null")
    if data["event_type"] not in {"started", "status"}:
        raise AttemptLedgerError("attempt event type is invalid")
    if data["status"] not in ACTIVE_ATTEMPT_STATUSES | TERMINAL_ATTEMPT_STATUSES:
        raise AttemptLedgerError("attempt event status is invalid")
    occurred_at = data["occurred_at"]
    if type(occurred_at) not in {int, float} or occurred_at < 0:
        raise AttemptLedgerError("attempt event occurred_at must be non-negative")
    evidence_raw = data["evidence"]
    evidence: CompletionEvidence | None = None
    if evidence_raw is not None:
        if not isinstance(evidence_raw, Mapping):
            raise AttemptLedgerError("attempt evidence must be an object or null")
        try:
            evidence = _completion_evidence_from_mapping(evidence_raw)
        except CompletionEvidenceError as error:
            raise AttemptLedgerError(str(error)) from error
    event = AttemptEvent(
        schema_version=data["schema_version"],
        sequence_no=data["sequence_no"],
        manifest_digest=_ledger_text(data["manifest_digest"], "manifest_digest"),
        operation_id=_ledger_text(data["operation_id"], "operation_id"),
        attempt_no=data["attempt_no"],
        retry_of=retry_of,
        submission_id=_ledger_text(data["submission_id"], "submission_id"),
        event_type=data["event_type"],
        status=data["status"],
        occurred_at=float(occurred_at),
        reason_code=_ledger_optional_text(data["reason_code"], "reason_code"),
        reason_detail=_ledger_optional_text(data["reason_detail"], "reason_detail"),
        evidence=evidence,
        previous_hash=_ledger_optional_text(data["previous_hash"], "previous_hash"),
        record_hash=_ledger_text(data["record_hash"], "record_hash"),
    )
    if event.schema_version != MANIFEST_SCHEMA_VERSION:
        raise AttemptLedgerError("attempt event schema version drifted")
    return event


def _ledger_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AttemptLedgerError(f"attempt event {label} must be non-empty text")
    return value


def _ledger_optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _ledger_text(value, label)


def _new_attempt_event(
    *,
    sequence_no: int,
    manifest_digest: str,
    operation_id: str,
    attempt_no: int,
    retry_of: int | None,
    submission_id: str,
    event_type: str,
    status: AttemptStatus,
    occurred_at: float,
    reason_code: str | None,
    reason_detail: str | None,
    evidence: CompletionEvidence | None,
    previous_hash: str | None,
) -> AttemptEvent:
    provisional = AttemptEvent(
        schema_version=MANIFEST_SCHEMA_VERSION,
        sequence_no=sequence_no,
        manifest_digest=manifest_digest,
        operation_id=operation_id,
        attempt_no=attempt_no,
        retry_of=retry_of,
        submission_id=submission_id,
        event_type=event_type,
        status=status,
        occurred_at=float(occurred_at),
        reason_code=reason_code,
        reason_detail=reason_detail,
        evidence=evidence,
        previous_hash=previous_hash,
        record_hash="pending",
    )
    return AttemptEvent(
        **{
            **provisional.__dict__,
            "record_hash": _sha256(provisional._unsigned_dict()),
        }
    )


class AttemptLedger:
    """Single-writer, append-only lifecycle records for one frozen manifest."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        manifest: AcceptanceManifest,
        *,
        registry: RegistryLike = p7_pack_registry,
        witness_verifier: WitnessVerifier | None = None,
    ) -> None:
        if not isinstance(manifest, AcceptanceManifest):
            raise AttemptLedgerError("attempt ledger requires an acceptance manifest")
        if registry_digest(registry) != manifest.registry_digest:
            raise ManifestDriftError(
                "live registry digest does not match the attempt manifest"
            )
        if set(registry.operation_ids()) != {
            row.operation_id for row in manifest.rows
        }:
            raise ManifestDriftError(
                "attempt manifest rows do not match the live registry"
            )
        self.path = Path(path)
        self.control_path = self.path.with_name(self.path.name + ".control.json")
        self.legacy_migration_path = self.path.with_name(
            self.path.name + ".legacy-migration.json"
        )
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.manifest = manifest
        self.witness_verifier = witness_verifier
        self._rows = {row.operation_id: row for row in manifest.rows}
        self._batches = {
            batch.pack_family: batch
            for batch in build_acceptance_batches(manifest.rows)
        }

    def _scope_ids(self, mode: AcceptanceRunMode) -> tuple[str, ...]:
        if mode == "operation":
            return tuple(
                sorted(
                    row.operation_id
                    for row in self.manifest.rows
                    if row.fixture_profile.status == "ready"
                )
            )
        return tuple(
            sorted(
                batch.pack_family
                for batch in self._batches.values()
                if batch.status == "ready"
            )
        )

    def _expected_run_control(
        self,
        mode: AcceptanceRunMode,
    ) -> AcceptanceRunControl:
        unsigned = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "manifest_digest": self.manifest.manifest_digest,
            "mode": mode,
            "scope_ids": list(self._scope_ids(mode)),
        }
        return AcceptanceRunControl(
            schema_version=MANIFEST_SCHEMA_VERSION,
            manifest_digest=self.manifest.manifest_digest,
            mode=mode,
            scope_ids=tuple(unsigned["scope_ids"]),
            control_digest=_sha256(unsigned),
        )

    def _load_run_control(self) -> AcceptanceRunControl:
        try:
            raw = _read_regular_bytes(self.control_path)
            parsed = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            data = _exact_mapping(
                parsed,
                "acceptance run control",
                {
                    "schema_version",
                    "manifest_digest",
                    "mode",
                    "scope_ids",
                    "control_digest",
                },
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ManifestDriftError) as error:
            raise AttemptLedgerError(f"acceptance run control is invalid: {error}") from error
        if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
            raise AttemptLedgerError("acceptance run control schema drifted")
        if data["manifest_digest"] != self.manifest.manifest_digest:
            raise AttemptLedgerError("acceptance run control names another manifest")
        if data["mode"] not in {"operation", "family_batch"}:
            raise AttemptLedgerError("acceptance run control mode is invalid")
        scope_ids = data["scope_ids"]
        if (
            not isinstance(scope_ids, list)
            or not scope_ids
            or any(not isinstance(value, str) or not value for value in scope_ids)
            or len(set(scope_ids)) != len(scope_ids)
        ):
            raise AttemptLedgerError("acceptance run control scope is invalid")
        control = AcceptanceRunControl(
            schema_version=MANIFEST_SCHEMA_VERSION,
            manifest_digest=self.manifest.manifest_digest,
            mode=data["mode"],
            scope_ids=tuple(scope_ids),
            control_digest=_required_text(
                data["control_digest"], "control_digest"
            ),
        )
        if _sha256(control._unsigned_dict()) != control.control_digest:
            raise AttemptLedgerError("acceptance run control digest is invalid")
        expected = self._expected_run_control(control.mode)
        if control != expected:
            raise AttemptLedgerError(
                "acceptance run control scope drifted from the frozen manifest"
            )
        return control

    def _ensure_run_control(
        self,
        mode: AcceptanceRunMode,
    ) -> AcceptanceRunControl:
        expected = self._expected_run_control(mode)
        if self.control_path.exists():
            actual = self._load_run_control()
            if actual != expected:
                mode_label = (
                    "family_batch mode (family batch)"
                    if actual.mode == "family_batch"
                    else "operation mode"
                )
                raise AttemptLedgerError(
                    f"acceptance run is frozen in {mode_label}"
                )
            return actual
        payload = _canonical_json(expected.to_dict())
        _publish_write_once_bytes(
            self.control_path,
            payload,
            label="acceptance run control",
            error_type=AttemptLedgerError,
        )
        return self._load_run_control()

    def _load_legacy_migration(self) -> LegacyLedgerMigration:
        try:
            raw = _read_regular_bytes(self.legacy_migration_path)
            parsed = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            data = _exact_mapping(
                parsed,
                "legacy ledger migration",
                {
                    "schema_version",
                    "manifest_digest",
                    "ledger_sha256",
                    "event_count",
                    "mode",
                    "control_digest",
                    "migrated_at",
                    "migration_digest",
                },
            )
            if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
                raise AttemptLedgerError("legacy ledger migration schema drifted")
            if data["mode"] not in {"operation", "family_batch"}:
                raise AttemptLedgerError("legacy ledger migration mode is invalid")
            if type(data["event_count"]) is not int or data["event_count"] <= 0:
                raise AttemptLedgerError(
                    "legacy ledger migration event_count is invalid"
                )
            if (
                type(data["migrated_at"]) not in {int, float}
                or not math.isfinite(float(data["migrated_at"]))
                or float(data["migrated_at"]) < 0
            ):
                raise AttemptLedgerError("legacy ledger migration timestamp is invalid")
            migration = LegacyLedgerMigration(
                schema_version=MANIFEST_SCHEMA_VERSION,
                manifest_digest=_required_text(
                    data["manifest_digest"], "migration manifest_digest"
                ),
                ledger_sha256=_required_text(
                    data["ledger_sha256"], "migration ledger_sha256"
                ),
                event_count=data["event_count"],
                mode=data["mode"],
                control_digest=_required_text(
                    data["control_digest"], "migration control_digest"
                ),
                migrated_at=float(data["migrated_at"]),
                migration_digest=_required_text(
                    data["migration_digest"], "migration_digest"
                ),
            )
            if _sha256(migration._unsigned_dict()) != migration.migration_digest:
                raise AttemptLedgerError("legacy ledger migration digest is invalid")
            return migration
        except (UnicodeDecodeError, json.JSONDecodeError, ManifestDriftError) as error:
            raise AttemptLedgerError(
                f"legacy ledger migration is invalid: {error}"
            ) from error

    @staticmethod
    def _legacy_mode_from_raw(raw: bytes) -> AcceptanceRunMode:
        try:
            first_line = raw.splitlines()[0]
            parsed = json.loads(
                first_line.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (IndexError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AttemptLedgerError(
                "legacy ledger cannot determine its execution mode"
            ) from error
        return (
            "family_batch"
            if isinstance(parsed, Mapping)
            and parsed.get("record_type") == "batch_transaction"
            else "operation"
        )

    def _validate_legacy_migration(
        self,
        migration: LegacyLedgerMigration,
        *,
        raw: bytes,
        event_count: int,
        expected_control: AcceptanceRunControl,
    ) -> None:
        if migration.manifest_digest != self.manifest.manifest_digest:
            raise AttemptLedgerError("legacy migration names another manifest")
        if migration.ledger_sha256 != hashlib.sha256(raw).hexdigest():
            raise AttemptLedgerError("legacy ledger changed after migration")
        if migration.event_count != event_count:
            raise AttemptLedgerError("legacy migration event count drifted")
        if migration.mode != expected_control.mode:
            raise AttemptLedgerError("legacy migration execution mode drifted")
        if migration.control_digest != expected_control.control_digest:
            raise AttemptLedgerError("legacy migration control digest drifted")

    def migrate_legacy(
        self,
        *,
        migrated_at: float | None = None,
    ) -> LegacyLedgerMigration:
        """Explicitly attach control authority to a valid legacy ledger.

        The original ledger is never rewritten.  This method is deliberately
        not called by ``events``, ``states``, ``next`` or ``resume`` paths.
        """

        if migrated_at is not None and (
            type(migrated_at) not in {int, float}
            or not math.isfinite(float(migrated_at))
            or float(migrated_at) < 0
        ):
            raise AttemptLedgerError("legacy migration timestamp is invalid")
        with self._locked_file(exclusive=True) as descriptor:
            raw = self._read_all(descriptor)
            if not raw:
                raise AttemptLedgerError(
                    "legacy migration requires persisted attempt progress"
                )
            if self.control_path.exists():
                if not self.legacy_migration_path.exists():
                    raise AttemptLedgerError(
                        "acceptance run already has control; it is not a legacy ledger"
                    )
                migration = self._load_legacy_migration()
                expected_control = self._expected_run_control(migration.mode)
                actual_control = self._load_run_control()
                if actual_control != expected_control:
                    raise AttemptLedgerError(
                        "legacy migration control does not match the frozen manifest"
                    )
                events = self._events_from_descriptor(descriptor)
                self._validate_legacy_migration(
                    migration,
                    raw=raw,
                    event_count=len(events),
                    expected_control=expected_control,
                )
                return migration

            events = self._events_from_descriptor(
                descriptor,
                require_control=False,
            )
            if not events:
                raise AttemptLedgerError(
                    "legacy migration requires at least one valid event"
                )
            mode = self._legacy_mode_from_raw(raw)
            expected_control = self._expected_run_control(mode)
            if self.legacy_migration_path.exists():
                migration = self._load_legacy_migration()
                self._validate_legacy_migration(
                    migration,
                    raw=raw,
                    event_count=len(events),
                    expected_control=expected_control,
                )
            else:
                unsigned = {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "manifest_digest": self.manifest.manifest_digest,
                    "ledger_sha256": hashlib.sha256(raw).hexdigest(),
                    "event_count": len(events),
                    "mode": mode,
                    "control_digest": expected_control.control_digest,
                    "migrated_at": (
                        float(migrated_at)
                        if migrated_at is not None
                        else datetime.now(timezone.utc).timestamp()
                    ),
                }
                migration = LegacyLedgerMigration(
                    **unsigned,
                    migration_digest=_sha256(unsigned),
                )
                _publish_write_once_bytes(
                    self.legacy_migration_path,
                    _canonical_json(migration.to_dict()),
                    label="legacy ledger migration",
                    error_type=AttemptLedgerError,
                )
            _publish_write_once_bytes(
                self.control_path,
                _canonical_json(expected_control.to_dict()),
                label="acceptance run control",
                error_type=AttemptLedgerError,
            )
            actual_control = self._load_run_control()
            if actual_control != expected_control:
                raise AttemptLedgerError(
                    "migrated acceptance run control does not match the manifest"
                )
            return self._load_legacy_migration()

    def run_control(self) -> AcceptanceRunControl:
        """Load the immutable execution mode and scope frozen by the first start."""

        if not self.control_path.exists():
            raise AttemptLedgerError("acceptance run has not started")
        return self._load_run_control()

    def _assert_run_mode(self, mode: AcceptanceRunMode) -> None:
        if not self.control_path.exists():
            return
        control = self._load_run_control()
        if control.mode != mode:
            mode_label = (
                "family_batch mode (family batch)"
                if control.mode == "family_batch"
                else "operation mode"
            )
            raise AttemptLedgerError(
                f"acceptance run is frozen in {mode_label}"
            )

    @contextmanager
    def _locked_file(self, *, exclusive: bool):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            info = os.lstat(self.lock_path)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise AttemptLedgerError(
                    "attempt ledger lock must be a regular non-symlink file"
                )
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            lock_descriptor = os.open(self.lock_path, lock_flags, 0o600)
        except OSError as error:
            raise AttemptLedgerError(
                f"cannot open attempt ledger lock safely: {error}"
            ) from error
        try:
            fcntl.flock(
                lock_descriptor,
                fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
            )
            if self.path.exists():
                info = os.lstat(self.path)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise AttemptLedgerError(
                        "attempt ledger path must be a regular non-symlink file"
                    )
            data_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(self.path, data_flags, 0o600)
            except OSError as error:
                raise AttemptLedgerError(
                    f"cannot open attempt ledger safely: {error}"
                ) from error
            try:
                yield descriptor
            finally:
                os.close(descriptor)
        finally:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)

    @staticmethod
    def _read_all(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def _events_from_descriptor(
        self,
        descriptor: int,
        *,
        require_control: bool = True,
    ) -> tuple[AttemptEvent, ...]:
        raw = self._read_all(descriptor)
        if not raw:
            return ()
        control: AcceptanceRunControl | None = None
        if self.control_path.exists():
            control = self._load_run_control()
        elif require_control:
            raise AttemptLedgerError(
                "acceptance run control is missing for persisted progress"
            )
        if not raw.endswith(b"\n"):
            raise AttemptLedgerError("attempt ledger has a truncated final record")
        events: list[AttemptEvent] = []
        physical_mode: AcceptanceRunMode | None = None
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            if not raw_line:
                raise AttemptLedgerError(
                    f"attempt ledger contains a blank record at line {line_no}"
                )
            try:
                parsed = json.loads(
                    raw_line.decode("utf-8"),
                    object_pairs_hook=_reject_duplicate_json_keys,
                )
                line_mode: AcceptanceRunMode = (
                    "family_batch"
                    if isinstance(parsed, Mapping)
                    and parsed.get("record_type") == "batch_transaction"
                    else "operation"
                )
                if physical_mode is None:
                    physical_mode = line_mode
                elif line_mode != physical_mode:
                    raise AttemptLedgerError(
                        "attempt ledger mixes operation and family-batch records"
                    )
                if line_no == 1 and control is not None and control.mode != line_mode:
                    raise AttemptLedgerError(
                        "acceptance run control mode disagrees with the first durable "
                        "record"
                    )
                if (
                    isinstance(parsed, Mapping)
                    and parsed.get("record_type") == "batch_transaction"
                ):
                    transaction = _exact_mapping(
                        parsed,
                        "attempt batch transaction",
                        {
                            "record_type",
                            "schema_version",
                            "manifest_digest",
                            "submission_id",
                            "events",
                            "transaction_hash",
                        },
                    )
                    unsigned = {
                        key: transaction[key]
                        for key in transaction
                        if key != "transaction_hash"
                    }
                    if transaction["schema_version"] != MANIFEST_SCHEMA_VERSION:
                        raise ManifestDriftError(
                            "attempt batch transaction schema drifted"
                        )
                    if transaction["manifest_digest"] != self.manifest.manifest_digest:
                        raise ManifestDriftError(
                            "attempt batch transaction names another manifest"
                        )
                    if transaction["transaction_hash"] != _sha256(unsigned):
                        raise ManifestDriftError(
                            "attempt batch transaction hash is invalid"
                        )
                    raw_events = transaction["events"]
                    if not isinstance(raw_events, list) or not raw_events:
                        raise ManifestDriftError(
                            "attempt batch transaction must contain events"
                        )
                    transaction_events = tuple(
                        _event_from_dict(raw_event) for raw_event in raw_events
                    )
                    if any(
                        event.submission_id != transaction["submission_id"]
                        for event in transaction_events
                    ):
                        raise ManifestDriftError(
                            "attempt batch transaction submission identity drifted"
                        )
                    events.extend(transaction_events)
                else:
                    events.append(_event_from_dict(parsed))
            except (UnicodeDecodeError, json.JSONDecodeError, ManifestDriftError) as error:
                raise AttemptLedgerError(
                    f"attempt ledger line {line_no} is invalid JSON: {error}"
                ) from error
        self._validate_events(tuple(events))
        return tuple(events)

    def _validate_events(
        self,
        events: tuple[AttemptEvent, ...],
        *,
        verify_witness: bool = True,
    ) -> None:
        """Validate the chain and reverify persisted witness claims by default."""

        previous_hash: str | None = None
        previous_time = -1.0
        latest: dict[str, AttemptEvent] = {}
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence_no != expected_sequence:
                raise AttemptLedgerError("attempt ledger sequence is not contiguous")
            if event.manifest_digest != self.manifest.manifest_digest:
                raise AttemptLedgerError(
                    "attempt ledger record names a different manifest"
                )
            if event.operation_id not in self._rows:
                raise AttemptLedgerError(
                    f"attempt ledger names unknown operation {event.operation_id!r}"
                )
            if event.previous_hash != previous_hash:
                raise AttemptLedgerError("attempt ledger previous hash is invalid")
            if _sha256(event._unsigned_dict()) != event.record_hash:
                raise AttemptLedgerError("attempt ledger record hash is invalid")
            if event.occurred_at < previous_time:
                raise AttemptLedgerError("attempt ledger timestamps are not monotonic")

            prior = latest.get(event.operation_id)
            if event.event_type == "started":
                if event.status != "awaiting_confirmation":
                    raise AttemptLedgerError(
                        "a started attempt must await visible confirmation"
                    )
                if event.reason_code or event.reason_detail or event.evidence:
                    raise AttemptLedgerError("a started attempt cannot carry an outcome")
                if prior is None:
                    if event.attempt_no != 1 or event.retry_of is not None:
                        raise AttemptLedgerError("first attempt identity is invalid")
                elif (
                    prior.status not in TERMINAL_ATTEMPT_STATUSES - {"completed"}
                    or event.attempt_no != prior.attempt_no + 1
                    or event.retry_of != prior.attempt_no
                ):
                    raise AttemptLedgerError("retry attempt identity is invalid")
                elif event.submission_id == prior.submission_id:
                    raise AttemptLedgerError("retry must use a new submission identity")
            else:
                if prior is None or event.attempt_no != prior.attempt_no:
                    raise AttemptLedgerError("attempt status has no matching start")
                if event.retry_of != prior.retry_of:
                    raise AttemptLedgerError("attempt status retry identity drifted")
                if event.submission_id != prior.submission_id:
                    raise AttemptLedgerError("attempt status submission identity drifted")
                if prior.status not in ACTIVE_ATTEMPT_STATUSES:
                    raise AttemptLedgerError("terminal attempt cannot be updated")
                if event.status == "awaiting_confirmation":
                    raise AttemptLedgerError("attempt cannot re-enter awaiting state")
                if prior.status == "running" and event.status == "running":
                    raise AttemptLedgerError("attempt cannot repeat running state")
                if event.status == "running":
                    if event.reason_code or event.reason_detail or event.evidence:
                        raise AttemptLedgerError("running state cannot carry an outcome")
                elif event.status == "completed":
                    if event.reason_code or event.reason_detail or event.evidence is None:
                        raise AttemptLedgerError(
                            "completed state requires only strict completion evidence"
                        )
                    try:
                        normalized = validate_completion_evidence(
                            self._rows[event.operation_id], event.evidence
                        )
                        authority = self._authority_for_event(events, event)
                        validate_completion_authority(normalized, authority)
                        _validate_completion_event_time(
                            normalized,
                            occurred_at=event.occurred_at,
                        )
                        if normalized.witness_trust_level not in {
                            None,
                            "witness_attested",
                            "human_identity_verified",
                        }:
                            raise CompletionEvidenceError(
                                "witness trust level is not a supported provider claim"
                            )
                        if (
                            verify_witness
                            and normalized.evidence_kind == "browser_witness_attested"
                        ):
                            verification = _validate_witness_completion(
                                normalized,
                                authority,
                                verifier=self.witness_verifier,
                                occurred_at=event.occurred_at,
                            )
                            if (
                                verification is not None
                                and normalized.witness_trust_level is not None
                                and normalized.witness_trust_level
                                != verification.trust_level
                            ):
                                raise CompletionEvidenceError(
                                    "witness trust level does not match the provider "
                                    "verification"
                                )
                    except CompletionEvidenceError as error:
                        raise AttemptLedgerError(str(error)) from error
                elif event.status in TERMINAL_ATTEMPT_STATUSES:
                    if not event.reason_code or event.evidence is not None:
                        raise AttemptLedgerError(
                            "non-completed terminal state requires a reason and no "
                            "completion evidence"
                        )
                else:
                    raise AttemptLedgerError("attempt status transition is invalid")
            latest[event.operation_id] = event
            previous_hash = event.record_hash
            previous_time = event.occurred_at

    def events(self) -> tuple[AttemptEvent, ...]:
        if not self.path.exists():
            return ()
        with self._locked_file(exclusive=False) as descriptor:
            return self._events_from_descriptor(descriptor)

    def _append_locked(
        self,
        descriptor: int,
        events: tuple[AttemptEvent, ...],
        event: AttemptEvent,
    ) -> AttemptEvent:
        self._validate_events((*events, event), verify_witness=False)
        payload = _canonical_json(event.to_dict())
        self._replace_with_appended_bytes(descriptor, payload)
        return event

    def _append_many_locked(
        self,
        descriptor: int,
        events: tuple[AttemptEvent, ...],
        additions: tuple[AttemptEvent, ...],
    ) -> tuple[AttemptEvent, ...]:
        if not additions:
            raise AttemptLedgerError("attempt batch cannot append zero records")
        self._validate_events((*events, *additions), verify_witness=False)
        submission_ids = {event.submission_id for event in additions}
        if len(submission_ids) != 1:
            raise AttemptLedgerError(
                "attempt batch transaction requires one submission identity"
            )
        unsigned = {
            "record_type": "batch_transaction",
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "manifest_digest": self.manifest.manifest_digest,
            "submission_id": next(iter(submission_ids)),
            "events": [event.to_dict() for event in additions],
        }
        payload = _canonical_json(
            {**unsigned, "transaction_hash": _sha256(unsigned)}
        )
        self._replace_with_appended_bytes(descriptor, payload)
        return additions

    def _replace_with_appended_bytes(self, descriptor: int, payload: bytes) -> None:
        """Atomically publish one complete extension of the durable ledger."""

        current = self._read_all(descriptor)
        replacement = current + payload
        temporary = self.path.with_name(
            f".{self.path.name}.{secrets.token_hex(16)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            staged = os.open(temporary, flags, 0o600)
        except OSError as error:
            raise AttemptLedgerError(
                f"cannot stage attempt ledger append: {error}"
            ) from error
        try:
            view = memoryview(replacement)
            while view:
                written = os.write(staged, view)
                view = view[written:]
            os.fsync(staged)
        except BaseException:
            os.close(staged)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(staged)

        try:
            current_info = os.fstat(descriptor)
            path_info = os.lstat(self.path)
            if (
                not stat.S_ISREG(path_info.st_mode)
                or path_info.st_dev != current_info.st_dev
                or path_info.st_ino != current_info.st_ino
            ):
                raise AttemptLedgerError(
                    "attempt ledger changed while its stable lock was held"
                )
            os.replace(temporary, self.path)
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(self.path.parent, directory_flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _row(self, operation_id: str) -> AcceptanceMatrixRow:
        try:
            return self._rows[operation_id]
        except KeyError as error:
            raise AttemptLedgerError(
                f"operation is not in the frozen manifest: {operation_id!r}"
            ) from error

    def _batch(self, pack_family: str) -> AcceptanceBatch:
        try:
            return self._batches[pack_family]
        except KeyError as error:
            raise AttemptLedgerError(
                f"pack family is not in the frozen manifest: {pack_family!r}"
            ) from error

    @staticmethod
    def _latest_by_operation(
        events: tuple[AttemptEvent, ...],
    ) -> dict[str, AttemptEvent]:
        latest: dict[str, AttemptEvent] = {}
        for event in events:
            latest[event.operation_id] = event
        return latest

    def _rate(self, events: tuple[AttemptEvent, ...], now: float) -> RateAdmission:
        starts_by_submission: dict[str, float] = {}
        for event in events:
            if event.event_type == "started":
                starts_by_submission.setdefault(event.submission_id, event.occurred_at)
        starts = tuple(starts_by_submission.values())
        return token_bucket_admission(
            self.manifest.rate_policy,
            admitted_at=starts,
            now=now,
        )

    def _submission_id(
        self,
        *,
        scope: str,
        attempt_no: int,
        sequence_no: int,
    ) -> str:
        return "submission:" + _sha256(
            {
                "manifest_digest": self.manifest.manifest_digest,
                "scope": scope,
                "attempt_no": attempt_no,
                "sequence_no": sequence_no,
                "nonce": secrets.token_hex(32),
            }
        )

    def _authority_for_event(
        self,
        events: tuple[AttemptEvent, ...],
        event: AttemptEvent,
    ) -> CompletionAuthority:
        starts = tuple(
            candidate
            for candidate in events
            if candidate.event_type == "started"
            and candidate.submission_id == event.submission_id
        )
        if not starts:
            raise AttemptLedgerError(
                "submission authority has no durable start record"
            )
        operation_ids = tuple(sorted(candidate.operation_id for candidate in starts))
        if len(set(operation_ids)) != len(operation_ids):
            raise AttemptLedgerError(
                "submission authority contains duplicate operation starts"
            )
        attempt_nos = {candidate.attempt_no for candidate in starts}
        started_at = {candidate.occurred_at for candidate in starts}
        rows = tuple(self._row(operation_id) for operation_id in operation_ids)
        fixture_ids = {row.fixture_profile.fixture_id for row in rows}
        project_roots = {row.fixture_profile.source for row in rows}
        if (
            len(attempt_nos) != 1
            or len(started_at) != 1
            or len(fixture_ids) != 1
            or len(project_roots) != 1
        ):
            raise AttemptLedgerError(
                "submission authority is inconsistent across operation starts"
            )
        if len(operation_ids) == 1:
            prompt = rows[0].prompt
        else:
            families = {row.pack_family for row in rows}
            if len(families) != 1:
                raise AttemptLedgerError(
                    "batch submission spans more than one pack family"
                )
            prompt = self._batch(next(iter(families))).prompt
        return CompletionAuthority(
            manifest_digest=self.manifest.manifest_digest,
            submission_id=event.submission_id,
            attempt_no=next(iter(attempt_nos)),
            attempt_started_at=next(iter(started_at)),
            fixture_id=next(iter(fixture_ids)),
            prompt=prompt,
            prompt_sha256=_sha256(prompt),
            provider=self.manifest.provider,
            model=self.manifest.model,
            operation_ids=operation_ids,
            operation_ids_digest=_sha256(list(operation_ids)),
            project_root=next(iter(project_roots)),
        )

    def completion_authority(self, operation_id: str) -> CompletionAuthority:
        """Return the current active submission context for evidence collection."""

        events = self.events()
        latest = self._latest_by_operation(events).get(operation_id)
        if latest is None or latest.status not in ACTIVE_ATTEMPT_STATUSES:
            raise AttemptLedgerError(
                "completion authority requires one active operation attempt"
            )
        return self._authority_for_event(events, latest)

    def witness_challenge(
        self,
        operation_id: str,
        *,
        notebook_id: str,
        option_id: str,
        option_revision: int,
    ) -> WitnessChallenge:
        """Return the exact challenge an external browser witness must attest."""

        return build_witness_challenge(
            self.completion_authority(operation_id),
            notebook_id=notebook_id,
            option_id=option_id,
            option_revision=option_revision,
        )

    def start_attempt(self, operation_id: str, *, occurred_at: float) -> AttemptEvent:
        row = self._row(operation_id)
        if row.fixture_profile.status == "blocked":
            raise AttemptLedgerError(
                f"fixture is blocked for {operation_id}: "
                f"{row.fixture_profile.blocker_code}"
            )
        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            self._ensure_run_control("operation")
            latest = self._latest_by_operation(events)
            active = next(
                (
                    event
                    for event in latest.values()
                    if event.status in ACTIVE_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                raise AttemptLedgerError(
                    "active browser attempt must be resumed before another starts: "
                    f"{active.operation_id} attempt {active.attempt_no}"
                )
            if operation_id in latest:
                raise AttemptLedgerError(
                    "operation already has an attempt; use explicit retry after a terminal failure"
                )
            rate = self._rate(events, occurred_at)
            if not rate.admitted:
                raise RateLimitError(rate.next_admission_at)
            submission_id = self._submission_id(
                scope=f"operation:{operation_id}",
                attempt_no=1,
                sequence_no=len(events) + 1,
            )
            event = _new_attempt_event(
                sequence_no=len(events) + 1,
                manifest_digest=self.manifest.manifest_digest,
                operation_id=operation_id,
                attempt_no=1,
                retry_of=None,
                submission_id=submission_id,
                event_type="started",
                status="awaiting_confirmation",
                occurred_at=occurred_at,
                reason_code=None,
                reason_detail=None,
                evidence=None,
                previous_hash=events[-1].record_hash if events else None,
            )
            return self._append_locked(descriptor, events, event)

    def start_batch(
        self,
        pack_family: str,
        *,
        occurred_at: float,
    ) -> tuple[AttemptEvent, ...]:
        """Atomically admit every operation in one ready family submission."""

        batch = self._batch(pack_family)
        if batch.status != "ready":
            raise AttemptLedgerError(
                f"family fixture is blocked for {pack_family}: {batch.blocker_code}"
            )
        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            self._ensure_run_control("family_batch")
            latest = self._latest_by_operation(events)
            active = next(
                (
                    event
                    for event in latest.values()
                    if event.status in ACTIVE_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                raise AttemptLedgerError(
                    "active browser attempt must be resumed before another starts: "
                    f"{active.operation_id} attempt {active.attempt_no}"
                )
            already_attempted = [
                operation_id
                for operation_id in batch.operation_ids
                if operation_id in latest
            ]
            if already_attempted:
                raise AttemptLedgerError(
                    "family already has an attempt; use explicit batch retry after "
                    "a terminal failure: " + ", ".join(already_attempted)
                )
            rate = self._rate(events, occurred_at)
            if not rate.admitted:
                raise RateLimitError(rate.next_admission_at)
            submission_id = self._submission_id(
                scope=batch.batch_id,
                attempt_no=1,
                sequence_no=len(events) + 1,
            )
            additions: list[AttemptEvent] = []
            previous_hash = events[-1].record_hash if events else None
            for offset, operation_id in enumerate(batch.operation_ids, start=1):
                event = _new_attempt_event(
                    sequence_no=len(events) + offset,
                    manifest_digest=self.manifest.manifest_digest,
                    operation_id=operation_id,
                    attempt_no=1,
                    retry_of=None,
                    submission_id=submission_id,
                    event_type="started",
                    status="awaiting_confirmation",
                    occurred_at=occurred_at,
                    reason_code=None,
                    reason_detail=None,
                    evidence=None,
                    previous_hash=previous_hash,
                )
                additions.append(event)
                previous_hash = event.record_hash
            return self._append_many_locked(descriptor, events, tuple(additions))

    def record_status(
        self,
        operation_id: str,
        attempt_no: int,
        status: AttemptStatus,
        *,
        occurred_at: float,
        evidence: CompletionEvidence | Mapping[str, object] | None = None,
        reason_code: str | None = None,
        reason_detail: str | None = None,
    ) -> AttemptEvent:
        row = self._row(operation_id)
        normalized_evidence: CompletionEvidence | None = None
        if status == "completed":
            if evidence is None:
                raise CompletionEvidenceError(
                    "completed state requires browser-visible Agent evidence"
                )
            normalized_evidence = validate_completion_evidence(row, evidence)
        elif evidence is not None:
            raise CompletionEvidenceError(
                "non-completed state cannot carry completion evidence"
            )
        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            latest = self._latest_by_operation(events).get(operation_id)
            if latest is None:
                raise AttemptLedgerError("attempt status has no matching start")
            if latest.attempt_no != attempt_no:
                raise AttemptLedgerError("attempt number is not the current attempt")
            if normalized_evidence is not None:
                authority = self._authority_for_event(events, latest)
                validate_completion_authority(
                    normalized_evidence,
                    authority,
                )
                _validate_completion_event_time(
                    normalized_evidence,
                    occurred_at=occurred_at,
                )
                normalized_evidence = _normalize_witness_trust(
                    normalized_evidence,
                    authority,
                    verifier=self.witness_verifier,
                    occurred_at=occurred_at,
                )
            submission_members = {
                event.operation_id
                for event in self._latest_by_operation(events).values()
                if event.submission_id == latest.submission_id
            }
            if len(submission_members) > 1:
                raise AttemptLedgerError(
                    "a family batch submission must be recorded atomically"
                )
            event = _new_attempt_event(
                sequence_no=len(events) + 1,
                manifest_digest=self.manifest.manifest_digest,
                operation_id=operation_id,
                attempt_no=attempt_no,
                retry_of=latest.retry_of,
                submission_id=latest.submission_id,
                event_type="status",
                status=status,
                occurred_at=occurred_at,
                reason_code=reason_code,
                reason_detail=reason_detail,
                evidence=normalized_evidence,
                previous_hash=events[-1].record_hash,
            )
            return self._append_locked(descriptor, events, event)

    def record_batch_status(
        self,
        pack_family: str,
        status: AttemptStatus,
        *,
        occurred_at: float,
        evidence_by_operation: Mapping[
            str, CompletionEvidence | Mapping[str, object]
        ]
        | None = None,
        reason_code: str | None = None,
        reason_detail: str | None = None,
    ) -> tuple[AttemptEvent, ...]:
        """Atomically advance every child of one visible family submission."""

        batch = self._batch(pack_family)
        normalized: dict[str, CompletionEvidence] = {}
        if status == "completed":
            if evidence_by_operation is None:
                raise CompletionEvidenceError(
                    "completed family state requires evidence for every operation"
                )
            if set(evidence_by_operation) != set(batch.operation_ids):
                raise CompletionEvidenceError(
                    "completed family evidence must exactly match every operation"
                )
            normalized = {
                operation_id: validate_completion_evidence(
                    self._row(operation_id), evidence_by_operation[operation_id]
                )
                for operation_id in batch.operation_ids
            }
            shared_parent = {
                (
                    evidence.agent_session_id,
                    evidence.parent_record_id,
                    evidence.confirmation_id,
                    evidence.confirmation_session_id,
                    evidence.confirmation_parent_record_id,
                )
                for evidence in normalized.values()
            }
            if len(shared_parent) != 1:
                raise CompletionEvidenceError(
                    "family completion evidence must come from the same visible parent"
                )
        elif evidence_by_operation is not None:
            raise CompletionEvidenceError(
                "non-completed family state cannot carry completion evidence"
            )

        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            latest_by_operation = self._latest_by_operation(events)
            latest = [
                latest_by_operation.get(operation_id)
                for operation_id in batch.operation_ids
            ]
            if any(event is None for event in latest):
                raise AttemptLedgerError(
                    "family status has no matching batch start for every operation"
                )
            current = tuple(event for event in latest if event is not None)
            submission_ids = {event.submission_id for event in current}
            if len(submission_ids) != 1:
                raise AttemptLedgerError(
                    "family operations do not share one active submission"
                )
            if any(event.status not in ACTIVE_ATTEMPT_STATUSES for event in current):
                raise AttemptLedgerError(
                    "family batch contains an operation that is no longer active"
                )
            active_outside = [
                event
                for operation_id, event in latest_by_operation.items()
                if operation_id not in batch.operation_ids
                and event.status in ACTIVE_ATTEMPT_STATUSES
            ]
            if active_outside:
                raise AttemptLedgerError(
                    "another active browser submission prevents batch reconciliation"
                )
            if normalized:
                authority = self._authority_for_event(events, current[0])
                for operation_id, evidence in tuple(normalized.items()):
                    validate_completion_authority(evidence, authority)
                    _validate_completion_event_time(
                        evidence,
                        occurred_at=occurred_at,
                    )
                    normalized[operation_id] = _normalize_witness_trust(
                        evidence,
                        authority,
                        verifier=self.witness_verifier,
                        occurred_at=occurred_at,
                    )

            additions: list[AttemptEvent] = []
            previous_hash = events[-1].record_hash
            for offset, event in enumerate(current, start=1):
                addition = _new_attempt_event(
                    sequence_no=len(events) + offset,
                    manifest_digest=self.manifest.manifest_digest,
                    operation_id=event.operation_id,
                    attempt_no=event.attempt_no,
                    retry_of=event.retry_of,
                    submission_id=event.submission_id,
                    event_type="status",
                    status=status,
                    occurred_at=occurred_at,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                    evidence=normalized.get(event.operation_id),
                    previous_hash=previous_hash,
                )
                additions.append(addition)
                previous_hash = addition.record_hash
            return self._append_many_locked(descriptor, events, tuple(additions))

    def retry(self, operation_id: str, *, occurred_at: float) -> AttemptEvent:
        self._assert_run_mode("operation")
        row = self._row(operation_id)
        if row.fixture_profile.status == "blocked":
            raise AttemptLedgerError(
                f"fixture is blocked for {operation_id}: "
                f"{row.fixture_profile.blocker_code}"
            )
        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            latest_by_operation = self._latest_by_operation(events)
            latest = latest_by_operation.get(operation_id)
            if latest is None:
                raise AttemptLedgerError("retry requires an existing terminal attempt")
            active = next(
                (
                    event
                    for event in latest_by_operation.values()
                    if event.status in ACTIVE_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                raise AttemptLedgerError(
                    "active browser attempt must be resumed before a retry: "
                    f"{active.operation_id} attempt {active.attempt_no}"
                )
            submission_members = {
                event.operation_id
                for event in latest_by_operation.values()
                if event.submission_id == latest.submission_id
            }
            if len(submission_members) > 1:
                raise AttemptLedgerError(
                    "a family batch submission requires explicit batch retry"
                )
            if latest.status == "completed":
                raise AttemptLedgerError("a completed operation cannot be retried")
            if latest.status not in TERMINAL_ATTEMPT_STATUSES:
                raise AttemptLedgerError(
                    "awaiting or running attempt cannot be resubmitted"
                )
            rate = self._rate(events, occurred_at)
            if not rate.admitted:
                raise RateLimitError(rate.next_admission_at)
            next_attempt_no = latest.attempt_no + 1
            submission_id = self._submission_id(
                scope=f"operation:{operation_id}",
                attempt_no=next_attempt_no,
                sequence_no=len(events) + 1,
            )
            event = _new_attempt_event(
                sequence_no=len(events) + 1,
                manifest_digest=self.manifest.manifest_digest,
                operation_id=operation_id,
                attempt_no=next_attempt_no,
                retry_of=latest.attempt_no,
                submission_id=submission_id,
                event_type="started",
                status="awaiting_confirmation",
                occurred_at=occurred_at,
                reason_code=None,
                reason_detail=None,
                evidence=None,
                previous_hash=events[-1].record_hash,
            )
            return self._append_locked(descriptor, events, event)

    def retry_batch(
        self,
        pack_family: str,
        *,
        occurred_at: float,
    ) -> tuple[AttemptEvent, ...]:
        """Start a new immutable submission for one failed family attempt."""

        self._assert_run_mode("family_batch")
        batch = self._batch(pack_family)
        if batch.status != "ready":
            raise AttemptLedgerError(
                f"family fixture is blocked for {pack_family}: {batch.blocker_code}"
            )
        with self._locked_file(exclusive=True) as descriptor:
            events = self._events_from_descriptor(descriptor)
            latest_by_operation = self._latest_by_operation(events)
            active = next(
                (
                    event
                    for event in latest_by_operation.values()
                    if event.status in ACTIVE_ATTEMPT_STATUSES
                ),
                None,
            )
            if active is not None:
                raise AttemptLedgerError(
                    "active browser attempt must be resumed before a batch retry: "
                    f"{active.operation_id} attempt {active.attempt_no}"
                )
            current = [
                latest_by_operation.get(operation_id)
                for operation_id in batch.operation_ids
            ]
            if any(event is None for event in current):
                raise AttemptLedgerError(
                    "batch retry requires a prior attempt for every family operation"
                )
            prior = tuple(event for event in current if event is not None)
            if any(event.status == "completed" for event in prior):
                raise AttemptLedgerError("a completed family batch cannot be retried")
            if any(event.status not in TERMINAL_ATTEMPT_STATUSES for event in prior):
                raise AttemptLedgerError(
                    "family batch must be terminal before it can be retried"
                )
            prior_submission_ids = {event.submission_id for event in prior}
            prior_attempt_nos = {event.attempt_no for event in prior}
            if len(prior_submission_ids) != 1 or len(prior_attempt_nos) != 1:
                raise AttemptLedgerError(
                    "family retry requires one coherent prior batch submission"
                )
            rate = self._rate(events, occurred_at)
            if not rate.admitted:
                raise RateLimitError(rate.next_admission_at)
            prior_attempt_no = next(iter(prior_attempt_nos))
            next_attempt_no = prior_attempt_no + 1
            submission_id = self._submission_id(
                scope=batch.batch_id,
                attempt_no=next_attempt_no,
                sequence_no=len(events) + 1,
            )
            additions: list[AttemptEvent] = []
            previous_hash = events[-1].record_hash
            for offset, event in enumerate(prior, start=1):
                addition = _new_attempt_event(
                    sequence_no=len(events) + offset,
                    manifest_digest=self.manifest.manifest_digest,
                    operation_id=event.operation_id,
                    attempt_no=next_attempt_no,
                    retry_of=prior_attempt_no,
                    submission_id=submission_id,
                    event_type="started",
                    status="awaiting_confirmation",
                    occurred_at=occurred_at,
                    reason_code=None,
                    reason_detail=None,
                    evidence=None,
                    previous_hash=previous_hash,
                )
                additions.append(addition)
                previous_hash = addition.record_hash
            return self._append_many_locked(descriptor, events, tuple(additions))

    def states(self) -> dict[str, OperationAcceptanceState]:
        events = self.events()
        latest = self._latest_by_operation(events)
        states: dict[str, OperationAcceptanceState] = {}
        for row in self.manifest.rows:
            event = latest.get(row.operation_id)
            if event is not None:
                trust_level = "none"
                verification_status = "NOT VERIFIED"
                if event.status == "completed" and event.evidence is not None:
                    if event.evidence.evidence_kind == "browser_witness_attested":
                        trust_level = (
                            event.evidence.witness_trust_level
                            or "witness_attested"
                        )
                        verification_status = "VERIFIED"
                    else:
                        trust_level = "coordinator_only"
                states[row.operation_id] = OperationAcceptanceState(
                    operation_id=row.operation_id,
                    status=event.status,
                    attempt_no=event.attempt_no,
                    retry_of=event.retry_of,
                    submission_id=event.submission_id,
                    reason_code=event.reason_code,
                    reason_detail=event.reason_detail,
                    trust_level=trust_level,
                    verification_status=verification_status,
                )
            elif row.fixture_profile.status == "blocked":
                states[row.operation_id] = OperationAcceptanceState(
                    operation_id=row.operation_id,
                    status="blocked",
                    attempt_no=None,
                    retry_of=None,
                    submission_id=None,
                    reason_code=row.fixture_profile.blocker_code,
                    reason_detail=row.fixture_profile.blocker_detail,
                )
            else:
                states[row.operation_id] = OperationAcceptanceState(
                    operation_id=row.operation_id,
                    status="pending",
                    attempt_no=None,
                    retry_of=None,
                    submission_id=None,
                )
        return states

    def next_admission(self, *, now: float) -> NextAdmission:
        self._assert_run_mode("operation")
        events = self.events()
        latest = self._latest_by_operation(events)
        active = next(
            (
                event
                for event in reversed(events)
                if latest.get(event.operation_id) == event
                and event.status in ACTIVE_ATTEMPT_STATUSES
            ),
            None,
        )
        rate = self._rate(events, now)
        if active is not None:
            active_submission = [
                event
                for event in latest.values()
                if event.submission_id == active.submission_id
                and event.status in ACTIVE_ATTEMPT_STATUSES
            ]
            if len(active_submission) != 1:
                raise AttemptLedgerError(
                    "active submission is a family batch; use the batch resume API"
                )
            return NextAdmission(
                row=self._rows[active.operation_id],
                rate=rate,
                action=(
                    "reopen_confirmation"
                    if active.status == "awaiting_confirmation"
                    else "reconcile_running"
                ),
                attempt_no=active.attempt_no,
                requires_provider_admission=False,
            )
        row = next(
            (
                candidate
                for candidate in self.manifest.rows
                if candidate.fixture_profile.status == "ready"
                and candidate.operation_id not in latest
            ),
            None,
        )
        return NextAdmission(
            row=row,
            rate=rate,
            action=(
                "submit"
                if row is not None and rate.admitted
                else "wait" if row is not None else None
            ),
            attempt_no=None,
            requires_provider_admission=row is not None and rate.admitted,
        )

    def next_batch_admission(self, *, now: float) -> NextBatchAdmission:
        """Return one family packet, or the exact active packet to resume."""

        self._assert_run_mode("family_batch")
        events = self.events()
        latest = self._latest_by_operation(events)
        active = tuple(
            event
            for event in latest.values()
            if event.status in ACTIVE_ATTEMPT_STATUSES
        )
        rate = self._rate(events, now)
        if active:
            submission_ids = {event.submission_id for event in active}
            families = {self._row(event.operation_id).pack_family for event in active}
            if len(submission_ids) != 1 or len(families) != 1:
                raise AttemptLedgerError(
                    "active records do not form one resumable family submission"
                )
            pack_family = next(iter(families))
            batch = self._batch(pack_family)
            if {event.operation_id for event in active} != set(batch.operation_ids):
                raise AttemptLedgerError(
                    "active submission is not a complete family batch"
                )
            attempt_nos = {event.attempt_no for event in active}
            if len(attempt_nos) != 1:
                raise AttemptLedgerError(
                    "active family submission has inconsistent attempt numbers"
                )
            return NextBatchAdmission(
                batch=batch,
                rate=rate,
                action=(
                    "reconcile_running"
                    if any(event.status == "running" for event in active)
                    else "reopen_confirmation"
                ),
                attempt_no=next(iter(attempt_nos)),
                submission_id=next(iter(submission_ids)),
                requires_provider_admission=False,
            )

        batch = next(
            (
                candidate
                for candidate in self._batches.values()
                if candidate.status == "ready"
                and all(
                    operation_id not in latest
                    for operation_id in candidate.operation_ids
                )
            ),
            None,
        )
        return NextBatchAdmission(
            batch=batch,
            rate=rate,
            action=(
                "submit"
                if batch is not None and rate.admitted
                else "wait" if batch is not None else None
            ),
            attempt_no=None,
            submission_id=None,
            requires_provider_admission=batch is not None and rate.admitted,
        )


__all__ = [
    "AcceptanceBatch",
    "AcceptanceManifest",
    "AcceptanceMatrixRow",
    "AcceptanceRunControl",
    "AttemptEvent",
    "AttemptLedger",
    "AttemptLedgerError",
    "CompletionEvidence",
    "CompletionAuthority",
    "CompletionEvidenceError",
    "ExpectedParentChildContract",
    "FixtureProfile",
    "LegacyLedgerMigration",
    "ManifestConflictError",
    "ManifestDriftError",
    "NextBatchAdmission",
    "NextAdmission",
    "OperationAcceptanceState",
    "P7AcceptanceError",
    "RateAdmission",
    "RateLimitError",
    "RatePolicy",
    "RegistryLike",
    "build_acceptance_manifest",
    "build_acceptance_batches",
    "build_acceptance_matrix",
    "build_witness_challenge",
    "load_acceptance_manifest",
    "registry_digest",
    "resolve_fixture_catalog",
    "token_bucket_admission",
    "validate_completion_evidence",
    "validate_completion_authority",
    "workspace_dirty_digest",
    "write_once_manifest",
]
