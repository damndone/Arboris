"""Agent-side proposal binding for high-risk dependency acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..capability_factory.contracts import _digest, _sequence, _text
from ..capability_factory.dependency_contract import DependencyLock
from ..custom_capability.canonical import domain_digest
from .proposals import (
    ProposalConfirmation,
    ProposalError,
    ProposalRevision,
    ProposalStore,
)
from .risk import RiskAuthorization, RiskAuthorizationStore


DEPENDENCY_ACQUISITION_OPERATION = "capability.dependency.acquire"
DEPENDENCY_OPERATION_VERSION = "v1"


class DependencyControlError(ValueError):
    """Raised when dependency acquisition skips an Agent control boundary."""


@dataclass(frozen=True, slots=True)
class DependencyAcquisitionProposal:
    proposal_id: str
    lock_ref: str
    policy_ref: str
    index_snapshot_ref: str
    artifact_refs: tuple[str, ...]
    status: str = "pending_confirmation"
    confirmation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "lock_ref", _digest(self.lock_ref, "lock_ref"))
        object.__setattr__(self, "policy_ref", _digest(self.policy_ref, "policy_ref"))
        object.__setattr__(
            self,
            "index_snapshot_ref",
            _digest(self.index_snapshot_ref, "index_snapshot_ref"),
        )
        refs = _sequence(self.artifact_refs, "artifact_refs")
        if any(len(item) != 64 for item in refs):
            raise DependencyControlError("artifact_refs must contain SHA-256 digests")
        object.__setattr__(self, "artifact_refs", tuple(_digest(item, "artifact_ref") for item in refs))
        if self.status not in {"pending_confirmation", "confirmed"}:
            raise DependencyControlError("unsupported dependency proposal status")
        if self.status == "confirmed":
            if self.confirmation_ref is None:
                raise DependencyControlError("confirmed proposal needs confirmation_ref")
            object.__setattr__(self, "confirmation_ref", _digest(self.confirmation_ref, "confirmation_ref"))
        elif self.confirmation_ref is not None:
            raise DependencyControlError("pending proposal cannot have confirmation_ref")

    @property
    def operation_id(self) -> str:
        return DEPENDENCY_ACQUISITION_OPERATION

    @property
    def operation_version(self) -> str:
        return DEPENDENCY_OPERATION_VERSION

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
    def user_data_access(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        """CF2 creates a binding only; no fetched code can execute here."""

        return False

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.dependency_acquisition_proposal/v1",
            {
                "proposal_id": self.proposal_id,
                "operation_id": self.operation_id,
                "operation_version": self.operation_version,
                "lock_ref": self.lock_ref,
                "policy_ref": self.policy_ref,
                "index_snapshot_ref": self.index_snapshot_ref,
                "artifact_refs": list(self.artifact_refs),
            },
        )

    def risk_binding(self) -> dict[str, Any]:
        if self.status != "confirmed":
            raise DependencyControlError("dependency acquisition requires user confirmation")
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.content_digest,
            "lock_ref": self.lock_ref,
            "index_snapshot_ref": self.index_snapshot_ref,
            "risk_level": self.risk_level,
            "risk_authorization_policy": self.risk_authorization_policy,
        }


@dataclass(frozen=True, slots=True)
class DependencyAuthorizationReceipt:
    """The durable proposal/risk boundary; it intentionally has no executor."""

    proposal: DependencyAcquisitionProposal
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
        raise DependencyControlError(str(error)) from error


class DependencyAcquisitionControl:
    """Produce a high-risk proposal without registering an executable tool."""

    def create_proposal(
        self,
        *,
        lock: DependencyLock,
        index_snapshot_ref: str,
        proposal_id: str,
    ) -> DependencyAcquisitionProposal:
        if not isinstance(lock, DependencyLock):
            raise DependencyControlError("lock must be a DependencyLock")
        return DependencyAcquisitionProposal(
            proposal_id=proposal_id,
            lock_ref=lock.content_digest,
            policy_ref=lock.resolver_policy_digest,
            index_snapshot_ref=index_snapshot_ref,
            artifact_refs=tuple(item.artifact_digest for item in lock.requirements),
        )

    def confirm(
        self,
        proposal: DependencyAcquisitionProposal,
        *,
        confirmation_ref: str,
    ) -> DependencyAcquisitionProposal:
        if not isinstance(proposal, DependencyAcquisitionProposal):
            raise DependencyControlError("proposal must be a DependencyAcquisitionProposal")
        if proposal.status != "pending_confirmation":
            raise DependencyControlError("dependency proposal is not pending confirmation")
        try:
            confirmation_ref = _digest(confirmation_ref, "confirmation_ref")
        except ValueError as error:
            raise DependencyControlError(str(error)) from error
        return DependencyAcquisitionProposal(
            proposal_id=proposal.proposal_id,
            lock_ref=proposal.lock_ref,
            policy_ref=proposal.policy_ref,
            index_snapshot_ref=proposal.index_snapshot_ref,
            artifact_refs=proposal.artifact_refs,
            status="confirmed",
            confirmation_ref=confirmation_ref,
        )

    def persist_proposal(
        self,
        proposal: DependencyAcquisitionProposal,
        *,
        root: Path | str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        command_id: str | None = None,
    ) -> ProposalRevision:
        """Persist one dependency proposal in the existing append-only store."""

        if not isinstance(proposal, DependencyAcquisitionProposal):
            raise DependencyControlError("proposal must be a DependencyAcquisitionProposal")
        session_id = _require_context(session_id, "session_id")
        chain_id = _require_context(chain_id, "chain_id")
        active_head_run_id = _require_context(active_head_run_id, "active_head_run_id")
        return ProposalStore(root).create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=proposal.operation_id,
            operation_version=proposal.operation_version,
            target={
                "dependency_proposal_digest": proposal.content_digest,
                "lock_ref": proposal.lock_ref,
                "index_snapshot_ref": proposal.index_snapshot_ref,
            },
            preconditions={
                "context_fingerprint": proposal.content_digest,
                "active_head_run_id": active_head_run_id,
            },
            changes={
                "artifact_refs": list(proposal.artifact_refs),
                "policy_ref": proposal.policy_ref,
            },
            evidence_refs=[
                f"dependency-lock:{proposal.lock_ref}",
                f"index-snapshot:{proposal.index_snapshot_ref}",
            ],
            expected_effect=["fetch locked artifacts into quarantine only"],
            risks=[
                "external dependency acquisition requires explicit high-risk authorization",
                "no user data access",
                "no fetched-code execution",
            ],
            command_id=command_id,
            proposal_id=proposal.proposal_id,
        )

    def confirm_persisted_proposal(
        self,
        proposal: DependencyAcquisitionProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> ProposalConfirmation:
        """Use ProposalStore's stale-checking confirmation gate."""

        if not isinstance(proposal, DependencyAcquisitionProposal):
            raise DependencyControlError("proposal must be a DependencyAcquisitionProposal")
        store = ProposalStore(root, create=False)
        latest = store.latest_revision(proposal.proposal_id)
        if latest.target.get("dependency_proposal_digest") != proposal.content_digest:
            raise DependencyControlError("persisted proposal is not bound to this dependency proposal")
        confirmation = store.confirm(
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
        """Issue the existing one-time high-risk grant, but never consume it."""

        if not isinstance(confirmation, ProposalConfirmation) or confirmation.status != "confirmed":
            raise DependencyControlError("a confirmed ProposalConfirmation is required")
        if confirmation.operation_id != DEPENDENCY_ACQUISITION_OPERATION:
            raise DependencyControlError("confirmation is not for dependency acquisition")
        current_active_head_run_id = _require_context(
            current_active_head_run_id,
            "current_active_head_run_id",
        )
        expected_head = confirmation.preconditions.get("active_head_run_id")
        if expected_head != current_active_head_run_id:
            raise DependencyControlError("active head changed before risk authorization")
        try:
            stored = ProposalStore(root, create=False).validate_confirmation_preconditions(
                confirmation.proposal_id,
                current_context_fingerprint=confirmation.preconditions.get(
                    "context_fingerprint"
                ),
                current_active_head_run_id=current_active_head_run_id,
            )
        except (KeyError, OSError, ProposalError, ValueError) as error:
            raise DependencyControlError(
                "durable proposal confirmation is unavailable"
            ) from error
        if stored != confirmation:
            raise DependencyControlError(
                "risk authorization confirmation does not match the durable proposal"
            )
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
        proposal: DependencyAcquisitionProposal,
        *,
        root: Path | str,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
        ttl_seconds: int = 300,
    ) -> DependencyAuthorizationReceipt:
        """Run proposal confirmation and risk issuance as one bounded lifecycle."""

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
        return DependencyAuthorizationReceipt(
            proposal=confirmed,
            proposal_revision=ProposalStore(root, create=False).latest_revision(
                proposal.proposal_id
            ),
            confirmation=confirmation,
            risk_authorization=grant,
        )


__all__ = [
    "DEPENDENCY_ACQUISITION_OPERATION",
    "DEPENDENCY_OPERATION_VERSION",
    "DependencyAcquisitionControl",
    "DependencyAcquisitionProposal",
    "DependencyAuthorizationReceipt",
    "DependencyControlError",
]
