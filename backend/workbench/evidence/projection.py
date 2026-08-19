"""Fail-closed, read-only evidence projection kernel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from workbench.canonical import sha256_canonical
from workbench.contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    ExecutionStatusV1,
)
from workbench.contracts.common.contract_ref import ContractRefV1

from .authority import (
    EVIDENCE_HOST_AUTHORITY_REQUIRED,
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from .contracts import (
    ArtifactAdmissionV1,
    artifact_content_hash,
    EvidenceFailureReceiptV1,
    EvidenceCoreContractError,
    _opaque_ref,
)
from .registry import EvidenceRegistryError, EvidenceRegistryV1


class EvidenceProjectionError(ValueError):
    """Projection refused to claim a successful evidence answer."""

    def __init__(self, code: str, message: str | None = None, *, receipt: EvidenceFailureReceiptV1 | None = None) -> None:
        self.code = code
        self.receipt = receipt or EvidenceFailureReceiptV1(code, message or code)
        super().__init__(message or code)


def _failure(
    code: str,
    message: str,
    *,
    artifact_id: str | None = None,
    scope_ref: str | None = None,
) -> EvidenceProjectionError:
    receipt = EvidenceFailureReceiptV1(
        code=code,
        message=message,
        artifact_id=_safe_opaque_ref(artifact_id),
        scope_ref=_safe_opaque_ref(scope_ref),
        retryable=False,
    )
    return EvidenceProjectionError(code, message, receipt=receipt)


def _safe_opaque_ref(value: object) -> str | None:
    if value is None:
        return None
    try:
        return _opaque_ref(value, "projection_ref")
    except EvidenceCoreContractError:
        return None


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [_thaw(item) for item in value]
    return value


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze(dict(value))


def _normalize_view_values(values: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    normalized["validation_summary"] = _frozen_mapping(normalized["validation_summary"])
    normalized["family_evidence"] = _frozen_mapping(normalized["family_evidence"])
    for name in ("facts", "figures", "diagnostics", "warnings"):
        normalized[name] = tuple(
            _frozen_mapping(dict(item)) for item in normalized[name]
        )
    return normalized


def _view_payload(values: Mapping[str, Any]) -> dict[str, object]:
    validator_ref = values["validator_ref"]
    return {
        "success": values["success"],
        "status": values["status"],
        "artifact_id": values["artifact_id"],
        "scope_ref": values["scope_ref"],
        "source_ref": values["source_ref"],
        "validator_ref": validator_ref.to_dict()
        if type(validator_ref) is ContractRefV1
        else validator_ref,
        "execution_ref": values["execution_ref"],
        "contract_digest": values["contract_digest"],
        "envelope_digest": values["envelope_digest"],
        "execution_status": values["execution_status"],
        "availability": values["availability"],
        "completeness_status": values["completeness_status"],
        "validation_summary": _thaw(values["validation_summary"]),
        "family_evidence": _thaw(values["family_evidence"]),
        "facts": [_thaw(item) for item in values["facts"]],
        "figures": [_thaw(item) for item in values["figures"]],
        "diagnostics": [_thaw(item) for item in values["diagnostics"]],
        "warnings": [_thaw(item) for item in values["warnings"]],
    }


class _ProjectionReceiptV1:
    __slots__ = ("_authority_handle", "_request", "_proof")

    def __init__(self, authority_handle: object, request: object, proof: object) -> None:
        self._authority_handle = authority_handle
        self._request = request
        self._proof = proof

    def matches(self, payload: Mapping[str, object], subject_id: int) -> bool:
        try:
            request = self._request
            if request.subject_id != subject_id or request.payload_digest != sha256_canonical(payload):
                return False
            validate_host_proof(self._authority_handle, request, self._proof)
            return True
        except (AttributeError, TypeError, ValueError, KeyError, RecursionError, EvidenceHostAuthorityError):
            return False

    def __reduce__(self):
        raise TypeError("projection receipts are host-bound capabilities")

    def __copy__(self):
        raise TypeError("projection receipts are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("projection receipts are host-bound capabilities")


def _view_values(view: "EvidenceProjectionViewV1") -> dict[str, Any]:
    return {
        "success": view.success,
        "status": view.status,
        "artifact_id": view.artifact_id,
        "scope_ref": view.scope_ref,
        "source_ref": view.source_ref,
        "validator_ref": view.validator_ref,
        "execution_ref": view.execution_ref,
        "contract_digest": view.contract_digest,
        "envelope_digest": view.envelope_digest,
        "execution_status": view.execution_status,
        "availability": view.availability,
        "completeness_status": view.completeness_status,
        "validation_summary": view.validation_summary,
        "family_evidence": view.family_evidence,
        "facts": view.facts,
        "figures": view.figures,
        "diagnostics": view.diagnostics,
        "warnings": view.warnings,
    }


def _outcome_payload(
    *,
    success: bool,
    status: str,
    view: "EvidenceProjectionViewV1" | None,
    failure_receipt: EvidenceFailureReceiptV1 | None,
) -> dict[str, object]:
    return {
        "success": success,
        "status": status,
        "view": None if view is None else view.to_dict(),
        "failure_receipt": None if failure_receipt is None else failure_receipt.to_dict(),
    }


@dataclass(frozen=True, init=False)
class EvidenceProjectionViewV1:
    success: bool
    status: str
    artifact_id: str
    scope_ref: str
    source_ref: str
    validator_ref: str | ContractRefV1
    execution_ref: str
    contract_digest: str
    envelope_digest: str
    execution_status: str
    availability: str
    completeness_status: str
    validation_summary: Mapping[str, Any]
    family_evidence: Mapping[str, Any]
    facts: tuple[Mapping[str, Any], ...]
    figures: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[Mapping[str, Any], ...]
    warnings: tuple[Mapping[str, Any], ...]
    _receipt: _ProjectionReceiptV1 = field(repr=False, compare=False)

    @classmethod
    def _from_host(cls, values: Mapping[str, Any], authority_handle: object) -> "EvidenceProjectionViewV1":
        normalized = _normalize_view_values(values)
        view = object.__new__(cls)
        payload = _view_payload(normalized)
        try:
            request = build_authority_request(
                authority_handle,
                purpose="evidence.projection.view",
                scope_ref=normalized["scope_ref"],
                subject_id=id(view),
                payload_digest=sha256_canonical(payload),
            )
            proof = issue_host_proof(authority_handle, request)
        except EvidenceHostAuthorityError as exc:
            raise TypeError(f"projection view requires host authority: {exc}") from exc
        receipt = _ProjectionReceiptV1(authority_handle, request, proof)
        if not receipt.matches(payload, id(view)):
            raise TypeError("projection view proof was rejected by the host authority")
        for name, value in normalized.items():
            object.__setattr__(view, name, value)
        object.__setattr__(view, "_receipt", receipt)
        return view

    def __init__(
        self,
        success: bool,
        status: str,
        artifact_id: str,
        scope_ref: str,
        source_ref: str,
        validator_ref: str | ContractRefV1,
        execution_ref: str,
        contract_digest: str,
        envelope_digest: str,
        execution_status: str,
        availability: str,
        completeness_status: str,
        validation_summary: Mapping[str, Any],
        family_evidence: Mapping[str, Any],
        facts: tuple[Mapping[str, Any], ...],
        figures: tuple[Mapping[str, Any], ...],
        diagnostics: tuple[Mapping[str, Any], ...],
        warnings: tuple[Mapping[str, Any], ...],
        *,
        _receipt: object | None = None,
    ) -> None:
        if type(_receipt) is not _ProjectionReceiptV1:
            raise TypeError("projection views must come from the projector-owned factory")
        values = _normalize_view_values(
            {
                "success": success,
                "status": status,
                "artifact_id": artifact_id,
                "scope_ref": scope_ref,
                "source_ref": source_ref,
                "validator_ref": validator_ref,
                "execution_ref": execution_ref,
                "contract_digest": contract_digest,
                "envelope_digest": envelope_digest,
                "execution_status": execution_status,
                "availability": availability,
                "completeness_status": completeness_status,
                "validation_summary": validation_summary,
                "family_evidence": family_evidence,
                "facts": facts,
                "figures": figures,
                "diagnostics": diagnostics,
                "warnings": warnings,
            }
        )
        if not _receipt.matches(_view_payload(values), id(self)):
            raise TypeError("projection receipt does not bind the supplied view")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_receipt", _receipt)

    def _validated_values(self) -> dict[str, Any]:
        try:
            values = _normalize_view_values(_view_values(self))
            if type(self._receipt) is not _ProjectionReceiptV1 or not self._receipt.matches(_view_payload(values), id(self)):
                raise TypeError("projection view is not bound to a server-issued receipt")
            return values
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, TypeError) and str(exc) == "projection view is not bound to a server-issued receipt":
                raise
            raise TypeError("projection view is not bound to a server-issued receipt") from exc

    def to_dict(self) -> dict[str, object]:
        values = self._validated_values()
        return {
            "success": values["success"],
            "status": values["status"],
            "artifact_id": values["artifact_id"],
            "scope_ref": values["scope_ref"],
            "source_ref": values["source_ref"],
            "validator_ref": values["validator_ref"].to_dict()
            if type(values["validator_ref"]) is ContractRefV1
            else self.validator_ref,
            "execution_ref": values["execution_ref"],
            "contract_digest": values["contract_digest"],
            "envelope_digest": values["envelope_digest"],
            "execution_status": values["execution_status"],
            "availability": values["availability"],
            "completeness_status": values["completeness_status"],
            "validation_summary": _thaw(values["validation_summary"]),
            "family_evidence": _thaw(values["family_evidence"]),
            "facts": [_thaw(fact) for fact in values["facts"]],
            "figures": [_thaw(figure) for figure in values["figures"]],
            "diagnostics": [_thaw(item) for item in values["diagnostics"]],
            "warnings": [_thaw(item) for item in values["warnings"]],
        }

    def __reduce__(self):
        raise TypeError("projection views are host-bound capabilities")

    def __copy__(self):
        raise TypeError("projection views are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("projection views are host-bound capabilities")


@dataclass(frozen=True, init=False)
class EvidenceProjectionOutcomeV1:
    success: bool
    status: str
    view: EvidenceProjectionViewV1 | None = None
    failure_receipt: EvidenceFailureReceiptV1 | None = None
    _receipt: _ProjectionReceiptV1 = field(repr=False, compare=False)

    @classmethod
    def _from_host(
        cls,
        *,
        success: bool,
        status: str,
        view: EvidenceProjectionViewV1 | None,
        failure_receipt: EvidenceFailureReceiptV1 | None,
        authority_handle: object,
        scope_ref: str,
    ) -> "EvidenceProjectionOutcomeV1":
        outcome = object.__new__(cls)
        payload = _outcome_payload(
            success=success,
            status=status,
            view=view,
            failure_receipt=failure_receipt,
        )
        try:
            request = build_authority_request(
                authority_handle,
                purpose="evidence.projection.outcome",
                scope_ref=scope_ref,
                subject_id=id(outcome),
                payload_digest=sha256_canonical(payload),
            )
            proof = issue_host_proof(authority_handle, request)
        except EvidenceHostAuthorityError as exc:
            raise TypeError(f"projection outcome requires host authority: {exc}") from exc
        receipt = _ProjectionReceiptV1(authority_handle, request, proof)
        if not receipt.matches(payload, id(outcome)):
            raise TypeError("projection outcome proof was rejected by the host authority")
        object.__setattr__(outcome, "success", success)
        object.__setattr__(outcome, "status", status)
        object.__setattr__(outcome, "view", view)
        object.__setattr__(outcome, "failure_receipt", failure_receipt)
        object.__setattr__(outcome, "_receipt", receipt)
        return outcome

    def __init__(
        self,
        success: bool,
        status: str,
        view: EvidenceProjectionViewV1 | None = None,
        failure_receipt: EvidenceFailureReceiptV1 | None = None,
        *,
        _receipt: object | None = None,
    ) -> None:
        if type(success) is not bool or type(status) is not str or not status:
            raise TypeError("projection outcome fields are invalid")
        if success and (type(view) is not EvidenceProjectionViewV1 or failure_receipt is not None):
            raise TypeError("successful projection outcomes require a projector-owned view")
        if not success and (view is not None or type(failure_receipt) is not EvidenceFailureReceiptV1):
            raise TypeError("failed projection outcomes require a failure receipt")
        if type(_receipt) is not _ProjectionReceiptV1:
            raise TypeError("projection outcomes require a server-issued receipt")
        if not _receipt.matches(
            _outcome_payload(
                success=success,
                status=status,
                view=view,
                failure_receipt=failure_receipt,
            ),
            id(self),
        ):
            raise TypeError("projection outcome receipt does not bind the supplied outcome")
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "view", view)
        object.__setattr__(self, "failure_receipt", failure_receipt)
        object.__setattr__(self, "_receipt", _receipt)

    def _validate_receipt(self) -> None:
        try:
            if type(self._receipt) is not _ProjectionReceiptV1:
                raise TypeError("projection outcome is not bound to a server-issued receipt")
            if type(self.success) is not bool or type(self.status) is not str or not self.status:
                raise TypeError("projection outcome fields are invalid")
            if self.success:
                if type(self.view) is not EvidenceProjectionViewV1 or self.failure_receipt is not None:
                    raise TypeError("successful projection outcome fields are invalid")
            elif self.view is not None or type(self.failure_receipt) is not EvidenceFailureReceiptV1:
                raise TypeError("failed projection outcome fields are invalid")
            if not self._receipt.matches(
                _outcome_payload(
                    success=self.success,
                    status=self.status,
                    view=self.view,
                    failure_receipt=self.failure_receipt,
                ),
                id(self),
            ):
                raise TypeError("projection outcome is not bound to a server-issued receipt")
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, TypeError) and str(exc).startswith("projection outcome"):
                raise
            raise TypeError("projection outcome is not bound to a server-issued receipt") from exc

    def to_dict(self) -> dict[str, object]:
        self._validate_receipt()
        return {
            "success": self.success,
            "status": self.status,
            "view": None if self.view is None else self.view.to_dict(),
            "failure_receipt": None
            if self.failure_receipt is None
            else self.failure_receipt.to_dict(),
        }

    def __reduce__(self):
        raise TypeError("projection outcomes are host-bound capabilities")

    def __copy__(self):
        raise TypeError("projection outcomes are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("projection outcomes are host-bound capabilities")


def _validator_ref(record: ArtifactAdmissionV1) -> str | ContractRefV1:
    return record.validator_ref


class EvidenceProjectionV1:
    """Project only facts already present in an admitted immutable envelope."""

    __slots__ = ("_registry",)

    def __init__(self, registry: EvidenceRegistryV1) -> None:
        if type(registry) is not EvidenceRegistryV1:
            raise TypeError("registry must be EvidenceRegistryV1")
        registry._require_authority()
        self._registry = registry

    @property
    def registry(self) -> EvidenceRegistryV1:
        return self._registry

    def _resolve(self, artifact_id: str, scope_ref: str | None) -> ArtifactAdmissionV1:
        try:
            return self._registry.resolve(artifact_id, scope_ref=scope_ref)
        except EvidenceRegistryError as exc:
            code = exc.code
            if code == "EVIDENCE_ARTIFACT_UNKNOWN":
                projection_code = "EVIDENCE_UNKNOWN_ARTIFACT"
            elif code == "EVIDENCE_CROSS_SCOPE":
                projection_code = "EVIDENCE_CROSS_SCOPE"
            elif code in {"EVIDENCE_TAMPERED", "EVIDENCE_CORRUPT"}:
                projection_code = "EVIDENCE_TAMPERED"
            else:
                projection_code = "EVIDENCE_REGISTRY_REFUSED"
            raise _failure(
                projection_code,
                str(exc),
                artifact_id=artifact_id,
                scope_ref=scope_ref or self._registry.scope_ref,
            ) from exc

    def _view(self, record: ArtifactAdmissionV1) -> EvidenceProjectionViewV1:
        try:
            envelope = record.envelope.envelope
            if artifact_content_hash(
                artifact_id=record.artifact_id,
                artifact_type=record.artifact_type,
                scope_ref=record.scope_ref,
                source_ref=record.source_ref,
                validator_ref=record.validator_ref,
                execution_ref=record.execution_ref,
                contract_digest=record.contract_digest,
                envelope=record.envelope,
            ) != record.content_hash:
                raise _failure("EVIDENCE_TAMPERED", "artifact content hash does not match the admitted envelope", artifact_id=record.artifact_id, scope_ref=record.scope_ref)
        except EvidenceCoreContractError as exc:
            raise _failure("EVIDENCE_CORRUPT", str(exc), artifact_id=record.artifact_id, scope_ref=record.scope_ref) from exc

        execution_status = envelope.execution_status.value
        availability = envelope.availability.value
        completeness = envelope.completeness_status.value
        if execution_status in {ExecutionStatusV1.BLOCKED.value, ExecutionStatusV1.FAILED.value}:
            raise _failure("EVIDENCE_EXECUTION_BLOCKED", "blocked or failed execution cannot project as success", artifact_id=record.artifact_id, scope_ref=record.scope_ref)
        if execution_status == ExecutionStatusV1.PARTIAL.value:
            raise _failure("EVIDENCE_EXECUTION_PARTIAL", "partial execution cannot project as success", artifact_id=record.artifact_id, scope_ref=record.scope_ref)
        if availability != AvailabilityStatusV1.AVAILABLE.value:
            raise _failure("EVIDENCE_UNAVAILABLE", "unavailable or not-applicable evidence cannot project as success", artifact_id=record.artifact_id, scope_ref=record.scope_ref)
        if completeness == CompletenessStatusV1.INSUFFICIENT.value:
            raise _failure("EVIDENCE_INSUFFICIENT", "insufficient evidence cannot project as success", artifact_id=record.artifact_id, scope_ref=record.scope_ref)

        status = "degraded" if completeness == CompletenessStatusV1.DEGRADED.value else "available"
        facts = tuple(_frozen_mapping(fact.to_dict()) for fact in envelope.numeric_facts)
        figures = tuple(_frozen_mapping(dict(item)) for item in envelope.figures)
        diagnostics = tuple(_frozen_mapping(dict(item)) for item in envelope.diagnostics)
        warnings = tuple(_frozen_mapping(dict(item)) for item in envelope.warnings)
        validator_ref = _validator_ref(record)
        values = _normalize_view_values(
            {
                "success": True,
                "status": status,
                "artifact_id": record.artifact_id,
                "scope_ref": record.scope_ref,
                "source_ref": record.source_ref,
                "validator_ref": validator_ref,
                "execution_ref": record.execution_ref,
                "contract_digest": record.contract_digest,
                "envelope_digest": record.envelope_digest,
                "execution_status": execution_status,
                "availability": availability,
                "completeness_status": completeness,
                "validation_summary": envelope.validation_summary.to_dict(),
                "family_evidence": dict(envelope.family_evidence),
                "facts": facts,
                "figures": figures,
                "diagnostics": diagnostics,
                "warnings": warnings,
            }
        )
        try:
            return EvidenceProjectionViewV1._from_host(
                values,
                self._registry._host_authority_handle(),
            )
        except TypeError as exc:
            raise _failure(
                "EVIDENCE_REGISTRY_REFUSED",
                "projection success was not authorized by the host",
                artifact_id=record.artifact_id,
                scope_ref=record.scope_ref,
            ) from exc

    def project(self, artifact_id: str, *, scope_ref: str | None = None) -> EvidenceProjectionViewV1:
        """Return a successful view or raise; no fallback/re-execution exists."""

        return self._view(self._resolve(artifact_id, scope_ref))

    def try_project(self, artifact_id: str, *, scope_ref: str | None = None) -> EvidenceProjectionOutcomeV1:
        try:
            view = self.project(artifact_id, scope_ref=scope_ref)
        except EvidenceProjectionError as exc:
            status_map = {
                "EVIDENCE_UNKNOWN_ARTIFACT": "unknown_artifact",
                "EVIDENCE_CROSS_SCOPE": "cross_scope",
                "EVIDENCE_TAMPERED": "tampered",
                "EVIDENCE_CORRUPT": "corrupt",
                "EVIDENCE_UNAVAILABLE": "unavailable",
                "EVIDENCE_EXECUTION_BLOCKED": "blocked",
                "EVIDENCE_EXECUTION_PARTIAL": "partial",
                "EVIDENCE_INSUFFICIENT": "insufficient",
            }
            status = status_map.get(exc.code, "blocked")
            try:
                return EvidenceProjectionOutcomeV1._from_host(
                    success=False,
                    status=status,
                    view=None,
                    failure_receipt=exc.receipt,
                    authority_handle=self._registry._host_authority_handle(),
                    scope_ref=scope_ref or self._registry.scope_ref,
                )
            except TypeError as auth_exc:
                raise EvidenceProjectionError(
                    "EVIDENCE_REGISTRY_REFUSED",
                    "projection failure was not authorized by the host",
                ) from auth_exc
        try:
            return EvidenceProjectionOutcomeV1._from_host(
                success=True,
                status=view.status,
                view=view,
                failure_receipt=None,
                authority_handle=self._registry._host_authority_handle(),
                scope_ref=view.scope_ref,
            )
        except TypeError as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_REGISTRY_REFUSED",
                "projection success was not authorized by the host",
            ) from exc

    def project_evidence(self, artifact_id: str, *, scope_ref: str | None = None) -> EvidenceProjectionViewV1:
        return self.project(artifact_id, scope_ref=scope_ref)


EvidenceProjectionKernelV1 = EvidenceProjectionV1
ConsumerProjectionV1 = EvidenceProjectionViewV1


__all__ = [
    "ConsumerProjectionV1",
    "EvidenceProjectionError",
    "EvidenceProjectionKernelV1",
    "EvidenceProjectionOutcomeV1",
    "EvidenceProjectionV1",
    "EvidenceProjectionViewV1",
]
