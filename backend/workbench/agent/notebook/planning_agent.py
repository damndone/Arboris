"""Typed provider loop for Notebook inspection and option planning."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
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
from .memory_defaults import MemoryDefaultApplicationError, apply_memory_defaults
from .proposal import TypedProposal
from .recommendation import (
    ForecastRollingOriginProtocol,
    RecommendationValidator,
)
from .store import ProjectionSource, dataset_workflow_source_pin
from .vocabulary import (
    ARTIFACT_VOCABULARY_VERSION,
    CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
    DECLARED_ARTIFACT_TYPES,
    capability_artifact_types,
)
from ..workflow_contracts import (
    MODEL_FAMILY_SPEC_FIELDS,
    OperationValidationError as WorkflowOperationValidationError,
    family_context_columns,
    model_family_contract,
    validate_model_genesis_spec,
    workflow_step_vocabulary,
)
from ..recipe_contracts import RecipeValidationError, recipe_contract_for_model_type


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
        "operation_id": {
            "type": "string",
            "enum": [
                "model.custom",
                "model.genesis",
                "model.rerun",
                "operation.multi_step",
            ],
        },
        "operation_version": {"type": "string", "const": "v1"},
        "target": {"type": "object"},
        "preconditions": {"type": "object"},
        "changes": {
            "type": "object",
            "description": (
                "For model.genesis use only table_params, model_params, and/or "
                "model_options as nested objects. For model.rerun use only the "
                "model_options nested object. For model.custom use only operation, "
                "input_handle, parameters, and consumer_slots. The server injects "
                "capability_ref and binding_ref. For operation.multi_step use only "
                "steps. Never put executable source, "
                "entrypoints, or trust/admission fields here."
            ),
            "properties": {
                "table_params": {"type": "object"},
                "model_params": {"type": "object"},
                "model_options": {"type": "object"},
                "operation": {"type": "string", "minLength": 1},
                "input_handle": {"type": "string", "minLength": 1},
                "parameters": {"type": "object"},
                "consumer_slots": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
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


def _interaction_mode(context: NotebookPlanningContextV1) -> str:
    """Return the persisted user-selected planning interaction mode."""

    mode = context.user_focus.get("interaction_mode", "plan")
    if mode not in {"plan", "action"}:
        raise NotebookPlanningContractError("Notebook interaction mode must be plan or action")
    return mode


_BASELINE_INSPECTION_IDS = frozenset(
    {"profile.v1", "quality.v1", "time_index.v1", "sample.v1"}
)


def _has_complete_baseline_evidence(evidence: DataEvidencePackV1) -> bool:
    """Whether the server-prepared source evidence is sufficient for submission."""

    return _BASELINE_INSPECTION_IDS.issubset(
        {
            record.inspection_id
            for record in evidence.records
            if record.status == "completed"
        }
    )


def _notebook_tools_for(
    max_options: int,
    *,
    include_inspection: bool = True,
) -> tuple[dict[str, Any], ...]:
    """Publish the closed tool vocabulary with a mode-specific batch cap."""

    if max_options not in {1, 2, 3}:
        raise ValueError("Notebook option limit must be between 1 and 3")
    inspection_tool, submit_tool = NOTEBOOK_TOOLS
    options_schema = submit_tool["input_schema"]["properties"]["options"]
    bounded_submit_tool = {
        **submit_tool,
        "description": (
            f"Submit 1 to {max_options} typed analysis option"
            f"{'s' if max_options != 1 else ''}. Every option must cite completed "
            "evidence and preserve the server-provided execution pins."
        ),
        "input_schema": {
            **submit_tool["input_schema"],
            "properties": {
                **submit_tool["input_schema"]["properties"],
                "options": {**options_schema, "maxItems": max_options},
            },
        },
    }
    if not include_inspection:
        return (bounded_submit_tool,)
    return (dict(inspection_tool), bounded_submit_tool)


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
    if operation_id not in {
        "model.custom",
        "model.genesis",
        "model.rerun",
        "operation.multi_step",
    }:
        raise NotebookPlanningContractError(
            "operation_id must be exactly model.custom, model.genesis, model.rerun, or operation.multi_step"
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
    if operation_id == "model.genesis":
        target_fields = ("dataset_source_id",)
    elif operation_id == "operation.multi_step":
        target_fields = ("run_id", "node_ref", "artifact_id")
    elif operation_id == "model.rerun":
        target_fields = ("run_id", "node_ref", "node_hash", "forest_node_key")
    elif "dataset_source_id" in target:
        target_fields = ("dataset_source_id",)
    else:
        target_fields = ("run_id", "node_ref", "node_hash", "forest_node_key")
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
    if operation_id == "model.custom":
        allowed = {"operation", "input_handle", "parameters", "consumer_slots"}
        unknown_changes = set(changes) - allowed
        if unknown_changes:
            if unknown_changes & {"capability_ref", "binding_ref"}:
                raise NotebookPlanningContractError(
                    "model.custom server-owned capability fields are server-owned"
                )
            raise NotebookPlanningContractError(
                "model.custom changes contain unknown field(s): "
                + ", ".join(sorted(unknown_changes))
            )
        _strict_string(changes.get("operation"), "model.custom changes.operation")
        if "input_handle" in changes:
            _strict_string(changes["input_handle"], "model.custom changes.input_handle")
        if "parameters" in changes:
            _strict_mapping(changes["parameters"], "model.custom changes.parameters")
        if "consumer_slots" in changes:
            _strict_string_list(
                changes["consumer_slots"], "model.custom changes.consumer_slots"
            )
    elif operation_id == "operation.multi_step":
        if set(changes) != {"steps"} or not isinstance(changes.get("steps"), list):
            raise NotebookPlanningContractError(
                "operation.multi_step changes must contain only a steps list"
            )
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
        capability_artifact_types: Mapping[str, Mapping[str, str]] | None = None,
        inspection_executor: InspectionExecutor | None = None,
        recommendation_validator: RecommendationValidator | None = None,
        operation_registry: OperationRegistry | None = None,
        proposal_validator: ProposalValidator | None = None,
        available_inspections: Sequence[str] | None = None,
        max_inspection_rounds: int = 5,
        max_contract_corrections: int = 2,
        model_timeout_s: float = 120.0,
        planning_timeout_s: float | None = None,
    ) -> None:
        self.adapter = adapter
        self.capability_catalog = dict(capability_catalog or {})
        self._capability_artifact_types = {
            str(capability_id): dict(artifact_types)
            for capability_id, artifact_types in (capability_artifact_types or {}).items()
            if isinstance(capability_id, str) and isinstance(artifact_types, Mapping)
        }
        self.inspection_executor = inspection_executor
        self.recommendation_validator = recommendation_validator or RecommendationValidator(
            protocols={"forecast.v1": ForecastRollingOriginProtocol()}
        )
        self.operation_registry = operation_registry or OperationRegistry()
        self.proposal_validator = proposal_validator
        self.available_inspections = frozenset(
            available_inspections if available_inspections is not None else INSPECTIONS
        )
        if max_inspection_rounds < 1 or max_inspection_rounds > 5:
            raise ValueError("max_inspection_rounds must be between 1 and 5")
        if max_contract_corrections < 0 or max_contract_corrections > 2:
            raise ValueError("max_contract_corrections must be between 0 and 2")
        self.max_inspection_rounds = max_inspection_rounds
        self.max_contract_corrections = max_contract_corrections
        if model_timeout_s <= 0:
            raise ValueError("model_timeout_s must be positive")
        self.model_timeout_s = float(model_timeout_s)
        if planning_timeout_s is not None and planning_timeout_s <= 0:
            raise ValueError("planning_timeout_s must be positive")
        self.planning_timeout_s = (
            None if planning_timeout_s is None else float(planning_timeout_s)
        )

    def _published_artifact_types(self, capability_id: str) -> Mapping[str, str]:
        dynamic = self._capability_artifact_types.get(capability_id)
        if dynamic is not None:
            return dynamic
        return capability_artifact_types(capability_id)

    def _supports_named_tool_choice(self) -> bool:
        capability = getattr(self.adapter, "supports_named_tool_choice", None)
        if callable(capability):
            return bool(capability())
        if isinstance(capability, bool):
            return capability
        # Test doubles and provider adapters that have not declared a
        # limitation retain the generic OpenAI-compatible behavior.
        return True

    def _planning_request_config(self) -> dict[str, Any]:
        config = getattr(self.adapter, "planning_request_config", None)
        if callable(config):
            value = config()
            if isinstance(value, Mapping):
                return dict(value)
        return {}

    def _workflow_primary_artifacts(
        self,
        steps: Any,
        catalog: Mapping[str, Any],
    ) -> tuple[dict[str, str], dict[str, int], frozenset[str]]:
        """Derive a composed option's primary results from its model steps."""

        artifact_types: dict[str, str] = {}
        counts: dict[str, int] = {}
        families: set[str] = set()
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, Mapping) or step.get("operation_id") != "model.genesis":
                continue
            spec = step.get("spec")
            if not isinstance(spec, Mapping):
                continue
            model_family = spec.get("model_family")
            if not isinstance(model_family, str) or not model_family:
                raise NotebookPlanningContractError(
                    "model.genesis workflow step requires a registered model_family"
                )
            declaration = catalog.get(model_family)
            if not isinstance(declaration, Mapping):
                raise NotebookPlanningContractError(
                    "model.genesis model_family is not a server-published capability: "
                    + model_family
                )
            declared_model_type = declaration.get("model_type")
            if declared_model_type is not None and declared_model_type != model_family:
                raise NotebookPlanningContractError(
                    "model.genesis model_family does not match its server capability identity"
                )
            branches = spec.get("branches")
            branch_count = len(branches) if isinstance(branches, list) else 0
            published = self._published_artifact_types(model_family)
            if branch_count and not published:
                raise NotebookPlanningContractError(
                    "model.genesis model_family has no published primary artifact: "
                    + model_family
                )
            families.add(model_family)
            for artifact_id, artifact_type in published.items():
                previous = artifact_types.setdefault(artifact_id, artifact_type)
                if previous != artifact_type:
                    raise NotebookPlanningContractError(
                        "model family artifact vocabulary assigns conflicting types to: "
                        + artifact_id
                    )
                counts[artifact_id] = counts.get(artifact_id, 0) + branch_count
        if not families:
            raise NotebookPlanningContractError(
                "operation.multi_step has no model.genesis branch outputs to contract"
            )
        return artifact_types, counts, frozenset(families)

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
        interaction_mode = _interaction_mode(context)
        max_options = 1 if interaction_mode == "action" else 3
        catalog = self.capability_catalog or {name: {} for name in context.available_capabilities}
        catalog = {
            capability_id: dict(declaration)
            for capability_id, declaration in catalog.items()
        }
        for capability_id, declaration in catalog.items():
            contract = recipe_contract_for_model_type(
                declaration.get("model_type", capability_id)
            )
            if contract is not None:
                declaration["recipe_contract"] = contract.to_payload()
        if not catalog:
            raise NotebookNoEligibleCapability("no registered executable Notebook capability is available")
        planning_deadline = (
            None
            if self.planning_timeout_s is None
            else asyncio.get_running_loop().time() + self.planning_timeout_s
        )
        context_payload = notebook_planning_workbench_context(context)
        context_payload["interaction_mode"] = interaction_mode
        context_payload["execution_pins"] = self._execution_pins(context)
        context_payload["available_inspection_ids"] = sorted(self.available_inspections)
        context_payload["typed_operation_contracts"] = self._typed_operation_contracts(context)
        context_payload["artifact_vocabulary"] = {
            "version": ARTIFACT_VOCABULARY_VERSION,
            "declared_artifact_types": dict(DECLARED_ARTIFACT_TYPES),
            "capability_version": CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
            "capability_artifact_types": {
                capability_id: dict(self._published_artifact_types(capability_id))
                for capability_id in sorted(catalog)
                if self._published_artifact_types(capability_id)
            },
            "required_expectations_must_use_declared_ids": True,
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    (
                        "Plan mode: submit one to three genuinely distinct, non-duplicate "
                        "executable paths. Do not force three options: submit one when the "
                        "evidence does not support meaningful alternatives, and say why. "
                        if interaction_mode == "plan"
                        else
                        "Action mode: the user chose direct specification checking. Submit exactly "
                        "one typed, editable Draft path with rank 1. Do not create alternatives, "
                        "call it a recommendation, or execute it. Treat the user's goal as the "
                        "requested specification; list only evidence-backed necessary assumptions "
                        "and limitations. "
                    )
                    + "Use only the two typed Notebook tools. Never invent metrics or executable capability ids. "
                    "Inspection ids are exactly profile.v1, quality.v1, time_index.v1, sample.v1, "
                    "or forecast_rolling_origin.v1; use dataset:active for a dataset projection and "
                    "run:active for a run projection. Treat completed evidence already supplied in "
                    "the initial Evidence Pack as sufficient for the evidence requirement; request "
                    "an inspection only to fill a concrete evidence gap needed by the option you "
                    "will submit. Do not request profile.v1, quality.v1, time_index.v1, or sample.v1 "
                    "again when that exact completed evidence is already present. "
                    f"You may make at most {self.max_inspection_rounds} inspection turns, each requesting "
                    "one to five distinct ids; after enough evidence is available, submit the option batch. "
                    "Submitted typed options must cite completed evidence refs. Comparative claims are "
                    "bound by the option's structured evidence_refs; do not use unsupported prose. "
                    "Evidence with status partial or failed is non-citable. A partial bounded inspection is "
                    "terminal for that inspection id: describe its omissions as a limitation, but do not "
                    "request it again merely to remove a declared cap. "
                    "Copy execution_pins exactly: for a standalone dataset proposal use model.genesis and set "
                    "target.dataset_source_id exactly to context.projection_source.upload_sha256; for a "
                    "dataset-rooted operation.multi_step use its target_exact and preconditions_exact instead. "
                    "A RecipeContract always remains a dataset-rooted model.genesis proposal when the "
                    "Notebook projection is a dataset, even after that Notebook has an active result head: "
                    "copy the dataset genesis pin and do not turn an ETS or ARMA/GARCH Recipe into a "
                    "model.rerun merely because a prior result is visible. "
                    "For a run proposal copy the active-head and node pins without rewriting them. For model.genesis, "
                    "changes may contain only table_params, model_params, or model_options, each as an object; "
                    "put model-specific fields inside one of those objects, never directly in changes. "
                    "For model.genesis, model_params must include an evidence-backed model_type. "
                    "Use the server-published capability form for that family: x is non-empty only "
                    "when the selected family requires covariates; DID families instead require their "
                    "published entity, time, and cohort or treatment-path columns. Do not add OLS "
                    "covariance fields to a DID family. "
                    "When context.typed_operation_contracts publishes operation.multi_step, use it for a "
                    "typed statistical workflow that needs declared categorical terms, polynomial terms, "
                    "or declared post-estimation steps. Copy its target_exact and preconditions_exact "
                    "verbatim, and use only its published step vocabulary. Every entry in changes.steps "
                    "has exactly this outer envelope: step_id, operation_id, spec, plus optional "
                    "depends_on and expected_artifacts. Omit depends_on when a step has no prerequisite; "
                    "otherwise depends_on must be a JSON array of exact earlier step_id strings, for example "
                    "[\"source_step\"], never a string, object, or branch_id. Put every operation-specific field inside spec; "
                    "never place model, exploration, or adapter fields beside spec. Do not replace a categorical "
                    "term with a numeric code or omit a requested polynomial/post-estimation step. "
                    "Each completed model.genesis branch automatically materializes residuals_vs_<predictor> and "
                    "fitted_vs_<predictor> diagnostic figures for its declared predictor columns. When the user "
                    "requests residuals versus a declared predictor, include that predictor in the branch and describe "
                    "the persisted diagnostic figure; do not claim that a separate scatter step is required. "
                    "capability_id always identifies a server-published model capability, never the "
                    "operation id. For an operation.multi_step comparison it must name one model_family "
                    "declared by that workflow, not operation.multi_step. Every model.genesis step must "
                    "use a server-published model_family; panel_ols requires entity_col or time_col, and "
                    "clustered panel_ols requires entity_col. "
                    "For OLS, the server-owned Agent envelope is model_options.covariance and its only "
                    "published values are robust, clustered, and unadjusted. For model.genesis, the "
                    "legacy model_params.covariance field is also accepted for human/Draft compatibility, "
                    "but a typed Agent option should use model_options.covariance so the contract binding "
                    "and rerun path remain inspectable. "
                    "For model.custom, capability_id selects a server-published planner projection; "
                    "changes may contain only operation, input_handle, parameters, and consumer_slots. "
                    "The server injects capability_ref and binding_ref. Never invent entrypoints, source "
                    "paths, dependency refs, trust tiers, admission refs, or executable permissions. "
                    "A custom option is experimental/high-risk by default and still requires the existing "
                    "Proposal/Risk authorization and containment gateway; it is never an automatic fallback. "
                    "For a regression model, y and x must be exact column names present in completed profile/sample evidence. "
                    "For a RecipeContract, do not submit regression y/x fields: use its exact model_options time/value fields. "
                    "Every time-series Recipe must have model_options.time_index_semantics resolved before Draft validation. "
                    "You may omit that field only when the current context includes an eligible approved memory default "
                    "for the same Recipe; the server then applies its exact registered value and provenance. "
                    "Without that exact current default, set model_options.time_index_semantics explicitly. "
                    "Use regular_calendar only when completed evidence establishes constant elapsed intervals; "
                    "otherwise use observation_order and state that index interpretation as an assumption for user confirmation. "
                    "Never submit recipe_contract.server_owned_option_fields; the server binds those fields to the typed dataset target. "
                    "if the target is not supported by evidence, do not submit the option. "
                    "For every non-empty model_options object, use the exact server-published field names "
                    "and nesting shown in capability_catalog's notebook_model_options_contract or "
                    "model_options_vocabulary. Never translate canonical fields into aliases such as ar, ma, "
                    "dist, or mean; the server validates the merged target contract and rejects invented keys. "
                    "If a model type has no published notebook_model_options_contract, omit model_options "
                    "entirely; never borrow options from a related model family. "
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
                        "evidence_citation_policy": self._evidence_citation_policy(
                            initial_evidence
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        evidence = initial_evidence
        requests_seen: list[InspectionRequest] = []
        terminal_inspection_ids = {
            record.inspection_id
            for record in evidence.records
            if record.status in {"completed", "partial"}
        }
        inspection_rounds = 0
        contract_corrections = 0
        for round_number in range(
            1, self.max_inspection_rounds + 2 + self.max_contract_corrections
        ):
            remaining_s = (
                None
                if planning_deadline is None
                else planning_deadline - asyncio.get_running_loop().time()
            )
            if remaining_s is not None and remaining_s <= 0:
                raise NotebookPlanningTimeout(
                    f"Notebook planning exceeded the {self.planning_timeout_s:g}s total budget"
                )
            total_budget_limited = (
                remaining_s is not None and remaining_s < self.model_timeout_s
            )
            baseline_complete = _has_complete_baseline_evidence(evidence)
            events = await self._call_model(
                messages,
                timeout_s=(
                    self.model_timeout_s
                    if remaining_s is None
                    else min(self.model_timeout_s, remaining_s)
                ),
                total_budget_limited=total_budget_limited,
                max_options=max_options,
                submit_only=baseline_complete,
            )
            calls = [event.tool_call for event in events if event.type == "tool_call_delta" and event.tool_call]
            if len(calls) != 1:
                error = NotebookPlanningContractError(
                    "text-only planning completion is not accepted"
                    if not calls
                    else "planning turn must contain exactly one typed tool call"
                )
                if contract_corrections >= self.max_contract_corrections:
                    raise error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call={},
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            call = calls[0]
            tool_id = call.get("tool_id")
            arguments = call.get("arguments")
            if tool_id == "request_notebook_inspections":
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
                    new_requests: list[InspectionRequest] = []
                    reused_requests: list[InspectionRequest] = []
                    requested_by_id: dict[str, InspectionRequest] = {}
                    for request in requests:
                        current = requested_by_id.get(request.inspection_id)
                        if current is not None:
                            if current != request:
                                raise NotebookPlanningContractError(
                                    "duplicate inspection id has conflicting arguments"
                                )
                            reused_requests.append(request)
                            continue
                        requested_by_id[request.inspection_id] = request
                        prior_request = next(
                            (
                                prior
                                for prior in requests_seen
                                if prior.inspection_id == request.inspection_id
                            ),
                            None,
                        )
                        if prior_request is not None:
                            if prior_request != request:
                                # A completed evidence record is scoped to the
                                # request that produced it.  Reusing it after
                                # a changed target or arguments would quietly
                                # relabel different evidence as equivalent.
                                raise NotebookPlanningContractError(
                                    "duplicate inspection id has conflicting arguments"
                                )
                            # A repeated, byte-for-byte equivalent read is
                            # idempotent. Reuse its immutable evidence packet
                            # below rather than spending another inspection
                            # turn or making the model start over.
                            reused_requests.append(request)
                            continue
                        if request.inspection_id in terminal_inspection_ids:
                            # Default no-argument inspections against the
                            # current pinned run are deterministic.  Initial
                            # evidence is server-created for that exact source,
                            # so this is an identity-preserving replay rather
                            # than a request to widen a bounded read.  Other
                            # target/argument shapes remain fail-closed because
                            # v1 records do not persist a caller envelope.
                            if (
                                request.target_ref == "run:active"
                                and not request.arguments
                                and context.active_head_run_id is not None
                                and evidence.source_id
                                == f"run:{context.active_head_run_id}"
                            ):
                                reused_requests.append(request)
                                continue
                            raise NotebookPlanningContractError("duplicate inspection request")
                        new_requests.append(request)
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
                if inspection_rounds >= self.max_inspection_rounds:
                    error = NotebookPlanningContractError("inspection round limit exceeded")
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
                if new_requests:
                    if self.inspection_executor is None:
                        raise NotebookPlanningUnavailable("inspection executor is not configured")
                    result = self.inspection_executor(tuple(new_requests), evidence)
                    inspection_pack = await result if hasattr(result, "__await__") else result
                    if not isinstance(inspection_pack, DataEvidencePackV1):
                        raise NotebookPlanningContractError("inspection executor returned no Evidence Pack")
                    inspection_rounds += 1
                    evidence = self._append_evidence_pack(evidence, inspection_pack)
                    resolved_inspection_ids = {
                        record.inspection_id
                        for record in inspection_pack.records
                        if record.status in {"completed", "partial"}
                    }
                    # A failed inspection has not produced reusable evidence.
                    # Leave it retriable so the provider can correct its target
                    # or arguments; only completed/partial reads become
                    # idempotent requests in this planning episode.
                    requests_seen.extend(
                        request
                        for request in new_requests
                        if request.inspection_id in resolved_inspection_ids
                    )
                    terminal_inspection_ids.update(
                        resolved_inspection_ids
                    )
                else:
                    inspection_pack = DataEvidencePackV1(
                        source_id=evidence.source_id,
                        records=(),
                    )
                messages.extend([
                    {"role": "assistant", "tool_calls": [call]},
                    {
                        "role": "tool",
                        "tool_call_id": call.get("tool_call_id", "inspection"),
                        "content": json.dumps(
                            {
                                "evidence": evidence.to_dict(),
                                "evidence_citation_policy": self._evidence_citation_policy(
                                    evidence
                                ),
                                "reused_inspection_ids": sorted(
                                    {request.inspection_id for request in reused_requests}
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
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
                submissions = _parse_submissions(arguments, max_options=max_options)
                submissions = self._validate_submissions(
                    context, evidence, submissions, catalog, max_options=max_options
                )
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
            try:
                drafts_without_decision = option_drafts_from_submissions(context, submissions)
                decision = self.recommendation_validator.decide(
                    batch_id=batch_id,
                    candidates=drafts_without_decision,
                    evidence_pack=evidence,
                    generation_context_hash=generation_context_hash(context),
                    freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                )
                drafts = option_drafts_from_submissions(context, submissions, decision=decision)
            except (KeyError, TypeError, ValueError) as error:
                # A trusted, server-side decision can reject an otherwise
                # typed provider batch.  Give the provider one bounded
                # correction opportunity instead of leaking this as the
                # route's generic request-validation failure.  The external
                # correction intentionally carries a stable category, not
                # internal exception text or provider-controlled content.
                contract_error = NotebookPlanningContractError(
                    "server recommendation validation failed"
                )
                if contract_corrections >= self.max_contract_corrections:
                    raise contract_error from error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=contract_error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            return PlanningResult(tuple(requests_seen), evidence, submissions, drafts, decision, round_number)
        raise NotebookPlanningContractError("planning loop did not submit an option batch")

    @staticmethod
    def _evidence_citation_policy(
        evidence: DataEvidencePackV1,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "completed_evidence_refs": [
                {
                    "evidence_id": record.evidence_id,
                    "result_hash": record.result_hash,
                    "source_refs": list(record.source_refs),
                }
                for record in evidence.records
                if record.status == "completed"
            ],
            "non_citable_evidence": [
                {
                    "evidence_id": record.evidence_id,
                    "status": record.status,
                    "omissions": [dict(item) for item in record.omissions],
                }
                for record in evidence.records
                if record.status != "completed"
            ],
        }

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
        elif message == "duplicate inspection request":
            remediation = (
                "Do not request an inspection id already present with status completed "
                "or partial. A partial result is the terminal bounded result; preserve "
                "its omissions as a limitation and proceed using only completed refs "
                "from evidence_citation_policy for citations."
            )
        elif message == "duplicate inspection id has conflicting arguments":
            remediation = (
                "This planning pass already completed that inspection id with a different "
                "target_ref or arguments. Do not relabel its evidence: use the evidence "
                "already returned, or continue with a different registered inspection id."
            )
        elif message == "text-only planning completion is not accepted":
            remediation = (
                "Do not answer in prose. You must call exactly one declared Notebook "
                "tool: request_notebook_inspections when more evidence is required, "
                "or submit_notebook_option_batch when the bounded evidence is enough."
            )
        elif message == "option tool arguments must contain only options":
            remediation = (
                "Call submit_notebook_option_batch with exactly one top-level field "
                "named options whose value is the option array. Do not include "
                "reasoning, explanation, evidence, metadata, or any other sibling "
                "field; put option-specific rationale inside each option.rationale."
            )
        elif message == "option evidence ref is missing, changed, or incomplete":
            completed = [
                {
                    "evidence_id": record.evidence_id,
                    "result_hash": record.result_hash,
                    "source_refs": list(record.source_refs),
                }
                for record in evidence.records
                if record.status == "completed"
            ]
            partial = [
                {
                    "evidence_id": record.evidence_id,
                    "status": record.status,
                    "omissions": [dict(item) for item in record.omissions],
                }
                for record in evidence.records
                if record.status == "partial"
            ]
            remediation = (
                "Resubmit the option batch using only an exact evidence_id, "
                "result_hash, and source_refs tuple from completed_evidence_refs "
                f"{json.dumps(completed, sort_keys=True)}. Partial evidence "
                f"{json.dumps(partial, sort_keys=True)} must not be cited as completed; "
                "its omissions may be described only as a limitation. Do not request "
                "the same bounded inspection again merely to remove a declared cap."
            )
        elif message.startswith("RECIPE_MODEL_OPTIONS_REQUIRED:"):
            recipe_id = message.partition(":")[2].partition(" requires")[0].strip()
            recipe_contract = recipe_contract_for_model_type(recipe_id)
            if recipe_contract is None:
                remediation = (
                    "Resubmit the Recipe proposal with the exact server-required "
                    "model_params.model_options object. Do not replace it with y/x "
                    "or an unregistered alias."
                )
            else:
                recipe_payload = recipe_contract.to_payload()
                required_inputs = recipe_payload["required_inputs"]
                remediation = (
                    "Resubmit model.genesis with model_params.model_type exactly "
                    f"{recipe_id!r} and model_params.model_options containing these "
                    f"exact required fields: {json.dumps(required_inputs)}. The field "
                    "values must be exact completed-evidence column names; do not use "
                    "regression y/x fields. Use only the remaining option fields and "
                    "values published in this Recipe vocabulary: "
                    f"{json.dumps(recipe_payload['parameter_vocabulary'], sort_keys=True)}."
                )
        elif message == "dataset-source proposal is not pinned to the source upload":
            source_id = (context.projection_source or {}).get("upload_sha256")
            remediation = (
                "Resubmit the dataset proposal without changing the server-owned pin: "
                "operation_id must be model.genesis and target.dataset_source_id must "
                f"equal exactly {source_id!r}. Do not derive or shorten this value."
            )
        elif message.startswith("operation.multi_step capability_id must name"):
            eligible = sorted(str(item) for item in context.available_capabilities)
            remediation = (
                "Resubmit the same source-pinned operation.multi_step proposal, but set "
                "capability_id to one server-published model_family declared by its "
                "model.genesis steps. capability_id is not an operation id. "
                f"Eligible published capabilities include {eligible}."
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
        elif "workflow step contains unknown field(s)" in message:
            remediation = (
                "Resubmit the workflow with each changes.steps entry using only "
                "step_id, operation_id, spec, and optionally depends_on or "
                "expected_artifacts at its outer level. Move every operation-specific "
                "field, including model, exploration, or adapter parameters, inside "
                "spec; then use only the exact field names published for that step's "
                "operation_id in typed_operation_contracts.operation.multi_step.step_vocabulary."
            )
        elif "depends_on must be step ids" in message:
            remediation = (
                "Resubmit every workflow step: omit depends_on when it has no prerequisite, "
                "or as a JSON array of exact earlier step ids, for example \"depends_on\": "
                "[\"source_step\"]. Never use a string, object, branch_id, or artifact id."
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
        elif "model.custom" in message:
            remediation = (
                "Resubmit model.custom with only operation, input_handle, parameters, and consumer_slots "
                "under changes. Keep capability_ref and binding_ref out of the Agent payload; the server "
                "resolves them from capability_id. Use only the exact input handle and consumer slots "
                "published by the server, and do not request execution outside the Proposal/Risk gateway."
            )
        elif (
            "model_options target contract rejected" in message
            and "MODEL_OPTIONS_UNSUPPORTED" in message
        ):
            remediation = (
                "This exact model type publishes no model_options contract. Resubmit "
                "the same proposal but omit model_options entirely. Do not borrow "
                "covariance or any other option from a related model family."
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
        elif message == "run-source proposal is not a rerun-child of the active head":
            # The server refused a target outside the active head's lineage.
            # Naming only the violation leaves an otherwise workable request
            # stranded, so hand back the eligible targets -- or, when the head
            # admits none, send the provider to genesis instead of asking it to
            # satisfy a rerun that cannot exist.
            pins = NotebookPlanningAgent._execution_pins(context)
            rerun_pins = pins.get("rerun_preconditions_by_target", [])
            if rerun_pins:
                remediation = (
                    "A run-source proposal must target a model node on the active head. "
                    "Resubmit with operation_id model.rerun (or model.custom) and one "
                    "exact target and precondition pair copied from the server-owned "
                    "execution_pins.rerun_preconditions_by_target; do not rewrite "
                    f"run_id, node_ref, node_hash, forest_node_key, or context_fingerprint: "
                    f"{json.dumps(rerun_pins, sort_keys=True)}."
                )
            else:
                remediation = (
                    "The active head exposes no eligible model node, so no rerun target "
                    "exists. Do not retry a run-source proposal. Submit a dataset-source "
                    "model.genesis proposal instead, copying the server-owned genesis "
                    f"execution pins exactly: {json.dumps(pins.get('genesis'), sort_keys=True)}."
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

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        timeout_s: float,
        total_budget_limited: bool,
        max_options: int = 3,
        submit_only: bool = False,
    ) -> list[ModelStreamEvent]:
        request = ModelRequest(
            messages=list(messages),
            tools=[
                dict(tool)
                for tool in _notebook_tools_for(
                    max_options,
                    include_inspection=not submit_only,
                )
            ],
            model_config=(
                {
                    **self._planning_request_config(),
                    **(
                        {
                            "tool_choice": {
                                "type": "function",
                                "function": {"name": "submit_notebook_option_batch"},
                            }
                        }
                        if submit_only and self._supports_named_tool_choice()
                        else {}
                    ),
                }
            ),
        )
        try:
            events = await asyncio.wait_for(
                self._collect_model_events(request), timeout=timeout_s
            )
        except asyncio.TimeoutError as exc:
            if total_budget_limited:
                raise NotebookPlanningTimeout(
                    f"Notebook planning exceeded the {self.planning_timeout_s:g}s total budget"
                ) from exc
            raise NotebookPlanningTimeout(
                f"Notebook planning provider exceeded {self.model_timeout_s:g}s"
            ) from exc
        if not any(event.type == "done" for event in events):
            raise NotebookPlanningUnavailable("model provider returned no completion")
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
    def _execution_pins(context: NotebookPlanningContextV1) -> dict[str, Any]:
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
        payload: dict[str, Any] = {
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
        # A composed workflow begins at the immutable raw-stage artifact, not
        # at a fitted model.  It is published only when the compiler has a
        # complete server-owned source identity; a model must never guess an
        # artifact path or substitute a model node as the source table.
        raw_sources = [
            item
            for item in context.bounded_lineage
            if item.get("kind") == "dataset_stage"
            and item.get("stage") == "source"
            and all(
                isinstance(item.get(field), str) and item[field]
                for field in ("node_id", "workflow_artifact_id", "context_fingerprint")
            )
        ]
        if context.active_head_run_id and len(raw_sources) == 1:
            source = raw_sources[0]
            payload["workflow_source"] = {
                "target": {
                    "run_id": context.active_head_run_id,
                    "node_ref": source["node_id"],
                    "artifact_id": source["workflow_artifact_id"],
                },
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": source["context_fingerprint"],
                    "active_head_run_id": context.active_head_run_id,
                    "owner_resolution": "single_candidate",
                },
            }
        elif isinstance(context.projection_source, Mapping):
            # A fresh dataset Notebook deliberately has no active result head.
            # It may still have a server-resolved raw source inherited from the
            # Run the user chose in the UI.  Decode the strict persisted shape
            # rather than trusting an ad-hoc context field from an Agent.
            try:
                source = ProjectionSource.from_dict(context.projection_source)
                dataset_pin = dataset_workflow_source_pin(source)
            except (TypeError, ValueError):
                dataset_pin = None
            if dataset_pin is not None:
                payload["workflow_source"] = dataset_pin
        return payload

    @staticmethod
    def _typed_operation_contracts(
        context: NotebookPlanningContextV1,
    ) -> dict[str, dict[str, Any]]:
        pins = NotebookPlanningAgent._execution_pins(context)
        contracts = {
            "model.custom": {
                "operation_id": "model.custom",
                "operation_version": "v1",
                "target_required": ["dataset_source_id"],
                "preconditions_exact": pins["genesis_preconditions"],
                "changes_allowed_fields": [
                    "operation",
                    "input_handle",
                    "parameters",
                    "consumer_slots",
                ],
                "changes_field_shape": (
                    "operation is a string; parameters is an object; "
                    "consumer_slots is a list of consumer slot ids"
                ),
                "server_bound_fields": ["capability_ref", "binding_ref"],
            },
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
        workflow_source = pins.get("workflow_source")
        if workflow_source is not None:
            contracts["operation.multi_step"] = {
                "operation_id": "operation.multi_step",
                "operation_version": "v1",
                "target_exact": workflow_source["target"],
                "preconditions_exact": workflow_source["preconditions"],
                "changes_allowed_fields": ["steps"],
                "step_vocabulary": workflow_step_vocabulary(),
            }
        return contracts

    def _validate_submissions(
        self,
        context: NotebookPlanningContextV1,
        evidence: DataEvidencePackV1,
        submissions: tuple[AgentOptionSubmission, ...],
        catalog: Mapping[str, Any],
        *,
        max_options: int = 3,
    ) -> tuple[AgentOptionSubmission, ...]:
        if len(submissions) > max_options or not submissions:
            raise NotebookPlanningContractError(
                f"option batch must contain 1 to {max_options} options"
            )
        if max_options == 1 and submissions[0].rank != 1:
            raise NotebookPlanningContractError("Action mode option must have rank 1")
        evidence_by_id = {record.evidence_id: record for record in evidence.records}
        option_ids = [submission.option_id or f"candidate_{index + 1}" for index, submission in enumerate(submissions)]
        if any(submission.option_id is None for submission in submissions):
            raise NotebookPlanningContractError("every provider option needs a stable option_id")
        if len(set(option_ids)) != len(option_ids):
            raise NotebookPlanningContractError("option ids must be unique")
        ranks = [submission.rank for submission in submissions]
        if len(set(ranks)) != len(ranks):
            raise NotebookPlanningContractError("option ranks must be unique")
        normalized_submissions: list[AgentOptionSubmission] = []
        for submission in submissions:
            # Recipe options are canonically nested under model_params.  Keep
            # the accepted top-level compatibility envelope useful for model
            # providers, but normalize it before memory defaults are applied;
            # otherwise a valid memory hint is reported as if its container
            # were malformed and the provider receives no actionable repair.
            if submission.proposal.operation_id == "model.genesis":
                changes = submission.proposal.changes
                model_params = changes.get("model_params")
                if isinstance(model_params, Mapping):
                    model_type = model_params.get("model_type")
                    recipe_contract = (
                        recipe_contract_for_model_type(model_type)
                        if isinstance(model_type, str)
                        else None
                    )
                    if recipe_contract is not None:
                        model_options = model_params.get("model_options")
                        top_level_options = changes.get("model_options")
                        if model_options is None and isinstance(top_level_options, Mapping):
                            normalized_params = {
                                **model_params,
                                "model_options": dict(top_level_options),
                            }
                            submission = replace(
                                submission,
                                proposal=replace(
                                    submission.proposal,
                                    changes={
                                        **changes,
                                        "model_params": normalized_params,
                                    },
                                ),
                            )
                        elif not isinstance(model_options, Mapping):
                            required_inputs = ", ".join(
                                f"model_options.{field_name}"
                                for field_name in recipe_contract.source_option_fields
                            )
                            raise NotebookPlanningContractError(
                                f"RECIPE_MODEL_OPTIONS_REQUIRED: {model_type} requires "
                                f"model_options containing {required_inputs}; a memory "
                                "default can fill only its registered field after those "
                                "source columns are declared"
                            )
            try:
                submission = replace(
                    submission,
                    proposal=apply_memory_defaults(
                        submission.proposal,
                        context.domain_memory_projection,
                    ),
                )
            except MemoryDefaultApplicationError as error:
                raise NotebookPlanningContractError(
                    f"memory-derived proposal default is invalid: {error}"
                ) from error
            if submission.capability_id not in catalog:
                if submission.proposal.operation_id == "operation.multi_step":
                    raise NotebookPlanningContractError(
                        "operation.multi_step capability_id must name a server-published "
                        "model capability, not operation.multi_step"
                    )
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
            workflow_artifact_types: dict[str, str] = {}
            workflow_artifact_counts: dict[str, int] = {}
            workflow_families: frozenset[str] = frozenset()
            evidence_columns = {
                str(column.get("name"))
                for record in evidence.records
                if isinstance(record.observations, Mapping)
                for column in (record.observations.get("columns") or [])
                if isinstance(column, Mapping) and column.get("name")
            }
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
                declaration = catalog.get(submission.capability_id) or {}
                declared_model_type = declaration.get("model_type")
                if declared_model_type is not None and model_type != declared_model_type:
                    raise NotebookPlanningContractError(
                        "model.genesis model_type does not match the server-declared "
                        "capability model identity"
                    )
                if not evidence_columns:
                    raise NotebookPlanningContractError(
                        "model.genesis requires completed column evidence before proposing inputs"
                    )
                recipe_contract = recipe_contract_for_model_type(model_type)
                y: str | None = None
                if recipe_contract is not None:
                    try:
                        recipe_contract.validate_planning_params(
                            model_params, columns=tuple(sorted(evidence_columns))
                        )
                    except RecipeValidationError as error:
                        raise NotebookPlanningContractError(str(error)) from error
                    family_contract = None
                    requires_x = recipe_contract.requires_nonempty_predictors
                else:
                    y = model_params.get("y")
                    if not isinstance(y, str) or not y:
                        raise NotebookPlanningContractError(
                            "model.genesis model_params must include evidence-backed y"
                        )
                    if y not in evidence_columns:
                        raise NotebookPlanningContractError(
                            f"model.genesis y is not present in completed evidence columns: {y}"
                        )
                    try:
                        family_contract = model_family_contract(model_type)
                    except WorkflowOperationValidationError:
                        family_contract = None
                    requires_x = (
                        family_contract.requires_nonempty_predictors
                        if family_contract is not None
                        else True
                    )
                if family_contract is not None:
                    family_values = {
                        field_name: model_params.get(field_name)
                        for field_name in family_contract.required_spec_fields
                    }
                    if family_contract.required_spec_field_mode == "all":
                        missing_family_fields = [
                            field_name
                            for field_name, value in family_values.items()
                            if not isinstance(value, str) or not value
                        ]
                    else:
                        missing_family_fields = (
                            list(family_values)
                            if family_values
                            and not any(
                                isinstance(value, str) and value
                                for value in family_values.values()
                            )
                            else []
                        )
                    if missing_family_fields:
                        raise NotebookPlanningContractError(
                            family_contract.missing_required_fields_message
                            or "model.genesis is missing family-required fields"
                        )
                    for field_name, value in family_values.items():
                        if value is None:
                            continue
                        if not isinstance(value, str) or not value:
                            raise NotebookPlanningContractError(
                                f"model.genesis {field_name} must be an evidence-backed column"
                            )
                        if value not in evidence_columns:
                            raise NotebookPlanningContractError(
                                f"model.genesis {field_name} is not present in completed evidence columns: {value}"
                            )
                    if not family_contract.allows_covariance and "covariance" in model_params:
                        raise NotebookPlanningContractError(
                            f"model.genesis {model_type} does not accept OLS covariance settings"
                        )
                x = model_params.get("x", [])
                if (
                    not isinstance(x, list)
                    or any(not isinstance(item, str) or not item for item in x)
                    or (requires_x and not x)
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
                if family_contract is not None:
                    family_spec: dict[str, Any] = {
                        "model_family": model_type,
                        "branches": [
                            {
                                "branch_id": "notebook",
                                "outcome": y,
                                "predictors": list(x),
                            }
                        ],
                    }
                    for field_name in MODEL_FAMILY_SPEC_FIELDS:
                        if field_name in model_params:
                            family_spec[field_name] = model_params[field_name]
                    if "covariance" in model_params:
                        family_spec["covariance"] = model_params["covariance"]
                    try:
                        validated_contract = validate_model_genesis_spec(family_spec)
                        declared_columns = family_context_columns(
                            validated_contract, family_spec
                        )
                    except WorkflowOperationValidationError as error:
                        raise NotebookPlanningContractError(str(error)) from error
                    missing_family_columns = sorted(
                        set(declared_columns) - evidence_columns
                    )
                    if missing_family_columns:
                        raise NotebookPlanningContractError(
                            "model.genesis family fields are not present in completed evidence columns: "
                            + ", ".join(missing_family_columns)
                        )
            elif operation_id == "operation.multi_step":
                workflow_source = self._execution_pins(context).get("workflow_source")
                if workflow_source is None:
                    raise NotebookPlanningContractError(
                        "operation.multi_step requires one server-pinned raw source"
                    )
                if submission.proposal.target != workflow_source["target"]:
                    raise NotebookPlanningContractError(
                        "operation.multi_step target does not copy the server workflow source pin"
                    )
                if submission.proposal.preconditions != workflow_source["preconditions"]:
                    raise NotebookPlanningContractError(
                        "operation.multi_step preconditions do not copy the server workflow source pin"
                    )
                if not evidence_columns:
                    raise NotebookPlanningContractError(
                        "operation.multi_step requires completed column evidence"
                    )
                from ..workflow_contracts import validate_workflow_steps

                try:
                    validate_workflow_steps(
                        changes.get("steps"),
                        available_columns=sorted(evidence_columns),
                    )
                except Exception as error:
                    raise NotebookPlanningContractError(
                        f"operation.multi_step source columns are invalid: {error}"
                    ) from error
                (
                    workflow_artifact_types,
                    workflow_artifact_counts,
                    workflow_families,
                ) = self._workflow_primary_artifacts(changes.get("steps"), catalog)
                if submission.capability_id not in workflow_families:
                    raise NotebookPlanningContractError(
                        "operation.multi_step capability_id must name one declared "
                        "model.genesis model_family"
                    )
            elif operation_id == "model.custom":
                unknown_changes = set(changes) - {
                    "operation",
                    "input_handle",
                    "parameters",
                    "consumer_slots",
                }
                if unknown_changes:
                    raise NotebookPlanningContractError(
                        "model.custom changes contain server-owned or unknown field(s): "
                        + ", ".join(sorted(unknown_changes))
                    )
                operation = changes.get("operation")
                if not isinstance(operation, str) or not operation:
                    raise NotebookPlanningContractError(
                        "model.custom changes.operation must be a non-empty string"
                    )
                if "input_handle" in changes and (
                    not isinstance(changes["input_handle"], str)
                    or not changes["input_handle"]
                ):
                    raise NotebookPlanningContractError(
                        "model.custom input_handle must be a non-empty string"
                    )
                if "parameters" in changes and not isinstance(
                    changes["parameters"], Mapping
                ):
                    raise NotebookPlanningContractError(
                        "model.custom parameters must be an object"
                    )
                if "consumer_slots" in changes:
                    slots = changes["consumer_slots"]
                    if (
                        not isinstance(slots, list)
                        or not slots
                        or any(not isinstance(item, str) or not item for item in slots)
                        or len(set(slots)) != len(slots)
                    ):
                        raise NotebookPlanningContractError(
                            "model.custom consumer_slots must be unique non-empty strings"
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
            published_artifacts: Mapping[str, str] = (
                workflow_artifact_types
                if operation_id == "operation.multi_step"
                else self._published_artifact_types(submission.capability_id)
            )
            canonical_expected_artifacts = submission.expected_artifacts
            if operation_id == "operation.multi_step":
                # A model-genesis workflow registers one primary result in
                # each sibling Run. The server derives its primary artifact
                # contract from the validated executable steps: letting the
                # provider guess artifact ids, branch count, or registry step
                # makes a non-executable presentation field block an otherwise
                # valid analysis plan.
                canonical_expected_artifacts = tuple(
                    ExpectedArtifact(
                        artifact_id=artifact_id,
                        artifact_type=artifact_type,
                        required=True,
                        count=workflow_artifact_counts[artifact_id],
                        step=None,
                    )
                    for artifact_id, artifact_type in sorted(published_artifacts.items())
                )
            elif published_artifacts and not submission.expected_artifacts:
                raise NotebookPlanningContractError(
                    "capability required artifact(s) missing: "
                    + ", ".join(sorted(published_artifacts))
                )
            try:
                build_artifact_contract(
                    canonical_expected_artifacts,
                    additional_artifact_types=published_artifacts,
                )
            except Exception as error:
                raise NotebookPlanningContractError(
                    f"expected artifact failed published artifact vocabulary validation: {error}"
                ) from error
            if published_artifacts:
                required_ids = {
                    artifact.artifact_id
                    for artifact in canonical_expected_artifacts
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
            if context.active_head_run_id:
                is_dataset_recipe_genesis = (
                    submission.proposal.operation_id == "model.genesis"
                    and isinstance(context.projection_source, Mapping)
                    and context.projection_source.get("kind") == "dataset"
                    and isinstance(submission.proposal.changes.get("model_params"), Mapping)
                    and recipe_contract_for_model_type(
                        submission.proposal.changes["model_params"].get("model_type")
                    )
                    is not None
                )
                if is_dataset_recipe_genesis:
                    if (
                        submission.proposal.target.get("dataset_source_id")
                        != context.projection_source.get("upload_sha256")
                    ):
                        raise NotebookPlanningContractError(
                            "dataset-source proposal is not pinned to the source upload"
                        )
                    if (
                        submission.proposal.preconditions
                        != self._execution_pins(context)["genesis_preconditions"]
                    ):
                        raise NotebookPlanningContractError(
                            "dataset-source proposal does not copy the server execution pins"
                        )
                elif submission.proposal.operation_id == "operation.multi_step":
                    workflow_source = self._execution_pins(context).get("workflow_source")
                    if workflow_source is None:
                        raise NotebookPlanningContractError(
                            "operation.multi_step requires one server-pinned raw source"
                        )
                    if (
                        submission.proposal.target != workflow_source["target"]
                        or submission.proposal.preconditions
                        != workflow_source["preconditions"]
                    ):
                        raise NotebookPlanningContractError(
                            "operation.multi_step is not pinned to the current raw source"
                        )
                elif submission.proposal.operation_id not in {"model.rerun", "model.custom"} or submission.proposal.target.get("run_id") != context.active_head_run_id:
                    raise NotebookPlanningContractError("run-source proposal is not a rerun-child of the active head")
                else:
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
                if submission.proposal.operation_id == "operation.multi_step":
                    # The preceding workflow-specific branch already verified
                    # the immutable raw-source pin.  A composed workflow has
                    # no single Pipeline Draft, so it must not be forced into
                    # the genesis-materialization path used by one-model
                    # dataset proposals.
                    pass
                elif submission.proposal.operation_id not in {"model.genesis", "model.custom"}:
                    raise NotebookPlanningContractError(
                        "dataset-source proposal requires a genesis, custom, or source-pinned workflow path"
                    )
                elif submission.proposal.target.get("dataset_source_id") != context.projection_source.get("upload_sha256"):
                    raise NotebookPlanningContractError("dataset-source proposal is not pinned to the source upload")
                elif submission.proposal.preconditions != self._execution_pins(context)["genesis_preconditions"]:
                    raise NotebookPlanningContractError("dataset-source proposal does not copy the server execution pins")
            normalized_submissions.append(
                replace(
                    submission,
                    expected_artifacts=canonical_expected_artifacts,
                )
            )
        proposal_hashes = [
            submission.proposal.canonical_hash()
            for submission in normalized_submissions
        ]
        if len(set(proposal_hashes)) != len(proposal_hashes):
            raise NotebookPlanningContractError(
                "option batch contains duplicate executable proposals"
            )
        return tuple(normalized_submissions)


def _parse_submissions(
    value: Any,
    *,
    max_options: int = 3,
) -> tuple[AgentOptionSubmission, ...]:
    payload = _strict_mapping(value, "option tool arguments")
    if set(payload) != {"options"} or not isinstance(payload["options"], list):
        raise NotebookPlanningContractError("option tool arguments must contain only options")
    if len(payload["options"]) > max_options:
        raise NotebookPlanningContractError(
            f"option batch must contain at most {max_options} options"
        )
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
