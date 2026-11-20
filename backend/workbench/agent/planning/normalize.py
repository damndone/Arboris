"""Parse provider envelopes and normalize server-owned planning fields."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from ...contracts.agent.notebook_option import EvidenceRef, ExpectedArtifact
from ...contracts.model.family import MODEL_FAMILY_CONTRACTS
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
)
from ..notebook.evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from ..notebook.proposal import TypedProposal
from ..notebook.store import ProjectionSource, dataset_workflow_source_pin
from ..workflow_contracts import workflow_step_vocabulary

from .types import NotebookPlanningContractError, AgentOptionSubmission, PlanningRefusal
from .provider_contract import NOTEBOOK_TOOLS

_BASELINE_INSPECTION_IDS = frozenset(
    {"profile.v1", "quality.v1", "time_index.v1", "sample.v1"}
)


def _interaction_mode(context: NotebookPlanningContextV1) -> str:
    """Return the persisted user-selected planning interaction mode."""

    mode = context.user_focus.get("interaction_mode", "plan")
    if mode not in {"plan", "action"}:
        raise NotebookPlanningContractError("Notebook interaction mode must be plan or action")
    return mode


def _has_complete_baseline_evidence(evidence: DataEvidencePackV1) -> bool:
    """Whether the server-prepared source evidence is sufficient for submission."""

    return _BASELINE_INSPECTION_IDS.issubset(
        {
            record.inspection_id
            for record in evidence.records
            if record.status == "completed"
        }
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


def _canonicalize_provider_option_batch(
    value: Any,
    *,
    evidence: DataEvidencePackV1,
    catalog: Mapping[str, Mapping[str, Any]],
) -> Any:
    """Fill only deterministic, server-owned option envelope fields.

    The model chooses the analysis and its human explanation.  It does not
    choose the evidence hashes, result vocabulary, or a stable option label.
    Older providers also omit ``comparative_claims`` when there is no claim;
    an empty list is the only truthful value in that case.  Repairing these
    envelope omissions before the strict parser prevents a harmless wrapper
    mismatch from consuming another provider turn, while all executable
    fields still pass the normal typed validators below.
    """

    if not isinstance(value, Mapping) or set(value) != {"options"}:
        return value
    raw_options = value.get("options")
    if not isinstance(raw_options, list):
        return value
    completed_refs = [
        {
            "evidence_id": record.evidence_id,
            "result_hash": record.result_hash,
            "source_refs": list(record.source_refs),
        }
        for record in evidence.records
        if record.status == "completed"
    ]
    normalized: list[Any] = []
    for index, raw in enumerate(raw_options, start=1):
        if not isinstance(raw, Mapping):
            normalized.append(raw)
            continue
        item = dict(raw)
        if "comparative_claims" not in item:
            item["comparative_claims"] = []
        if "evidence_refs" not in item and completed_refs:
            item["evidence_refs"] = list(completed_refs)
        if "option_id" not in item:
            rank = item.get("rank")
            item["option_id"] = (
                f"option_{rank}" if type(rank) is int and rank > 0 else f"option_{index}"
            )
        if "capability_id" not in item:
            proposal = item.get("proposal")
            changes = proposal.get("changes") if isinstance(proposal, Mapping) else None
            model_params = changes.get("model_params") if isinstance(changes, Mapping) else None
            model_type = model_params.get("model_type") if isinstance(model_params, Mapping) else None
            if isinstance(model_type, str) and model_type in catalog:
                item["capability_id"] = model_type
        normalized.append(item)
    return {"options": normalized}


def _parse_submissions(
    value: Any,
    *,
    max_options: int = 3,
) -> tuple[AgentOptionSubmission, ...]:
    payload = _strict_mapping(value, "option tool arguments")
    if set(payload) != {"options"}:
        raise NotebookPlanningContractError("option tool arguments must contain only options")
    options = payload["options"]
    if not isinstance(options, list):
        raise NotebookPlanningContractError("options must be a JSON array")
    if len(options) > max_options:
        raise NotebookPlanningContractError(
            f"option batch must contain at most {max_options} options"
        )
    return tuple(_submission(item) for item in options)


def _parse_planning_refusal(
    value: Any,
    *,
    requests_seen: tuple[InspectionRequest, ...],
    evidence: DataEvidencePackV1,
    rounds: int,
) -> PlanningRefusal:
    """Parse the closed refusal envelope without accepting provider metadata."""

    payload = _strict_mapping(value, "planning refusal arguments")
    if set(payload) != {"reason_code", "message"}:
        raise NotebookPlanningContractError(
            "planning refusal fields must contain only reason_code and message"
        )
    reason_code = _strict_string(payload["reason_code"], "planning refusal reason_code")
    reason_codes = next(
        tool["input_schema"]["properties"]["reason_code"]["enum"]
        for tool in NOTEBOOK_TOOLS
        if tool["tool_id"] == "decline_notebook_plan"
    )
    if reason_code not in reason_codes:
        raise NotebookPlanningContractError(
            "planning refusal reason_code is not published: " + reason_code
        )
    message = _strict_string(payload["message"], "planning refusal message")
    if len(message) > 2000:
        raise NotebookPlanningContractError(
            "planning refusal message must be at most 2000 characters"
        )
    return PlanningRefusal(
        reason_code=reason_code,
        message=message,
        inspection_requests=requests_seen,
        evidence_pack=evidence,
        rounds=rounds,
    )


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


def _typed_operation_contracts(
    context: NotebookPlanningContextV1,
) -> dict[str, dict[str, Any]]:
    pins = _execution_pins(context)
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


def _canonicalize_server_owned_pins(
    context: NotebookPlanningContextV1,
    submission: AgentOptionSubmission,
) -> AgentOptionSubmission:
    """Replace provider-guessed source pins with the current server pins.

    A Notebook is already bound to one dataset (or one active run).  The
    provider therefore does not get to choose a different upload by
    spelling a different hash, nor does it get to reconstruct the context
    preconditions from prose.  Those fields are envelope data owned by the
    server.  Canonicalizing them once here removes a whole class of
    correction turns while preserving the fail-closed validation of all
    user/model fields.
    """

    proposal = submission.proposal
    source = context.projection_source
    if not isinstance(source, Mapping):
        return submission

    expected_target: Mapping[str, Any] | None = None
    expected_preconditions: Mapping[str, Any] | None = None
    operation_id = proposal.operation_id

    if source.get("kind") == "dataset":
        upload_sha256 = source.get("upload_sha256")
        if not isinstance(upload_sha256, str) or not upload_sha256:
            return submission
        if operation_id in {"model.genesis", "model.custom"}:
            # Both native Genesis and an experimental custom capability are
            # dataset-rooted when the Notebook projection is a dataset. The
            # upload pin is server-owned in both cases; requiring the
            # provider to spell it first made custom proposals fail one
            # correction turn before this canonicalizer could help.
            expected_target = {"dataset_source_id": upload_sha256}
            expected_preconditions = _execution_pins(context)[
                "genesis_preconditions"
            ]
        elif operation_id == "operation.multi_step":
            workflow_source = _execution_pins(context).get(
                "workflow_source"
            )
            if isinstance(workflow_source, Mapping):
                expected_target = workflow_source["target"]
                expected_preconditions = workflow_source["preconditions"]

    if expected_target is None or expected_preconditions is None:
        return submission
    if (
        proposal.target == dict(expected_target)
        and proposal.preconditions == dict(expected_preconditions)
    ):
        return submission
    return replace(
        submission,
        proposal=replace(
            proposal,
            target=dict(expected_target),
            preconditions=dict(expected_preconditions),
        ),
    )


def _canonicalize_provider_capability_id(
    submission: AgentOptionSubmission,
    catalog: Mapping[str, Mapping[str, Any]],
) -> AgentOptionSubmission:
    """Bind a Genesis envelope to the model family it actually selects.

    ``capability_id`` is a provider-facing label, while
    ``changes.model_params.model_type`` is the executable family.  Models
    occasionally retain the label from an earlier candidate (for example
    ``ols``) after changing the proposal to ``logit``.  Treating that
    stale label as authoritative produces misleading downstream failures:
    the wrong model-options policy is applied and the wrong artifact
    vocabulary is selected.  The server already publishes the family
    catalog, so binding the label to an exact registered model type is a
    deterministic envelope repair.  It never invents a family or changes
    executable model parameters.
    """

    proposal = submission.proposal
    if proposal.operation_id != "model.genesis":
        return submission
    changes = proposal.changes
    model_params = changes.get("model_params")
    model_type = (
        model_params.get("model_type")
        if isinstance(model_params, Mapping)
        else None
    )
    if not isinstance(model_type, str) or not model_type:
        return submission
    declaration = catalog.get(model_type)
    if not isinstance(declaration, Mapping):
        return submission
    declared_model_type = declaration.get("model_type")
    if declared_model_type is not None and declared_model_type != model_type:
        return submission
    if submission.capability_id == model_type:
        return submission
    return replace(submission, capability_id=model_type)


def _canonicalize_workflow_family_context(
    submission: AgentOptionSubmission,
) -> AgentOptionSubmission:
    proposal = submission.proposal
    steps = proposal.changes.get("steps")
    if proposal.operation_id != "operation.multi_step" or not isinstance(steps, list):
        return submission
    normalized = [_hoist_shared_family_fields(step) for step in steps]
    if all(original is updated for original, updated in zip(steps, normalized, strict=True)):
        return submission
    return replace(
        submission,
        proposal=replace(proposal, changes={**proposal.changes, "steps": normalized}),
    )


def _hoist_shared_family_fields(step: Any) -> Any:
    """Move family context only when every branch explicitly agrees."""

    if not isinstance(step, Mapping) or step.get("operation_id") != "model.genesis":
        return step
    spec = step.get("spec")
    if not isinstance(spec, Mapping):
        return step
    family = spec.get("model_family")
    contract = MODEL_FAMILY_CONTRACTS.get(family) if isinstance(family, str) else None
    branches = spec.get("branches")
    if (
        contract is None or not isinstance(branches, list) or not branches
        or not all(isinstance(branch, Mapping) for branch in branches)
    ):
        return step

    shared: dict[str, Any] = {}
    for field in contract.context_spec_fields:
        values = [branch[field] for branch in branches if field in branch]
        if not values:
            continue
        if field in spec:
            if any(value != spec[field] for value in values):
                return step
            continue
        first = values[0]
        # Only identical strings or lists of strings are candidates. The
        # registry still checks field types, source columns and model roles.
        if not isinstance(first, str) and not (
            isinstance(first, list) and all(isinstance(item, str) for item in first)
        ):
            return step
        if len(values) != len(branches) or any(value != first for value in values[1:]):
            return step
        shared[field] = first
    if not shared:
        return step
    return {
        **step,
        "spec": {
            **spec,
            **shared,
            "branches": [
                {key: value for key, value in branch.items() if key not in shared}
                for branch in branches
            ],
        },
    }


def _strip_unsupported_model_options(
    submission: AgentOptionSubmission,
    catalog: Mapping[str, Mapping[str, Any]],
) -> AgentOptionSubmission:
    """Apply an explicit server policy that a family has no option envelope.

    The provider-facing catalog is advisory input to an untrusted model. A
    model can still copy an OLS ``model_options`` object into a family that
    explicitly publishes ``supported: false``. Removing that envelope at
    the typed-planning boundary is safe canonicalization: the selected
    family has declared that it cannot consume those fields, and retaining
    them would only force a bounded retry (or fail after the user waits).
    Families with no explicit policy are left unchanged so a missing
    catalog entry never silently weakens a newly registered contract.
    """

    if submission.proposal.operation_id != "model.genesis":
        return submission
    declaration = catalog.get(submission.capability_id)
    policy = declaration.get("notebook_model_options_policy") if declaration else None
    model_params = submission.proposal.changes.get("model_params")
    model_type = model_params.get("model_type") if isinstance(model_params, Mapping) else None
    # The capability id is an admission label; the nested model_type owns
    # the actual option contract.  Providers occasionally keep the former
    # label from an earlier candidate while changing the latter.  Resolve
    # the policy by the actual family as well, so an OLS covariance cannot
    # leak into logit/GLM/DID merely because the wrapper label was stale.
    if isinstance(model_type, str):
        model_declaration = catalog.get(model_type)
        model_policy = (
            model_declaration.get("notebook_model_options_policy")
            if model_declaration
            else None
        )
        if isinstance(model_policy, Mapping):
            policy = model_policy
    if not isinstance(policy, Mapping) or policy.get("supported") is not False:
        return submission

    changes = dict(submission.proposal.changes)
    changed = False
    if "model_options" in changes:
        changes.pop("model_options", None)
        changed = True
    model_params = changes.get("model_params")
    if isinstance(model_params, Mapping) and "model_options" in model_params:
        normalized_params = dict(model_params)
        normalized_params.pop("model_options", None)
        changes["model_params"] = normalized_params
        changed = True
    model_params = changes.get("model_params")
    if isinstance(model_params, Mapping) and "covariance" in model_params:
        normalized_params = dict(model_params)
        normalized_params.pop("covariance", None)
        changes["model_params"] = normalized_params
        changed = True
    if not changed:
        return submission
    return replace(
        submission,
        proposal=replace(submission.proposal, changes=changes),
    )
