"""Immutable binding consumed by Notebook capability options.

This module joins already-created CF1 resolution, CF3 adapter, and CF4
assessment/admission facts.  It does not resolve, load, or execute anything;
the binding is a content-addressed handoff that later Notebook and runtime
gates can verify against their authoritative stores.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapter_contract import AdapterContract
from .admission_contract import (
    CapabilityAdmissionController,
    EVIDENCE_TIERS,
    SCOPE_KINDS,
    EvidenceAssessment,
    ScopedAdmissionRecord,
)
from .validation_contract import ValidationBundle
from .freshness import ValidityCursorSnapshot
from .contracts import (
    ContractError,
    ResolutionBinding,
    _content_digest,
    _digest,
    _sequence,
    _text,
)


CAPABILITY_RESOLUTION_BINDING_SCHEMA_VERSION = (
    "workbench_capability_factory_resolution_binding_v1"
)
_EVIDENCE_RANK = {tier: rank for rank, tier in enumerate(EVIDENCE_TIERS)}


class CapabilityResolutionBindingError(ContractError):
    """Raised when resolution and admission facts cannot be joined safely."""


@dataclass(frozen=True, slots=True)
class CapabilityResolutionBinding:
    """A typed, execution-free join of one resolved capability and admission."""

    resolution_binding_ref: str
    implementation_ref: str
    adapter_ref: str
    validation_bundle_ref: str
    assessment_ref: str
    admission_id: str
    admission_ref: str
    runtime_policy_ref: str
    validity_cursor_ref: str
    scope_kind: str
    scope_ref: str
    minimum_evidence_tier: str
    allowed_operations: tuple[str, ...]
    allowed_consumers: tuple[str, ...]
    # This is the exact CF2 bundle consumed by the runtime gate.  It is
    # optional only for backwards-compatible in-process/native fixtures; a
    # production registration must provide the sealed bundle's dependency
    # reference explicitly.
    dependency_bundle_ref: str | None = None
    schema_version: str = CAPABILITY_RESOLUTION_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            if self.schema_version != CAPABILITY_RESOLUTION_BINDING_SCHEMA_VERSION:
                raise CapabilityResolutionBindingError("unsupported resolution binding schema")
            for field in (
                "resolution_binding_ref",
                "implementation_ref",
                "adapter_ref",
                "validation_bundle_ref",
                "assessment_ref",
                "admission_ref",
                "runtime_policy_ref",
                "validity_cursor_ref",
            ):
                object.__setattr__(self, field, _digest(getattr(self, field), field))
            dependency_bundle_ref = self.dependency_bundle_ref
            if dependency_bundle_ref is None:
                dependency_bundle_ref = self.validation_bundle_ref
            object.__setattr__(
                self,
                "dependency_bundle_ref",
                _digest(dependency_bundle_ref, "dependency_bundle_ref"),
            )
            object.__setattr__(self, "admission_id", _text(self.admission_id, "admission_id"))
            if self.scope_kind not in SCOPE_KINDS:
                raise CapabilityResolutionBindingError("unsupported binding scope")
            object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
            if self.minimum_evidence_tier not in EVIDENCE_TIERS:
                raise CapabilityResolutionBindingError("unsupported binding evidence tier")
            object.__setattr__(
                self,
                "allowed_operations",
                _sequence(self.allowed_operations, "allowed_operations"),
            )
            object.__setattr__(
                self,
                "allowed_consumers",
                _sequence(self.allowed_consumers, "allowed_consumers", allow_empty=True),
            )
        except ContractError as error:
            if isinstance(error, CapabilityResolutionBindingError):
                raise
            raise CapabilityResolutionBindingError(str(error)) from error

    @classmethod
    def from_records(
        cls,
        *,
        admission_controller: CapabilityAdmissionController,
        resolution_binding: ResolutionBinding,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment: EvidenceAssessment,
        admission: ScopedAdmissionRecord,
        current_validity: ValidityCursorSnapshot,
        dependency_bundle_ref: str | None = None,
    ) -> "CapabilityResolutionBinding":
        """Join exact immutable records without consulting mutable registries."""

        if not isinstance(admission_controller, CapabilityAdmissionController):
            raise CapabilityResolutionBindingError(
                "admission_controller must be a CapabilityAdmissionController"
            )
        if not isinstance(resolution_binding, ResolutionBinding):
            raise CapabilityResolutionBindingError(
                "resolution_binding must be a ResolutionBinding"
            )
        if not isinstance(adapter, AdapterContract):
            raise CapabilityResolutionBindingError("adapter must be an AdapterContract")
        if not isinstance(validation_bundle, ValidationBundle):
            raise CapabilityResolutionBindingError(
                "validation_bundle must be a ValidationBundle"
            )
        if not isinstance(assessment, EvidenceAssessment):
            raise CapabilityResolutionBindingError(
                "assessment must be an EvidenceAssessment"
            )
        if not isinstance(admission, ScopedAdmissionRecord):
            raise CapabilityResolutionBindingError(
                "admission must be a ScopedAdmissionRecord"
            )
        if not isinstance(current_validity, ValidityCursorSnapshot):
            raise CapabilityResolutionBindingError(
                "current_validity must be a ValidityCursorSnapshot"
            )
        if admission.status != "admitted":
            raise CapabilityResolutionBindingError(
                "resolution binding requires an admitted admission record"
            )
        if resolution_binding.implementation_ref != adapter.implementation_ref:
            raise CapabilityResolutionBindingError(
                "resolution binding implementation does not match adapter"
            )
        bundle_ref = validation_bundle.content_digest
        if assessment.adapter_ref != adapter.content_digest:
            raise CapabilityResolutionBindingError(
                "assessment is bound to another adapter"
            )
        if assessment.validation_bundle_ref != bundle_ref:
            raise CapabilityResolutionBindingError(
                "assessment does not match validation bundle"
            )
        if admission.adapter_ref != adapter.content_digest:
            raise CapabilityResolutionBindingError(
                "admission is bound to another adapter"
            )
        if admission.validation_bundle_ref != bundle_ref:
            raise CapabilityResolutionBindingError(
                "admission does not match validation bundle"
            )
        if admission.assessment_ref != assessment.content_digest:
            raise CapabilityResolutionBindingError(
                "admission does not match evidence assessment"
            )
        if _EVIDENCE_RANK[assessment.tier] < _EVIDENCE_RANK[admission.minimum_evidence_tier]:
            raise CapabilityResolutionBindingError(
                "assessment evidence tier is below admission floor"
            )
        admission_controller.assert_usable(
            admission,
            adapter=adapter,
            validation_bundle=validation_bundle,
            assessment=assessment,
            runtime_policy_ref=admission.runtime_policy_ref,
            scope_kind=admission.scope_kind,
            scope_ref=admission.scope_ref,
            requested_operations=admission.allowed_operations,
            requested_consumers=admission.allowed_consumers,
        )
        if resolution_binding.validity_cursor_digest != current_validity.content_digest:
            raise CapabilityResolutionBindingError(
                "resolution binding validity cursor is stale"
            )
        return cls(
            resolution_binding_ref=resolution_binding.content_digest,
            implementation_ref=resolution_binding.implementation_ref,
            adapter_ref=adapter.content_digest,
            validation_bundle_ref=bundle_ref,
            assessment_ref=assessment.content_digest,
            admission_id=admission.admission_id,
            admission_ref=admission.content_digest,
            runtime_policy_ref=admission.runtime_policy_ref,
            validity_cursor_ref=resolution_binding.validity_cursor_digest,
            scope_kind=admission.scope_kind,
            scope_ref=admission.scope_ref,
            minimum_evidence_tier=admission.minimum_evidence_tier,
            allowed_operations=admission.allowed_operations,
            allowed_consumers=admission.allowed_consumers,
            dependency_bundle_ref=dependency_bundle_ref,
        )

    @property
    def execution_allowed(self) -> bool:
        """The binding is an identity packet, never an execution grant."""

        return False

    def assert_current(
        self,
        *,
        admission_controller: CapabilityAdmissionController,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        assessment: EvidenceAssessment,
        runtime_policy_ref: str,
        scope_kind: str,
        scope_ref: str,
        current_validity: ValidityCursorSnapshot,
    ) -> None:
        """Verify this binding against current controller and evidence facts."""

        if not isinstance(admission_controller, CapabilityAdmissionController):
            raise CapabilityResolutionBindingError(
                "admission_controller must be a CapabilityAdmissionController"
            )
        if not isinstance(validation_bundle, ValidationBundle):
            raise CapabilityResolutionBindingError(
                "validation_bundle must be a ValidationBundle"
            )
        if not isinstance(current_validity, ValidityCursorSnapshot):
            raise CapabilityResolutionBindingError(
                "current_validity must be a ValidityCursorSnapshot"
            )
        current = admission_controller.latest(self.admission_id)
        if current.content_digest != self.admission_ref:
            raise CapabilityResolutionBindingError(
                "binding admission record is not current"
            )
        if self.adapter_ref != adapter.content_digest:
            raise CapabilityResolutionBindingError("binding adapter does not match")
        if self.validation_bundle_ref != validation_bundle.content_digest:
            raise CapabilityResolutionBindingError(
                "binding validation bundle does not match"
            )
        if self.assessment_ref != assessment.content_digest:
            raise CapabilityResolutionBindingError("binding assessment does not match")
        if self.runtime_policy_ref != _digest(runtime_policy_ref, "runtime_policy_ref"):
            raise CapabilityResolutionBindingError("binding runtime policy does not match")
        if self.validity_cursor_ref != current_validity.content_digest:
            raise CapabilityResolutionBindingError("binding validity cursor is stale")
        if self.scope_kind != scope_kind or self.scope_ref != scope_ref:
            raise CapabilityResolutionBindingError("binding scope does not match")
        admission_controller.assert_usable(
            current,
            adapter=adapter,
            validation_bundle=validation_bundle,
            assessment=assessment,
            runtime_policy_ref=runtime_policy_ref,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            requested_operations=self.allowed_operations,
            requested_consumers=self.allowed_consumers,
        )

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = [
    "CAPABILITY_RESOLUTION_BINDING_SCHEMA_VERSION",
    "CapabilityResolutionBinding",
    "CapabilityResolutionBindingError",
]
