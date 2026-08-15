"""Strict, immutable workflow state and artifact-binding contracts.

This module is deliberately a wire contract only.  It does not read the
active workflow head, resolve artifacts, or execute a migration.  A persisted
state from an unknown/legacy schema therefore remains explicitly
``migration_required`` until a later, server-owned migration line supplies a
safe migrator.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import wraps
from enum import Enum
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json
from workbench.contracts.evidence.envelope import NotApplicableV1


WORKFLOW_STATE_SCHEMA_V2 = "workflow-execution-state.v2"
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REQUIRED_DEVELOPMENT_STATE_FIELDS = {
    "schema_version",
    "workflow_id",
    "run_id",
    "status",
    "semantic_plan_hash",
    "execution_instance_hash",
    "contract_snapshot_ref",
    "catalog_snapshot_ref",
    "policy_snapshot_ref",
    "output_bindings",
    "model_branches",
}
_VALIDATION_RECEIPT_ISSUANCES: dict[tuple[int, str], object] = {}


class WorkflowStateContractError(ContractError):
    """A workflow wire-boundary failure with a stable reason code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class WorkflowExecutionStatusV2(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class PortDirectionV1(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class PortValidationStatusV1(str, Enum):
    VALIDATED = "validated"
    UNVALIDATED = "unvalidated"
    NOT_APPLICABLE = "not_applicable"


def _error(code: str, message: str) -> WorkflowStateContractError:
    return WorkflowStateContractError(code, message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("WORKFLOW_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("WORKFLOW_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _contract_ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not dict:
        raise _error("WORKFLOW_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    try:
        return ContractRefV1.from_dict(value)
    except (ContractError, ValueError) as exc:
        raise _error("WORKFLOW_CONTRACT_REF_INVALID", f"{name} is invalid") from exc


def _enum(value: object, enum_type: type[Enum], name: str) -> Any:
    if type(value) is not str:
        raise _error("WORKFLOW_ENUM_INVALID", f"{name} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _error("WORKFLOW_ENUM_INVALID", f"{name} enum is invalid") from exc


def _validate_json(value: object, name: str, active: set[int] | None = None) -> None:
    """Validate the strict JSON subset before canonicalization/freezing."""

    if value is None or type(value) in {str, bool}:
        return
    if type(value) is int:
        if not -_MAX_JSON_SAFE_INTEGER <= value <= _MAX_JSON_SAFE_INTEGER:
            raise _error("WORKFLOW_JSON_INVALID", f"{name} contains a nonportable integer")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise _error("WORKFLOW_JSON_INVALID", f"{name} contains a non-finite number")
        return
    if type(value) not in {dict, list, tuple}:
        raise _error("WORKFLOW_JSON_INVALID", f"{name} contains an unsupported value")
    active_ids = active if active is not None else set()
    value_id = id(value)
    if value_id in active_ids:
        raise _error("WORKFLOW_JSON_INVALID", f"{name} must be acyclic JSON")
    active_ids.add(value_id)
    try:
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise _error("WORKFLOW_JSON_INVALID", f"{name} keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _validate_json(child, f"{name}[]", active_ids)
    finally:
        active_ids.remove(value_id)


def _frozen_json(value: object, name: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise _error("WORKFLOW_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    _validate_json(value, name)
    try:
        canonical_json_v1(value)
        frozen = freeze_json(value, name)
    except (
        AttributeError,
        CanonicalJSONError,
        ContractError,
        RecursionError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise _error("WORKFLOW_JSON_INVALID", f"{name} must be canonical JSON") from exc
    if not isinstance(frozen, Mapping):  # pragma: no cover - defensive invariant
        raise _error("WORKFLOW_JSON_INVALID", f"{name} must be an object")
    return frozen


def _wire_list(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise _error("WORKFLOW_ARRAY_INVALID", f"{name} must be a built-in list")
    return value


def _wire_boundary(function):
    @wraps(function)
    def wrapped(cls, value):
        try:
            return function(cls, value)
        except WorkflowStateContractError:
            raise
        except (
            AttributeError,
            CanonicalJSONError,
            ContractError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise _error("WORKFLOW_WIRE_INVALID", "workflow wire value is invalid") from exc

    return wrapped


@dataclass(frozen=True)
class PortValidationReceiptV1:
    """Content-bound proof that one artifact was checked against one schema."""

    receipt_ref: str
    validator_ref: ContractRefV1
    artifact_digest: str
    schema_ref: ContractRefV1
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.receipt_ref, "receipt_ref")
        if type(self.validator_ref) is not ContractRefV1:
            raise _error("WORKFLOW_CONTRACT_REF_INVALID", "validator_ref is invalid")
        _digest(self.artifact_digest, "artifact_digest")
        if type(self.schema_ref) is not ContractRefV1:
            raise _error("WORKFLOW_CONTRACT_REF_INVALID", "schema_ref is invalid")

    @property
    def validation_digest(self) -> str:
        return sha256_canonical(
            {
                "receipt_ref": self.receipt_ref,
                "validator_ref": self.validator_ref.to_dict(),
                "artifact_digest": self.artifact_digest,
                "schema_ref": self.schema_ref.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "validator_ref": self.validator_ref.to_dict(),
            "artifact_digest": self.artifact_digest,
            "schema_ref": self.schema_ref.to_dict(),
            "validation_digest": self.validation_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "PortValidationReceiptV1":
        if type(value) is not dict:
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "validation_receipt must be a built-in dict")
        required = {
            "receipt_ref",
            "validator_ref",
            "artifact_digest",
            "schema_ref",
            "validation_digest",
        }
        if set(value) != required or any(type(key) is not str for key in value):
            raise _error("WORKFLOW_SCHEMA_INVALID", "validation_receipt fields are not exact")
        receipt = cls(
            receipt_ref=value["receipt_ref"],  # type: ignore[arg-type]
            validator_ref=_contract_ref(value["validator_ref"], "validator_ref"),
            artifact_digest=value["artifact_digest"],  # type: ignore[arg-type]
            schema_ref=_contract_ref(value["schema_ref"], "schema_ref"),
        )
        if value["validation_digest"] != receipt.validation_digest:
            raise _error("WORKFLOW_RECEIPT_DIGEST_MISMATCH", "validation receipt digest does not match")
        return receipt


@dataclass(frozen=True)
class PortBindingV1:
    """An immutable artifact binding; output bindings require validation proof."""

    port_name: str
    direction: PortDirectionV1
    artifact_ref: str
    artifact_digest: str
    schema_ref: ContractRefV1
    validation_status: PortValidationStatusV1
    validation_receipt: PortValidationReceiptV1 | NotApplicableV1

    def __post_init__(self) -> None:
        _text(self.port_name, "port_name")
        if type(self.direction) is not PortDirectionV1:
            raise _error("WORKFLOW_ENUM_INVALID", "direction is invalid")
        _text(self.artifact_ref, "artifact_ref")
        _digest(self.artifact_digest, "artifact_digest")
        if type(self.schema_ref) is not ContractRefV1:
            raise _error("WORKFLOW_CONTRACT_REF_INVALID", "schema_ref is invalid")
        if type(self.validation_status) is not PortValidationStatusV1:
            raise _error("WORKFLOW_ENUM_INVALID", "validation_status is invalid")
        if type(self.validation_receipt) is PortValidationReceiptV1:
            if self.validation_receipt.artifact_digest != self.artifact_digest:
                raise _error("WORKFLOW_RECEIPT_SCOPE_MISMATCH", "validation receipt artifact scope mismatches")
            if self.validation_receipt.schema_ref != self.schema_ref:
                raise _error("WORKFLOW_RECEIPT_SCOPE_MISMATCH", "validation receipt schema scope mismatches")
            if not ValidationReceiptStoreV1.is_server_issued(self.validation_receipt):
                raise _error(
                    "WORKFLOW_VALIDATION_AUTHORITY_REQUIRED",
                    "validated binding requires a receipt issued by a server validation store",
                )
        elif type(self.validation_receipt) is not NotApplicableV1:
            raise _error("WORKFLOW_RECEIPT_INVALID", "validation_receipt is invalid")

        if self.direction is PortDirectionV1.OUTPUT:
            if self.validation_status is not PortValidationStatusV1.VALIDATED:
                raise _error("WORKFLOW_OUTPUT_UNVALIDATED", "output binding must be validated")
            if type(self.validation_receipt) is not PortValidationReceiptV1:
                raise _error("WORKFLOW_OUTPUT_RECEIPT_REQUIRED", "output binding requires a validation receipt")
        elif self.validation_status is PortValidationStatusV1.VALIDATED and type(
            self.validation_receipt
        ) is not PortValidationReceiptV1:
            raise _error("WORKFLOW_OUTPUT_RECEIPT_REQUIRED", "validated binding requires a validation receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "port_name": self.port_name,
            "direction": self.direction.value,
            "artifact_ref": self.artifact_ref,
            "artifact_digest": self.artifact_digest,
            "schema_ref": self.schema_ref.to_dict(),
            "validation_status": self.validation_status.value,
            "validation_receipt": self.validation_receipt.to_dict(),
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "PortBindingV1":
        if type(value) is not dict:
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "port binding must be a built-in dict")
        required = {
            "port_name",
            "direction",
            "artifact_ref",
            "artifact_digest",
            "schema_ref",
            "validation_status",
            "validation_receipt",
        }
        if set(value) != required or any(type(key) is not str for key in value):
            raise _error("WORKFLOW_SCHEMA_INVALID", "port binding fields are not exact")
        raw_receipt = value["validation_receipt"]
        if type(raw_receipt) is not dict:
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "validation_receipt must be a built-in dict")
        receipt: PortValidationReceiptV1 | NotApplicableV1
        if raw_receipt.get("status") == "not_applicable":
            receipt = NotApplicableV1.from_dict(raw_receipt)
        else:
            receipt = PortValidationReceiptV1.from_dict(raw_receipt)
        return cls(
            port_name=value["port_name"],  # type: ignore[arg-type]
            direction=_enum(value["direction"], PortDirectionV1, "direction"),
            artifact_ref=value["artifact_ref"],  # type: ignore[arg-type]
            artifact_digest=value["artifact_digest"],  # type: ignore[arg-type]
            schema_ref=_contract_ref(value["schema_ref"], "schema_ref"),
            validation_status=_enum(value["validation_status"], PortValidationStatusV1, "validation_status"),
            validation_receipt=receipt,
        )


class ValidationReceiptStoreV1:
    """Server-owned issuance and verification seam for validation receipts."""

    def __init__(self) -> None:
        self._issuer_token = object()
        self._receipts: dict[str, PortValidationReceiptV1] = {}

    def issue(self, receipt: PortValidationReceiptV1) -> PortValidationReceiptV1:
        if type(receipt) is not PortValidationReceiptV1:
            raise _error("WORKFLOW_RECEIPT_REQUIRED", "validator store accepts a typed receipt")
        if receipt._issuer_token is not None and receipt._issuer_token is not self._issuer_token:
            raise _error("WORKFLOW_RECEIPT_ISSUER_MISMATCH", "receipt belongs to another validator store")
        object.__setattr__(receipt, "_issuer_token", self._issuer_token)
        self._receipts[receipt.validation_digest] = receipt
        _VALIDATION_RECEIPT_ISSUANCES[(id(self._issuer_token), receipt.validation_digest)] = receipt
        return receipt

    @classmethod
    def is_server_issued(cls, receipt: object) -> bool:
        return (
            type(receipt) is PortValidationReceiptV1
            and receipt._issuer_token is not None
            and _VALIDATION_RECEIPT_ISSUANCES.get((id(receipt._issuer_token), receipt.validation_digest)) is receipt
        )

    def require(self, receipt: PortValidationReceiptV1) -> PortValidationReceiptV1:
        if type(receipt) is not PortValidationReceiptV1:
            raise _error(
                "WORKFLOW_VALIDATION_AUTHORITY_REQUIRED",
                "a server-issued validation receipt is required",
            )
        if receipt._issuer_token is not self._issuer_token:
            raise _error(
                "WORKFLOW_VALIDATION_AUTHORITY_REQUIRED",
                "validation receipt was not issued by the server validator issuer authority",
            )
        if self._receipts.get(receipt.validation_digest) is not receipt or not self.is_server_issued(receipt):
            raise _error(
                "WORKFLOW_VALIDATION_RECEIPT_INVALID",
                "validation receipt is not current store state",
            )
        return receipt


@dataclass(frozen=True)
class ModelBranchRefV1:
    """Opaque model-branch identity used by resume, never a copied model payload."""

    branch_id: str
    run_ref: str
    artifact_refs: tuple[str, ...]
    model_family: str
    schema_ref: ContractRefV1

    def __post_init__(self) -> None:
        _text(self.branch_id, "branch_id")
        _text(self.run_ref, "run_ref")
        if not isinstance(self.artifact_refs, (tuple, list)):
            raise _error("WORKFLOW_ARRAY_INVALID", "artifact_refs must be an array")
        refs = tuple(_text(ref, "artifact_refs[]") for ref in self.artifact_refs)
        if len(set(refs)) != len(refs):
            raise _error("WORKFLOW_DUPLICATE_ID", "artifact_refs must be unique")
        object.__setattr__(self, "artifact_refs", refs)
        _text(self.model_family, "model_family")
        if type(self.schema_ref) is not ContractRefV1:
            raise _error("WORKFLOW_CONTRACT_REF_INVALID", "schema_ref is invalid")

    @property
    def branch_digest(self) -> str:
        return sha256_canonical(
            {
                "branch_id": self.branch_id,
                "run_ref": self.run_ref,
                "artifact_refs": list(self.artifact_refs),
                "model_family": self.model_family,
                "schema_ref": self.schema_ref.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "run_ref": self.run_ref,
            "artifact_refs": list(self.artifact_refs),
            "model_family": self.model_family,
            "schema_ref": self.schema_ref.to_dict(),
            "branch_digest": self.branch_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ModelBranchRefV1":
        if type(value) is not dict:
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "model branch must be a built-in dict")
        required = {"branch_id", "run_ref", "artifact_refs", "model_family", "schema_ref", "branch_digest"}
        if set(value) != required or any(type(key) is not str for key in value):
            raise _error("WORKFLOW_SCHEMA_INVALID", "model branch fields are not exact")
        raw_refs = _wire_list(value["artifact_refs"], "artifact_refs")
        branch = cls(
            branch_id=value["branch_id"],  # type: ignore[arg-type]
            run_ref=value["run_ref"],  # type: ignore[arg-type]
            artifact_refs=tuple(raw_refs),  # type: ignore[arg-type]
            model_family=value["model_family"],  # type: ignore[arg-type]
            schema_ref=_contract_ref(value["schema_ref"], "schema_ref"),
        )
        if value["branch_digest"] != branch.branch_digest:
            raise _error("WORKFLOW_DIGEST_MISMATCH", "model branch digest does not match")
        return branch


@dataclass(frozen=True)
class WorkflowMigrationRequiredV1:
    source_schema_version: str
    target_schema_version: str = WORKFLOW_STATE_SCHEMA_V2
    status: str = "migration_required"
    reason_code: str = "MIGRATION_REQUIRED"

    def __post_init__(self) -> None:
        _text(self.source_schema_version, "source_schema_version")
        if self.target_schema_version != WORKFLOW_STATE_SCHEMA_V2:
            raise _error("WORKFLOW_SCHEMA_INVALID", "target schema version is invalid")
        if self.status != "migration_required" or self.reason_code != "MIGRATION_REQUIRED":
            raise _error("WORKFLOW_SCHEMA_INVALID", "migration result is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "source_schema_version": self.source_schema_version,
            "target_schema_version": self.target_schema_version,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class WorkflowExecutionStateV2:
    schema_version: str
    workflow_id: str
    run_id: str
    status: WorkflowExecutionStatusV2
    semantic_plan_hash: str
    execution_instance_hash: str | NotApplicableV1
    contract_snapshot_ref: str
    catalog_snapshot_ref: str
    policy_snapshot_ref: str
    output_bindings: tuple[PortBindingV1, ...]
    model_branches: tuple[ModelBranchRefV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != WORKFLOW_STATE_SCHEMA_V2:
            raise _error("MIGRATION_REQUIRED", "workflow state requires an explicit safe migration")
        _text(self.workflow_id, "workflow_id")
        _text(self.run_id, "run_id")
        if type(self.status) is not WorkflowExecutionStatusV2:
            raise _error("WORKFLOW_ENUM_INVALID", "status is invalid")
        _digest(self.semantic_plan_hash, "semantic_plan_hash")
        if type(self.execution_instance_hash) is str:
            _digest(self.execution_instance_hash, "execution_instance_hash")
        elif type(self.execution_instance_hash) is not NotApplicableV1:
            raise _error("WORKFLOW_DIGEST_INVALID", "execution_instance_hash is invalid")
        for name, value in (
            ("contract_snapshot_ref", self.contract_snapshot_ref),
            ("catalog_snapshot_ref", self.catalog_snapshot_ref),
            ("policy_snapshot_ref", self.policy_snapshot_ref),
        ):
            _text(value, name)
        if not isinstance(self.output_bindings, (tuple, list)):
            raise _error("WORKFLOW_ARRAY_INVALID", "output_bindings must be an array")
        bindings = tuple(self.output_bindings)
        if any(type(binding) is not PortBindingV1 for binding in bindings):
            raise _error("WORKFLOW_BINDING_INVALID", "output_bindings contain an invalid binding")
        if len({binding.port_name for binding in bindings}) != len(bindings):
            raise _error("WORKFLOW_DUPLICATE_ID", "output binding port names must be unique")
        if any(binding.direction is not PortDirectionV1.OUTPUT for binding in bindings):
            raise _error("WORKFLOW_BINDING_INVALID", "workflow output_bindings must be output bindings")
        object.__setattr__(self, "output_bindings", bindings)
        if not isinstance(self.model_branches, (tuple, list)):
            raise _error("WORKFLOW_ARRAY_INVALID", "model_branches must be an array")
        branches = tuple(self.model_branches)
        if len({branch.branch_id for branch in branches}) != len(branches):
            raise _error("WORKFLOW_DUPLICATE_ID", "model branch IDs must be unique")
        if any(type(branch) is not ModelBranchRefV1 for branch in branches):
            raise _error("WORKFLOW_BINDING_INVALID", "model_branches contain an invalid branch")
        object.__setattr__(self, "model_branches", branches)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "semantic_plan_hash": self.semantic_plan_hash,
            "execution_instance_hash": (
                self.execution_instance_hash.to_dict()
                if type(self.execution_instance_hash) is NotApplicableV1
                else self.execution_instance_hash
            ),
            "contract_snapshot_ref": self.contract_snapshot_ref,
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "output_bindings": [binding.to_dict() for binding in self.output_bindings],
            "model_branches": [branch.to_dict() for branch in self.model_branches],
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "WorkflowExecutionStateV2":
        if type(value) is not dict:
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "workflow state must be a built-in dict")
        if value.get("schema_version") != WORKFLOW_STATE_SCHEMA_V2:
            source = value.get("schema_version", "legacy")
            source_text = source if type(source) is str and source else "legacy"
            raise _error(
                "MIGRATION_REQUIRED",
                f"MIGRATION_REQUIRED: workflow state {source_text} needs an explicit safe migrator",
            )
        if set(value) != _REQUIRED_DEVELOPMENT_STATE_FIELDS or any(type(key) is not str for key in value):
            raise _error("WORKFLOW_SCHEMA_INVALID", "workflow state fields are not exact")
        raw_execution = value["execution_instance_hash"]
        execution: str | NotApplicableV1
        if type(raw_execution) is dict:
            execution = NotApplicableV1.from_dict(raw_execution)
        else:
            execution = raw_execution  # type: ignore[assignment]
        raw_outputs = _wire_list(value["output_bindings"], "output_bindings")
        raw_branches = _wire_list(value["model_branches"], "model_branches")
        if any(type(item) is not dict for item in raw_outputs + raw_branches):
            raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "nested workflow entries must be built-in dicts")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            workflow_id=value["workflow_id"],  # type: ignore[arg-type]
            run_id=value["run_id"],  # type: ignore[arg-type]
            status=_enum(value["status"], WorkflowExecutionStatusV2, "status"),
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
            execution_instance_hash=execution,
            contract_snapshot_ref=value["contract_snapshot_ref"],  # type: ignore[arg-type]
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            output_bindings=tuple(PortBindingV1.from_dict(item) for item in raw_outputs),  # type: ignore[arg-type]
            model_branches=tuple(ModelBranchRefV1.from_dict(item) for item in raw_branches),  # type: ignore[arg-type]
        )


def load_workflow_state(
    value: dict[str, object],
    *,
    safe_migrator: object | None = None,
) -> WorkflowExecutionStateV2 | WorkflowMigrationRequiredV1:
    """Load current state or return an explicit migration-required result.

    No callable or defaulting migration is accepted here.  A future migration
    line can introduce a typed, server-owned migrator without changing this
    current-state contract.
    """

    if type(value) is not dict:
        raise _error("WORKFLOW_NESTED_DICT_REQUIRED", "workflow state must be a built-in dict")
    if value.get("schema_version") == WORKFLOW_STATE_SCHEMA_V2:
        return WorkflowExecutionStateV2.from_dict(value)
    if safe_migrator is not None:
        raise _error("MIGRATION_REQUIRED", "MIGRATION_REQUIRED: no safe migrator is registered")
    source = value.get("schema_version", "legacy")
    source_text = source if type(source) is str and source else "legacy"
    return WorkflowMigrationRequiredV1(source_schema_version=source_text)


__all__ = [
    "ModelBranchRefV1",
    "PortBindingV1",
    "PortDirectionV1",
    "PortValidationReceiptV1",
    "PortValidationStatusV1",
    "ValidationReceiptStoreV1",
    "WORKFLOW_STATE_SCHEMA_V2",
    "WorkflowExecutionStateV2",
    "WorkflowExecutionStatusV2",
    "WorkflowMigrationRequiredV1",
    "WorkflowStateContractError",
    "load_workflow_state",
]
