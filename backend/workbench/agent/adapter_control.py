"""Proposal/risk binding for CF3 adapters without an execution surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capability_factory.adapter_contract import AdapterContract
from ..capability_factory.contracts import _digest, _text
from ..capability_factory.validation_contract import ValidationBundle
from ..custom_capability.canonical import domain_digest
from .proposals import ProposalConfirmation, ProposalError, ProposalRevision, ProposalStore
from .risk import RiskAuthorization, RiskAuthorizationStore


ADAPTER_PROPOSAL_OPERATION = "capability.adapter.propose"
ADAPTER_OPERATION_VERSION = "v1"


class AdapterControlError(ValueError):
    """Raised when an adapter proposal crosses a control boundary incorrectly."""


@dataclass(frozen=True, slots=True)
class AdapterProposal:
    proposal_id: str
    adapter_ref: str
    implementation_ref: str
    validation_bundle_ref: str
    status: str = "pending_confirmation"
    confirmation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        for field in ("adapter_ref", "implementation_ref", "validation_bundle_ref"):
            try:
                object.__setattr__(self, field, _digest(getattr(self, field), field))
            except ValueError as error:
                raise AdapterControlError(str(error)) from error
        if self.status not in {"pending_confirmation", "confirmed"}:
            raise AdapterControlError("unsupported adapter proposal status")
        if self.status == "confirmed":
            if self.confirmation_ref is None:
                raise AdapterControlError("confirmed proposal needs confirmation_ref")
            object.__setattr__(self, "confirmation_ref", _digest(self.confirmation_ref, "confirmation_ref"))
        elif self.confirmation_ref is not None:
            raise AdapterControlError("pending proposal cannot have confirmation_ref")

    @property
    def operation_id(self) -> str:
        return ADAPTER_PROPOSAL_OPERATION

    @property
    def operation_version(self) -> str:
        return ADAPTER_OPERATION_VERSION

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
        """Admission is a later control-plane decision, never this proposal."""

        return False

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.adapter_proposal/v1",
            {
                "proposal_id": self.proposal_id,
                "operation_id": self.operation_id,
                "operation_version": self.operation_version,
                "adapter_ref": self.adapter_ref,
                "implementation_ref": self.implementation_ref,
                "validation_bundle_ref": self.validation_bundle_ref,
            },
        )

    def risk_binding(self) -> dict[str, Any]:
        if self.status != "confirmed":
            raise AdapterControlError("adapter proposal requires user confirmation")
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.content_digest,
            "adapter_ref": self.adapter_ref,
            "validation_bundle_ref": self.validation_bundle_ref,
            "risk_level": self.risk_level,
            "risk_authorization_policy": self.risk_authorization_policy,
        }


@dataclass(frozen=True, slots=True)
class AdapterAuthorizationReceipt:
    proposal: AdapterProposal
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
        raise AdapterControlError(str(error)) from error


class AdapterProposalControl:
    """Persist and authorize adapter proposals; it deliberately has no executor."""

    def create_proposal(
        self,
        *,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        proposal_id: str,
    ) -> AdapterProposal:
        if not isinstance(adapter, AdapterContract):
            raise AdapterControlError("adapter must be an AdapterContract")
        if not isinstance(validation_bundle, ValidationBundle):
            raise AdapterControlError("validation_bundle must be a ValidationBundle")
        if validation_bundle.adapter_ref != adapter.content_digest:
            raise AdapterControlError("validation bundle is bound to another adapter")
        return AdapterProposal(
            proposal_id=proposal_id,
            adapter_ref=adapter.content_digest,
            implementation_ref=adapter.implementation_ref,
            validation_bundle_ref=validation_bundle.content_digest,
        )

    def confirm(self, proposal: AdapterProposal, *, confirmation_ref: str) -> AdapterProposal:
        if not isinstance(proposal, AdapterProposal):
            raise AdapterControlError("proposal must be an AdapterProposal")
        if proposal.status != "pending_confirmation":
            raise AdapterControlError("adapter proposal is not pending confirmation")
        try:
            confirmation_ref = _digest(confirmation_ref, "confirmation_ref")
        except ValueError as error:
            raise AdapterControlError(str(error)) from error
        return AdapterProposal(
            proposal_id=proposal.proposal_id,
            adapter_ref=proposal.adapter_ref,
            implementation_ref=proposal.implementation_ref,
            validation_bundle_ref=proposal.validation_bundle_ref,
            status="confirmed",
            confirmation_ref=confirmation_ref,
        )

    def persist_proposal(
        self,
        proposal: AdapterProposal,
        *,
        root: Path | str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        command_id: str | None = None,
    ) -> ProposalRevision:
        if not isinstance(proposal, AdapterProposal):
            raise AdapterControlError("proposal must be an AdapterProposal")
        session_id = _require_context(session_id, "session_id")
        chain_id = _require_context(chain_id, "chain_id")
        active_head_run_id = _require_context(active_head_run_id, "active_head_run_id")
        return ProposalStore(root).create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=proposal.operation_id,
            operation_version=proposal.operation_version,
            target={
                "adapter_proposal_digest": proposal.content_digest,
                "adapter_ref": proposal.adapter_ref,
                "implementation_ref": proposal.implementation_ref,
            },
            preconditions={
                "context_fingerprint": proposal.content_digest,
                "active_head_run_id": active_head_run_id,
            },
            changes={"validation_bundle_ref": proposal.validation_bundle_ref},
            evidence_refs=[
                f"adapter:{proposal.adapter_ref}",
                f"validation-bundle:{proposal.validation_bundle_ref}",
            ],
            expected_effect=["record an adapter proposal for later review"],
            risks=[
                "generated adapter requires explicit high-risk review",
                "no user data access",
                "no adapter execution",
            ],
            command_id=command_id,
            proposal_id=proposal.proposal_id,
        )

    def confirm_persisted_proposal(
        self,
        proposal: AdapterProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> ProposalConfirmation:
        if not isinstance(proposal, AdapterProposal):
            raise AdapterControlError("proposal must be an AdapterProposal")
        store = ProposalStore(root, create=False)
        latest = store.latest_revision(proposal.proposal_id)
        if latest.target.get("adapter_proposal_digest") != proposal.content_digest:
            raise AdapterControlError("persisted proposal is not bound to this adapter proposal")
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
            raise AdapterControlError("a confirmed ProposalConfirmation is required")
        if confirmation.operation_id != ADAPTER_PROPOSAL_OPERATION:
            raise AdapterControlError("confirmation is not for adapter proposal")
        current_active_head_run_id = _require_context(current_active_head_run_id, "current_active_head_run_id")
        if confirmation.preconditions.get("active_head_run_id") != current_active_head_run_id:
            raise AdapterControlError("active head changed before risk authorization")
        try:
            stored = ProposalStore(root, create=False).validate_confirmation_preconditions(
                confirmation.proposal_id,
                current_context_fingerprint=confirmation.preconditions.get("context_fingerprint"),
                current_active_head_run_id=current_active_head_run_id,
            )
        except (KeyError, OSError, ProposalError, ValueError) as error:
            raise AdapterControlError("durable adapter proposal confirmation is unavailable") from error
        if stored != confirmation:
            raise AdapterControlError("risk grant confirmation does not match the durable proposal")
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
        proposal: AdapterProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        ttl_seconds: int = 300,
    ) -> AdapterAuthorizationReceipt:
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
        return AdapterAuthorizationReceipt(
            proposal=confirmed,
            proposal_revision=ProposalStore(root, create=False).latest_revision(proposal.proposal_id),
            confirmation=confirmation,
            risk_authorization=grant,
        )


__all__ = [
    "ADAPTER_OPERATION_VERSION",
    "ADAPTER_PROPOSAL_OPERATION",
    "AdapterAuthorizationReceipt",
    "AdapterControlError",
    "AdapterProposal",
    "AdapterProposalControl",
]
