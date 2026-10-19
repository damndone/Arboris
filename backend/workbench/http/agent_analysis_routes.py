"""agent analysis routes: extracted HTTP responsibility."""
from __future__ import annotations
from time import perf_counter
from typing import Any
from ..agent.analysis_loop_driver import forward_analysis_intent
from ..agent.context_tools import AnalysisLoopContextError, inspect_analysis_loop_context, parse_analysis_loop_packet_payloads
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..analysis_loop.compare import ComparePacket
from ..analysis_loop.lifecycle import AnalysisLoopProposalError, create_analysis_loop_proposal
from ..analysis_loop.plan import PlanDiff, PlanValidationError
from ..analysis_loop.recovery import RECOVERY_ACTIONS
from ..analysis_loop.resolver import AnalysisLoopSourceResolutionError, resolve_analysis_loop_inputs, resolve_analysis_loop_run
from ..analysis_loop.storage import ComparePacketStore, PlanDiffStore, ValidationPacketStore
from ..analysis_loop.validation import ValidationPacket
from ..contracts.common.errors import OperationValidationError
from ..agent.orchestrator import WorkbenchOrchestrator
from ..api_errors import WorkbenchAPIError
from .responses.agent import AnalysisLoopContext, AnalysisLoopIntent, AnalysisLoopPackets, AnalysisLoopProposal
from .agent_route_context import (_authoritative_active_head, _ensure_main_session, _get_session, _project_root)
from .agent_route_proposals import (_public_proposal)
from .agent_route_requests import (AnalysisLoopContextRequest, AnalysisLoopIntentRequest, AnalysisLoopProposalRequest)

from fastapi import APIRouter
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

def _analysis_loop_run_facts(resolved) -> dict[str, Any]:
    """Expose bounded persisted OLS facts for the read-only detail surface."""

    result = resolved.result if isinstance(resolved.result, dict) else {}
    sample = result.get("analysis_sample")
    fingerprints = {
        key: result.get(key)
        for key in (
            "dataset_snapshot_fingerprint",
            "analysis_sample_fingerprint",
            "point_estimation_fingerprint",
            "coefficient_schema_fingerprint",
            "inference_config_fingerprint",
        )
        if result.get(key) is not None
    }
    return {
        "run_id": resolved.run_id,
        "status": resolved.manifest.get("status"),
        "model": result.get("model"),
        "contract_version": result.get("contract_version"),
        "covariance": result.get("covariance"),
        "covariance_product": (
            "conventional"
            if result.get("covariance") == "unadjusted"
            else result.get("covariance")
        ),
        "covariance_wire": result.get("covariance_wire"),
        "entity_col": result.get("entity_col"),
        "stable_result_ids": list(result.get("stable_result_ids") or []),
        "primary_estimand": result.get("primary_estimand"),
        "analysis_sample": {
            "row_count": sample.get("row_count"),
            "row_order": list(sample.get("row_order") or []),
        } if isinstance(sample, dict) else None,
        "fingerprints": fingerprints,
    }


def _analysis_loop_packet_bundle(
    *,
    validation_packet,
    compare_packets: list[ComparePacket],
    plan_packets,
) -> dict[str, Any]:
    compare = next(
        (
            packet
            for packet in compare_packets
            if packet.child_run_id == validation_packet.child_run_id
            and packet.source_run_id == validation_packet.source_run_id
        ),
        None,
    )
    plan = next(
        (
            packet.plan_diff
            for packet in plan_packets
            if packet.plan_diff.plan_hash == validation_packet.plan_hash
        ),
        None,
    )
    return {
        "child_run_id": validation_packet.child_run_id,
        "source_run_id": validation_packet.source_run_id,
        "plan_diff": plan.to_dict() if plan is not None else None,
        "validation_packet": validation_packet.to_dict(),
        "compare_packet": compare.to_dict() if compare is not None else None,
    }


