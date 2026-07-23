"""Typed provider loop for Notebook inspection and option planning."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from ...contracts.agent.notebook_option import EvidenceRef, ExpectedArtifact
from ...agent.model import ModelAdapter, ModelRequest, ModelStreamEvent
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from .evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from .proposal import TypedProposal
from .recommendation import (
    ForecastRollingOriginProtocol,
    RecommendationValidator,
)


class NotebookPlanningUnavailable(RuntimeError):
    """The provider or typed planning boundary could not produce a plan."""

    code = "NOTEBOOK_PLANNING_UNAVAILABLE"


class NotebookNoEligibleCapability(NotebookPlanningUnavailable):
    code = "NOTEBOOK_NO_ELIGIBLE_CAPABILITY"


class NotebookPlanningContractError(NotebookPlanningUnavailable):
    """The provider returned an untrusted or untyped planning payload."""

    code = "NOTEBOOK_PLANNING_CONTRACT_INVALID"


@dataclass(frozen=True)
class AgentOptionSubmission:
    rank: int
    rationale: str
    proposal: TypedProposal
    assumptions: tuple[str, ...] = ()
    expected_artifacts: tuple[ExpectedArtifact, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    comparative_claims: tuple[str, ...] = ()
    option_id: str | None = None
    capability_id: str = ""


@dataclass(frozen=True)
class PlanningResult:
    inspection_requests: tuple[InspectionRequest, ...]
    evidence_pack: DataEvidencePackV1
    submissions: tuple[AgentOptionSubmission, ...]
    option_drafts: tuple[Any, ...]
    decision: Any
    rounds: int


InspectionExecutor = Callable[
    [tuple[InspectionRequest, ...], DataEvidencePackV1],
    DataEvidencePackV1 | Awaitable[DataEvidencePackV1],
]


NOTEBOOK_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "tool_id": "request_notebook_inspections",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["requests"],
            "properties": {
                "requests": {"type": "array", "maxItems": 5, "items": {"type": "object"}},
            },
        },
    },
    {
        "tool_id": "submit_notebook_option_batch",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["options"],
            "properties": {
                "options": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object"}},
            },
        },
    },
)


def _strict_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NotebookPlanningContractError(f"{label} must be an object")
    return value


def _inspection_requests(value: Any) -> tuple[InspectionRequest, ...]:
    payload = _strict_mapping(value, "inspection tool arguments")
    if set(payload) != {"requests"}:
        raise NotebookPlanningContractError("inspection tool arguments contain unknown fields")
    raw_requests = payload["requests"]
    if not isinstance(raw_requests, list) or not 1 <= len(raw_requests) <= 5:
        raise NotebookPlanningContractError("inspection requests must contain 1 to 5 items")
    result: list[InspectionRequest] = []
    for raw in raw_requests:
        item = _strict_mapping(raw, "inspection request")
        allowed = {"inspection_id", "target_ref", "arguments", "why_needed"}
        if set(item) - allowed or not {"inspection_id", "target_ref", "arguments"}.issubset(item):
            raise NotebookPlanningContractError("inspection request fields are invalid")
        inspection_id = item["inspection_id"]
        if inspection_id not in INSPECTIONS and inspection_id != "forecast_rolling_origin.v1":
            raise NotebookPlanningContractError(f"unknown inspection id: {inspection_id}")
        result.append(InspectionRequest(str(inspection_id), str(item["target_ref"]), dict(_strict_mapping(item["arguments"], "inspection arguments"))))
    return tuple(result)


def _submission(value: Any) -> AgentOptionSubmission:
    item = _strict_mapping(value, "option submission")
    allowed = {
        "rank", "rationale", "assumptions", "proposal", "expected_artifacts",
        "evidence_refs", "comparative_claims", "option_id", "capability_id",
    }
    if set(item) - allowed or not {"rank", "rationale", "proposal", "evidence_refs", "comparative_claims", "capability_id"}.issubset(item):
        raise NotebookPlanningContractError("option submission fields are incomplete or unknown")
    expected = tuple(ExpectedArtifact.from_dict(_strict_mapping(raw, "expected artifact")) for raw in item.get("expected_artifacts", []))
    refs = tuple(EvidenceRef.from_dict(_strict_mapping(raw, "evidence ref")) for raw in item["evidence_refs"])
    proposal = TypedProposal.from_dict(_strict_mapping(item["proposal"], "typed proposal"))
    return AgentOptionSubmission(
        rank=item["rank"],
        rationale=item["rationale"],
        proposal=proposal,
        assumptions=tuple(item.get("assumptions", [])),
        expected_artifacts=expected,
        evidence_refs=refs,
        comparative_claims=tuple(item["comparative_claims"]),
        option_id=item.get("option_id"),
        capability_id=item["capability_id"],
    )


class NotebookPlanningAgent:
    """A two-tool, bounded planning loop over the existing model adapter."""

    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        capability_catalog: Mapping[str, Any] | None = None,
        inspection_executor: InspectionExecutor | None = None,
        recommendation_validator: RecommendationValidator | None = None,
        max_inspection_rounds: int = 2,
    ) -> None:
        self.adapter = adapter
        self.capability_catalog = dict(capability_catalog or {})
        self.inspection_executor = inspection_executor
        self.recommendation_validator = recommendation_validator or RecommendationValidator(
            protocols={"forecast.v1": ForecastRollingOriginProtocol()}
        )
        if max_inspection_rounds < 1 or max_inspection_rounds > 2:
            raise ValueError("max_inspection_rounds must be 1 or 2")
        self.max_inspection_rounds = max_inspection_rounds

    def plan(
        self,
        *,
        context: NotebookPlanningContextV1,
        initial_evidence: DataEvidencePackV1,
    ) -> PlanningResult:
        return asyncio.run(self.plan_async(context=context, initial_evidence=initial_evidence))

    async def plan_async(
        self,
        *,
        context: NotebookPlanningContextV1,
        initial_evidence: DataEvidencePackV1,
    ) -> PlanningResult:
        if self.adapter is None:
            raise NotebookPlanningUnavailable("no model provider is configured")
        catalog = self.capability_catalog or {name: {} for name in context.available_capabilities}
        if not catalog:
            raise NotebookNoEligibleCapability("no registered executable Notebook capability is available")
        context_payload = context.to_dict()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Use only the two typed Notebook tools. Never invent metrics or executable capability ids."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": context_payload,
                        "capability_catalog": catalog,
                        "evidence": initial_evidence.to_dict(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        evidence = initial_evidence
        requests_seen: list[InspectionRequest] = []
        for round_number in range(1, self.max_inspection_rounds + 2):
            events = await self._call_model(messages)
            calls = [event.tool_call for event in events if event.type == "tool_call_delta" and event.tool_call]
            if len(calls) != 1:
                raise NotebookPlanningContractError("planning turn must contain exactly one typed tool call")
            call = calls[0]
            tool_id = call.get("tool_id")
            arguments = call.get("arguments")
            if tool_id == "request_notebook_inspections":
                if round_number > self.max_inspection_rounds:
                    raise NotebookPlanningContractError("inspection round limit exceeded")
                requests = _inspection_requests(arguments)
                if any(request in requests_seen for request in requests):
                    raise NotebookPlanningContractError("duplicate inspection request")
                requests_seen.extend(requests)
                if self.inspection_executor is None:
                    raise NotebookPlanningUnavailable("inspection executor is not configured")
                result = self.inspection_executor(requests, evidence)
                evidence = await result if hasattr(result, "__await__") else result
                if not isinstance(evidence, DataEvidencePackV1):
                    raise NotebookPlanningContractError("inspection executor returned no Evidence Pack")
                messages.extend([
                    {"role": "assistant", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": call.get("tool_call_id", "inspection"), "content": json.dumps(evidence.to_dict(), ensure_ascii=False)},
                ])
                continue
            if tool_id != "submit_notebook_option_batch":
                raise NotebookPlanningContractError(f"unknown Notebook planning tool: {tool_id}")
            submissions = _parse_submissions(arguments)
            self._validate_submissions(context, evidence, submissions, catalog)
            from .producer import option_drafts_from_submissions

            batch_id = f"batch_agent_{context.context_id}"
            drafts_without_decision = option_drafts_from_submissions(context, submissions)
            decision = self.recommendation_validator.decide(
                batch_id=batch_id,
                candidates=drafts_without_decision,
                evidence_pack=evidence,
                generation_context_hash=generation_context_hash(context),
                freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
            )
            drafts = option_drafts_from_submissions(context, submissions, decision=decision)
            return PlanningResult(tuple(requests_seen), evidence, submissions, drafts, decision, round_number)
        raise NotebookPlanningContractError("planning loop did not submit an option batch")

    async def _call_model(self, messages: list[dict[str, Any]]) -> list[ModelStreamEvent]:
        request = ModelRequest(messages=list(messages), tools=[dict(tool) for tool in NOTEBOOK_TOOLS])
        events: list[ModelStreamEvent] = []
        try:
            async for event in self.adapter.stream(request):
                if event.type == "error":
                    raise NotebookPlanningUnavailable(event.error or "model provider failed")
                events.append(event)
        except NotebookPlanningUnavailable:
            raise
        except Exception as exc:
            raise NotebookPlanningUnavailable(f"model provider failed: {type(exc).__name__}") from exc
        if not any(event.type == "done" for event in events):
            raise NotebookPlanningUnavailable("model provider returned no completion")
        if not any(event.type == "tool_call_delta" for event in events):
            raise NotebookPlanningContractError("text-only planning completion is not accepted")
        return events

    @staticmethod
    def _validate_submissions(
        context: NotebookPlanningContextV1,
        evidence: DataEvidencePackV1,
        submissions: tuple[AgentOptionSubmission, ...],
        catalog: Mapping[str, Any],
    ) -> None:
        if len(submissions) > 3 or not submissions:
            raise NotebookPlanningContractError("option batch must contain 1 to 3 options")
        evidence_by_id = {record.evidence_id: record for record in evidence.records}
        option_ids = [submission.option_id or f"candidate_{index + 1}" for index, submission in enumerate(submissions)]
        if any(submission.option_id is None for submission in submissions):
            raise NotebookPlanningContractError("every provider option needs a stable option_id")
        if len(set(option_ids)) != len(option_ids):
            raise NotebookPlanningContractError("option ids must be unique")
        for submission in submissions:
            if submission.capability_id not in catalog:
                raise NotebookPlanningUnavailable(f"capability is not registered: {submission.capability_id}")
            if not submission.evidence_refs:
                raise NotebookPlanningContractError("every option needs at least one evidence ref")
            for reference in submission.evidence_refs:
                record = evidence_by_id.get(reference.evidence_id)
                if record is None or record.result_hash != reference.result_hash or record.status != "completed":
                    raise NotebookPlanningContractError("option evidence ref is missing, changed, or incomplete")
            for claim in submission.comparative_claims:
                if not any(reference.evidence_id in claim for reference in submission.evidence_refs):
                    raise NotebookPlanningContractError("comparative claim has no evidence ref")
            if context.active_head_run_id:
                if submission.proposal.operation_id != "model.rerun" or submission.proposal.target.get("run_id") != context.active_head_run_id:
                    raise NotebookPlanningContractError("run-source proposal is not a rerun-child of the active head")
            elif context.projection_source and context.projection_source.get("kind") == "dataset":
                if submission.proposal.operation_id != "model.genesis":
                    raise NotebookPlanningContractError("dataset-source proposal requires a genesis materialization path")
                if submission.proposal.target.get("dataset_source_id") != context.projection_source.get("upload_sha256"):
                    raise NotebookPlanningContractError("dataset-source proposal is not pinned to the source upload")


def _parse_submissions(value: Any) -> tuple[AgentOptionSubmission, ...]:
    payload = _strict_mapping(value, "option tool arguments")
    if set(payload) != {"options"} or not isinstance(payload["options"], list):
        raise NotebookPlanningContractError("option tool arguments must contain only options")
    return tuple(_submission(item) for item in payload["options"])


__all__ = [
    "AgentOptionSubmission",
    "NOTEBOOK_TOOLS",
    "NotebookPlanningAgent",
    "NotebookPlanningContractError",
    "NotebookNoEligibleCapability",
    "NotebookPlanningUnavailable",
    "PlanningResult",
]
