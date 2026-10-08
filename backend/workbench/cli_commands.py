"""What the generated `workbench` commands do (V1812-CLI-FROM-CATALOG).

Each command uses the service the HTTP API or the Agent uses for the same
action, so the command line is not a second implementation: runs go through
``_submit_run``, post-estimation through the workflow engine, exports through
the script-export service, and the model list is the capability catalog.
Imported only when a command runs, so start-up stays light.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL_EVENT_PREFIX = "workflow_"


class CommandError(Exception):
    """A refusal to report on stderr with a non-zero exit status."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _project(project_root: Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not (root / "config.yml").is_file() or not (root / "runs").is_dir():
        raise CommandError(f"{root} is not a Workbench project (create one with `workbench create`).")
    return root


def submit_run(
    project_root: Path,
    data_file: Path,
    values: Mapping[str, Any],
    *,
    on_event: Callable[[dict], None] = lambda _event: None,
) -> tuple[str, str]:
    """Submit a run as POST /runs does, wait for it, return (run_id, status)."""

    from .analysis_ledger import record_ui_action
    from .events import get_event_manager
    from .model_options import ModelOptionsError
    from .orchestrator._errors import WorkflowValidationError
    from .orchestrator._model_types import _validate_requested_model_type
    from .run_request import RunRequestError, form_from_request
    from .services.run_service import _submit_run

    root = _project(project_root)
    data = Path(data_file)
    if not data.is_file():
        raise CommandError(f"data file not found: {data}")
    try:
        form = form_from_request(values)
    except RunRequestError as exc:
        raise CommandError(exc.detail) from exc
    try:
        # The engine's own allowlist, checked before a run exists.
        _validate_requested_model_type(str(form.get("model_type") or "auto"))
    except WorkflowValidationError as exc:
        supported = ", ".join(exc.evidence.get("supported_types", []))
        raise CommandError(f"{exc.error_code}: {exc}" + (f"\nsupported: {supported}" if supported else "")) from exc

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise CommandError("A run is already in progress.")
    run_id: str | None = None
    try:
        try:
            result = _submit_run(
                root, form=form, upload_bytes=data.read_bytes(), upload_filename=data.name,
                started_at=datetime.now(timezone.utc).isoformat(), rerun_reason="initial",
            )
        except ModelOptionsError as exc:
            raise CommandError(exc.code) from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        run_id = str(result["run_id"])
    except Exception:
        events.release_slot(run_id)
        raise
    record_ui_action(
        root, source="workbench run (CLI)", steps=["run.submit"], produced_run_id=run_id,
        summary=json.dumps(
            {key: form.get(key) for key in ("model_type", "y", "x") if form.get(key)},
            ensure_ascii=False, sort_keys=True, default=str,
        )[:500],
    )
    return run_id, _wait_for_terminal(root, run_id, on_event)


def _wait_for_terminal(root: Path, run_id: str, on_event: Callable[[dict], None]) -> str:
    """Follow the run's event stream (as the UI's live log does) to its end.

    A stream closed without a workflow_* event leaves the status the run's
    manifest records.
    """

    from .artifacts import read_json
    from .events import get_event_manager

    events = get_event_manager()
    subscriber, history = events.subscribe(run_id)
    try:
        for event in history:
            on_event(event)
            if str(event.get("event", "")).startswith(TERMINAL_EVENT_PREFIX):
                return str(event.get("status"))
        while True:
            event = subscriber.get()
            if event is None:
                break
            on_event(event)
            if str(event.get("event", "")).startswith(TERMINAL_EVENT_PREFIX):
                return str(event.get("status"))
    finally:
        events.unsubscribe(run_id, subscriber)
    manifest = root / "runs" / run_id / "run_manifest.json"
    return str(read_json(manifest).get("status") or "unknown") if manifest.is_file() else "unknown"


def _model_source(root: Path, run_id: str, model_ref: str) -> dict[str, str]:
    """The dataset node and artifact a model was estimated from, with its SHA-256.

    The workflow records them as the post-estimation step's source; the
    fingerprint is the artifact's content hash, not a placeholder. The
    dataset is the one the run's lineage graph draws into the model node,
    resolved through the same binding the workflow runtime uses, which
    re-checks the artifact's hash.
    """

    from .agent.postestimation_steps import model_id_from_ref
    from .artifacts import read_json
    from .data_operations import resolve_data_column_cast_context

    run_root = root / "runs" / run_id
    if not (run_root / "run_manifest.json").is_file():
        raise CommandError(f"run not found: {run_id}")
    model_node = "model:" + model_id_from_ref(model_ref)
    graph = read_json(run_root / "graph.json")
    nodes = graph.get("nodes") or {}
    if not isinstance(nodes.get(model_node), Mapping):
        raise CommandError(f"{model_node} is not a model node of run {run_id}")
    inputs = {
        str(edge.get("source_id")) for edge in (graph.get("edges") or {}).values()
        if isinstance(edge, Mapping) and edge.get("target_id") == model_node
        and (nodes.get(edge.get("source_id")) or {}).get("kind") == "dataset_stage"
    }
    if len(inputs) != 1:
        raise CommandError(f"the lineage graph of run {run_id} does not name one dataset {model_node} was estimated from")
    [source_node] = inputs
    try:
        context = resolve_data_column_cast_context(root, source_run_id=run_id, source_node_id=source_node)
    except ValueError as exc:
        raise CommandError(f"the dataset {model_node} was estimated from is unavailable: {exc}") from exc
    records = read_json(run_root / "artifacts_index.json").get("artifacts", [])
    record = next((item for item in records if item.get("artifact_id") == context["source_artifact_id"]), None)
    if record is None or not record.get("sha256"):
        raise CommandError(f"the dataset {model_node} was estimated from has no registered content hash")
    return {
        "node_ref": source_node,
        "artifact_id": str(record["artifact_id"]),
        "fingerprint": "sha256:" + str(record["sha256"]),
    }