@router.get("/analysis-loop/packets/{run_id}")
def get_analysis_loop_packets(
    run_id: str,
    project_root: str,
) -> AnalysisLoopPackets:
    """Read persisted Analysis Loop facts for one graph run.

    This endpoint is deliberately read-only.  It never builds a packet or
    infers a comparison.  Terminal packets are selected by their durable
    child/source IDs; the UI receives the backend's exact packet payloads.
    """

    root = _project_root(project_root)
    try:
        resolved = resolve_analysis_loop_run(root, run_id=run_id, require_result=False)
    except AnalysisLoopSourceResolutionError as exc:
        status_code = 404 if exc.code == "SOURCE_RUN_NOT_FOUND" else 422
        raise WorkbenchAPIError(
            status_code=status_code,
            code=("ANALYSIS_LOOP_RUN_NOT_FOUND" if status_code == 404 else exc.code),
            message=str(exc),
            details={"run_id": run_id},
        ) from exc

    validation_store = ValidationPacketStore(root, create=False)
    compare_store = ComparePacketStore(root, create=False)
    plan_store = PlanDiffStore(root, create=False)
    validations = validation_store.list_terminal_packets()
    compares = compare_store.list_terminal_packets()
    plans = plan_store.list_terminal_packets()

    current = [packet for packet in validations if packet.child_run_id == run_id]
    current.sort(key=lambda packet: packet.logical_key)
    current_bundle = (
        _analysis_loop_packet_bundle(
            validation_packet=current[0],
            compare_packets=compares,
            plan_packets=plans,
        )
        if current
        else None
    )
    child_bundles = [
        _analysis_loop_packet_bundle(
            validation_packet=packet,
            compare_packets=compares,
            plan_packets=plans,
        )
        for packet in sorted(
            (item for item in validations if item.source_run_id == run_id),
            key=lambda item: item.logical_key,
        )
    ]

    source_run = None
    source_run_id = (
        current[0].source_run_id
        if current
        else str(
            resolved.run_inputs.get("rerun_of")
            or resolved.manifest.get("source_run_id")
            or run_id
        )
    )
    try:
        source_resolved = resolve_analysis_loop_run(
            root,
            run_id=source_run_id,
            require_result=False,
        )
        source_run = _analysis_loop_run_facts(source_resolved)
    except AnalysisLoopSourceResolutionError:
        # The packet remains inspectable even if a historical source has been
        # removed or became unreadable; do not hide the durable child evidence.
        source_run = {"run_id": source_run_id, "status": "unavailable"}

    lifecycle_status = str(resolved.manifest.get("status") or "")
    status = (
        current[0].status
        if current
        else "pending"
        if lifecycle_status in {"queued", "running", "pending"}
        else "absent"
    )
    return {
        "status": status,
        "run": _analysis_loop_run_facts(resolved),
        "source_run": source_run,
        "packet": current_bundle,
        "children": child_bundles,
    }


def _analysis_loop_packets_from_request(
    body: AnalysisLoopContextRequest,
) -> tuple[PlanDiff | None, ValidationPacket | None, ComparePacket | None]:
    """Parse packet payloads without reading or mutating project state."""

    try:
        return parse_analysis_loop_packet_payloads(
            plan_diff=body.plan_diff,
            validation_packet=body.validation_packet,
            compare_packet=body.compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message="The analysis-loop packet payload is invalid.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/agent/sessions/{session_id}/analysis-loop/context")
