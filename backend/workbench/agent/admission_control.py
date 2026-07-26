"""High-risk proposal binding for scoped capability admission."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capability_factory.admission_contract import (
    CapabilityAdmissionController,
    EVIDENCE_TIERS,
    SCOPE_KINDS,
    ScopedAdmissionRecord,
)
from ..capability_factory.contracts import _digest, _text
from ..custom_capability.canonical import domain_digest
from .proposals import ProposalConfirmation, ProposalError, ProposalRevision, ProposalStore
from .risk import RiskAuthorization, RiskAuthorizationStore


ADMISSION_PROPOSAL_OPERATION = "capability.admission.propose"
ADMISSION_OPERATION_VERSION = "v1"


class CapabilityAdmissionControlError(ValueError):
    """Raised when an admission proposal crosses a control boundary incorrectly."""


@dataclass(frozen=True, slots=True)
class CapabilityAdmissionProposal:
    proposal_id: str
    admission_id: str
    admission_ref: str
    adapter_ref: str
    validation_bundle_ref: str
    assessment_ref: str
    scope_kind: str
    scope_ref: str
    minimum_evidence_tier: str
    status: str = "pending_confirmation"
    confirmation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "admission_id", _text(self.admission_id, "admission_id"))
        for field in (
            "admission_ref",
            "adapter_ref",
            "validation_bundle_ref",
            "assessment_ref",
        ):
            try:
                object.__setattr__(self, field, _digest(getattr(self, field), field))
            except ValueError as error:
                raise CapabilityAdmissionControlError(str(error)) from error
        if self.scope_kind not in SCOPE_KINDS:
            raise CapabilityAdmissionControlError("unsupported admission scope")
        object.__setattr__(self, "scope_ref", _text(self.scope_ref, "scope_ref"))
        if self.minimum_evidence_tier not in EVIDENCE_TIERS:
            raise CapabilityAdmissionControlError("unsupported minimum evidence tier")
        if self.status not in {"pending_confirmation", "confirmed"}:
            raise CapabilityAdmissionControlError("unsupported admission proposal status")
        if self.status == "confirmed":
            if self.confirmation_ref is None:
                raise CapabilityAdmissionControlError("confirmed proposal needs confirmation_ref")
            object.__setattr__(self, "confirmation_ref", _digest(self.confirmation_ref, "confirmation_ref"))
        elif self.confirmation_ref is not None:
            raise CapabilityAdmissionControlError("pending proposal cannot have confirmation_ref")

    @property
    def operation_id(self) -> str:
        return ADMISSION_PROPOSAL_OPERATION

    @property
    def operation_version(self) -> str:
        return ADMISSION_OPERATION_VERSION

    @property
    def risk_level(self) -> str:
        return "high"

    @property
    def confirmation_policy(self) -> str:
        return "required"

    @property
    def risk_authorization_policy(self) -> str:
        return "explicit_single_use"

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def source_eligible(self) -> bool:
        """Admission approval never changes the assessment's evidence tier."""

        return False

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.admission_proposal/v1",
            {
                "proposal_id": self.proposal_id,
                "admission_id": self.admission_id,
                "operation_id": self.operation_id,
                "operation_version": self.operation_version,
                "admission_ref": self.admission_ref,
                "adapter_ref": self.adapter_ref,
                "validation_bundle_ref": self.validation_bundle_ref,
                "assessment_ref": self.assessment_ref,
                "scope_kind": self.scope_kind,
                "scope_ref": self.scope_ref,
                "minimum_evidence_tier": self.minimum_evidence_tier,
            },
        )

    def risk_binding(self) -> dict[str, Any]:
        if self.status != "confirmed":
            raise CapabilityAdmissionControlError("admission proposal requires user confirmation")
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.content_digest,
            "admission_ref": self.admission_ref,
            "adapter_ref": self.adapter_ref,
            "validation_bundle_ref": self.validation_bundle_ref,
            "assessment_ref": self.assessment_ref,
            "scope_kind": self.scope_kind,
            "scope_ref": self.scope_ref,
            "minimum_evidence_tier": self.minimum_evidence_tier,
            "risk_level": self.risk_level,
            "risk_authorization_policy": self.risk_authorization_policy,
        }


@dataclass(frozen=True, slots=True)
class CapabilityAdmissionAuthorizationReceipt:
    proposal: CapabilityAdmissionProposal
    proposal_revision: ProposalRevision
    confirmation: ProposalConfirmation
    risk_authorization: RiskAuthorization

    @property
    def execution_allowed(self) -> bool:
        return False


def _require_context(value: str, field: str) -> str:
    try:
        return _text(value, field)
    except ValueError as error:
        raise CapabilityAdmissionControlError(str(error)) from error


