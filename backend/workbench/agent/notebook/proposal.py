"""The typed proposal an option carries, and the draft an agent submits.

Spec §3.2/§3.7: `rationale` and `assumptions` are for humans and take part in no
check whatsoever; what gets executed is only ever the typed proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import ExpectedArtifact, EvidenceRef

CANONICAL_PROPOSAL_HASH_PREFIX = "prop1:"


@dataclass(frozen=True)
class TypedProposal:
    """One executable operation, in the shape `operations.py` already validates."""

    proposal_id: str
    operation_id: str
    target: dict[str, Any] = field(default_factory=dict)
    preconditions: dict[str, Any] = field(default_factory=dict)
    changes: dict[str, Any] = field(default_factory=dict)
    operation_version: str = "v1"
    proposal_revision: int = 1

    def canonical_hash(self) -> str:
        """Content identity, deliberately excluding `proposal_id`.

        Two drafts that differ only by a freshly generated id are the same
        analysis path; §6's duplicate rule exists to catch exactly that, so the
        id must not be able to disguise it.
        """

        return CANONICAL_PROPOSAL_HASH_PREFIX + sha256_canonical(
            {
                "operation_id": self.operation_id,
                "operation_version": self.operation_version,
                "target": self.target,
                "preconditions": self.preconditions,
                "changes": self.changes,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "target": dict(self.target),
            "preconditions": dict(self.preconditions),
            "changes": dict(self.changes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedProposal":
        return cls(
            proposal_id=str(value["proposal_id"]),
            operation_id=str(value["operation_id"]),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            changes=dict(value.get("changes") or {}),
            operation_version=str(value.get("operation_version", "v1")),
            proposal_revision=int(value.get("proposal_revision", 1)),
        )


@dataclass(frozen=True)
class OptionDraft:
    """What an agent planning pass hands in for one option.

    Note what is absent: `risk_level`, `validation_status`, `freshness_status`
    and the two hashes. Those are derived by the service from the operation
    registry and the compiled context — an agent that could assert them could
    assert itself safe.
    """

    rank: int
    rationale: str
    proposal: TypedProposal
    assumptions: tuple[str, ...] = ()
    expected_artifacts: tuple[ExpectedArtifact, ...] = ()
    option_id: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    comparative_claims: tuple[str, ...] = ()
    blocked_reason: str | None = None
    recommendation_decision_id: str | None = None
    recommendation_status: str | None = None


__all__ = ["CANONICAL_PROPOSAL_HASH_PREFIX", "OptionDraft", "TypedProposal"]