def inspect_agent_analysis_loop_context(
    session_id: str,
    project_root: str,
    body: AnalysisLoopContextRequest,
) -> AnalysisLoopContext:
    """Return one scope of typed analysis-loop context, read-only.

    The HTTP seam intentionally accepts already-structured packet payloads so
    fixture clients and future backend resolvers share one strict domain
    boundary. It does not calculate packets, read arbitrary files, create a
    proposal, or execute an operation.
    """

    root = _project_root(project_root)
    _get_session(root, session_id)
    plan_diff, validation_packet, compare_packet = _analysis_loop_packets_from_request(body)
    try:
        context = inspect_analysis_loop_context(
            source_context=body.source_context,
            scope=body.scope,
            plan_diff=plan_diff,
            validation_packet=validation_packet,
            compare_packet=compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"scope": body.scope},
        ) from exc
    return {
        "status": context["status"],
        "context": context,
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/intents")
def submit_agent_analysis_loop_intent(
    session_id: str,
    project_root: str,
    body: AnalysisLoopIntentRequest,
) -> AnalysisLoopIntent:
    """Classify one untrusted intent without creating a proposal or effect."""

    root = _project_root(project_root)
    _get_session(root, session_id)
    decision = forward_analysis_intent(body.intent)
    return {
        "status": "accepted" if decision.accepted else "rejected",
        "decision": decision.to_dict(),
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/proposals")
def create_agent_analysis_loop_proposal(
    session_id: str,
    project_root: str,
    body: AnalysisLoopProposalRequest,
) -> AnalysisLoopProposal:
    """Resolve persisted OLS facts and create one confirmation-gated proposal."""

    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    if metadata.get("role") != "chain":
        raise WorkbenchAPIError(
            status_code=409,
            code="ANALYSIS_LOOP_SCOPE_INVALID",
            message="An analysis-loop proposal must belong to a Chain Agent session.",
            details={"session_id": session_id},
        )
    chain_id = str(metadata.get("chain_id") or "")
    authoritative_active_head_run_id = _authoritative_active_head(
        root,
        chain_id=chain_id,
        requested_active_head_run_id=body.active_head_run_id,
    )
    provider = NodeOperationContextProvider(root)
    context_started = perf_counter()
    try:
        snapshot = provider.inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"analysis-loop-proposal:{body.source_run_id}:{body.source_node_ref}",
                owner_run_id=body.source_run_id,
                op_node_id=body.source_node_ref,
                active_head_run_id=authoritative_active_head_run_id,
            )
        )
        context_ms = round((perf_counter() - context_started) * 1000, 3)
        resolved = resolve_analysis_loop_inputs(
            root,
            run_id=body.source_run_id,
            cluster_variable=body.cluster_variable,
        )
    except AnalysisLoopSourceResolutionError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"run_id": body.source_run_id},
        ) from exc
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected OLS node or active head could not be verified.",
            details={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
            },
        ) from exc
    if resolved.source.run_id != body.source_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="SOURCE_IDENTITY_MISMATCH",
            message="The resolved source does not match the requested run.",
            details={"run_id": body.source_run_id},
        )
    if snapshot.get("active_head_run_id") != authoritative_active_head_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected source is outside the current active head.",
            details={"run_id": body.source_run_id},
        )

    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=provider,
    )
    plan_started = perf_counter()
    try:
        proposal = create_analysis_loop_proposal(
            orchestrator=orchestrator,
            chain_id=chain_id,
            session_id=session_id,
            plan_store=PlanDiffStore(repository.root, create=False),
            source=resolved.source,
            intent={
                "action_id": "ols.use_clustered_covariance_v1",
                "patch": {
                    "covariance": "clustered",
                    "cluster_variable": body.cluster_variable,
                },
            },
            cluster_values=resolved.cluster_values,
            model_row_ids=resolved.model_row_ids,
            requested_result_id=body.result_id,
            source_context_fingerprint=str(snapshot["context_fingerprint"]),
            source_identity={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "node_hash": str(snapshot["node_hash"]),
                "forest_node_key": str(snapshot["forest_node_key"]),
            },
            active_head_run_id=authoritative_active_head_run_id,
            owner_resolution=str(snapshot["owner_resolution"]),
        )
        plan_ms = round((perf_counter() - plan_started) * 1000, 3)
    except AnalysisLoopProposalError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except PlanValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="ANALYSIS_LOOP_PROPOSAL_INVALID",
            message="The canonical analysis-loop proposal was rejected by the operation registry.",
            details={"reason": str(exc)},
        ) from exc
    plan_store = PlanDiffStore(repository.root, create=False)
    logical_key = proposal.preconditions.get("plan_logical_key")
    packet = plan_store.get_terminal_packet(str(logical_key)) if logical_key else None
    if packet is None:
        raise WorkbenchAPIError(
            status_code=500,
            code="ANALYSIS_LOOP_PLAN_MISSING",
            message="The analysis-loop proposal has no persisted PlanDiff.",
            details={"proposal_id": proposal.proposal_id},
        )
    return {
        "session_id": session_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "plan_diff": packet.plan_diff.to_dict(),
        "registered_action": RECOVERY_ACTIONS["ols.use_clustered_covariance_v1"].to_dict(),
        "timings_ms": {
            "node_operation_context_ms": context_ms,
            "plan_diff_ms": plan_ms,
        },
        "status": "pending",
    }

