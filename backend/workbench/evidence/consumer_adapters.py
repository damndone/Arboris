"""Port-based, fail-closed projections of persisted evidence envelopes.

This module deliberately has no statistical implementation dependency.  A
projection may select, order, redact, or omit already persisted facts, but it
never derives a new value or fills a missing value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.agent.context_egress import (
    ContextEgressGatewayV1,
    ContextEgressReceiptIssuerV1,
    ContextEgressReceiptV1,
    EgressContractError,
    SensitivityClassV1,
    require_context_egress_receipt,
)
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    ExecutionStatusV1,
    TransactionStatusV1,
)
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1, NumericFactV1
from workbench.contracts.evidence.persistence import (
    EvidenceCommitBindingV1,
)


class EvidenceProjectionError(ValueError):
    """A stable, caller-visible projection contract failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ProjectionStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be non-empty text")
    return value


def _ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} must be ContractRefV1")
    return value


def _sensitivity(value: object, name: str) -> SensitivityClassV1:
    if isinstance(value, SensitivityClassV1):
        return value
    if type(value) is str:
        try:
            return SensitivityClassV1(value)
        except ValueError as exc:
            raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} is invalid") from exc
    raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} is invalid")


def _sensitivity_tuple(value: object, name: str) -> tuple[SensitivityClassV1, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} must be non-empty")
    result = tuple(_sensitivity(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} must be unique")
    return result


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be unique")
    return result


@dataclass(frozen=True)
class PersistedEvidenceEnvelopeV1:
    """The only input shape accepted by a consumer adapter.

    The binding and envelope digest are checked at construction time so a
    caller cannot turn an uncommitted or altered payload into a projection.
    """

    commit_id: str
    artifact_ref: str
    envelope_ref: str
    sensitivity: SensitivityClassV1 | str
    binding: EvidenceCommitBindingV1
    envelope: EvidenceEnvelopeV1

    def __post_init__(self) -> None:
        _text(self.commit_id, "commit_id")
        _text(self.artifact_ref, "artifact_ref")
        _text(self.envelope_ref, "envelope_ref")
        object.__setattr__(self, "sensitivity", _sensitivity(self.sensitivity, "sensitivity"))
        if type(self.binding) is not EvidenceCommitBindingV1:
            raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", "binding is invalid")
        if type(self.envelope) is not EvidenceEnvelopeV1:
            raise EvidenceProjectionError("PROJECTION_ENVELOPE_INVALID", "envelope is invalid")
        if self.binding.commit_id != self.commit_id:
            raise EvidenceProjectionError("PROJECTION_COMMIT_MISMATCH", "binding commit_id differs")
        if self.binding.transaction_status is not TransactionStatusV1.COMMITTED:
            raise EvidenceProjectionError("PROJECTION_NOT_COMMITTED", "only committed evidence may be projected")
        if self.binding.envelope_digest != sha256_canonical(self.envelope.to_dict()):
            raise EvidenceProjectionError("PROJECTION_DIGEST_MISMATCH", "persisted envelope digest differs")

    @property
    def envelope_digest(self) -> str:
        return self.binding.envelope_digest


@dataclass(frozen=True)
class ConsumerProjectionSpecV1:
    consumer_id: str
    semantic_version: str
    projection_ref: ContractRefV1
    policy_ref: ContractRefV1
    renderer_key: str
    max_token_budget: int
    max_row_budget: int
    allowed_sensitivity: tuple[SensitivityClassV1 | str, ...]
    ordering: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.consumer_id, "consumer_id")
        _text(self.semantic_version, "semantic_version")
        _ref(self.projection_ref, "projection_ref")
        _ref(self.policy_ref, "policy_ref")
        _text(self.renderer_key, "renderer_key")
        if type(self.max_token_budget) is not int or self.max_token_budget <= 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_token_budget must be positive")
        if type(self.max_row_budget) is not int or self.max_row_budget <= 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_row_budget must be positive")
        object.__setattr__(
            self,
            "allowed_sensitivity",
            _sensitivity_tuple(self.allowed_sensitivity, "allowed_sensitivity"),
        )
        object.__setattr__(self, "ordering", _string_tuple(self.ordering, "ordering"))

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "semantic_version": self.semantic_version,
            "projection_ref": self.projection_ref.to_dict(),
            "policy_ref": self.policy_ref.to_dict(),
            "renderer_key": self.renderer_key,
            "max_token_budget": self.max_token_budget,
            "max_row_budget": self.max_row_budget,
            "allowed_sensitivity": [value.value for value in self.allowed_sensitivity],
            "ordering": list(self.ordering),
        }


