"""Evidence-gated, batch-level Notebook recommendation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import (
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    MAX_RECOMMENDATION_CANDIDATES,
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
    if len(ids) > MAX_RECOMMENDATION_CANDIDATES:
        raise RecommendationValidationError("candidate cohort allows at most 3 options")
    return _candidate_cohort_hash(ids)


def _server_text(value: Any, field: str) -> str:
    if type(value) is not str or not value:
        raise RecommendationValidationError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ComparisonDecisionRecord:
    """A server-registered comparison result bound to one candidate cohort."""

    comparison_decision_id: str
    batch_id: str
    generation_context_hash: str
    freshness_dependency_fingerprint: str
    evidence_pack_hashes: tuple[str, ...]
    candidate_option_ids: tuple[str, ...]
    candidate_cohort_hash: str
    outcome: str
    recommended_option_id: str | None
    protocol_ref: str

    def __post_init__(self) -> None:
        for field in (
            "comparison_decision_id",
            "batch_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "protocol_ref",
        ):
            _server_text(getattr(self, field), field)
        evidence_pack_hashes = tuple(self.evidence_pack_hashes)
        candidate_option_ids = tuple(self.candidate_option_ids)
        if not evidence_pack_hashes or any(not isinstance(item, str) or not item for item in evidence_pack_hashes):
            raise RecommendationValidationError("comparison evidence hashes are required")
        candidate_cohort_hash(candidate_option_ids)
        if self.candidate_cohort_hash != candidate_cohort_hash(candidate_option_ids):
            raise RecommendationValidationError("comparison decision cohort hash does not match candidates")
        if self.outcome not in {"recommended", "tied", "insufficient_evidence"}:
            raise RecommendationValidationError("comparison decision outcome is invalid")
        if self.outcome == "recommended":
            selected = _server_text(self.recommended_option_id, "recommended_option_id")
            if selected not in candidate_option_ids:
                raise RecommendationValidationError("comparison winner is outside the candidate cohort")
        elif self.recommended_option_id is not None:
            raise RecommendationValidationError("non-winning comparison decisions cannot name a winner")
        object.__setattr__(self, "evidence_pack_hashes", evidence_pack_hashes)
        object.__setattr__(self, "candidate_option_ids", candidate_option_ids)


class ServerDecisionRegistry:
    """Trusted process-local bridge for server-owned decision records.

    Registration is a control-plane operation.  Agent payload parsers must not
    expose it; the registry is intentionally not a Notebook route or tool.
    A durable implementation will replace this process-local store before any
    decision is used by materialization or execution consumers.
    """

    def __init__(self) -> None:
        self._feasibility: dict[str, FeasibilityDecision] = {}
        self._comparison: dict[str, ComparisonDecisionRecord] = {}

    def register_feasibility(self, decision: FeasibilityDecision) -> None:
        if not isinstance(decision, FeasibilityDecision):
            raise RecommendationValidationError("feasibility decision must be a contract")
        ref = decision.feasibility_decision_id
        if ref in self._feasibility or ref in self._comparison:
            raise RecommendationValidationError("server decision reference is already registered")
        self._feasibility[ref] = decision

    def register_comparison(self, decision: ComparisonDecisionRecord) -> None:
        if not isinstance(decision, ComparisonDecisionRecord):
            raise RecommendationValidationError("comparison decision must be a server record")
        ref = decision.comparison_decision_id
        if ref in self._feasibility or ref in self._comparison:
            raise RecommendationValidationError("server decision reference is already registered")
        self._comparison[ref] = decision

    def feasibility(self, ref: str) -> FeasibilityDecision:
        try:
            return self._feasibility[ref]
        except (KeyError, TypeError) as error:
            raise RecommendationValidationError("feasibility decision is unavailable") from error

    def comparison(self, ref: str) -> ComparisonDecisionRecord:
        try:
            return self._comparison[ref]
        except (KeyError, TypeError) as error:
            raise RecommendationValidationError("comparison decision is unavailable") from error

    def validate_recommendation(self, decision: RecommendationDecisionV11) -> None:
        if not isinstance(decision, RecommendationDecisionV11):
            raise RecommendationValidationError("recommendation must be the v1.1 contract")
        self._assert_common_binding(
            decision.batch_id,
            decision.generation_context_hash,
            decision.freshness_dependency_fingerprint,
            decision.evidence_pack_hashes,
            decision.candidate_option_ids,
            decision.candidate_cohort_hash,
        )
        if decision.feasibility_decision_ref is not None:
            source = self.feasibility(decision.feasibility_decision_ref)
            self._assert_recommendation_binding(decision, source)
            self._assert_common_binding(
                source.batch_id,
                source.generation_context_hash,
                source.freshness_dependency_fingerprint,
                source.evidence_pack_hashes,
                source.candidate_option_ids,
                source.candidate_cohort_hash,
            )
            feasible = tuple(item.option_id for item in source.candidates if item.outcome == "feasible")
            expected_outcome = "recommended" if len(feasible) == 1 else "insufficient_evidence"
            expected_winner = feasible[0] if len(feasible) == 1 else None
            if (decision.outcome, decision.recommended_option_id) != (expected_outcome, expected_winner):
                raise RecommendationValidationError("recommendation does not match feasibility decision")
        else:
            source = self.comparison(decision.comparison_decision_ref or "")
            self._assert_recommendation_binding(decision, source)
            self._assert_common_binding(
                source.batch_id,
                source.generation_context_hash,
                source.freshness_dependency_fingerprint,
                source.evidence_pack_hashes,
                source.candidate_option_ids,
                source.candidate_cohort_hash,
            )
            if (decision.outcome, decision.recommended_option_id) != (
                source.outcome,
                source.recommended_option_id,
            ):
                raise RecommendationValidationError("recommendation does not match comparison decision")

    @staticmethod
    def _assert_recommendation_binding(
        decision: RecommendationDecisionV11,
        source: FeasibilityDecision | ComparisonDecisionRecord,
    ) -> None:
        if (
            decision.batch_id != source.batch_id
            or decision.generation_context_hash != source.generation_context_hash
            or decision.freshness_dependency_fingerprint
            != source.freshness_dependency_fingerprint
            or decision.evidence_pack_hashes != source.evidence_pack_hashes
            or set(decision.candidate_option_ids) != set(source.candidate_option_ids)
            or decision.candidate_cohort_hash != source.candidate_cohort_hash
        ):
            raise RecommendationValidationError(
                "recommendation binding does not match server decision"
            )

    @staticmethod
    def _assert_common_binding(
        batch_id: str,
        generation_context_hash: str,
        freshness_dependency_fingerprint: str,
        evidence_pack_hashes: tuple[str, ...],
        candidate_option_ids: tuple[str, ...],
        candidate_cohort_hash_value: str,
    ) -> None:
        if not candidate_option_ids or candidate_cohort_hash(candidate_option_ids) != candidate_cohort_hash_value:
            raise RecommendationValidationError("server decision does not bind a complete candidate cohort")
        if not all(isinstance(value, str) and value for value in (batch_id, generation_context_hash, freshness_dependency_fingerprint)):
            raise RecommendationValidationError("server decision binding is incomplete")
        if not evidence_pack_hashes:
            raise RecommendationValidationError("server decision has no evidence pack")


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
        decision_registry: ServerDecisionRegistry,
        feasibility_decision_ref: str | None = None,
        comparison_decision_ref: str | None = None,
    ) -> RecommendationDecisionV11:
        """Build the server-owned recommendation successor.

        The method accepts only candidate identities and a reference resolved
        by the trusted registry.  It deliberately has no ``OptionDraft`` input,
        so an Agent's ``blocked_reason`` or preference cannot become a trusted
        feasibility fact.
        """

        ids = tuple(candidate_option_ids)
        cohort_hash = candidate_cohort_hash(ids)
        if not evidence_pack_hashes:
            raise RecommendationValidationError("v1.1 requires evidence pack hashes")
        if not isinstance(decision_registry, ServerDecisionRegistry):
            raise RecommendationValidationError("decision_registry is required")
        if (feasibility_decision_ref is None) == (comparison_decision_ref is None):
            raise RecommendationValidationError(
                "exactly one server feasibility or comparison decision is required"
            )

        recommended: str | None = None
        outcome = "insufficient_evidence"
        reason_refs: tuple[str, ...] = ()
        if feasibility_decision_ref is not None:
            feasibility_decision = decision_registry.feasibility(feasibility_decision_ref)
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
        else:
            comparison = decision_registry.comparison(comparison_decision_ref or "")
            if (
                comparison.batch_id != batch_id
                or comparison.generation_context_hash != generation_context_hash
                or comparison.freshness_dependency_fingerprint
                != freshness_dependency_fingerprint
                or comparison.evidence_pack_hashes != tuple(evidence_pack_hashes)
                or set(comparison.candidate_option_ids) != set(ids)
                or comparison.candidate_cohort_hash != cohort_hash
            ):
                raise RecommendationValidationError(
                    "comparison decision does not cover the requested candidate cohort"
                )
            outcome = comparison.outcome
            recommended = comparison.recommended_option_id
            reason_refs = (comparison.protocol_ref,)
        seed = {
            "batch_id": batch_id,
            "candidate_cohort_hash": cohort_hash,
            "outcome": outcome,
            "recommended_option_id": recommended,
            "feasibility_decision_ref": feasibility_decision_ref,
            "comparison_decision_ref": comparison_decision_ref,
            "evidence_pack_hashes": tuple(evidence_pack_hashes),
        }
        result = RecommendationDecisionV11(
            recommendation_decision_id=f"rec11_{sha256_canonical(seed)[:24]}",
            batch_id=batch_id,
            generation_context_hash=generation_context_hash,
            freshness_dependency_fingerprint=freshness_dependency_fingerprint,
            evidence_pack_hashes=tuple(evidence_pack_hashes),
            candidate_option_ids=ids,
            candidate_cohort_hash=cohort_hash,
            outcome=outcome,
            recommended_option_id=recommended,
            feasibility_decision_ref=feasibility_decision_ref,
            comparison_decision_ref=comparison_decision_ref,
            reason_refs=reason_refs,
        )
        decision_registry.validate_recommendation(result)
        return result

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
    "ComparisonDecisionRecord",
    "FeasibilityCandidateDecision",
    "FeasibilityDecision",
    "ForecastRollingOriginProtocol",
    "ProtocolResult",
    "RecommendationProtocol",
    "RecommendationDecisionV11",
    "RecommendationValidationError",
    "RecommendationValidator",
    "ServerDecisionRegistry",
]
