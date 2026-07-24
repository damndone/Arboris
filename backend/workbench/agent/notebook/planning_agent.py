"""Typed provider loop for Notebook inspection and option planning."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence
from uuid import uuid4

from ...contracts.agent.notebook_option import EvidenceRef, ExpectedArtifact
from ...agent.model import ModelAdapter, ModelRequest, ModelStreamEvent
from ..operations import OperationRegistry
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
    generation_context_hash,
    notebook_planning_workbench_context,
)
from .artifact_contract import build_artifact_contract
from .evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from .proposal import TypedProposal
from .recommendation import (
    ForecastRollingOriginProtocol,
    RecommendationValidator,
)
from .vocabulary import (
    ARTIFACT_VOCABULARY_VERSION,
    CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
    DECLARED_ARTIFACT_TYPES,
    capability_artifact_types,
)


class NotebookPlanningUnavailable(RuntimeError):
    """The provider or typed planning boundary could not produce a plan."""

    code = "NOTEBOOK_PLANNING_UNAVAILABLE"


class NotebookPlanningTimeout(NotebookPlanningUnavailable):
    """The provider did not finish one bounded planning turn in time."""

    code = "NOTEBOOK_PLANNING_TIMEOUT"


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
ProposalValidator = Callable[[NotebookPlanningContextV1, AgentOptionSubmission], None]


_INSPECTION_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inspection_id", "target_ref", "arguments"],
    "properties": {
        "inspection_id": {
            "type": "string",
            "enum": [
                "profile.v1",
                "quality.v1",
                "time_index.v1",
                "sample.v1",
                "forecast_rolling_origin.v1",
            ],
        },
        "target_ref": {"type": "string", "minLength": 1},
        # Inspection-specific arguments are validated again by the registered
        # inspection executor.  The request envelope itself remains closed.
        "arguments": {"type": "object"},
        "why_needed": {"type": "string", "minLength": 1},
    },
}

_TYPED_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "proposal_id",
        "proposal_revision",
        "operation_id",
        "operation_version",
        "target",
        "preconditions",
        "changes",
    ],
    "properties": {
        "proposal_id": {"type": "string", "minLength": 1},
        "proposal_revision": {"type": "integer", "minimum": 1},
        "operation_id": {"type": "string", "enum": ["model.genesis", "model.rerun"]},
        "operation_version": {"type": "string", "const": "v1"},
        "target": {"type": "object"},
        "preconditions": {"type": "object"},
        "changes": {
            "type": "object",
            "description": (
                "For model.genesis use only table_params, model_params, and/or "
                "model_options as nested objects. For model.rerun use only the "
                "model_options nested object. Never put model_type, x, y, "
                "covariance, capability, or other model fields directly here."
            ),
            "properties": {
                "table_params": {"type": "object"},
                "model_params": {"type": "object"},
                "model_options": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
}

_EXPECTED_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["artifact_id", "artifact_type", "required", "count", "step"],
    "properties": {
        "artifact_id": {"type": "string", "minLength": 1},
        "artifact_type": {"type": "string", "minLength": 1},
        "required": {"type": "boolean"},
        "count": {"type": "integer", "minimum": 0},
        "step": {"type": ["string", "null"]},
    },
}

_EVIDENCE_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["evidence_id", "result_hash", "source_refs"],
    "properties": {
        "evidence_id": {"type": "string", "minLength": 1},
        "result_hash": {"type": "string", "minLength": 1},
        "source_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}

_OPTION_SUBMISSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "rank",
        "rationale",
        "proposal",
        "evidence_refs",
        "comparative_claims",
        "capability_id",
        "option_id",
    ],
    "properties": {
        "rank": {"type": "integer", "minimum": 1, "maximum": 3},
        "rationale": {"type": "string", "minLength": 1},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "proposal": _TYPED_PROPOSAL_SCHEMA,
        "expected_artifacts": {"type": "array", "items": _EXPECTED_ARTIFACT_SCHEMA},
        "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
        "comparative_claims": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "option_id": {"type": "string", "minLength": 1},
        "capability_id": {"type": "string", "minLength": 1},
    },
}


NOTEBOOK_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "tool_id": "request_notebook_inspections",
        "description": (
            "Request registered, bounded evidence inspections. Use only the "
            "inspection_id enum in the schema and never invent an id."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["requests"],
            "properties": {
                "requests": {"type": "array", "maxItems": 5, "items": _INSPECTION_REQUEST_SCHEMA},
            },
        },
    },
    {
        "tool_id": "submit_notebook_option_batch",
        "description": (
            "Submit 1 to 3 typed analysis options. Every option must cite "
            "completed evidence and preserve the server-provided execution pins."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["options"],
            "properties": {
                "options": {"type": "array", "minItems": 1, "maxItems": 3, "items": _OPTION_SUBMISSION_SCHEMA},
            },
        },
    },
)


def _strict_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NotebookPlanningContractError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise NotebookPlanningContractError(f"{label} object keys must be strings")
    return value


def _strict_string(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        raise NotebookPlanningContractError(f"{label} must be a non-empty string")
    return value


def _strict_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = f" >= {minimum}" if minimum is not None else ""
        raise NotebookPlanningContractError(f"{label} must be an integer{suffix}")
    return value


def _strict_string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise NotebookPlanningContractError(f"{label} must be an array")
    return tuple(_strict_string(item, f"{label} item") for item in value)


def _strict_typed_proposal(value: Any) -> TypedProposal:
    item = _strict_mapping(value, "typed proposal")
    required = {
        "proposal_id",
        "proposal_revision",
        "operation_id",
        "operation_version",
        "target",
        "preconditions",
        "changes",
    }
    missing = sorted(required - set(item))
    unknown = sorted(set(item) - required)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise NotebookPlanningContractError(
            "typed proposal fields are incomplete or unknown: " + "; ".join(details)
        )
    _strict_string(item["proposal_id"], "proposal_id")
    _strict_int(item["proposal_revision"], "proposal_revision", minimum=1)
    _strict_string(item["operation_id"], "operation_id")
    if item["operation_version"] != "v1":
        raise NotebookPlanningContractError("operation_version must be exactly v1")
    operation_id = item["operation_id"]
    if operation_id not in {"model.genesis", "model.rerun"}:
        raise NotebookPlanningContractError(
            "operation_id must be exactly model.genesis or model.rerun"
        )
    target = _strict_mapping(item["target"], "typed proposal target")
    preconditions = _strict_mapping(
        item["preconditions"], "typed proposal preconditions"
    )
    changes = _strict_mapping(item["changes"], "typed proposal changes")
    for field, mapping in (
        ("target", target),
        ("preconditions", preconditions),
        ("changes", changes),
    ):
        if any(type(key) is not str for key in mapping):
            raise NotebookPlanningContractError(f"typed proposal {field} keys must be strings")
    target_fields = (
        ("dataset_source_id",)
        if operation_id == "model.genesis"
        else ("run_id", "node_ref", "node_hash", "forest_node_key")
    )
    for key in target_fields:
        if key in target:
            _strict_string(target[key], f"typed proposal target.{key}")
    for key in (
        "context_version",
        "context_fingerprint",
        "active_head_run_id",
        "owner_resolution",
    ):
        if key in preconditions:
            _strict_string(preconditions[key], f"typed proposal preconditions.{key}")
    if "context_fingerprint_by_node" in preconditions:
        fingerprint_map = _strict_mapping(
            preconditions["context_fingerprint_by_node"],
            "typed proposal preconditions.context_fingerprint_by_node",
        )
        for key, value in fingerprint_map.items():
            _strict_string(key, "context fingerprint node id")
            _strict_string(value, "context fingerprint value")
    for key, nested in changes.items():
        if key in {"table_params", "model_params", "model_options"}:
            _strict_mapping(nested, f"typed proposal changes.{key}")
    return TypedProposal.from_dict(item)


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
        inspection_id = _strict_string(item["inspection_id"], "inspection_id")
        if inspection_id not in INSPECTIONS and inspection_id != "forecast_rolling_origin.v1":
            raise NotebookPlanningContractError(f"unknown inspection id: {inspection_id}")
        target_ref = _strict_string(item["target_ref"], "inspection target_ref")
        arguments = dict(_strict_mapping(item["arguments"], "inspection arguments"))
        if "why_needed" in item:
            _strict_string(item["why_needed"], "inspection why_needed")
        result.append(InspectionRequest(inspection_id, target_ref, arguments))
    return tuple(result)


def _submission(value: Any) -> AgentOptionSubmission:
    item = _strict_mapping(value, "option submission")
    allowed = {
        "rank", "rationale", "assumptions", "proposal", "expected_artifacts",
        "evidence_refs", "comparative_claims", "option_id", "capability_id",
    }
    if set(item) - allowed or not {"rank", "rationale", "proposal", "evidence_refs", "comparative_claims", "capability_id"}.issubset(item):
        raise NotebookPlanningContractError("option submission fields are incomplete or unknown")
    rank = _strict_int(item["rank"], "option rank", minimum=1)
    if rank > 3:
        raise NotebookPlanningContractError("option rank must be between 1 and 3")
    rationale = _strict_string(item["rationale"], "option rationale")
    assumptions = _strict_string_list(item.get("assumptions", []), "option assumptions")
    expected_raw = item.get("expected_artifacts", [])
    if not isinstance(expected_raw, list):
        raise NotebookPlanningContractError("expected_artifacts must be an array")
    evidence_raw = item["evidence_refs"]
    if not isinstance(evidence_raw, list):
        raise NotebookPlanningContractError("evidence_refs must be an array")
    comparative_claims = _strict_string_list(
        item["comparative_claims"], "comparative_claims"
    )
    option_id = _strict_string(item["option_id"], "option_id")
    capability_id = _strict_string(item["capability_id"], "capability_id")
    try:
        expected = tuple(
            ExpectedArtifact.from_dict(_strict_mapping(raw, "expected artifact"))
            for raw in expected_raw
        )
        refs = tuple(
            EvidenceRef.from_dict(_strict_mapping(raw, "evidence ref"))
            for raw in evidence_raw
        )
        proposal = _strict_typed_proposal(item["proposal"])
    except NotebookPlanningContractError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        # Provider-owned nested packets use the shared contract constructors,
        # which intentionally raise their own ValueError subclasses. Normalize
        # those failures at this boundary so the bounded correction loop can
        # reject the call without leaking a raw parser exception or persisting a
        # partially parsed option.
        raise NotebookPlanningContractError(
            "option submission typed fields are invalid"
        ) from error
    return AgentOptionSubmission(
        rank=rank,
        rationale=rationale,
        proposal=proposal,
        assumptions=assumptions,
        expected_artifacts=expected,
        evidence_refs=refs,
        comparative_claims=comparative_claims,
        option_id=option_id,
        capability_id=capability_id,
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
        operation_registry: OperationRegistry | None = None,
        proposal_validator: ProposalValidator | None = None,
        available_inspections: Sequence[str] | None = None,
        max_inspection_rounds: int = 2,
        max_contract_corrections: int = 2,
        model_timeout_s: float = 120.0,
    ) -> None:
        self.adapter = adapter
        self.capability_catalog = dict(capability_catalog or {})
        self.inspection_executor = inspection_executor
        self.recommendation_validator = recommendation_validator or RecommendationValidator(
            protocols={"forecast.v1": ForecastRollingOriginProtocol()}
        )
        self.operation_registry = operation_registry or OperationRegistry()
        self.proposal_validator = proposal_validator
        self.available_inspections = frozenset(
            available_inspections if available_inspections is not None else INSPECTIONS
        )
        if max_inspection_rounds < 1 or max_inspection_rounds > 2:
            raise ValueError("max_inspection_rounds must be 1 or 2")
        if max_contract_corrections < 0 or max_contract_corrections > 2:
            raise ValueError("max_contract_corrections must be between 0 and 2")
        self.max_inspection_rounds = max_inspection_rounds
        self.max_contract_corrections = max_contract_corrections
        if model_timeout_s <= 0:
            raise ValueError("model_timeout_s must be positive")
        self.model_timeout_s = float(model_timeout_s)

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
        context_payload = notebook_planning_workbench_context(context)
        context_payload["execution_pins"] = self._execution_pins(context)
        context_payload["available_inspection_ids"] = sorted(self.available_inspections)
        context_payload["typed_operation_contracts"] = self._typed_operation_contracts(context)
        context_payload["artifact_vocabulary"] = {
            "version": ARTIFACT_VOCABULARY_VERSION,
            "declared_artifact_types": dict(DECLARED_ARTIFACT_TYPES),
            "capability_version": CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
            "capability_artifact_types": {
                capability_id: dict(capability_artifact_types(capability_id))
                for capability_id in sorted(catalog)
                if capability_artifact_types(capability_id)
            },
            "required_expectations_must_use_declared_ids": True,
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Use only the two typed Notebook tools. Never invent metrics or executable capability ids. "
                    "Inspection ids are exactly profile.v1, quality.v1, time_index.v1, sample.v1, "
                    "or forecast_rolling_origin.v1; use dataset:active for a dataset projection and "
                    "run:active for a run projection. Request evidence first, then submit only typed options "
                    "whose claims cite completed evidence refs. Every comparative_claim must literally contain "
                    "the evidence_id of one of that option's evidence_refs; do not use unsupported prose. "
                    "Copy execution_pins exactly: for a dataset proposal use model.genesis and set "
                    "target.dataset_source_id exactly to context.projection_source.upload_sha256; for a run "
                    "proposal copy the active-head and node pins without rewriting them. For model.genesis, "
                    "changes may contain only table_params, model_params, or model_options, each as an object; "
                    "put model-specific fields inside one of those objects, never directly in changes. "
                    "For model.genesis, model_params must include an evidence-backed model_type and y; "
                    "all non-time-series genesis models must also include x as a non-empty list. "
                    "For OLS specifically, put covariance directly in model_params.covariance; OLS has no "
                    "model_options owner, so never put covariance or any other field in model_options for OLS. "
                    "y and x must be exact column names present in completed profile/sample evidence; "
                    "if the target is not supported by evidence, do not submit the option. "
                    "For every non-empty model_options object, use the exact server-published field names "
                    "and nesting shown in capability_catalog's notebook_model_options_contract or "
                    "model_options_vocabulary. Never translate canonical fields into aliases such as ar, ma, "
                    "dist, or mean; the server validates the merged target contract and rejects invented keys. "
                    "Do not claim missingness is random, a model is superior, or a diagnostic is clean unless "
                    "the completed evidence record explicitly supports that claim. If evidence cannot separate "
                    "options, submit the options as tied/insufficient evidence rather than forcing a winner. "
                    "Only declare required artifacts whose ids appear in context.artifact_vocabulary; "
                    "for a capability with a capability_artifact_types entry, declare its listed "
                    "primary result artifact as required; if an artifact is not published there, "
                    "omit it rather than inventing an id."
                ),
            },
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
        completed_inspection_ids = {
            record.inspection_id
            for record in evidence.records
            if record.status == "completed"
        }
        contract_corrections = 0
        for round_number in range(
            1, self.max_inspection_rounds + 2 + self.max_contract_corrections
        ):
            events = await self._call_model(messages)
            calls = [event.tool_call for event in events if event.type == "tool_call_delta" and event.tool_call]
            if len(calls) != 1:
                raise NotebookPlanningContractError("planning turn must contain exactly one typed tool call")
            call = calls[0]
            tool_id = call.get("tool_id")
            arguments = call.get("arguments")
            if tool_id == "request_notebook_inspections":
                if round_number > self.max_inspection_rounds:
                    error = NotebookPlanningContractError("inspection round limit exceeded")
                    if contract_corrections < self.max_contract_corrections:
                        contract_corrections += 1
                        self._append_contract_correction(
                            messages,
                            call=call,
                            error=error,
                            context=context,
                            evidence=evidence,
                            correction_number=contract_corrections,
                        )
                        continue
                    raise error
                try:
                    requests = _inspection_requests(arguments)
                    unavailable = sorted(
                        {
                            request.inspection_id
                            for request in requests
                            if request.inspection_id not in self.available_inspections
                        }
                    )
                    if unavailable:
                        raise NotebookPlanningContractError(
                            "inspection is not available: "
                            + ", ".join(unavailable)
                            + "; available: "
                            + ", ".join(sorted(self.available_inspections))
                        )
                    if any(
                        request in requests_seen
                        or request.inspection_id in completed_inspection_ids
                        for request in requests
                    ):
                        raise NotebookPlanningContractError("duplicate inspection request")
                except NotebookPlanningContractError as error:
                    if contract_corrections >= self.max_contract_corrections:
                        raise
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=error,
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                    continue
                requests_seen.extend(requests)
                if self.inspection_executor is None:
                    raise NotebookPlanningUnavailable("inspection executor is not configured")
                result = self.inspection_executor(requests, evidence)
                inspection_pack = await result if hasattr(result, "__await__") else result
                if not isinstance(inspection_pack, DataEvidencePackV1):
                    raise NotebookPlanningContractError("inspection executor returned no Evidence Pack")
                evidence = self._append_evidence_pack(evidence, inspection_pack)
                completed_inspection_ids.update(
                    record.inspection_id
                    for record in inspection_pack.records
                    if record.status == "completed"
                )
                messages.extend([
                    {"role": "assistant", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": call.get("tool_call_id", "inspection"), "content": json.dumps(evidence.to_dict(), ensure_ascii=False)},
                ])
                failed_codes = sorted(
                    {
                        record.failure_code
                        for record in inspection_pack.records
                        if record.status == "failed" and record.failure_code
                    }
                )
                if failed_codes:
                    if contract_corrections >= self.max_contract_corrections:
                        raise NotebookPlanningContractError(
                            "inspection evidence failed: " + ", ".join(failed_codes)
                        )
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=NotebookPlanningContractError(
                            "inspection evidence failed: " + ", ".join(failed_codes)
                        ),
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                continue
            if tool_id != "submit_notebook_option_batch":
                error = NotebookPlanningContractError(f"unknown Notebook planning tool: {tool_id}")
                if contract_corrections >= self.max_contract_corrections:
                    raise error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            try:
                submissions = _parse_submissions(arguments)
                self._validate_submissions(context, evidence, submissions, catalog)
            except NotebookPlanningContractError as error:
                if contract_corrections >= self.max_contract_corrections:
                    raise
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            from .producer import option_drafts_from_submissions

            # A planning pass is a new recommendation episode, even when the
            # compiler produces the same context id.  Reusing the context-only
            # batch id would make a deliberate replan collide with the old
            # append-only RecommendationDecision record.
            batch_id = f"batch_agent_{context.context_id}_{uuid4().hex}"
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

    @staticmethod
    def _append_evidence_pack(
        current: DataEvidencePackV1,
        incoming: DataEvidencePackV1,
    ) -> DataEvidencePackV1:
        """Keep inspection evidence append-only across bounded model rounds.

        The service persists each inspection call as its own immutable pack.
        The planner, however, validates one option batch against the complete
        evidence available to the model. Replacing the current pack with the
        latest inspection would make an earlier, otherwise valid evidence ref
        disappear between rounds. Merge by stable evidence id and reject a
        conflicting payload rather than silently choosing one.
        """

        if current.records and incoming.source_id and current.source_id != incoming.source_id:
            raise NotebookPlanningContractError("inspection evidence changed source")
        # A bounded correction may repeat the same inspection with a corrected
        # target (for example ``dataset:active`` -> ``run:active``).  The
        # failed record is useful in the trace, but it must not remain in the
        # planner's final evidence view beside the successful replacement:
        # RecommendationValidator treats any failed record as incomplete and
        # would therefore suppress an otherwise evidence-backed recommendation.
        # Keep the latest record per inspection id in the planning view while
        # the individual immutable packs and trace retain the full history.
        records_by_id: dict[str, Any] = {record.evidence_id: record for record in current.records}
        records_by_inspection: dict[str, Any] = {
            record.inspection_id: record for record in current.records
        }
        for record in incoming.records:
            existing = records_by_id.get(record.evidence_id)
            if existing is not None and existing.to_dict() != record.to_dict():
                raise NotebookPlanningContractError("inspection evidence changed for an existing evidence id")
            records_by_id[record.evidence_id] = record
            records_by_inspection[record.inspection_id] = record
        return DataEvidencePackV1(
            source_id=(incoming.source_id if incoming.records else current.source_id)
            or incoming.source_id,
            records=tuple(
                records_by_inspection[key]
                for key in sorted(records_by_inspection)
            ),
            pack_omissions=tuple(dict(item) for item in (*current.pack_omissions, *incoming.pack_omissions)),
        )

    @staticmethod
    def _append_contract_correction(
        messages: list[dict[str, Any]],
        *,
        call: Mapping[str, Any],
        error: NotebookPlanningContractError,
        context: NotebookPlanningContextV1,
        evidence: DataEvidencePackV1,
        correction_number: int,
    ) -> None:
        """Give the provider typed feedback without repairing its payload.

        The rejected call is never executed and never becomes evidence.  When
        it names a declared Notebook tool, echoing the assistant/tool pair
        keeps the next provider request valid on OpenAI-compatible APIs.  An
        undeclared tool name is not echoed because some providers reject a
        transcript containing a function that was not offered.
        """

        tool_id = call.get("tool_id")
        if tool_id in {tool["tool_id"] for tool in NOTEBOOK_TOOLS}:
            messages.append({"role": "assistant", "tool_calls": [dict(call)]})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("tool_call_id") or f"contract-{correction_number}"),
                    "content": json.dumps(
                        {
                            "status": "rejected",
                            "error_code": NotebookPlanningContractError.code,
                            "message": str(error),
                            "retryable": True,
                            "do_not_use_as_evidence": True,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": NotebookPlanningAgent._correction_instruction(
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=correction_number,
                ),
            }
        )

    @staticmethod
    def _correction_instruction(
        *,
        error: NotebookPlanningContractError,
        context: NotebookPlanningContextV1,
        evidence: DataEvidencePackV1,
        correction_number: int,
    ) -> str:
        message = str(error)
        evidence_ids = [record.evidence_id for record in evidence.records if record.status == "completed"]
        failed_targets = {
            record.failure_code
            for record in evidence.records
            if record.status == "failed" and record.failure_code
        }
        if "TARGET_REF_INVALID" in failed_targets:
            expected_target = (
                "run:active"
                if context.projection_source
                and context.projection_source.get("kind") == "run"
                else "dataset:active"
            )
            remediation = (
                "The inspection target did not match the server-bound Notebook projection. "
                f"Request the same inspection ids again with target_ref exactly {expected_target!r}; "
                "do not switch between run:active and dataset:active. Do not submit options until "
                "the resulting evidence records have status completed."
            )
        elif message.startswith("unknown inspection id:"):
            remediation = (
                "Call request_notebook_inspections again with one of these exact ids: "
                "profile.v1, quality.v1, time_index.v1, sample.v1, "
                "forecast_rolling_origin.v1. Never use an internal name such as "
                "inspect_head."
            )
        elif message.startswith("inspection is not available:"):
            available = message.split("; available:", 1)[-1].strip()
            remediation = (
                "Do not request an unregistered inspection. Use only the server-published "
                f"inspection ids: {available}. If the available evidence cannot separate "
                "options, submit them as tied or insufficient evidence."
            )
        elif message == "comparative claim has no evidence ref":
            available = ", ".join(evidence_ids) or "none"
            remediation = (
                "Resubmit the option batch. Every comparative_claim must literally "
                f"contain one completed evidence_id from this pack: {available}."
            )
        elif message == "dataset-source proposal is not pinned to the source upload":
            source_id = (context.projection_source or {}).get("upload_sha256")
            remediation = (
                "Resubmit the dataset proposal without changing the server-owned pin: "
                "operation_id must be model.genesis and target.dataset_source_id must "
                f"equal exactly {source_id!r}. Do not derive or shorten this value."
            )
        elif "model.genesis preconditions missing" in message:
            pins = NotebookPlanningAgent._execution_pins(context)["genesis_preconditions"]
            remediation = (
                "Resubmit model.genesis with the complete server-owned preconditions "
                f"copied exactly: {json.dumps(pins, sort_keys=True)}."
            )
        elif "model.genesis changes contain unknown field(s)" in message:
            remediation = (
                "Resubmit model.genesis with changes containing only these exact "
                "object fields: table_params, model_params, or model_options. Put "
                "model_type, y, x, covariance, and other model settings inside "
                "model_params or model_options; never put capability_id, params, "
                "capability, parameters, or raw model fields directly under changes."
            )
        elif message == "model.genesis ols does not accept model_options":
            remediation = (
                "Resubmit the OLS genesis proposal with covariance, when needed, directly inside "
                "changes.model_params.covariance. OLS does not declare a model_options owner; do not "
                "send covariance or any other OLS setting in changes.model_options or inside "
                "model_params.model_options."
            )
        elif (
            message.startswith("model.genesis model_params must")
            or message.startswith("model.genesis requires completed column evidence")
            or message.startswith("model.genesis y is not present")
            or message.startswith("model.genesis x is not present")
        ):
            columns = sorted(
                {
                    str(column.get("name"))
                    for record in evidence.records
                    if isinstance(record.observations, Mapping)
                    for column in (record.observations.get("columns") or [])
                    if isinstance(column, Mapping) and column.get("name")
                }
            )
            remediation = (
                "Resubmit model.genesis with model_params containing model_type, an exact target y, "
                "and a non-empty x list for non-time-series models. Every name must be present in "
                f"completed evidence columns {columns or ['not available']}; do not infer a target "
                "from convention."
            )
        elif "model.rerun changes contain unknown field(s)" in message:
            remediation = (
                "Resubmit model.rerun with changes containing only model_options as "
                "an object; do not put capability, params, or raw model fields "
                "directly under changes."
            )
        elif "model_options target contract rejected" in message:
            remediation = (
                "Resubmit the same typed proposal only after correcting model_options against the "
                "server-published target contract. Preserve the exact nested field names and value types "
                "shown in capability_catalog.notebook_model_options_contract or model_options_vocabulary; "
                "send a patch, not a new alias vocabulary. Do not guess a model setting."
            )
        elif message.startswith("typed proposal fields are incomplete or unknown:"):
            remediation = (
                "Resubmit the proposal with exactly these fields and no others: "
                "proposal_id, proposal_revision, operation_id, operation_version, "
                "target, preconditions, changes. proposal_revision must be an "
                "integer >= 1; do not omit it or add model fields at proposal level."
            )
        elif message == "option batch contains duplicate executable proposals":
            remediation = (
                "Do not submit duplicate executable proposals under different option "
                "ids. Each option must have a distinct canonical typed proposal; if "
                "there is no genuinely distinct supported path, submit fewer options."
            )
        elif message == "option ranks must be unique":
            remediation = "Use each rank only once, from 1 through the number of submitted options."
        elif message == "option batch must contain at most 3 options":
            remediation = (
                "Resubmit at most three options in one submit_notebook_option_batch call. "
                "Keep only genuinely distinct supported paths; do not split one analysis "
                "across multiple calls or silently invent a fourth option."
            )
        elif "published artifact vocabulary validation" in message:
            remediation = (
                "Remove the unsupported required artifact and resubmit. A required "
                "artifact_id must appear exactly in context.artifact_vocabulary with "
                "its declared artifact_type; do not invent artifact ids or types. If "
                "no published artifact is certain, do not submit this capability; "
                "the server will not accept an unauditable option."
            )
        elif message.startswith("capability required artifact(s) missing:"):
            remediation = (
                "Resubmit the option with every server-published primary result "
                "artifact named in the error as a required expected_artifact, using "
                "the exact artifact_type from context.artifact_vocabulary."
            )
        elif "operation is not registered:" in message:
            if context.projection_source and context.projection_source.get("kind") == "dataset":
                remediation = (
                    "For this dataset projection, operation_id must be exactly "
                    "model.genesis and operation_version exactly v1. Never append "
                    "another operation id, adapter name, or @version suffix. Use "
                    "the exact dataset_source_id and genesis execution pins already "
                    "provided in context."
                )
            else:
                remediation = (
                    "operation_id must be exactly model.genesis or model.rerun and "
                    "operation_version exactly v1. Never append another operation "
                    "id, adapter name, or @version suffix."
                )
        elif "does not copy the server execution pins" in message:
            pins = NotebookPlanningAgent._execution_pins(context)
            remediation = (
                "Resubmit the proposal with the matching server-owned preconditions "
                f"copied exactly from execution_pins: {json.dumps(pins, sort_keys=True)}."
            )
        elif message == "run-source proposal target is not a server-pinned model node":
            pins = NotebookPlanningAgent._execution_pins(context).get(
                "rerun_preconditions_by_target", []
            )
            remediation = (
                "Choose one exact target and precondition pair from the server-owned "
                "execution_pins.rerun_preconditions_by_target list; do not rewrite "
                f"node_ref, node_hash, forest_node_key, or context_fingerprint: {json.dumps(pins, sort_keys=True)}."
            )
        else:
            remediation = (
                "Resubmit exactly one typed Notebook tool call after correcting the "
                "reported contract error. Do not invent evidence, capabilities, or "
                "execution pins."
            )
        return (
            "Workbench rejected the previous Notebook tool call; it was not executed "
            "and is not evidence. This is bounded contract correction attempt "
            f"{correction_number}/2. {message}. {remediation}"
        )

    async def _call_model(self, messages: list[dict[str, Any]]) -> list[ModelStreamEvent]:
        request = ModelRequest(messages=list(messages), tools=[dict(tool) for tool in NOTEBOOK_TOOLS])
        try:
            events = await asyncio.wait_for(
                self._collect_model_events(request), timeout=self.model_timeout_s
            )
        except asyncio.TimeoutError as exc:
            raise NotebookPlanningTimeout(
                f"Notebook planning provider exceeded {self.model_timeout_s:g}s"
            ) from exc
        if not any(event.type == "done" for event in events):
            raise NotebookPlanningUnavailable("model provider returned no completion")
        if not any(event.type == "tool_call_delta" for event in events):
            raise NotebookPlanningContractError("text-only planning completion is not accepted")
        return events

    async def _collect_model_events(self, request: ModelRequest) -> list[ModelStreamEvent]:
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
        return events

    @staticmethod
    def _execution_pins(context: NotebookPlanningContextV1) -> dict[str, dict[str, Any]]:
        model_context_fingerprints = {
            str(item["node_id"]): str(item["context_fingerprint"])
            for item in context.bounded_lineage
            if item.get("kind") == "model" and item.get("context_fingerprint")
        }
        rerun_target_pins: list[dict[str, Any]] = []
        for item in context.bounded_lineage:
            if item.get("kind") != "model" or not item.get("context_fingerprint"):
                continue
            node_id = item.get("node_id")
            node_hash = item.get("node_hash")
            forest_node_key = item.get("forest_node_key")
            if not all(isinstance(value, str) and value for value in (node_id, node_hash, forest_node_key)):
                continue
            target = {
                "run_id": context.active_head_run_id,
                "node_ref": node_id,
                "node_hash": node_hash,
                "forest_node_key": forest_node_key,
            }
            preconditions = {
                "context_version": "node-operation-context/v1",
                "context_fingerprint": str(item["context_fingerprint"]),
                "active_head_run_id": context.active_head_run_id,
                "owner_resolution": "single_candidate",
                "context_fingerprint_by_node": model_context_fingerprints,
            }
            rerun_target_pins.append({"target": target, "preconditions": preconditions})
        first_context_fingerprint = (
            rerun_target_pins[0]["preconditions"]["context_fingerprint"]
            if rerun_target_pins
            else ""
        )
        return {
            "rerun_preconditions": {
                "context_version": "node-operation-context/v1",
                # The materializer and node-write validator consume this exact
                # top-level pin. Keep the per-node map as an explanatory
                # projection, but never make it a substitute for the registry's
                # required scalar fingerprint.
                "context_fingerprint": first_context_fingerprint,
                "active_head_run_id": context.active_head_run_id,
                "owner_resolution": "single_candidate",
                "context_fingerprint_by_node": model_context_fingerprints,
            },
            "rerun_preconditions_by_target": rerun_target_pins,
            "genesis_preconditions": {
                "context_version": "node-operation-context/v1",
                "context_fingerprint": freshness_dependency_fingerprint(context),
                "owner_resolution": "single_candidate",
            },
        }

    @staticmethod
    def _typed_operation_contracts(
        context: NotebookPlanningContextV1,
    ) -> dict[str, dict[str, Any]]:
        pins = NotebookPlanningAgent._execution_pins(context)
        return {
            "model.genesis": {
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target_required": ["dataset_source_id"],
                "preconditions_exact": pins["genesis_preconditions"],
                "changes_allowed_fields": ["table_params", "model_params", "model_options"],
                "changes_field_shape": "each allowed field is an object",
            },
            "model.rerun": {
                "operation_id": "model.rerun",
                "operation_version": "v1",
                "target_required": ["run_id", "node_ref", "node_hash", "forest_node_key"],
                "preconditions_exact": pins["rerun_preconditions"],
                "preconditions_by_target": pins["rerun_preconditions_by_target"],
                "changes_allowed_fields": ["model_options"],
                "changes_field_shape": "model_options is a non-empty object",
            },
        }

    def _validate_submissions(
        self,
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
        ranks = [submission.rank for submission in submissions]
        if len(set(ranks)) != len(ranks):
            raise NotebookPlanningContractError("option ranks must be unique")
        proposal_hashes = [submission.proposal.canonical_hash() for submission in submissions]
        if len(set(proposal_hashes)) != len(proposal_hashes):
            raise NotebookPlanningContractError(
                "option batch contains duplicate executable proposals"
            )
        for submission in submissions:
            if submission.capability_id not in catalog:
                raise NotebookPlanningUnavailable(f"capability is not registered: {submission.capability_id}")
            try:
                definition = self.operation_registry.require(
                    submission.proposal.operation_id,
                    submission.proposal.operation_version,
                )
                definition.validate(
                    target=submission.proposal.target,
                    preconditions=submission.proposal.preconditions,
                    changes=submission.proposal.changes,
                )
            except Exception as error:
                raise NotebookPlanningContractError(
                    f"typed proposal failed registry validation: {error}"
                ) from error
            if self.proposal_validator is not None:
                try:
                    self.proposal_validator(context, submission)
                except NotebookPlanningContractError:
                    raise
                except Exception as error:
                    code = getattr(error, "code", "MODEL_OPTIONS_PATCH_INVALID")
                    raise NotebookPlanningContractError(
                        f"model_options target contract rejected [{code}]: {error}"
                    ) from error
            operation_id = submission.proposal.operation_id
            changes = submission.proposal.changes
            if operation_id == "model.genesis":
                unknown_changes = set(changes) - {"table_params", "model_params", "model_options"}
                if unknown_changes:
                    raise NotebookPlanningContractError(
                        "model.genesis changes contain unknown field(s): "
                        + ", ".join(sorted(unknown_changes))
                    )
                model_params = changes.get("model_params")
                if not isinstance(model_params, Mapping):
                    raise NotebookPlanningContractError(
                        "model.genesis model_params must be an object containing model_type, y, and x"
                    )
                model_type = model_params.get("model_type")
                if not isinstance(model_type, str) or not model_type:
                    raise NotebookPlanningContractError(
                        "model.genesis model_params must include model_type"
                    )
                if model_type == "ols" and (
                    "model_options" in changes or "model_options" in model_params
                ):
                    raise NotebookPlanningContractError(
                        "model.genesis ols does not accept model_options"
                    )
                y = model_params.get("y")
                if not isinstance(y, str) or not y:
                    raise NotebookPlanningContractError(
                        "model.genesis model_params must include evidence-backed y"
                    )
                evidence_columns = {
                    str(column.get("name"))
                    for record in evidence.records
                    if isinstance(record.observations, Mapping)
                    for column in (record.observations.get("columns") or [])
                    if isinstance(column, Mapping) and column.get("name")
                }
                if not evidence_columns:
                    raise NotebookPlanningContractError(
                        "model.genesis requires completed column evidence before proposing y or x"
                    )
                if y not in evidence_columns:
                    raise NotebookPlanningContractError(
                        f"model.genesis y is not present in completed evidence columns: {y}"
                    )
                if model_type != "time_series.arma_garch":
                    x = model_params.get("x")
                    if (
                        not isinstance(x, list)
                        or not x
                        or any(not isinstance(item, str) or not item for item in x)
                    ):
                        raise NotebookPlanningContractError(
                            "model.genesis model_params must include non-empty evidence-backed x"
                        )
                    missing_x = sorted(set(x) - evidence_columns)
                    if missing_x:
                        raise NotebookPlanningContractError(
                            "model.genesis x is not present in completed evidence columns: "
                            + ", ".join(missing_x)
                        )
            elif operation_id == "model.rerun":
                unknown_changes = set(changes) - {"model_options"}
                if unknown_changes:
                    raise NotebookPlanningContractError(
                        "model.rerun changes contain unknown field(s): "
                        + ", ".join(sorted(unknown_changes))
                    )
            if not submission.evidence_refs:
                raise NotebookPlanningContractError("every option needs at least one evidence ref")
            published_artifacts = capability_artifact_types(submission.capability_id)
            if published_artifacts and not submission.expected_artifacts:
                raise NotebookPlanningContractError(
                    "capability required artifact(s) missing: "
                    + ", ".join(sorted(published_artifacts))
                )
            try:
                build_artifact_contract(
                    submission.expected_artifacts,
                    additional_artifact_types=published_artifacts,
                )
            except Exception as error:
                raise NotebookPlanningContractError(
                    f"expected artifact failed published artifact vocabulary validation: {error}"
                ) from error
            if published_artifacts:
                required_ids = {
                    artifact.artifact_id
                    for artifact in submission.expected_artifacts
                    if artifact.required
                }
                missing_artifacts = set(published_artifacts) - required_ids
                if missing_artifacts:
                    raise NotebookPlanningContractError(
                        "capability required artifact(s) missing: "
                        + ", ".join(sorted(missing_artifacts))
                    )
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
                pins = self._execution_pins(context)
                matching_pins = [
                    item
                    for item in pins["rerun_preconditions_by_target"]
                    if item["target"] == submission.proposal.target
                ]
                if not matching_pins:
                    raise NotebookPlanningContractError(
                        "run-source proposal target is not a server-pinned model node"
                    )
                if submission.proposal.preconditions != matching_pins[0]["preconditions"]:
                    raise NotebookPlanningContractError("run-source proposal does not copy the server execution pins")
            elif context.projection_source and context.projection_source.get("kind") == "dataset":
                if submission.proposal.operation_id != "model.genesis":
                    raise NotebookPlanningContractError("dataset-source proposal requires a genesis materialization path")
                if submission.proposal.target.get("dataset_source_id") != context.projection_source.get("upload_sha256"):
                    raise NotebookPlanningContractError("dataset-source proposal is not pinned to the source upload")
                if submission.proposal.preconditions != self._execution_pins(context)["genesis_preconditions"]:
                    raise NotebookPlanningContractError("dataset-source proposal does not copy the server execution pins")


def _parse_submissions(value: Any) -> tuple[AgentOptionSubmission, ...]:
    payload = _strict_mapping(value, "option tool arguments")
    if set(payload) != {"options"} or not isinstance(payload["options"], list):
        raise NotebookPlanningContractError("option tool arguments must contain only options")
    if len(payload["options"]) > 3:
        raise NotebookPlanningContractError("option batch must contain at most 3 options")
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