@dataclass(frozen=True)
class ProjectionAuditV1:
    requested_fact_ids: tuple[str, ...]
    selected_fact_ids: tuple[str, ...]
    omitted_fact_ids: tuple[str, ...]
    redacted_fact_ids: tuple[str, ...]
    destination: str
    policy_ref: ContractRefV1
    token_budget: int
    row_budget: int
    raw_rows_rejected: bool
    restriction_reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "requested_fact_ids",
            "selected_fact_ids",
            "omitted_fact_ids",
            "redacted_fact_ids",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name), name))
        if self.destination not in {"local", "remote"}:
            raise EvidenceProjectionError("PROJECTION_DESTINATION_INVALID", "destination is invalid")
        _ref(self.policy_ref, "policy_ref")
        if type(self.token_budget) is not int or self.token_budget < 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "token_budget is invalid")
        if type(self.row_budget) is not int or self.row_budget < 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "row_budget is invalid")
        if type(self.raw_rows_rejected) is not bool:
            raise EvidenceProjectionError("PROJECTION_RAW_ROWS_INVALID", "raw_rows_rejected is invalid")
        if self.restriction_reason is not None:
            _text(self.restriction_reason, "restriction_reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_fact_ids": list(self.requested_fact_ids),
            "selected_fact_ids": list(self.selected_fact_ids),
            "omitted_fact_ids": list(self.omitted_fact_ids),
            "redacted_fact_ids": list(self.redacted_fact_ids),
            "destination": self.destination,
            "policy_ref": self.policy_ref.to_dict(),
            "token_budget": self.token_budget,
            "row_budget": self.row_budget,
            "raw_rows_rejected": self.raw_rows_rejected,
            "restriction_reason": self.restriction_reason,
        }


@dataclass(frozen=True)
class EvidenceProjectionV1:
    consumer_id: str
    consumer_version: str
    projection_ref: ContractRefV1
    artifact_ref: str
    commit_id: str
    envelope_ref: str
    envelope_digest: str
    result_identity: Mapping[str, Any]
    execution_status: str
    availability: str
    completeness_status: str
    numerical_method: str
    inference_basis: str
    evaluation_design: str
    validation_summary: Mapping[str, Any]
    facts: tuple[NumericFactV1, ...]
    status: ProjectionStatus
    audit: ProjectionAuditV1
    lineage_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.consumer_id, "consumer_id")
        _text(self.consumer_version, "consumer_version")
        _ref(self.projection_ref, "projection_ref")
        for name in ("artifact_ref", "commit_id", "envelope_ref", "envelope_digest"):
            _text(getattr(self, name), name)
        if not isinstance(self.result_identity, Mapping):
            raise EvidenceProjectionError("PROJECTION_IDENTITY_INVALID", "result_identity is invalid")
        if not isinstance(self.validation_summary, Mapping):
            raise EvidenceProjectionError("PROJECTION_VALIDATION_INVALID", "validation_summary is invalid")
        if not isinstance(self.facts, (list, tuple)) or any(type(fact) is not NumericFactV1 for fact in self.facts):
            raise EvidenceProjectionError("PROJECTION_FACTS_INVALID", "facts must be persisted NumericFactV1 values")
        object.__setattr__(self, "facts", tuple(self.facts))
        if type(self.status) is not ProjectionStatus:
            raise EvidenceProjectionError("PROJECTION_STATUS_INVALID", "status is invalid")
        if type(self.audit) is not ProjectionAuditV1:
            raise EvidenceProjectionError("PROJECTION_AUDIT_INVALID", "audit is invalid")
        object.__setattr__(self, "lineage_refs", _string_tuple(self.lineage_refs, "lineage_refs"))

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(fact.fact_id for fact in self.facts)

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "consumer_version": self.consumer_version,
            "projection_ref": self.projection_ref.to_dict(),
            "artifact_ref": self.artifact_ref,
            "commit_id": self.commit_id,
            "envelope_ref": self.envelope_ref,
            "envelope_digest": self.envelope_digest,
            "result_identity": dict(self.result_identity),
            "execution_status": self.execution_status,
            "availability": self.availability,
            "completeness_status": self.completeness_status,
            "numerical_method": self.numerical_method,
            "inference_basis": self.inference_basis,
            "evaluation_design": self.evaluation_design,
            "validation_summary": dict(self.validation_summary),
            "facts": [fact.to_dict() for fact in self.facts],
            "status": self.status.value,
            "audit": self.audit.to_dict(),
            "lineage_refs": list(self.lineage_refs),
        }