def run_postestimation(project_root: Path, run_id: str, operation: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Run one post-estimation operation as a one-step workflow, as the Agent does."""

    from .contracts.common.errors import OperationValidationError
    from .agent.workflow import WorkflowExecutor, compile_workflow
    from .agent.workflow_runtime import build_workflow_step_executor
    from .analysis_ledger import record_ui_action

    root = _project(project_root)
    source_run = str(spec.get("model_run_id") or run_id)
    source = _model_source(root, source_run, str(spec.get("model_ref", "")))
    workflow_id = f"cli-{operation}-{uuid.uuid4().hex[:12]}"
    try:
        draft = compile_workflow(
            workflow_id=workflow_id,
            target={"run_id": source_run, "node_ref": source["node_ref"], "artifact_id": source["artifact_id"]},
            preconditions={
                "context_version": "workbench-cli/v1",
                "context_fingerprint": source["fingerprint"],
                "source_artifact_fingerprint": source["fingerprint"],
                "active_head_run_id": run_id,
                "owner_resolution": "explicit_run",
            },
            steps=[{"step_id": operation, "operation_id": "postestimation." + operation, "spec": dict(spec)}],
        )
    except OperationValidationError as exc:
        raise CommandError(str(exc)) from exc
    state = WorkflowExecutor(root).execute(draft, build_workflow_step_executor(root, draft))
    step = state.steps[operation]
    if state.status != "completed":
        raise CommandError(f"postestimation {operation} {state.status}: {step.error or 'no detail'}", code=1)
    record_ui_action(
        root, source="workbench postestimation (CLI)", steps=["postestimation." + operation],
        run_id=source_run, node_id=source["node_ref"], summary=f"{operation} on {spec.get('model_ref')}",
    )
    artifacts = {item["artifact_id"]: item for item in _artifact_records(root, source_run)}
    return {
        "workflow_id": workflow_id,
        "status": state.status,
        "run_id": source_run,
        "artifact_ids": list(step.artifact_ids),
        "results": [_read_result(root, source_run, artifacts.get(artifact_id)) for artifact_id in step.artifact_ids],
    }


def _artifact_records(root: Path, run_id: str) -> list[dict]:
    from .artifacts import read_json

    return list(read_json(root / "runs" / run_id / "artifacts_index.json").get("artifacts", []))


def _read_result(root: Path, run_id: str, record: Mapping[str, Any] | None) -> Any:
    from .artifacts import read_json

    if not record or not str(record.get("path", "")).endswith(".json"):
        return None
    payload = read_json(root / "runs" / run_id / str(record["path"]))
    return payload.get("result", payload) if isinstance(payload, Mapping) else payload


def export_targets(project_root: Path, run_id: str, model_target: str) -> dict[str, Any]:
    from .script_export.plan import ScriptExportRefusal
    from .services.script_export import list_script_export_targets

    root = _project(project_root)
    try:
        return list_script_export_targets(root, run_id, model_target)
    except ScriptExportRefusal as exc:
        raise CommandError(f"{exc.code}: {exc}") from exc


def export_script(
    project_root: Path, run_id: str, target: str, language: str, *, require_native: bool, output: Path | None,
) -> dict[str, Any]:
    """Export as POST /runs/{id}/script-export does; optionally copy the bundle out."""

    from .analysis_ledger import record_ui_action
    from .egress import EgressPolicyError
    from .script_export.plan import ScriptExportRefusal
    from .services.script_export import export_analysis_script

    root = _project(project_root)
    try:
        result = export_analysis_script(root, run_id, target, language, require_native=require_native)
    except EgressPolicyError as exc:
        raise CommandError(f"SCRIPT_EXPORT_EGRESS_DENIED: {exc}") from exc
    except ScriptExportRefusal as exc:
        raise CommandError(f"{exc.code}: {exc}") from exc
    record_ui_action(
        root, source="workbench export-script (CLI)", steps=["export.analysis_script"],
        run_id=run_id, node_id=target, summary="Local " + str(result["language"]) + " script export",
    )
    record = next((item for item in _artifact_records(root, run_id) if item["artifact_id"] == result["artifact_id"]), None)
    if record is None:
        raise CommandError(f"the exported bundle {result['artifact_id']} is not registered in run {run_id}", code=1)
    bundle = root / "runs" / run_id / str(record["path"])
    result = {key: value for key, value in result.items() if key != "download_url"}
    result["bundle_path"] = str(bundle)
    if output is not None:
        destination = Path(output).expanduser()
        if destination.is_dir():
            destination = destination / str(result["filename"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle, destination)
        result["output_path"] = str(destination.resolve())
    return result


def catalog(model_type: str | None = None) -> dict[str, Any]:
    from .engine.capabilities import build_capabilities

    capabilities = build_capabilities()
    if model_type is None:
        return capabilities
    for entry in capabilities["model_types"]:
        if entry["key"] == model_type:
            return entry
    known = ", ".join(entry["key"] for entry in capabilities["model_types"])
    raise CommandError(f"unknown model type {model_type!r}; known: {known}")
