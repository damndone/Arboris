"""Proposal-only guard for Agent-authored capability candidates."""

from __future__ import annotations

from dataclasses import dataclass

from ..capability_factory.contracts import _digest, _text


_AUTHORING_SOURCES = frozenset({"generated_adapter", "authored_implementation"})


@dataclass(frozen=True, slots=True)
class AuthoringRiskDecision:
    candidate_ref: str
    source_kind: str
    risk_level: str
    confirmation_required: bool
    execution_allowed: bool


class CapabilityAuthoringGuard:
    """Classify authoring as high risk without opening an execution surface."""

    def evaluate(self, *, candidate_ref: str, source_kind: str) -> AuthoringRiskDecision:
        if source_kind not in _AUTHORING_SOURCES:
            raise ValueError("source_kind is not an authoring source")
        return AuthoringRiskDecision(
            candidate_ref=_digest(candidate_ref, "candidate_ref"),
            source_kind=_text(source_kind, "source_kind"),
            risk_level="high",
            confirmation_required=True,
            execution_allowed=False,
        )


__all__ = ["AuthoringRiskDecision", "CapabilityAuthoringGuard"]