def _fact_token_cost(fact: NumericFactV1) -> int:
    """Use a deterministic serialization bound; never transform a statistic."""

    return max(1, (len(canonical_json_v1(fact.to_dict())) + 3) // 4)


class ConsumerProjectionRegistryV1:
    def __init__(self, specs: Sequence[ConsumerProjectionSpecV1] = ()) -> None:
        self._specs: dict[str, ConsumerProjectionSpecV1] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ConsumerProjectionSpecV1) -> None:
        if type(spec) is not ConsumerProjectionSpecV1:
            raise EvidenceProjectionError("PROJECTION_SPEC_INVALID", "spec is invalid")
        if spec.consumer_id in self._specs:
            raise EvidenceProjectionError("PROJECTION_DUPLICATE", spec.consumer_id)
        self._specs[spec.consumer_id] = spec

    def resolve(self, consumer_id: str) -> ConsumerProjectionSpecV1 | None:
        return self._specs.get(consumer_id)

    @property
    def consumer_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def without(self, consumer_id: str) -> "ConsumerProjectionRegistryV1":
        return ConsumerProjectionRegistryV1(
            tuple(spec for key, spec in self._specs.items() if key != consumer_id)
        )

    def project(
        self,
        record: PersistedEvidenceEnvelopeV1,
        *,
        consumer_id: str,
        destination: str,
        requested_fact_ids: Sequence[str] | None = None,
        raw_rows: object | None = None,
        gateway: ContextEgressGatewayV1 | None = None,
        receipt: ContextEgressReceiptV1 | None = None,
        issuer: ContextEgressReceiptIssuerV1 | None = None,
    ) -> EvidenceProjectionV1:
        if type(record) is not PersistedEvidenceEnvelopeV1:
            raise EvidenceProjectionError("PROJECTION_RECORD_INVALID", "record is not persisted evidence")
        spec = self.resolve(consumer_id)
        if spec is None:
            raise EvidenceProjectionError("PROJECTION_CONSUMER_UNKNOWN", f"unknown consumer {consumer_id}")
        if destination not in {"local", "remote"}:
            raise EvidenceProjectionError("PROJECTION_DESTINATION_INVALID", "destination is invalid")
        requested = (
            tuple(fact.fact_id for fact in record.envelope.numeric_facts)
            if requested_fact_ids is None
            else _string_tuple(requested_fact_ids, "requested_fact_ids")
        )
        all_fact_ids = tuple(fact.fact_id for fact in record.envelope.numeric_facts)
        requested_set = set(requested)
        missing_requested = tuple(fact_id for fact_id in requested if fact_id not in set(all_fact_ids))
        redacted = tuple()
        restriction_reason: str | None = None

        if record.sensitivity not in spec.allowed_sensitivity:
            redacted = all_fact_ids
            restriction_reason = "sensitivity_not_allowed"
        elif destination == "remote":
            if gateway is None or receipt is None or issuer is None:
                redacted = all_fact_ids
                restriction_reason = "egress_receipt_required"
            else:
                try:
                    require_context_egress_receipt(gateway, receipt, issuer=issuer)
                except EgressContractError as exc:
                    redacted = all_fact_ids
                    restriction_reason = exc.code

        raw_rows_rejected = raw_rows is not None
        if redacted or record.envelope.availability is not AvailabilityStatusV1.AVAILABLE:
            selected: tuple[NumericFactV1, ...] = tuple()
            omitted = tuple(dict.fromkeys((*missing_requested, *all_fact_ids)))
            if redacted:
                omitted = missing_requested
        else:
            selected_list: list[NumericFactV1] = []
            omitted_list: list[str] = list(missing_requested)
            used_tokens = 0
            # Preserve the envelope's persisted sequence.  ``ordering`` is a
            # declaration for the consumer contract, not permission to sort or
            # otherwise rewrite source evidence.
            for fact in (fact for fact in record.envelope.numeric_facts if fact.fact_id in requested_set):
                cost = _fact_token_cost(fact)
                if len(selected_list) >= spec.max_row_budget or used_tokens + cost > spec.max_token_budget:
                    omitted_list.append(fact.fact_id)
                    continue
                selected_list.append(fact)
                used_tokens += cost
            selected = tuple(selected_list)
            omitted = tuple(dict.fromkeys(omitted_list))

        if record.envelope.availability is not AvailabilityStatusV1.AVAILABLE:
            status = ProjectionStatus.UNAVAILABLE
        elif redacted:
            status = ProjectionStatus.BLOCKED
        elif (
            omitted
            or record.envelope.completeness_status is CompletenessStatusV1.DEGRADED
            or record.envelope.execution_status is ExecutionStatusV1.PARTIAL
        ):
            status = ProjectionStatus.DEGRADED
        else:
            status = ProjectionStatus.AVAILABLE

        audit = ProjectionAuditV1(
            requested_fact_ids=requested,
            selected_fact_ids=tuple(fact.fact_id for fact in selected),
            omitted_fact_ids=omitted,
            redacted_fact_ids=redacted,
            destination=destination,
            policy_ref=spec.policy_ref,
            token_budget=sum(_fact_token_cost(fact) for fact in selected),
            row_budget=len(selected),
            raw_rows_rejected=raw_rows_rejected,
            restriction_reason=restriction_reason,
        )
        return EvidenceProjectionV1(
            consumer_id=spec.consumer_id,
            consumer_version=spec.semantic_version,
            projection_ref=spec.projection_ref,
            artifact_ref=record.artifact_ref,
            commit_id=record.commit_id,
            envelope_ref=record.envelope_ref,
            envelope_digest=record.envelope_digest,
            result_identity=record.envelope.result_identity,
            execution_status=record.envelope.execution_status.value,
            availability=record.envelope.availability.value,
            completeness_status=record.envelope.completeness_status.value,
            numerical_method=record.envelope.numerical_method.value,
            inference_basis=record.envelope.inference_basis.value,
            evaluation_design=record.envelope.evaluation_design.value,
            validation_summary=record.envelope.validation_summary.to_dict(),
            facts=selected,
            status=status,
            audit=audit,
            lineage_refs=record.envelope.lineage_refs,
        )