class CapabilityAdmissionProposalControl:
    """Bind admission review to existing proposal and risk stores only."""

    def create_proposal(self, record: ScopedAdmissionRecord) -> CapabilityAdmissionProposal:
        if not isinstance(record, ScopedAdmissionRecord):
            raise CapabilityAdmissionControlError("record must be a ScopedAdmissionRecord")
        if record.status != "proposed":
            raise CapabilityAdmissionControlError("only proposed admissions can enter review")
        return CapabilityAdmissionProposal(
            proposal_id=f"proposal.{record.admission_id}",
            admission_id=record.admission_id,
            admission_ref=record.content_digest,
            adapter_ref=record.adapter_ref,
            validation_bundle_ref=record.validation_bundle_ref,
            assessment_ref=record.assessment_ref,
            scope_kind=record.scope_kind,
            scope_ref=record.scope_ref,
            minimum_evidence_tier=record.minimum_evidence_tier,
        )

    def confirm(
        self,
        proposal: CapabilityAdmissionProposal,
        *,
        confirmation_ref: str,
    ) -> CapabilityAdmissionProposal:
        if not isinstance(proposal, CapabilityAdmissionProposal):
            raise CapabilityAdmissionControlError("proposal must be a CapabilityAdmissionProposal")
        if proposal.status != "pending_confirmation":
            raise CapabilityAdmissionControlError("admission proposal is not pending confirmation")
        try:
            confirmation_ref = _digest(confirmation_ref, "confirmation_ref")
        except ValueError as error:
            raise CapabilityAdmissionControlError(str(error)) from error
        return CapabilityAdmissionProposal(
            proposal_id=proposal.proposal_id,
            admission_id=proposal.admission_id,
            admission_ref=proposal.admission_ref,
            adapter_ref=proposal.adapter_ref,
            validation_bundle_ref=proposal.validation_bundle_ref,
            assessment_ref=proposal.assessment_ref,
            scope_kind=proposal.scope_kind,
            scope_ref=proposal.scope_ref,
            minimum_evidence_tier=proposal.minimum_evidence_tier,
            status="confirmed",
            confirmation_ref=confirmation_ref,
        )

    def persist_proposal(
        self,
        proposal: CapabilityAdmissionProposal,
        *,
        root: Path | str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        command_id: str | None = None,
    ) -> ProposalRevision:
        if not isinstance(proposal, CapabilityAdmissionProposal):
            raise CapabilityAdmissionControlError("proposal must be a CapabilityAdmissionProposal")
        session_id = _require_context(session_id, "session_id")
        chain_id = _require_context(chain_id, "chain_id")
        active_head_run_id = _require_context(active_head_run_id, "active_head_run_id")
        return ProposalStore(root).create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=proposal.operation_id,
            operation_version=proposal.operation_version,
            target={
                "admission_proposal_digest": proposal.content_digest,
                "admission_ref": proposal.admission_ref,
                "adapter_ref": proposal.adapter_ref,
                "assessment_ref": proposal.assessment_ref,
            },
            preconditions={
                "context_fingerprint": proposal.content_digest,
                "active_head_run_id": active_head_run_id,
            },
            changes={
                "validation_bundle_ref": proposal.validation_bundle_ref,
                "scope_kind": proposal.scope_kind,
                "scope_ref": proposal.scope_ref,
                "minimum_evidence_tier": proposal.minimum_evidence_tier,
            },
            evidence_refs=[
                f"admission:{proposal.admission_ref}",
                f"adapter:{proposal.adapter_ref}",
                f"assessment:{proposal.assessment_ref}",
            ],
            expected_effect=["record a scoped capability admission proposal for review"],
            risks=[
                "capability admission requires explicit high-risk review",
                "no user data access",
                "no adapter execution",
            ],
            command_id=command_id,
            proposal_id=proposal.proposal_id,
        )

    def confirm_persisted_proposal(
        self,
        proposal: CapabilityAdmissionProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> ProposalConfirmation:
        if not isinstance(proposal, CapabilityAdmissionProposal):
            raise CapabilityAdmissionControlError("proposal must be a CapabilityAdmissionProposal")
        store = ProposalStore(root, create=False)
        latest = store.latest_revision(proposal.proposal_id)
        if latest.target.get("admission_proposal_digest") != proposal.content_digest:
            raise CapabilityAdmissionControlError("durable proposal is not bound to this admission proposal")
        store.confirm(
            proposal.proposal_id,
            revision=revision,
            fingerprint=fingerprint,
            actor_type=_require_context(actor_type, "actor_type"),
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
        )
        return store.validate_confirmation_preconditions(
            proposal.proposal_id,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
        )

    def issue_risk_authorization(
        self,
        confirmation: ProposalConfirmation,
        *,
        root: Path | str,
        current_active_head_run_id: str,
        actor_type: str,
        ttl_seconds: int = 300,
    ) -> RiskAuthorization:
        if not isinstance(confirmation, ProposalConfirmation) or confirmation.status != "confirmed":
            raise CapabilityAdmissionControlError("a confirmed ProposalConfirmation is required")
        if confirmation.operation_id != ADMISSION_PROPOSAL_OPERATION:
            raise CapabilityAdmissionControlError("confirmation is not for capability admission")
        current_active_head_run_id = _require_context(current_active_head_run_id, "current_active_head_run_id")
        if confirmation.preconditions.get("active_head_run_id") != current_active_head_run_id:
            raise CapabilityAdmissionControlError("active head changed before risk authorization")
        try:
            stored = ProposalStore(root, create=False).validate_confirmation_preconditions(
                confirmation.proposal_id,
                current_context_fingerprint=confirmation.preconditions.get("context_fingerprint"),
                current_active_head_run_id=current_active_head_run_id,
            )
        except (KeyError, OSError, ProposalError, ValueError) as error:
            raise CapabilityAdmissionControlError("durable admission proposal confirmation is unavailable") from error
        if stored != confirmation:
            raise CapabilityAdmissionControlError("risk grant confirmation does not match the durable proposal")
        return RiskAuthorizationStore(root).issue(
            operation_id=confirmation.operation_id,
            operation_version=confirmation.operation_version,
            proposal_id=confirmation.proposal_id,
            revision=confirmation.revision,
            fingerprint=confirmation.fingerprint,
            session_id=confirmation.session_id,
            chain_id=confirmation.chain_id,
            active_head_run_id=current_active_head_run_id,
            actor_type=_require_context(actor_type, "actor_type"),
            ttl_seconds=ttl_seconds,
        )

    def authorize_persisted_proposal(
        self,
        proposal: CapabilityAdmissionProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        ttl_seconds: int = 300,
    ) -> CapabilityAdmissionAuthorizationReceipt:
        confirmation = self.confirm_persisted_proposal(
            proposal,
            root=root,
            revision=revision,
            fingerprint=fingerprint,
            actor_type=actor_type,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=current_active_head_run_id,
        )
        grant = self.issue_risk_authorization(
            confirmation,
            root=root,
            current_active_head_run_id=str(current_active_head_run_id or ""),
            actor_type=actor_type,
            ttl_seconds=ttl_seconds,
        )
        confirmed = self.confirm(proposal, confirmation_ref=confirmation.fingerprint)
        return CapabilityAdmissionAuthorizationReceipt(
            proposal=confirmed,
            proposal_revision=ProposalStore(root, create=False).latest_revision(proposal.proposal_id),
            confirmation=confirmation,
            risk_authorization=grant,
        )

    def complete_admission(
        self,
        *,
        admission_controller: CapabilityAdmissionController,
        proposal: CapabilityAdmissionProposal,
        receipt: CapabilityAdmissionAuthorizationReceipt,
        approver_ref: str,
    ) -> ScopedAdmissionRecord:
        """Apply one issued risk receipt to the matching scoped record.

        This changes only the control-plane admission state.  The risk grant
        remains issued and no adapter operation is dispatched or consumed.
        """

        if not isinstance(admission_controller, CapabilityAdmissionController):
            raise CapabilityAdmissionControlError(
                "admission_controller must be a CapabilityAdmissionController"
            )
        if not isinstance(proposal, CapabilityAdmissionProposal):
            raise CapabilityAdmissionControlError("proposal must be a CapabilityAdmissionProposal")
        if not isinstance(receipt, CapabilityAdmissionAuthorizationReceipt):
            raise CapabilityAdmissionControlError("receipt must be an admission authorization receipt")
        if receipt.proposal.content_digest != proposal.content_digest:
            raise CapabilityAdmissionControlError("receipt is not bound to this admission proposal")
        if receipt.confirmation.status != "confirmed":
            raise CapabilityAdmissionControlError("admission receipt is not confirmed")
        grant = receipt.risk_authorization
        if (
            grant.status != "issued"
            or grant.operation_id != proposal.operation_id
            or grant.proposal_id != proposal.proposal_id
            or grant.fingerprint != receipt.confirmation.fingerprint
        ):
            raise CapabilityAdmissionControlError("risk grant is not bound to this admission receipt")
        current = admission_controller.latest(proposal.admission_id)
        if current.content_digest != proposal.admission_ref:
            raise CapabilityAdmissionControlError(
                "current admission record does not match the confirmed proposal"
            )
        return admission_controller.admit(
            proposal.admission_id,
            approver_ref=_require_context(approver_ref, "approver_ref"),
            approval_ref=receipt.confirmation.fingerprint,
        )


__all__ = [
    "ADMISSION_OPERATION_VERSION",
    "ADMISSION_PROPOSAL_OPERATION",
    "CapabilityAdmissionAuthorizationReceipt",
    "CapabilityAdmissionControlError",
    "CapabilityAdmissionProposal",
    "CapabilityAdmissionProposalControl",
]
