"""Server-side execution-admission request and receipt contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, thaw_json
from workbench.contracts.agent.planning import (
    CompilationRecordReferenceV1,
    CompilationRecordStoreV1,
    ConfirmationBindingV1,
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


def _parse_effect(value: object) -> AdmissionEffectV1:
    if type(value) is not str:
        raise _error("ADMISSION_ENUM_INVALID", "effect is invalid")
    try:
        return AdmissionEffectV1(value)
    except ValueError as exc:
        raise _error("ADMISSION_ENUM_INVALID", "effect is invalid") from exc


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("ADMISSION_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("ADMISSION_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: object, name: str):
    from datetime import UTC, datetime

    if type(value) is not str or not value or value != value.strip():
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error("ADMISSION_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _contract_ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise _error("ADMISSION_CONTRACT_REF_INVALID", f"{name} is invalid")
    return value


def _ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error("ADMISSION_ARRAY_INVALID", f"{name} must be an array")
    refs = tuple(_contract_ref(item, f"{name}[]") for item in value)
    if len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}) != len(refs):
        raise _error("ADMISSION_DUPLICATE_ID", f"{name} contains duplicate identities")
    return refs


def _wire_ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if type(value) is not list:
        raise _error("ADMISSION_ARRAY_INVALID", f"{name} must be a built-in list")
    refs = []
    for item in value:
        if type(item) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} entries must be built-in dicts")
        from workbench.contracts.common.contract_ref import ContractRefV1 as Ref

        try:
            refs.append(Ref.from_dict(item))
        except (ContractError, ValueError) as exc:
            raise _error("ADMISSION_CONTRACT_REF_INVALID", f"{name} contains an invalid ref") from exc
    return _ref_tuple(refs, name)


def _budget(value: object, name: str) -> dict[str, int | float]:
    if type(value) is not dict:
        raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    result: dict[str, int | float] = {}
    for key, item in value.items():
        _text(key, f"{name} key")
        if type(item) is int:
            if not -_MAX_JSON_SAFE_INTEGER <= item <= _MAX_JSON_SAFE_INTEGER or item < 0:
                raise _error("ADMISSION_BUDGET_INVALID", f"{name} contains an invalid integer")
        elif type(item) is float:
            if not math.isfinite(item) or item < 0:
                raise _error("ADMISSION_BUDGET_INVALID", f"{name} contains an invalid number")
        else:
            raise _error("ADMISSION_BUDGET_INVALID", f"{name} values must be finite numbers")
        result[key] = item
    if not result:
        raise _error("ADMISSION_BUDGET_INVALID", f"{name} must not be empty")
    return result


def _wire(value: object, required: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _error("ADMISSION_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    if any(type(key) is not str for key in value) or set(value) != required:
        raise _error("ADMISSION_SCHEMA_INVALID", f"{name} fields are not exact")
    return value


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
    resource_budget: dict[str, int | float]
    requested_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        if type(self.compilation_record_ref) is not CompilationRecordReferenceV1:
            raise _error(
                "SERVER_RECORD_REFERENCE_REQUIRED",
                "admission request accepts only an untrusted record reference; runtime needs server resolution",
            )
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
        requested = _timestamp(self.requested_at, "requested_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= requested:
            raise _error("ADMISSION_EXPIRY_INVALID", "expires_at must be after requested_at")

    @property
    def request_digest(self) -> str:
        return sha256_canonical(self._payload())

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
            "resource_budget": dict(self.resource_budget),
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "request_digest": self.request_digest}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ExecutionAdmissionV1":
        required = {
            "schema_version",
            "request_id",
            "compilation_record_ref",
            "confirmation_ref",
            "confirmation_digest",
            "principal_ref",
            "session_ref",
            "project_ref",
            "contract_snapshot_refs",
            "catalog_snapshot_ref",
            "policy_snapshot_ref",
            "effect",
            "resource_budget",
            "requested_at",
            "expires_at",
            "request_digest",
        }
        value = _wire(value, required, "execution_admission")
        if value["schema_version"] != ADMISSION_SCHEMA_V1:
            raise _error("ADMISSION_SCHEMA_INVALID", "admission schema_version is invalid")
        raw_ref = value["compilation_record_ref"]
        if type(raw_ref) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "compilation_record_ref must be a built-in dict")
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
            resource_budget=_budget(value["resource_budget"], "resource_budget"),  # type: ignore[arg-type]
            requested_at=value["requested_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
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
    resource_budget: dict[str, int | float]
    issued_at: str
    expires_at: str
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.receipt_id, "receipt_id")
        _digest(self.admission_request_digest, "admission_request_digest")
        if type(self.compilation_record_ref) is not CompilationRecordReferenceV1:
            raise _error("ADMISSION_RECORD_REFERENCE_INVALID", "receipt compilation reference is invalid")
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
        issued = _timestamp(self.issued_at, "issued_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= issued:
            raise _error("ADMISSION_EXPIRY_INVALID", "expires_at must be after issued_at")

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
            "resource_budget": dict(self.resource_budget),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def receipt_digest(self) -> str:
        return sha256_canonical(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ExecutionAdmissionReceiptV1":
        required = {
            "schema_version",
            "receipt_id",
            "admission_request_digest",
            "compilation_record_ref",
            "confirmation_ref",
            "confirmation_digest",
            "principal_ref",
            "session_ref",
            "project_ref",
            "contract_snapshot_refs",
            "catalog_snapshot_ref",
            "policy_snapshot_ref",
            "effect",
            "resource_budget",
            "issued_at",
            "expires_at",
            "receipt_digest",
        }
        value = _wire(value, required, "execution_admission_receipt")
        if value["schema_version"] != ADMISSION_RECEIPT_SCHEMA_V1:
            raise _error("ADMISSION_SCHEMA_INVALID", "receipt schema_version is invalid")
        raw_ref = value["compilation_record_ref"]
        if type(raw_ref) is not dict:
            raise _error("ADMISSION_NESTED_DICT_REQUIRED", "receipt compilation reference must be a built-in dict")
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
            resource_budget=_budget(value["resource_budget"], "resource_budget"),  # type: ignore[arg-type]
            issued_at=value["issued_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
        )
        if value["receipt_digest"] != receipt.receipt_digest:
            raise _error("ADMISSION_DIGEST_MISMATCH", "receipt_digest does not match receipt fields")
        return receipt


def _budget_within(requested: dict[str, int | float], allowed: Mapping[str, Any]) -> bool:
    for key, value in requested.items():
        maximum = allowed.get(key)
        if type(maximum) not in {int, float} or value > maximum:
            return False
    return True


class ExecutionAdmissionGateV1:
    """Resolve records and confirmations, then mint short-lived receipts."""

    def __init__(self, record_store: CompilationRecordStoreV1) -> None:
        if type(record_store) is not CompilationRecordStoreV1:
            raise _error("SERVER_RECORD_STORE_REQUIRED", "admission gate requires a server record store")
        self.record_store = record_store
        self._issuer_token = object()
        self._receipts: dict[str, ExecutionAdmissionReceiptV1] = {}

    def admit(
        self,
        request: ExecutionAdmissionV1,
        confirmation: ConfirmationBindingV1,
        *,
        at: str | None = None,
    ) -> ExecutionAdmissionReceiptV1:
        if type(request) is not ExecutionAdmissionV1:
            raise _error("ADMISSION_REQUEST_REQUIRED", "runtime requires an ExecutionAdmissionV1 request")
        if type(confirmation) is not ConfirmationBindingV1:
            raise _error("CONFIRMATION_REQUIRED", "runtime requires a ConfirmationBindingV1")
        record, server_ref = self.record_store.resolve_client_reference(request.compilation_record_ref)
        if confirmation.confirmation_id != request.confirmation_ref or confirmation.confirmation_digest != request.confirmation_digest:
            raise _error("ADMISSION_CONFIRMATION_MISMATCH", "confirmation reference or digest mismatches request")
        if confirmation.compilation_record_ref != request.compilation_record_ref:
            raise _error("ADMISSION_SCOPE_MISMATCH", "confirmation is bound to another compilation record")
        if (request.principal_ref, request.session_ref, request.project_ref) != (
            record.principal_ref,
            record.session_ref,
            record.project_ref,
        ):
            raise _error("ADMISSION_SCOPE_MISMATCH", "principal/session/project scope mismatches record")
        if request.policy_snapshot_ref != record.policy_snapshot_ref:
            raise _error("ADMISSION_POLICY_CHANGED", "policy snapshot changed after compilation")
        if request.catalog_snapshot_ref != record.catalog_snapshot_ref:
            raise _error("ADMISSION_CATALOG_CHANGED", "catalog snapshot changed after compilation")
        if request.contract_snapshot_refs != record.contract_snapshot_refs:
            raise _error("ADMISSION_CONTRACT_CHANGED", "contract snapshot changed after compilation")
        if request.effect.value != record.compiled_workflow.effect:
            raise _error("ADMISSION_EFFECT_MISMATCH", "requested effect mismatches compiled effect")
        if not _budget_within(request.resource_budget, record.compiled_workflow.resource_budget):
            raise _error("ADMISSION_BUDGET_EXCEEDED", "requested resource budget exceeds compiled budget")
        requested = _timestamp(request.requested_at, "requested_at")
        expires = _timestamp(request.expires_at, "expires_at")
        record_expires = _timestamp(record.expires_at, "record.expires_at")
        check_at = _timestamp(at or request.requested_at, "at")
        if check_at >= expires or check_at >= record_expires or expires > record_expires:
            raise _error("ADMISSION_EXPIRED", "admission or compilation record is expired")
        if not confirmation.is_valid(
            actor_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            semantic_plan_hash=record.semantic_plan_hash,
            method_snapshot_ref=confirmation.method_snapshot_ref,
            risk_snapshot_ref=confirmation.risk_snapshot_ref,
            policy_snapshot_ref=request.policy_snapshot_ref,
            at=(at or request.requested_at),
        ):
            raise _error("CONFIRMATION_INVALID", "confirmation is expired or its method/risk/policy scope changed")
        if requested > check_at or expires <= requested:
            raise _error("ADMISSION_TIMESTAMP_INVALID", "admission timestamps are inconsistent")

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
            issued_at=at or request.requested_at,
            expires_at=request.expires_at,
            _issuer_token=self._issuer_token,
        )
        self._receipts[receipt.receipt_digest] = receipt
        _ISSUED_RECEIPTS[(id(self._issuer_token), receipt.receipt_digest)] = receipt
        return receipt

    def require(self, receipt: ExecutionAdmissionReceiptV1, *, at: str | None = None) -> None:
        if type(receipt) is not ExecutionAdmissionReceiptV1:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "runtime requires an execution admission receipt")
        if receipt._issuer_token is not self._issuer_token:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "receipt was not issued by the server admission gate")
        if self._receipts.get(receipt.receipt_digest) is not receipt:
            raise _error("ADMISSION_RECEIPT_INVALID", "receipt is not an immutable gate-issued receipt")
        if at is not None and _timestamp(at, "at") >= _timestamp(receipt.expires_at, "expires_at"):
            raise _error("ADMISSION_EXPIRED", "execution admission receipt is expired")


def require_execution_admission_receipt(
    value: object,
    *,
    gate: ExecutionAdmissionGateV1 | None = None,
    at: str | None = None,
) -> ExecutionAdmissionReceiptV1:
    """The contract-level choke point used by future runtime cutover."""

    if type(value) is not ExecutionAdmissionReceiptV1:
        raise _error("ADMISSION_RECEIPT_REQUIRED", "runtime requires an execution admission receipt")
    if gate is not None:
        gate.require(value, at=at)
    else:
        token = value._issuer_token
        if token is None or _ISSUED_RECEIPTS.get((id(token), value.receipt_digest)) is not value:
            raise _error("ADMISSION_RECEIPT_REQUIRED", "receipt was not issued by a server admission gate")
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