def _builtin_ref(kind: str, consumer_id: str) -> ContractRefV1:
    logical_id = f"workbench.consumer_projection.{consumer_id}"
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest=sha256_canonical({"kind": kind, "logical_id": logical_id, "semantic_version": "1.0"}),
    )


def projection_registry_from_catalog(catalog: object | None = None) -> ConsumerProjectionRegistryV1:
    """Build the local adapter registry from the provider contribution refs."""

    if catalog is None:
        from workbench.providers.catalog import load_builtin_catalog

        catalog = load_builtin_catalog()
    providers = getattr(catalog, "providers", ())
    provider = next(
        (candidate for candidate in providers if getattr(candidate, "provider_id", None) == "workbench.consumer_projection"),
        None,
    )
    if provider is None:
        raise EvidenceProjectionError("PROJECTION_PROVIDER_MISSING", "consumer projection provider is not declared")
    path_refs: dict[str, ContractRefV1] = {}
    for path in provider.exposure_paths:
        path_refs.update(path.projection_refs)
    policy_refs = {
        ref.logical_id.rsplit(".", 1)[-1]: ref for ref in provider.policy_refs
    }
    renderer_refs = {
        ref.logical_id.rsplit(".", 1)[-1]: ref for ref in provider.renderer_refs
    }
    specs: list[ConsumerProjectionSpecV1] = []
    for consumer_id, projection_ref in sorted(path_refs.items()):
        policy_ref = policy_refs.get(consumer_id)
        renderer_ref = renderer_refs.get(consumer_id)
        if policy_ref is None or renderer_ref is None:
            raise EvidenceProjectionError(
                "PROJECTION_DECLARATION_INCOMPLETE",
                f"consumer {consumer_id} lacks policy or renderer ref",
            )
        specs.append(
            ConsumerProjectionSpecV1(
                consumer_id=consumer_id,
                semantic_version=projection_ref.semantic_version,
                projection_ref=projection_ref,
                policy_ref=policy_ref,
                renderer_key=renderer_ref.logical_id,
                max_token_budget=4096,
                max_row_budget=64,
                allowed_sensitivity=(SensitivityClassV1.PUBLIC, SensitivityClassV1.INTERNAL),
                ordering=("fact_id",),
            )
        )
    return ConsumerProjectionRegistryV1(tuple(specs))


def default_projection_registry() -> ConsumerProjectionRegistryV1:
    """Return the package-local declarations for the minimum consumer slice."""

    return projection_registry_from_catalog()


__all__ = [
    "ConsumerProjectionRegistryV1",
    "ConsumerProjectionSpecV1",
    "EvidenceProjectionError",
    "EvidenceProjectionV1",
    "PersistedEvidenceEnvelopeV1",
    "ProjectionAuditV1",
    "ProjectionStatus",
    "default_projection_registry",
    "projection_registry_from_catalog",
]
