"""Evidence assessment and scoped capability admission control contracts.

The records in this module are control-plane facts only.  They do not load a
bundle, run an adapter, or grant a caller an execution primitive.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .adapter_contract import AdapterContract
from .contracts import CONSUMER_SLOTS, ContractError, _content_digest, _digest, _sequence, _text
from .validation_contract import ValidationBundle


ADMISSION_SCHEMA_VERSION = "workbench_capability_factory_admission_v1"
ADMISSION_STATES = frozenset({"proposed", "admitted", "rejected", "expired", "revoked"})
SCOPE_KINDS = frozenset({"project", "run_family", "organization", "release_builtin"})
VALIDITY_STATES = frozenset({"valid", "superseded", "invalid"})
EVIDENCE_TIERS = ("E0", "E1", "E2", "E3")
_EVIDENCE_RANK = {tier: rank for rank, tier in enumerate(EVIDENCE_TIERS)}


class AdmissionContractError(ContractError):
    """Raised when an assessment or scoped admission fails closed."""


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Server-derived evidence for one exact adapter and validation bundle."""

    assessment_id: str
    adapter_ref: str
    validation_bundle_ref: str
    tier: str
    assessment_rule_ref: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
            object.__setattr__(self, "adapter_ref", _digest(self.adapter_ref, "adapter_ref"))
            object.__setattr__(self, "validation_bundle_ref", _digest(self.validation_bundle_ref, "validation_bundle_ref"))
            if self.tier not in EVIDENCE_TIERS:
                raise AdmissionContractError("unsupported evidence tier")
            object.__setattr__(self, "assessment_rule_ref", _digest(self.assessment_rule_ref, "assessment_rule_ref"))
            refs = _sequence(self.evidence_refs, "evidence_refs", allow_empty=True)
            object.__setattr__(self, "evidence_refs", tuple(_digest(item, "evidence_ref") for item in refs))
        except ContractError as error:
            if isinstance(error, AdmissionContractError):
                raise
            raise AdmissionContractError(str(error)) from error

    @classmethod
    def from_validation_bundle(
        cls,
        *,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment_id: str,
        assessment_rule_ref: str,
    ) -> "EvidenceAssessment":
        if not isinstance(adapter, AdapterContract):
            raise AdmissionContractError("adapter must be an AdapterContract")
        if not isinstance(validation_bundle, ValidationBundle):
            raise AdmissionContractError("validation_bundle must be a ValidationBundle")
        if validation_bundle.adapter_ref != adapter.content_digest:
            raise AdmissionContractError("validation bundle is bound to another adapter")

        evidence_by_case = {
            case.content_digest: tuple(item for item in validation_bundle.evidence if item.case_ref == case.content_digest)
            for case in validation_bundle.cases
        }
        every_case_has_independent_evidence = all(
            any(item.source_eligible for item in items) for items in evidence_by_case.values()
        )
        if every_case_has_independent_evidence:
            # E3 evidence is sufficient for the E2 floor, but this slice does
            # not infer the broader E3 suite claim from one holdout contract.
            tier = "E2"
        elif any(item.tier in {"E1", "E2", "E3"} for item in validation_bundle.evidence):
            tier = "E1"
        else:
            tier = "E0"
        return cls(
            assessment_id=assessment_id,
            adapter_ref=adapter.content_digest,
            validation_bundle_ref=validation_bundle.content_digest,
            tier=tier,
            assessment_rule_ref=assessment_rule_ref,
            evidence_refs=tuple(item.content_digest for item in validation_bundle.evidence),
        )

    @property
    def source_eligible(self) -> bool:
        return self.tier in {"E2", "E3"}

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class EvidenceValidityRecord:
    """One append-only validity observation for an assessment."""

    validity_id: str
    assessment_ref: str
    sequence: int
    status: str
    reason_ref: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "validity_id", _text(self.validity_id, "validity_id"))
            object.__setattr__(self, "assessment_ref", _digest(self.assessment_ref, "assessment_ref"))
            if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
                raise AdmissionContractError("sequence must be a positive integer")
            if self.status not in VALIDITY_STATES:
                raise AdmissionContractError("unsupported validity state")
            object.__setattr__(self, "reason_ref", _digest(self.reason_ref, "reason_ref"))
        except ContractError as error:
            if isinstance(error, AdmissionContractError):
                raise
            raise AdmissionContractError(str(error)) from error

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ScopedAdmissionRecord:
    """A scope-limited permission record, independent of evidence tier."""

    admission_id: str
    revision: int
    adapter_ref: str
    validation_bundle_ref: str
    assessment_ref: str
    runtime_policy_ref: str
    scope_kind: str
    scope_ref: str
    minimum_evidence_tier: str
    allowed_operations: tuple[str, ...]
    allowed_consumers: tuple[str, ...]
    status: str = "proposed"
    approver_ref: str | None = None
    approval_ref: str | None = None
    reason_ref: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "admission_id", _text(self.admission_id, "admission_id"))
            if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
                raise AdmissionContractError("revision must be a positive integer")
            for field in ("adapter_ref", "validation_bundle_ref", "assessment_ref", "runtime_policy_ref"):
                object.__setattr__(self, field, _digest(getattr(self, field), field))
            if self.scope_kind not in SCOPE_KINDS:
                raise AdmissionContractError("unsupported admission scope")
            object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
            if self.minimum_evidence_tier not in EVIDENCE_TIERS:
                raise AdmissionContractError("unsupported minimum evidence tier")
            operations = _sequence(self.allowed_operations, "allowed_operations")
            consumers = _sequence(self.allowed_consumers, "allowed_consumers", allow_empty=True)
            if not set(consumers) <= set(CONSUMER_SLOTS):
                raise AdmissionContractError("allowed_consumers contain unknown slots")
            object.__setattr__(self, "allowed_operations", operations)
            object.__setattr__(self, "allowed_consumers", consumers)
            if self.status not in ADMISSION_STATES:
                raise AdmissionContractError("unsupported admission state")
            if self.status == "admitted":
                if self.approver_ref is None or self.approval_ref is None:
                    raise AdmissionContractError("admitted record needs approval identity")
                object.__setattr__(self, "approver_ref", _text(self.approver_ref, "approver_ref"))
                object.__setattr__(self, "approval_ref", _digest(self.approval_ref, "approval_ref"))
            elif self.approver_ref is not None or self.approval_ref is not None:
                raise AdmissionContractError("approval identity is only valid for admitted records")
            if self.reason_ref is not None:
                object.__setattr__(self, "reason_ref", _digest(self.reason_ref, "reason_ref"))
        except ContractError as error:
            if isinstance(error, AdmissionContractError):
                raise
            raise AdmissionContractError(str(error)) from error

    def transition(
        self,
        *,
        status: str,
        approver_ref: str | None = None,
        approval_ref: str | None = None,
        reason_ref: str | None = None,
    ) -> "ScopedAdmissionRecord":
        allowed = {
            "proposed": {"admitted", "rejected"},
            "admitted": {"expired", "revoked"},
        }
        if status not in allowed.get(self.status, set()):
            raise AdmissionContractError(f"invalid admission transition {self.status} -> {status}")
        return replace(
            self,
            revision=self.revision + 1,
            status=status,
            approver_ref=approver_ref,
            approval_ref=approval_ref,
            reason_ref=reason_ref,
        )

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class CapabilityAdmissionController:
    """Append-only assessment validity and scoped admission state."""

    def __init__(self) -> None:
        self._assessments: dict[str, EvidenceAssessment] = {}
        self._validity: dict[str, list[EvidenceValidityRecord]] = {}
        self._admissions: dict[str, list[ScopedAdmissionRecord]] = {}

    def assess(
        self,
        *,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment_id: str,
        assessment_rule_ref: str,
    ) -> EvidenceAssessment:
        assessment = EvidenceAssessment.from_validation_bundle(
            adapter=adapter,
            validation_bundle=validation_bundle,
            assessment_id=assessment_id,
            assessment_rule_ref=assessment_rule_ref,
        )
        if assessment.content_digest in self._assessments:
            raise AdmissionContractError("assessment already exists")
        self._assessments[assessment.content_digest] = assessment
        self._validity[assessment.content_digest] = [
            EvidenceValidityRecord(
                validity_id=f"{assessment.assessment_id}.validity.1",
                assessment_ref=assessment.content_digest,
                sequence=1,
                status="valid",
                reason_ref=assessment.assessment_rule_ref,
            )
        ]
        return assessment

    def invalidate(self, assessment_ref: str, *, reason_ref: str, status: str = "invalid") -> EvidenceValidityRecord:
        assessment_ref = _digest(assessment_ref, "assessment_ref")
        if status not in {"invalid", "superseded"}:
            raise AdmissionContractError("invalidity transition must be invalid or superseded")
        history = self._validity.get(assessment_ref)
        if not history or history[-1].status != "valid":
            raise AdmissionContractError("assessment is not currently valid")
        next_record = EvidenceValidityRecord(
            validity_id=f"{self._assessments[assessment_ref].assessment_id}.validity.{len(history) + 1}",
            assessment_ref=assessment_ref,
            sequence=len(history) + 1,
            status=status,
            reason_ref=reason_ref,
        )
        history.append(next_record)
        return next_record

    def validity(self, assessment_ref: str) -> EvidenceValidityRecord:
        assessment_ref = _digest(assessment_ref, "assessment_ref")
        try:
            return self._validity[assessment_ref][-1]
        except (KeyError, IndexError) as error:
            raise AdmissionContractError("assessment validity is unavailable") from error

    def propose(
        self,
        *,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment: EvidenceAssessment,
        admission_id: str,
        runtime_policy_ref: str,
        scope_kind: str,
        scope_ref: str,
        minimum_evidence_tier: str,
        allowed_operations: tuple[str, ...],
        allowed_consumers: tuple[str, ...],
    ) -> ScopedAdmissionRecord:
        self._assert_binding(adapter, validation_bundle, assessment)
        self._assert_valid_assessment(assessment)
        if _EVIDENCE_RANK[assessment.tier] < _EVIDENCE_RANK.get(minimum_evidence_tier, -1):
            raise AdmissionContractError("evidence tier is below the requested admission floor")
        operations = _sequence(allowed_operations, "allowed_operations")
        if not set(operations) <= set(adapter.operations):
            raise AdmissionContractError("allowed operation is not declared by adapter")
        consumers = _sequence(allowed_consumers, "allowed_consumers", allow_empty=True)
        if not set(consumers) <= {
            slot for slot in CONSUMER_SLOTS if adapter.consumer_support[slot] is not None
        }:
            raise AdmissionContractError("allowed consumer is not declared by adapter")
        record = ScopedAdmissionRecord(
            admission_id=admission_id,
            revision=1,
            adapter_ref=adapter.content_digest,
            validation_bundle_ref=validation_bundle.content_digest,
            assessment_ref=assessment.content_digest,
            runtime_policy_ref=runtime_policy_ref,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            minimum_evidence_tier=minimum_evidence_tier,
            allowed_operations=operations,
            allowed_consumers=consumers,
        )
        if record.admission_id in self._admissions:
            raise AdmissionContractError("admission already exists")
        self._admissions[record.admission_id] = [record]
        return record

    def admit(self, admission_id: str, *, approver_ref: str, approval_ref: str) -> ScopedAdmissionRecord:
        current = self.latest(admission_id)
        self._assert_valid_assessment_ref(current.assessment_ref)
        return self._append(
            current.transition(
                status="admitted",
                approver_ref=approver_ref,
                approval_ref=approval_ref,
            )
        )

    def invalidate_admission(self, admission_id: str, *, reason_ref: str) -> ScopedAdmissionRecord:
        current = self.latest(admission_id)
        return self._append(current.transition(status="revoked", reason_ref=reason_ref))

    def expire(self, admission_id: str, *, reason_ref: str) -> ScopedAdmissionRecord:
        current = self.latest(admission_id)
        return self._append(current.transition(status="expired", reason_ref=reason_ref))

    def latest(self, admission_id: str) -> ScopedAdmissionRecord:
        admission_id = _text(admission_id, "admission_id")
        try:
            return self._admissions[admission_id][-1]
        except (KeyError, IndexError) as error:
            raise AdmissionContractError("admission is unavailable") from error

    def history(self, admission_id: str) -> tuple[ScopedAdmissionRecord, ...]:
        admission_id = _text(admission_id, "admission_id")
        return tuple(self._admissions.get(admission_id, ()))

    def assert_usable(
        self,
        admission: ScopedAdmissionRecord,
        *,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment: EvidenceAssessment,
        runtime_policy_ref: str,
        scope_kind: str,
        scope_ref: str,
        requested_operations: tuple[str, ...],
        requested_consumers: tuple[str, ...],
    ) -> None:
        current = self.latest(admission.admission_id)
        if current != admission:
            raise AdmissionContractError("admission record is not current")
        if admission.status != "admitted":
            raise AdmissionContractError("admission is not active")
        self._assert_binding(adapter, validation_bundle, assessment)
        if admission.adapter_ref != adapter.content_digest or admission.validation_bundle_ref != validation_bundle.content_digest:
            raise AdmissionContractError("admission binding does not match current bundle")
        if admission.assessment_ref != assessment.content_digest:
            raise AdmissionContractError("admission assessment does not match")
        if admission.runtime_policy_ref != _digest(runtime_policy_ref, "runtime_policy_ref"):
            raise AdmissionContractError("runtime policy does not match admission")
        self._assert_valid_assessment(assessment)
        if _EVIDENCE_RANK[assessment.tier] < _EVIDENCE_RANK[admission.minimum_evidence_tier]:
            raise AdmissionContractError("current evidence tier is below admission floor")
        if admission.scope_kind != scope_kind or admission.scope_ref != scope_ref:
            raise AdmissionContractError("admission scope does not match")
        operations = _sequence(requested_operations, "requested_operations")
        consumers = _sequence(requested_consumers, "requested_consumers", allow_empty=True)
        if not set(operations) <= set(admission.allowed_operations):
            raise AdmissionContractError("requested operation is outside admission")
        if not set(consumers) <= set(admission.allowed_consumers):
            raise AdmissionContractError("requested consumer is outside admission")

    def _assert_binding(
        self,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment: EvidenceAssessment,
    ) -> None:
        if not isinstance(adapter, AdapterContract):
            raise AdmissionContractError("adapter must be an AdapterContract")
        if not isinstance(validation_bundle, ValidationBundle):
            raise AdmissionContractError("validation_bundle must be a ValidationBundle")
        if not isinstance(assessment, EvidenceAssessment):
            raise AdmissionContractError("assessment must be an EvidenceAssessment")
        if validation_bundle.adapter_ref != adapter.content_digest:
            raise AdmissionContractError("validation bundle is bound to another adapter")
        if assessment.adapter_ref != adapter.content_digest or assessment.validation_bundle_ref != validation_bundle.content_digest:
            raise AdmissionContractError("assessment binding does not match current capability")

    def _assert_valid_assessment(self, assessment: EvidenceAssessment) -> None:
        self._assert_valid_assessment_ref(assessment.content_digest)

    def _assert_valid_assessment_ref(self, assessment_ref: str) -> None:
        assessment_ref = _digest(assessment_ref, "assessment_ref")
        if assessment_ref not in self._assessments:
            raise AdmissionContractError("assessment is not registered")
        if self.validity(assessment_ref).status != "valid":
            raise AdmissionContractError("assessment validity is not current")

    def _append(self, record: ScopedAdmissionRecord) -> ScopedAdmissionRecord:
        self._admissions[record.admission_id].append(record)
        return record


__all__ = [
    "ADMISSION_SCHEMA_VERSION",
    "ADMISSION_STATES",
    "EVIDENCE_TIERS",
    "EvidenceAssessment",
    "EvidenceValidityRecord",
    "AdmissionContractError",
    "CapabilityAdmissionController",
    "ScopedAdmissionRecord",
    "SCOPE_KINDS",
    "VALIDITY_STATES",
]
