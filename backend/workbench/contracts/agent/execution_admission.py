"""Server-side execution-admission requests and immutable receipts."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json
from workbench.contracts.agent.planning import (
    CompilationRecordReferenceV1,
    CompilationRecordStoreV1,
    ConfirmationBindingV1,
    ConfirmationBindingStoreV1,
    PlanningContractError,
)


ADMISSION_SCHEMA_V1 = "execution-admission.v1"
ADMISSION_RECEIPT_SCHEMA_V1 = "execution-admission-receipt.v1"
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ISSUED_RECEIPTS: dict[tuple[int, str], object] = {}


class AdmissionContractError(ContractError):
    """A fail-closed admission boundary failure."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class AdmissionEffectV1(str, Enum):
    READ_ONLY = "read_only"
    DATASET_MUTATION = "dataset_mutation"
    MODEL_FIT = "model_fit"
    REPORT_MUTATION = "report_mutation"
    PROVIDER_EGRESS = "provider_egress"


def _error(code: str, message: str) -> AdmissionContractError:
    return AdmissionContractError(code, message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("ADMISSION_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("ADMISSION_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _parse_effect(value: object) -> AdmissionEffectV1:
    if type(value) is not str:
        raise _error("ADMISSION_ENUM_INVALID", "effect is invalid")
    try:
        return AdmissionEffectV1(value)
    except ValueError as exc:
        raise _error("ADMISSION_ENUM_INVALID", "effect is invalid") from exc


def _timestamp(value: object, name: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _now(clock: Callable[[], datetime] | None, at: str | None = None) -> datetime:
    if at is not None:
        return _timestamp(at, "at")
    current = datetime.now(UTC) if clock is None else clock()
    if type(current) is not datetime or current.tzinfo is None or current.utcoffset() is None:
        raise _error("ADMISSION_CLOCK_INVALID", "clock must return an aware datetime")
    return current.astimezone(UTC)


def _contract_ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise _error("ADMISSION_CONTRACT_REF_INVALID", f"{name} is invalid")
    return value


def _ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error("ADMISSION_ARRAY_INVALID", f"{name} must be an array")
    refs = tuple(_contract_ref(item, f"{name}[]") for item in value)
    identities = {(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}
    if len(identities) != len(refs):
        raise _error("ADMISSION_DUPLICATE_ID", f"{name} contains duplicate identities")
    return refs


def _wire_ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if type(value) is not list:
        raise _error("ADMISSION_ARRAY_INVALID", f"{name} must be a built-in list")
    refs: list[ContractRefV1] = []
    for item in value:
        if type(item) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} entries must be built-in dicts")
        try:
            refs.append(ContractRefV1.from_dict(item))
        except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
            raise _error("ADMISSION_CONTRACT_REF_INVALID", f"{name} contains an invalid ref") from exc
    return _ref_tuple(refs, name)


def _budget(value: object, name: str) -> Mapping[str, int | float]:
    if not isinstance(value, Mapping) or type(value) is dict and any(type(key) is not str for key in value):
        raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} must be a mapping with string keys")
    result: dict[str, int | float] = {}
    for key, item in value.items():
        _text(key, f"{name} key")
        if type(item) is int:
            if not 0 <= item <= _MAX_JSON_SAFE_INTEGER:
                raise _error("ADMISSION_BUDGET_INVALID", f"{name} contains an invalid integer")
        elif type(item) is float:
            if not math.isfinite(item) or item < 0:
                raise _error("ADMISSION_BUDGET_INVALID", f"{name} contains an invalid number")
        else:
            raise _error("ADMISSION_BUDGET_INVALID", f"{name} values must be finite numbers")
        result[key] = item
    if not result:
        raise _error("ADMISSION_BUDGET_INVALID", f"{name} must not be empty")
    try:
        frozen = freeze_json(result, name)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("ADMISSION_BUDGET_INVALID", f"{name} is not safely serializable") from exc
    return frozen


def _string_map(value: object, name: str, *, digest_values: bool) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        _text(key, f"{name} key")
        normalized[key] = _digest(item, f"{name}.{key}") if digest_values else _text(item, f"{name}.{key}")
    if not normalized:
        raise _error("ADMISSION_SCOPE_INVALID", f"{name} must not be empty")
    try:
        frozen = freeze_json(normalized, name)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("ADMISSION_SCOPE_INVALID", f"{name} is not safely serializable") from exc
    return frozen


def _plain(value: object) -> object:
    try:
        return thaw_json(value)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("ADMISSION_JSON_INVALID", "admission value is not safely serializable") from exc


def _wire(value: object, required: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    if any(type(key) is not str for key in value) or set(value) != required:
        raise _error("ADMISSION_SCHEMA_INVALID", f"{name} fields are not exact")
    return value


def _wire_boundary(function):
    @wraps(function)
    def wrapped(cls, value):
        try:
            return function(cls, value)
        except AdmissionContractError:
            raise
        except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
            raise _error("ADMISSION_WIRE_INVALID", "admission wire value is invalid") from exc

    return wrapped


def _budget_within(requested: Mapping[str, int | float], allowed: Mapping[str, Any]) -> bool:
    for key, value in requested.items():
        maximum = allowed.get(key)
        if type(maximum) not in {int, float} or value > maximum:
            return False
    return True


@dataclass(frozen=True)
class ExecutionAdmissionV1:
    request_id: str
    compilation_record_ref: CompilationRecordReferenceV1
    confirmation_ref: str
    confirmation_digest: str
    principal_ref: str
    session_ref: str
    project_ref: str
    contract_snapshot_refs: tuple[ContractRefV1, ...]
    catalog_snapshot_ref: str
    policy_snapshot_ref: str
    effect: AdmissionEffectV1
    resource_budget: Mapping[str, int | float]
    requested_at: str
    expires_at: str
    execution_instance_hash: str | None = None
    resolved_run_identity: str | None = None
    resolved_node_identities: Mapping[str, str] = field(default_factory=dict)
    resolved_artifact_digests: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        if type(self.compilation_record_ref) is not CompilationRecordReferenceV1:
            raise _error("SERVER_RECORD_REFERENCE_REQUIRED", "runtime requires a server-resolved compilation reference")
        _text(self.confirmation_ref, "confirmation_ref")
        _digest(self.confirmation_digest, "confirmation_digest")
        for name, value in (
            ("principal_ref", self.principal_ref),
            ("session_ref", self.session_ref),
            ("project_ref", self.project_ref),
            ("catalog_snapshot_ref", self.catalog_snapshot_ref),
            ("policy_snapshot_ref", self.policy_snapshot_ref),
        ):
            _text(value, name)
        object.__setattr__(self, "contract_snapshot_refs", _ref_tuple(self.contract_snapshot_refs, "contract_snapshot_refs"))
        if type(self.effect) is not AdmissionEffectV1:
            raise _error("ADMISSION_ENUM_INVALID", "effect is invalid")
        object.__setattr__(self, "resource_budget", _budget(self.resource_budget, "resource_budget"))
        _timestamp(self.requested_at, "requested_at")
        requested = _timestamp(self.requested_at, "requested_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= requested:
            raise _error("ADMISSION_EXPIRY_INVALID", "expires_at must be after requested_at")
        if self.execution_instance_hash is None or self.resolved_run_identity is None:
            raise _error("ADMISSION_EXECUTION_BINDING_REQUIRED", "execution identity and artifact binding are required")
        _digest(self.execution_instance_hash, "execution_instance_hash")
        _text(self.resolved_run_identity, "resolved_run_identity")
        object.__setattr__(self, "resolved_node_identities", _string_map(self.resolved_node_identities, "resolved_node_identities", digest_values=False))
        object.__setattr__(self, "resolved_artifact_digests", _string_map(self.resolved_artifact_digests, "resolved_artifact_digests", digest_values=True))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": ADMISSION_SCHEMA_V1,
            "request_id": self.request_id,
            "compilation_record_ref": self.compilation_record_ref.to_dict(),
            "confirmation_ref": self.confirmation_ref,
            "confirmation_digest": self.confirmation_digest,
            "principal_ref": self.principal_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "contract_snapshot_refs": [ref.to_dict() for ref in self.contract_snapshot_refs],
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "effect": self.effect.value,
            "resource_budget": _plain(self.resource_budget),
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
            "execution_instance_hash": self.execution_instance_hash,
            "resolved_run_identity": self.resolved_run_identity,
            "resolved_node_identities": _plain(self.resolved_node_identities),
            "resolved_artifact_digests": _plain(self.resolved_artifact_digests),
        }

    @property
    def request_digest(self) -> str:
        return sha256_canonical(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "request_digest": self.request_digest}

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ExecutionAdmissionV1":
        value = _wire(
            value,
            {
                "schema_version", "request_id", "compilation_record_ref", "confirmation_ref", "confirmation_digest",
                "principal_ref", "session_ref", "project_ref", "contract_snapshot_refs", "catalog_snapshot_ref",
                "policy_snapshot_ref", "effect", "resource_budget", "requested_at", "expires_at",
                "execution_instance_hash", "resolved_run_identity", "resolved_node_identities",
                "resolved_artifact_digests", "request_digest",
            },
            "execution_admission",
        )
        if value["schema_version"] != ADMISSION_SCHEMA_V1:
            raise _error("ADMISSION_SCHEMA_INVALID", "admission schema_version is invalid")
        raw_ref = value["compilation_record_ref"]
        if type(raw_ref) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "compilation_record_ref must be a built-in dict")
        raw_budget = value["resource_budget"]
        if type(raw_budget) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "resource_budget must be a built-in dict")
        raw_nodes = value["resolved_node_identities"]
        raw_artifacts = value["resolved_artifact_digests"]
        if type(raw_nodes) is not dict or type(raw_artifacts) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "resolved identity maps must be built-in dicts")
        request = cls(
            request_id=value["request_id"],  # type: ignore[arg-type]
            compilation_record_ref=CompilationRecordReferenceV1.from_dict(raw_ref),
            confirmation_ref=value["confirmation_ref"],  # type: ignore[arg-type]
            confirmation_digest=value["confirmation_digest"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            session_ref=value["session_ref"],  # type: ignore[arg-type]
            project_ref=value["project_ref"],  # type: ignore[arg-type]
            contract_snapshot_refs=_wire_ref_tuple(value["contract_snapshot_refs"], "contract_snapshot_refs"),
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            effect=_parse_effect(value["effect"]),
            resource_budget=_budget(raw_budget, "resource_budget"),
            requested_at=value["requested_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
            execution_instance_hash=value["execution_instance_hash"],  # type: ignore[arg-type]
            resolved_run_identity=value["resolved_run_identity"],  # type: ignore[arg-type]
            resolved_node_identities=_string_map(raw_nodes, "resolved_node_identities", digest_values=False),
            resolved_artifact_digests=_string_map(raw_artifacts, "resolved_artifact_digests", digest_values=True),
        )
        if value["request_digest"] != request.request_digest:
            raise _error("ADMISSION_DIGEST_MISMATCH", "request_digest does not match request fields")
        return request


@dataclass(frozen=True)
class ExecutionAdmissionReceiptV1:
    receipt_id: str
    admission_request_digest: str
    compilation_record_ref: CompilationRecordReferenceV1
    confirmation_ref: str
    confirmation_digest: str
    principal_ref: str
    session_ref: str
    project_ref: str
    contract_snapshot_refs: tuple[ContractRefV1, ...]
    catalog_snapshot_ref: str
    policy_snapshot_ref: str
    effect: AdmissionEffectV1
    resource_budget: Mapping[str, int | float]
    issued_at: str
    expires_at: str
    execution_instance_hash: str
    resolved_run_identity: str
    resolved_node_identities: Mapping[str, str]
    resolved_artifact_digests: Mapping[str, str]
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.receipt_id, "receipt_id")
        _digest(self.admission_request_digest, "admission_request_digest")
        if type(self.compilation_record_ref) is not CompilationRecordReferenceV1:
            raise _error("ADMISSION_RECORD_REFERENCE_INVALID", "receipt compilation reference is invalid")
        _text(self.confirmation_ref, "confirmation_ref")
        _digest(self.confirmation_digest, "confirmation_digest")
        for name, value in (("principal_ref", self.principal_ref), ("session_ref", self.session_ref), ("project_ref", self.project_ref), ("catalog_snapshot_ref", self.catalog_snapshot_ref), ("policy_snapshot_ref", self.policy_snapshot_ref)):
            _text(value, name)
        object.__setattr__(self, "contract_snapshot_refs", _ref_tuple(self.contract_snapshot_refs, "contract_snapshot_refs"))
        if type(self.effect) is not AdmissionEffectV1:
            raise _error("ADMISSION_ENUM_INVALID", "effect is invalid")
        object.__setattr__(self, "resource_budget", _budget(self.resource_budget, "resource_budget"))
        issued = _timestamp(self.issued_at, "issued_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= issued:
            raise _error("ADMISSION_EXPIRY_INVALID", "expires_at must be after issued_at")
        _digest(self.execution_instance_hash, "execution_instance_hash")
        _text(self.resolved_run_identity, "resolved_run_identity")
        object.__setattr__(self, "resolved_node_identities", _string_map(self.resolved_node_identities, "resolved_node_identities", digest_values=False))
        object.__setattr__(self, "resolved_artifact_digests", _string_map(self.resolved_artifact_digests, "resolved_artifact_digests", digest_values=True))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": ADMISSION_RECEIPT_SCHEMA_V1,
            "receipt_id": self.receipt_id,
            "admission_request_digest": self.admission_request_digest,
            "compilation_record_ref": self.compilation_record_ref.to_dict(),
            "confirmation_ref": self.confirmation_ref,
            "confirmation_digest": self.confirmation_digest,
            "principal_ref": self.principal_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "contract_snapshot_refs": [ref.to_dict() for ref in self.contract_snapshot_refs],
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "effect": self.effect.value,
            "resource_budget": _plain(self.resource_budget),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "execution_instance_hash": self.execution_instance_hash,
            "resolved_run_identity": self.resolved_run_identity,
            "resolved_node_identities": _plain(self.resolved_node_identities),
            "resolved_artifact_digests": _plain(self.resolved_artifact_digests),
        }

    @property
    def receipt_digest(self) -> str:
        return sha256_canonical(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_digest": self.receipt_digest}

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ExecutionAdmissionReceiptV1":
        value = _wire(
            value,
            {
                "schema_version", "receipt_id", "admission_request_digest", "compilation_record_ref",
                "confirmation_ref", "confirmation_digest", "principal_ref", "session_ref", "project_ref",
                "contract_snapshot_refs", "catalog_snapshot_ref", "policy_snapshot_ref", "effect",
                "resource_budget", "issued_at", "expires_at", "execution_instance_hash",
                "resolved_run_identity", "resolved_node_identities", "resolved_artifact_digests", "receipt_digest",
            },
            "execution_admission_receipt",
        )
        if value["schema_version"] != ADMISSION_RECEIPT_SCHEMA_V1:
            raise _error("ADMISSION_SCHEMA_INVALID", "receipt schema_version is invalid")
        raw_ref = value["compilation_record_ref"]
        raw_budget = value["resource_budget"]
        raw_nodes = value["resolved_node_identities"]
        raw_artifacts = value["resolved_artifact_digests"]
        if type(raw_ref) is not dict or type(raw_budget) is not dict or type(raw_nodes) is not dict or type(raw_artifacts) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "receipt nested values must be built-in dicts")
        receipt = cls(
            receipt_id=value["receipt_id"],  # type: ignore[arg-type]
            admission_request_digest=value["admission_request_digest"],  # type: ignore[arg-type]
            compilation_record_ref=CompilationRecordReferenceV1.from_dict(raw_ref),
            confirmation_ref=value["confirmation_ref"],  # type: ignore[arg-type]
            confirmation_digest=value["confirmation_digest"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            session_ref=value["session_ref"],  # type: ignore[arg-type]
            project_ref=value["project_ref"],  # type: ignore[arg-type]
            contract_snapshot_refs=_wire_ref_tuple(value["contract_snapshot_refs"], "contract_snapshot_refs"),
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            effect=_parse_effect(value["effect"]),
            resource_budget=_budget(raw_budget, "resource_budget"),
            issued_at=value["issued_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
            execution_instance_hash=value["execution_instance_hash"],  # type: ignore[arg-type]
            resolved_run_identity=value["resolved_run_identity"],  # type: ignore[arg-type]
            resolved_node_identities=_string_map(raw_nodes, "resolved_node_identities", digest_values=False),
            resolved_artifact_digests=_string_map(raw_artifacts, "resolved_artifact_digests", digest_values=True),
        )
        if value["receipt_digest"] != receipt.receipt_digest:
            raise _error("ADMISSION_DIGEST_MISMATCH", "receipt_digest does not match receipt fields")
        return receipt


class ExecutionAdmissionGateV1:
    """Resolve records/confirmations and mint short-lived server receipts."""

    def __init__(
        self,
        record_store: CompilationRecordStoreV1,
        *,
        method_snapshot_ref: str | None = None,
        risk_snapshot_ref: str | None = None,
        policy_snapshot_ref: str | None = None,
        confirmation_store: ConfirmationBindingStoreV1 | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(record_store) is not CompilationRecordStoreV1:
            raise _error("SERVER_RECORD_STORE_REQUIRED", "admission gate requires a server record store")
        self.record_store = record_store
        self.method_snapshot_ref = method_snapshot_ref
        self.risk_snapshot_ref = risk_snapshot_ref
        self.policy_snapshot_ref = policy_snapshot_ref
        if confirmation_store is not None and type(confirmation_store) is not ConfirmationBindingStoreV1:
            raise _error(
                "ADMISSION_CONFIRMATION_STORE_REQUIRED",
                "confirmation_store must be a server confirmation store",
            )
        self.confirmation_store = confirmation_store if confirmation_store is not None else ConfirmationBindingStoreV1()
        self.clock = clock
        self._issuer_token = object()
        self._receipts: dict[str, ExecutionAdmissionReceiptV1] = {}

    def admit(self, request: ExecutionAdmissionV1, confirmation: ConfirmationBindingV1, *, at: str | None = None) -> ExecutionAdmissionReceiptV1:
        if type(request) is not ExecutionAdmissionV1:
            raise _error("ADMISSION_REQUEST_REQUIRED", "runtime requires an ExecutionAdmissionV1 request")
        if type(confirmation) is not ConfirmationBindingV1:
            raise _error("CONFIRMATION_REQUIRED", "runtime requires a ConfirmationBindingV1")
        self.confirmation_store.require(confirmation)
        if not all(type(value) is str and value for value in (self.method_snapshot_ref, self.risk_snapshot_ref, self.policy_snapshot_ref)):
            raise _error("ADMISSION_CURRENT_SNAPSHOT_REQUIRED", "runtime requires independent current method/risk/policy snapshots")
        record, server_ref = self.record_store.resolve_client_reference(request.compilation_record_ref)
        if confirmation.confirmation_id != request.confirmation_ref or confirmation.confirmation_digest != request.confirmation_digest:
            raise _error("ADMISSION_CONFIRMATION_MISMATCH", "confirmation reference or digest mismatches request")
        if confirmation.compilation_record_ref != request.compilation_record_ref:
            raise _error("ADMISSION_SCOPE_MISMATCH", "confirmation is bound to another compilation record")
        if (request.principal_ref, request.session_ref, request.project_ref) != (record.principal_ref, record.session_ref, record.project_ref):
            raise _error("ADMISSION_SCOPE_MISMATCH", "principal/session/project scope mismatches record")
        if request.policy_snapshot_ref != record.policy_snapshot_ref:
            raise _error("ADMISSION_POLICY_CHANGED", "policy snapshot changed after compilation")
        if request.catalog_snapshot_ref != record.catalog_snapshot_ref:
            raise _error("ADMISSION_CATALOG_CHANGED", "catalog snapshot changed after compilation")
        if request.contract_snapshot_refs != record.contract_snapshot_refs:
            raise _error("ADMISSION_CONTRACT_CHANGED", "contract snapshot changed after compilation")
        if request.effect.value != record.compiled_workflow.effect.value:
            raise _error("ADMISSION_EFFECT_MISMATCH", "requested effect mismatches compiled effect")
        if not _budget_within(request.resource_budget, record.compiled_workflow.resource_budget):
            raise _error("ADMISSION_BUDGET_EXCEEDED", "requested resource budget exceeds compiled budget")
        if confirmation.method_snapshot_ref != self.method_snapshot_ref or confirmation.risk_snapshot_ref != self.risk_snapshot_ref or confirmation.policy_snapshot_ref != self.policy_snapshot_ref:
            raise _error("CONFIRMATION_SNAPSHOT_CHANGED", "current server method/risk/policy snapshot changed")
        if confirmation.policy_snapshot_ref != request.policy_snapshot_ref:
            raise _error("CONFIRMATION_POLICY_CHANGED", "confirmation policy snapshot differs from request")
        requested = _timestamp(request.requested_at, "requested_at")
        confirmed = _timestamp(confirmation.confirmed_at, "confirmed_at")
        expires = _timestamp(request.expires_at, "expires_at")
        record_expires = _timestamp(record.expires_at, "record.expires_at")
        current = _now(self.clock, at)
        if requested < confirmed:
            raise _error("ADMISSION_PRE_CONFIRMATION", "requested_at precedes confirmation time")
        if not confirmation.is_valid(
            actor_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            semantic_plan_hash=record.semantic_plan_hash,
            method_snapshot_ref=self.method_snapshot_ref,
            risk_snapshot_ref=self.risk_snapshot_ref,
            policy_snapshot_ref=self.policy_snapshot_ref,
            at=current.isoformat(),
        ):
            raise _error("CONFIRMATION_INVALID", "confirmation is expired or its scope changed")
        if current < requested or current >= expires or current >= record_expires or expires > record_expires:
            raise _error("ADMISSION_EXPIRED", "admission or compilation record is expired or not yet valid")
        try:
            expected_execution_hash = record.compiled_workflow.execution_instance_hash(
                dict(request.resolved_artifact_digests),
                resolved_run_identity=request.resolved_run_identity,
                resolved_node_identities=dict(request.resolved_node_identities),
            )
        except (AttributeError, CanonicalJSONError, ContractError, PlanningContractError, RecursionError, TypeError, ValueError) as exc:
            raise _error("ADMISSION_EXECUTION_BINDING_INVALID", "resolved execution identity is invalid") from exc
        if request.execution_instance_hash != expected_execution_hash:
            raise _error("ADMISSION_EXECUTION_MISMATCH", "execution instance hash does not match resolved artifacts")
        receipt = ExecutionAdmissionReceiptV1(
            receipt_id=f"admission-receipt:{request.request_id}",
            admission_request_digest=request.request_digest,
            compilation_record_ref=server_ref.as_untrusted_reference(),
            confirmation_ref=confirmation.confirmation_id,
            confirmation_digest=confirmation.confirmation_digest,
            principal_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            contract_snapshot_refs=request.contract_snapshot_refs,
            catalog_snapshot_ref=request.catalog_snapshot_ref,
            policy_snapshot_ref=request.policy_snapshot_ref,
            effect=request.effect,
            resource_budget=request.resource_budget,
            issued_at=current.isoformat(),
            expires_at=request.expires_at,
            execution_instance_hash=request.execution_instance_hash,
            resolved_run_identity=request.resolved_run_identity,
            resolved_node_identities=request.resolved_node_identities,
            resolved_artifact_digests=request.resolved_artifact_digests,
            _issuer_token=self._issuer_token,
        )
        self._receipts[receipt.receipt_digest] = receipt
        _ISSUED_RECEIPTS[(id(self._issuer_token), receipt.receipt_digest)] = receipt
        return receipt

    def require(self, receipt: ExecutionAdmissionReceiptV1, *, at: str | None = None) -> None:
        if type(receipt) is not ExecutionAdmissionReceiptV1:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "runtime requires an execution admission receipt")
        if receipt._issuer_token is not self._issuer_token or self._receipts.get(receipt.receipt_digest) is not receipt:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "receipt was not issued by the server admission gate")
        current = _now(self.clock, at)
        issued = _timestamp(receipt.issued_at, "issued_at")
        expires = _timestamp(receipt.expires_at, "expires_at")
        if current < issued:
            raise _error("ADMISSION_NOT_YET_VALID", "execution admission receipt is not yet valid")
        if current >= expires:
            raise _error("ADMISSION_EXPIRED", "execution admission receipt is expired")


def require_execution_admission_receipt(value: object, *, gate: ExecutionAdmissionGateV1 | None = None, at: str | None = None) -> ExecutionAdmissionReceiptV1:
    if type(value) is not ExecutionAdmissionReceiptV1:
        raise _error("ADMISSION_RECEIPT_REQUIRED", "runtime requires an execution admission receipt")
    if gate is not None:
        gate.require(value, at=at)
    else:
        token = value._issuer_token
        if token is None or _ISSUED_RECEIPTS.get((id(token), value.receipt_digest)) is not value:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "receipt was not issued by a server admission gate")
        current = _now(None, at)
        if current < _timestamp(value.issued_at, "issued_at"):
            raise _error("ADMISSION_NOT_YET_VALID", "execution admission receipt is not yet valid")
        if current >= _timestamp(value.expires_at, "expires_at"):
            raise _error("ADMISSION_EXPIRED", "execution admission receipt is expired")
    return value


__all__ = [
    "ADMISSION_RECEIPT_SCHEMA_V1",
    "ADMISSION_SCHEMA_V1",
    "AdmissionContractError",
    "AdmissionEffectV1",
    "ExecutionAdmissionGateV1",
    "ExecutionAdmissionReceiptV1",
    "ExecutionAdmissionV1",
    "require_execution_admission_receipt",
]
