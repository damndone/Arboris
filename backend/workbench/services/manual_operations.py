"""Provider-free manual workflows using the existing proposal lifecycle."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, Mapping

from filelock import FileLock

from ..agent.events import AgentEventStream
from ..agent.operations import OperationRecordStore, OperationRegistry
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.session import JsonlSessionRepository
from ..agent.workflow import WorkflowStateStore, compile_workflow
from ..agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from ..api_errors import WorkbenchAPIError
from ..artifacts import read_json
from ..canonical import sha256_canonical
from ..contracts.common.errors import OperationValidationError
from ..statistical_exploration import resolve_statistical_source


def _error(code: str, message: str, status: int = 422) -> WorkbenchAPIError:
    return WorkbenchAPIError(status, code, message)


def _safe_run(root: Path, run_id: str) -> None:
    runs = (root / "runs").resolve()
    if not run_id or Path(run_id).name != run_id or run_id.startswith("."):
        raise ValueError("run_id must be a path-safe run identity")
    (runs / run_id).resolve().relative_to(runs)


def _resolve_target(root: Path, requested: Mapping[str, Any]):
    """Return server-owned workflow target, data, and optional upload source."""
    kind = requested["kind"]
    if kind == "upload":
        from ..agent.notebook.store import ProjectionSource, reserve_dataset_upload_workflow_source
        from .notebook_source_materialization import read_notebook_upload_frame

        source = reserve_dataset_upload_workflow_source(ProjectionSource(
            kind="dataset", upload_sha256=requested["upload_sha256"],
            filename=requested["filename"], sheet_names=tuple(requested.get("sheet_names", [])),
        ))
        frame = read_notebook_upload_frame(root, source)
        binding = source.workflow_source
        assert binding is not None
        return ({"run_id": binding.run_id, "node_ref": binding.node_ref, "artifact_id": binding.artifact_id},
                frame, str(binding.source_sha256), source)
    run_id = requested["run_id"]
    _safe_run(root, run_id)
    if kind == "model_node":
        from ..cli_commands import _model_source

        source = _model_source(root, run_id, requested["node_id"])
        target = {"run_id": run_id, "node_ref": source["node_ref"], "artifact_id": source["artifact_id"]}
    else:
        target = {"run_id": run_id, "node_ref": requested["node_id"], "artifact_id": requested["artifact_id"]}
    context, frame = resolve_statistical_source(
        root, source_run_id=target["run_id"], source_node_id=target["node_ref"],
        source_artifact_id=target["artifact_id"],
    )
    return target, frame, str(context["source_sha256"]), None


def _compile(root: Path, request: Mapping[str, Any], token: str):
    target, frame, source_sha, upload = _resolve_target(root, request["target"])
    steps = deepcopy(request["steps"])
    if request["target"]["kind"] == "model_node":
        for step in steps:
            if str(step.get("operation_id", "")).startswith("postestimation."):
                spec = step.setdefault("spec", {})
                spec.setdefault("model_ref", request["target"]["node_id"])
                spec.setdefault("model_run_id", request["target"]["run_id"])
    preconditions = {
        "context_version": "manual-operation-source/v1",
        "context_fingerprint": sha256_canonical({"target": target, "source_sha256": source_sha}),
        "source_artifact_fingerprint": source_sha,
        "active_head_run_id": target["run_id"], "owner_resolution": "explicit_manual_source",
    }
    draft = compile_workflow(
        workflow_id=f"workflow_manual_{token}", target=target, preconditions=preconditions,
        steps=steps, available_columns=[str(column) for column in frame.columns],
    )
    for step in draft.steps:
        contract = WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id]
        if contract.dispatcher_key == "capability_factory.custom_dispatcher":
            raise _error("AUTHORIZED_GATEWAY_REQUIRED", "This dispatcher requires a server-bound capability authorization and containment gateway.")
        if contract.risk_level == "high" and contract.confirmation_policy not in {
            "proposal_authorization", "proposal_confirmation",
        }:
            raise _error("AUTHORIZED_GATEWAY_REQUIRED", "The declared authorization policy requires a dedicated confirmation gateway.")
    # Upload materialization is itself a mutation even for a read-only step.
    requires_confirmation = upload is not None or any(
        WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id].effect_level != "read_only"
        or WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id].risk_level == "high"
        for step in draft.steps
    )
    return draft, steps, upload, requires_confirmation


def _result(root: Path, proposal, request_id: str, record=None) -> dict[str, Any]:
    workflow_id = f"workflow_{record.record_id}" if record is not None else None
    if record is not None:
        workflow_id = str(record.execution.get("workflow_id") or workflow_id)
    response: dict[str, Any] = {
        "request_id": request_id, "preview_id": proposal.proposal_id,
        "fingerprint": proposal.fingerprint, "revision": proposal.revision,
        "status": record.status if record is not None else "awaiting_confirmation",
        "confirmation_required": bool(proposal.preconditions["manual_confirmation_required"]),
        "workflow_id": workflow_id, "operation_record_id": record.record_id if record is not None else None,
        "target": dict(proposal.target), "steps": [], "error": record.error if record is not None else None,
        "expected_effect": list(proposal.expected_effect), "risks": list(proposal.risks),
    }
    state = None
    if workflow_id and (root / "workbench" / "workflows" / f"{workflow_id}.jsonl").is_file():
        state = WorkflowStateStore(root, workflow_id).current()
    source_run = str(proposal.target["run_id"])
    for step in proposal.changes["steps"]:
        step_id = step["step_id"]
        stored = state.steps.get(step_id) if state is not None else None
        artifacts, nodes = [], []
        run_ids = {source_run}
        if stored is not None:
            for branch in stored.model_branches or []:
                if branch.get("run_id"):
                    run_ids.add(str(branch["run_id"]))
            spec_run = step.get("spec", {}).get("model_run_id")
            if spec_run:
                run_ids.add(str(spec_run))
            for run_id in sorted(run_ids):
                _safe_run(root, run_id)
                run_root = root / "runs" / run_id
                index_path = run_root / "artifacts_index.json"
                index = read_json(index_path).get("artifacts", []) if index_path.is_file() else []
                # Model-producing steps publish run-qualified identities;
                # read both forms only against the selected run's index.
                owned = {item["artifact_id"]: item for item in index if (
                    item.get("artifact_id") in stored.artifact_ids
                    or f"{run_id}:{item.get('artifact_id')}" in stored.artifact_ids
                )}
                artifacts.extend({"run_id": run_id, "artifact_id": item} for item in sorted(owned))
                graph_path = run_root / "graph.json"
                graph = read_json(graph_path) if graph_path.is_file() else {}
                paths = {item.get("path") for item in owned.values()}
                nodes.extend({"run_id": run_id, "node_id": key} for key, node in graph.get("nodes", {}).items()
                             if node.get("payload_ref") in paths and node.get("payload_ref"))
        response["steps"].append({
            "step_id": step_id, "operation_id": step["operation_id"],
            "spec": deepcopy(step["spec"]),
            "status": stored.status if stored is not None else "pending",
            "artifact_refs": artifacts, "node_refs": nodes,
            "error": stored.error if stored is not None else None,
            "row_counts": dict(stored.row_counts) if stored is not None else {},
        })
    return response


def run_manual_operation(
    project_root: str | Path, request: Mapping[str, Any], *, origin: Literal["ui", "cli"] = "ui",
) -> dict[str, Any]:
    """Prepare or execute a server-pinned workflow; never contact a provider.

    The request lock serializes creation/replay across processes. Execution
    retains WorkbenchOperationLifecycle's own effect binding and domain lease.
    This synchronous service runs in the HTTP threadpool, not the event loop.
    """
    from ..cli_commands import CommandError

    if origin not in {"ui", "cli"}:
        raise _error("OPERATION_ORIGIN_INVALID", "Unknown trusted operation adapter.")
    role = "manual_operation_cli" if origin == "cli" else "manual_operation"
    actor_type = "human_cli" if origin == "cli" else "human_ui"
    evidence_ref = "workbench data (CLI)" if origin == "cli" else "POST /operations/run"
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir() or not (root / "runs").is_dir():
        raise _error("PROJECT_NOT_FOUND", "Workbench project runs directory was not found.", 404)
    request_id = str(request["request_id"])
    token = sha256_canonical({"request_id": request_id})[:24]
    proposal_id = f"proposal_manual_{token}"
    mode = request["mode"]
    semantic = {"target": request.get("target"), "steps": request.get("steps")}
    # Validate new submissions before creating any business records.
    existing_path = root / "workbench" / "proposals" / f"{proposal_id}.jsonl"
    if mode != "confirm" and not existing_path.is_file():
        try:
            _compile(root, semantic, token)
        except (OSError, ValueError, KeyError, CommandError, OperationValidationError) as exc:
            raise _error("OPERATION_INVALID", str(exc)) from exc
    locks = root / "workbench" / "manual-operation-locks"
    locks.mkdir(parents=True, exist_ok=True)
    with FileLock(str(locks / f"{token}.lock")):
        store = ProposalStore(root / "workbench", create=False)
        try:
            proposal = store.latest_revision(proposal_id)
        except KeyError:
            proposal = None
        if proposal is None and mode == "confirm":
            raise _error("PREVIEW_NOT_FOUND", "No manual preview exists for this request_id.", 404)
        if proposal is not None:
            if proposal.preconditions.get("manual_origin", "ui") != origin:
                raise _error("REQUEST_ORIGIN_CONFLICT", "This request_id belongs to another adapter origin.", 409)
            if mode == "confirm":
                if request.get("preview_id") != proposal_id or request.get("fingerprint") != proposal.fingerprint:
                    raise _error("CONFIRMATION_CONFLICT", "Confirmation does not match the server preview.", 409)
            elif sha256_canonical(semantic) != proposal.preconditions["manual_request_hash"]:
                raise _error("REQUEST_ID_CONFLICT", "This request_id already belongs to different parameters or target.", 409)
            # Return the same terminal result without running or logging again.
            confirmation = store.latest_confirmation(proposal_id)
            if confirmation is not None:
                records = OperationRecordStore(root / "workbench", create=False)
                record_id = records._record_id(confirmation, command_id=confirmation.command_id)
                try:
                    record = records.get(record_id)
                except KeyError:
                    record = None
                if record is not None and record.status in {"completed", "failed", "stale", "cancelled"}:
                    return _result(root, proposal, request_id, record)
            semantic = proposal.preconditions["manual_request"]
        try:
            # Recheck at confirmation, even if preview validation succeeded.
            draft, steps, upload, requires_confirmation = _compile(root, semantic, token)
        except (OSError, ValueError, KeyError, CommandError, OperationValidationError) as exc:
            raise _error("OPERATION_STALE" if proposal else "OPERATION_INVALID", str(exc), 409 if proposal else 422) from exc
        if proposal is not None and proposal.preconditions["context_fingerprint"] != draft.preconditions["context_fingerprint"]:
            raise _error("OPERATION_STALE", "The source changed after the manual preview.", 409)
        repository = JsonlSessionRepository(root / "workbench")
        session_id = f"manual_operation_{token}"
        chain_id = f"manual_source_{sha256_canonical(draft.target)[:24]}"
        try:
            metadata = repository.get_metadata(session_id)
        except (KeyError, ValueError):
            metadata = repository.create_session(session_id, chain_id=chain_id, role=role)
        if metadata.get("role") != role or metadata.get("chain_id") != chain_id:
            raise _error("SESSION_CONFLICT", "Manual execution session identity is inconsistent.", 409)
        events = AgentEventStream(root / "workbench")
        store = ProposalStore(root / "workbench")
        if proposal is None:
            preconditions = {**draft.preconditions, "manual_request": semantic,
                             "manual_request_hash": sha256_canonical(semantic),
                             "manual_confirmation_required": requires_confirmation, "manual_origin": origin}
            proposal = store.create(
                session_id=session_id, chain_id=chain_id, command_id=request_id,
                operation_id="operation.multi_step", target=draft.target, preconditions=preconditions,
                changes={"steps": steps}, evidence_refs=[evidence_ref],
                expected_effect=[WORKFLOW_STEP_SPEC_CONTRACTS[step.operation_id].summary for step in draft.steps],
                risks=["Creates immutable analysis artifacts and declared dataset/model outputs."],
                proposal_id=proposal_id,
            )
        if mode == "preview" or (mode == "execute" and requires_confirmation):
            return _result(root, proposal, request_id)
        orchestrator = WorkbenchOrchestrator(repository, events, main_session_id=session_id, proposal_store=store)
        try:
            record = orchestrator.confirm_proposal(
                proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
                actor_type=actor_type, current_context_fingerprint=draft.preconditions["context_fingerprint"],
                current_active_head_run_id=draft.target["run_id"],
            )
            if upload is not None:
                from ..agent.notebook.service import NotebookService
                from .notebook_source_materialization import materialize_notebook_upload_source

                notebook = NotebookService(root).ensure_default_projection(dataset=upload, created_by=actor_type)
                materialize_notebook_upload_source(root, source=upload, run_family_id=notebook.run_family_id)
            record = asyncio.run(orchestrator.execute_confirmed_operation(
                record.record_id, project_root=root,
                current_context_fingerprint=draft.preconditions["context_fingerprint"],
                current_active_head_run_id=draft.target["run_id"],
                allow_recovery=record.status in {"submitted", "running", "recovering"},
            ))
        except (ProposalStaleError, ProposalConfirmationError) as exc:
            raise _error("OPERATION_STALE", str(exc), 409) from exc
        return _result(root, proposal, request_id, record)
