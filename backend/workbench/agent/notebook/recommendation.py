"""Evidence-gated, batch-level Notebook recommendation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import (
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    RecommendationDecision,
    RecommendationDecisionV11,
    _candidate_cohort_hash,
)
from .evidence import DataEvidencePackV1, EvidenceRecord
from .proposal import OptionDraft


class RecommendationValidationError(ValueError):
    """A recommendation protocol or candidate batch is not comparable."""


def candidate_cohort_hash(option_ids: Sequence[str]) -> str:
    """Return the order-independent identity of a complete candidate cohort."""

    ids = tuple(option_ids)
    if not ids or any(not isinstance(option_id, str) or not option_id for option_id in ids):
        raise RecommendationValidationError("candidate cohort must contain option ids")
    if len(set(ids)) != len(ids):
        raise RecommendationValidationError("candidate cohort option ids must be unique")
    return _candidate_cohort_hash(ids)


@dataclass(frozen=True)
class ProtocolResult:
    protocol_id: str
    protocol_version: str
    cohort: str
    scores: Mapping[str, float]
    margin: float
    direction: str = "lower_is_better"
    evidence_ids: tuple[str, ...] = ()
    reason_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.protocol_id or not self.protocol_version or not self.cohort:
            raise RecommendationValidationError("protocol identity is required")
        if self.direction not in {"lower_is_better", "higher_is_better"}:
            raise RecommendationValidationError("protocol direction is invalid")
        if type(self.margin) not in {int, float} or self.margin < 0:
            raise RecommendationValidationError("protocol margin must be nonnegative")
        if not isinstance(self.scores, Mapping):
            raise RecommendationValidationError("protocol scores must be a mapping")


class RecommendationProtocol(Protocol):
    protocol_id: str

    def evaluate(
        self,
        candidates: tuple[OptionDraft, ...],
        evidence: DataEvidencePackV1,
    ) -> ProtocolResult: ...


class ForecastRollingOriginProtocol:
    """Consume only declared rolling-origin evidence, never a global score."""

    protocol_id = "forecast.v1"

    def evaluate(
        self,
        candidates: tuple[OptionDraft, ...],
        evidence: DataEvidencePackV1,
    ) -> ProtocolResult:
        records = [
            record
            for record in evidence.records
            if record.inspection_id == "forecast_rolling_origin.v1"
            and record.status == "completed"
        ]
        if not records or any(record.status != "completed" for record in evidence.records if record.inspection_id == "forecast_rolling_origin.v1"):
            raise RecommendationValidationError("rolling-origin evidence is missing or incomplete")
        cohorts = {str(record.observations.get("cohort")) for record in records}
        protocols = {record.protocol_version for record in records}
        if len(cohorts) != 1 or len(protocols) != 1:
            raise RecommendationValidationError("rolling-origin evidence has no common cohort")
        scores: dict[str, float] = {}
        evidence_ids: list[str] = []
        for record in records:
            candidate_scores = record.metrics.get("candidate_scores")
            if not isinstance(candidate_scores, Mapping):
                option_id = record.metrics.get("option_id")
                if len(candidates) == 1 and isinstance(option_id, str):
                    candidate_scores = {option_id: record.metrics.get("mae")}
            if not isinstance(candidate_scores, Mapping):
                raise RecommendationValidationError("rolling-origin evidence has no candidate scores")
            for option_id, score in candidate_scores.items():
                if type(score) not in {int, float}:
                    raise RecommendationValidationError("rolling-origin score is not numeric")
                scores[str(option_id)] = float(score)
            evidence_ids.append(record.evidence_id)
        return ProtocolResult(
            protocol_id=self.protocol_id,
            protocol_version=next(iter(protocols)),
            cohort=next(iter(cohorts)),
            scores=scores,
            margin=float(records[0].metrics.get("margin", 0.0)),
            evidence_ids=tuple(evidence_ids),
        )


def _candidate_id(candidate: OptionDraft, index: int) -> str:
    return candidate.option_id or f"candidate_{index + 1}"


def _hard_block(candidate: OptionDraft) -> str | None:
    explicit = getattr(candidate, "blocked_reason", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    proposal = candidate.proposal
    if proposal.preconditions.get("input_contract_valid") is False:
        return "INPUT_CONTRACT_INVALID"
    if proposal.changes.get("blocked") is True:
        return str(proposal.changes.get("blocked_reason") or "CANDIDATE_BLOCKED")
    return None


def _pack_parts(evidence: DataEvidencePackV1) -> tuple[dict[str, EvidenceRecord], bool]:
    records = {record.evidence_id: record for record in evidence.records}
    incomplete = any(record.status != "completed" for record in evidence.records)
    return records, incomplete


class RecommendationValidator:
    """Turn one option batch into exactly one evidence-gated decision."""

    def __init__(self, *, protocols: Mapping[str, RecommendationProtocol] | None = None) -> None:
        self.protocols = dict(protocols or {})

    def decide(
        self,
        *,
        batch_id: str,
        candidates: tuple[OptionDraft, ...],
        evidence_pack: DataEvidencePackV1,
        generation_context_hash: str = "sha256:unbound",
        freshness_dependency_fingerprint: str = "fresh1:unbound",
        evidence_pack_hashes: tuple[str, ...] | None = None,
    ) -> RecommendationDecision:
        if not candidates or len(candidates) > 3:
            raise RecommendationValidationError("candidate batch must contain 1 to 3 options")
        if len({_candidate_id(candidate, index) for index, candidate in enumerate(candidates)}) != len(candidates):
            raise RecommendationValidationError("candidate option ids must be unique")
        records, incomplete = _pack_parts(evidence_pack)
        ids = tuple(_candidate_id(candidate, index) for index, candidate in enumerate(candidates))
        blocked = {option_id: _hard_block(candidate) for option_id, candidate in zip(ids, candidates)}
        blocked = {option_id: reason for option_id, reason in blocked.items() if reason}
        viable = tuple(option_id for option_id in ids if option_id not in blocked)
        reason_refs = tuple(sorted(records))
        pack_hash = evidence_pack.evidence_pack_hash

        for candidate in candidates:
            for evidence_ref in getattr(candidate, "evidence_refs", ()):
                if evidence_ref.evidence_id not in records or records[evidence_ref.evidence_id].result_hash != evidence_ref.result_hash:
                    return self._decision(
                        batch_id=batch_id,
                        ids=ids,
                        outcome="insufficient_evidence",
                        recommended=None,
                        generation_context_hash=generation_context_hash,
                        freshness_dependency_fingerprint=freshness_dependency_fingerprint,
                        evidence_pack_hashes=evidence_pack_hashes or (pack_hash,),
                        protocols=(),
                        reason_refs=reason_refs,
                    )
            for claim in getattr(candidate, "comparative_claims", ()):
                if not any(evidence_id in claim for evidence_id in records):
                    return self._decision(
                        batch_id=batch_id,
                        ids=ids,
                        outcome="insufficient_evidence",
                        recommended=None,
                        generation_context_hash=generation_context_hash,
                        freshness_dependency_fingerprint=freshness_dependency_fingerprint,
                        evidence_pack_hashes=evidence_pack_hashes or (pack_hash,),
                        protocols=(),
                        reason_refs=reason_refs,
                    )

        if len(viable) == 1 and len(blocked) == len(candidates) - 1 and bool(records) and not incomplete:
            outcome = "recommended"
            recommended = viable[0]
            protocols_used: tuple[str, ...] = ()
        elif len(viable) < 2 or incomplete:
            outcome = "insufficient_evidence"
            recommended = None
            protocols_used = ()
        else:
            result = self._evaluate_common_protocol(tuple(candidate for candidate, option_id in zip(candidates, ids) if option_id in viable), evidence_pack)
            if result is None or set(result.scores) != set(viable):
                outcome = "insufficient_evidence"
                recommended = None
                protocols_used = ()
            else:
                ordered = sorted(((float(result.scores[option_id]), option_id) for option_id in viable), key=lambda item: (item[0], item[1]), reverse=result.direction == "higher_is_better")
                gap = abs(ordered[1][0] - ordered[0][0])
                if gap <= float(result.margin):
                    outcome = "tied"
                    recommended = None
                else:
                    outcome = "recommended"
                    recommended = ordered[0][1]
                protocols_used = (f"{result.protocol_id}:{result.protocol_version}",)
                reason_refs = tuple(sorted(set(reason_refs) | set(result.reason_refs) | set(result.evidence_ids)))

        return self._decision(
            batch_id=batch_id,
            ids=ids,
            outcome=outcome,
            recommended=recommended,
            generation_context_hash=generation_context_hash,
            freshness_dependency_fingerprint=freshness_dependency_fingerprint,
            evidence_pack_hashes=evidence_pack_hashes or (pack_hash,),
            protocols=protocols_used,
            reason_refs=reason_refs,
        )

    def decide_v11(
        self,
        *,
        batch_id: str,
        candidate_option_ids: tuple[str, ...],
        generation_context_hash: str,
        freshness_dependency_fingerprint: str,
        evidence_pack_hashes: tuple[str, ...],
        feasibility_decision: FeasibilityDecision | None = None,
        comparison_decision_ref: str | None = None,
    ) -> RecommendationDecisionV11:
        """Build the server-owned recommendation successor.

        The method accepts only candidate identities and a decision produced by
        a registered server protocol.  It deliberately has no ``OptionDraft``
        input, so an Agent's ``blocked_reason`` or preference cannot become a
        trusted feasibility fact.
        """

        ids = tuple(candidate_option_ids)
        cohort_hash = candidate_cohort_hash(ids)
        if not evidence_pack_hashes:
            raise RecommendationValidationError("v1.1 requires evidence pack hashes")
        if (feasibility_decision is None) == (comparison_decision_ref is None):
            raise RecommendationValidationError(
                "exactly one server feasibility or comparison decision is required"
            )

        recommended: str | None = None
        outcome = "insufficient_evidence"
        reason_refs: tuple[str, ...] = ()
        feasibility_ref: str | None = None
        if feasibility_decision is not None:
            if (
                feasibility_decision.batch_id != batch_id
                or feasibility_decision.generation_context_hash != generation_context_hash
                or feasibility_decision.freshness_dependency_fingerprint
                != freshness_dependency_fingerprint
                or feasibility_decision.evidence_pack_hashes != tuple(evidence_pack_hashes)
                or set(feasibility_decision.candidate_option_ids) != set(ids)
                or feasibility_decision.candidate_cohort_hash != cohort_hash
            ):
                raise RecommendationValidationError(
                    "feasibility decision does not cover the requested candidate cohort"
                )
            feasibility_ref = feasibility_decision.feasibility_decision_id
            feasible = tuple(
                item.option_id
                for item in feasibility_decision.candidates
                if item.outcome == "feasible"
            )
            if len(feasible) == 1:
                outcome = "recommended"
                recommended = feasible[0]
            reason_refs = tuple(
                sorted(
                    {
                        ref
                        for item in feasibility_decision.candidates
                        for ref in (*item.inspection_refs, *item.evidence_refs)
                    }
                )
            )
        seed = {
            "batch_id": batch_id,
            "candidate_cohort_hash": cohort_hash,
            "outcome": outcome,
            "recommended_option_id": recommended,
            "feasibility_decision_ref": feasibility_ref,
            "comparison_decision_ref": comparison_decision_ref,
            "evidence_pack_hashes": tuple(evidence_pack_hashes),
        }
        return RecommendationDecisionV11(
            recommendation_decision_id=f"rec11_{sha256_canonical(seed)[:24]}",
            batch_id=batch_id,
            generation_context_hash=generation_context_hash,
            freshness_dependency_fingerprint=freshness_dependency_fingerprint,
            evidence_pack_hashes=tuple(evidence_pack_hashes),
            candidate_option_ids=ids,
            candidate_cohort_hash=cohort_hash,
            outcome=outcome,
            recommended_option_id=recommended,
            feasibility_decision_ref=feasibility_ref,
            comparison_decision_ref=comparison_decision_ref,
            reason_refs=reason_refs,
        )

    @staticmethod
    def _decision(
        *,
        batch_id: str,
        ids: tuple[str, ...],
        outcome: str,
        recommended: str | None,
        generation_context_hash: str,
        freshness_dependency_fingerprint: str,
        evidence_pack_hashes: tuple[str, ...],
        protocols: tuple[str, ...],
        reason_refs: tuple[str, ...],
    ) -> RecommendationDecision:
        seed = {
            "batch_id": batch_id,
            "candidate_option_ids": ids,
            "outcome": outcome,
            "recommended_option_id": recommended,
            "evidence_pack_hashes": evidence_pack_hashes,
            "comparison_protocol_refs": protocols,
        }
        return RecommendationDecision(
            recommendation_decision_id=f"rec_{sha256_canonical(seed)[:24]}",
            batch_id=batch_id,
            generation_context_hash=generation_context_hash,
            freshness_dependency_fingerprint=freshness_dependency_fingerprint,
            evidence_pack_hashes=evidence_pack_hashes,
            comparison_protocol_refs=protocols,
            candidate_option_ids=ids,
            outcome=outcome,
            recommended_option_id=recommended,
            reason_refs=reason_refs,
        )

    def _evaluate_common_protocol(
        self,
        candidates: tuple[OptionDraft, ...],
        evidence_pack: DataEvidencePackV1,
    ) -> ProtocolResult | None:
        for protocol_id in sorted(self.protocols):
            protocol = self.protocols[protocol_id]
            try:
                result = protocol.evaluate(candidates, evidence_pack)
            except (RecommendationValidationError, ValueError, KeyError, TypeError):
                continue
            if not isinstance(result, ProtocolResult):
                continue
            if result.protocol_id != protocol_id:
                continue
            return result
        return None


__all__ = [
    "candidate_cohort_hash",
    "FeasibilityCandidateDecision",
    "FeasibilityDecision",
    "ForecastRollingOriginProtocol",
    "ProtocolResult",
    "RecommendationProtocol",
    "RecommendationDecisionV11",
    "RecommendationValidationError",
    "RecommendationValidator",
]
