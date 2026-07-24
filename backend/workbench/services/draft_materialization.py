"""Domain constructors for Notebook-owned Pipeline Draft materialization.

The HTTP draft routes and the Notebook materializer must create the same draft
shape.  These functions contain no request models and never execute a draft;
they only validate the source identity and persist a reviewable Draft.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..graph_store import GraphStore
from ..lineage.node_index import NODE_INDEX_FILENAME
from ..lineage.node_write_validation import NodeWriteOperationRequestV1, validate_rerun_operation_target
from ..lineage.op_contract import resolve_operation_contract
from ..lineage.pipeline_drafts import (
    PipelineDraftStore,
    StoredDraft,
    compute_executable_draft_hash,
    new_draft_id,
    schema_hash,
    utc_now,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import verify_upload
from ..repository.run_repository import _read_manifest, _resolve_project_runs_dir, _resolve_run_root
from ..services.run_service import _STRUCTURAL_FOCAL_FAMILIES, _parse_focal_x, parse_column_selector
from ..artifacts import read_json
from pydantic import ValidationError


_TERMINAL_RUN_STATUSES = {
    "completed", "failed", "cancelled", "interrupted", "partial", "blocked",
}


def _backfill_schema_values(editable_schema: list[dict[str, Any]], form: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for param in editable_schema:
        copy = dict(param)
        key = copy.get("key")
        if key in form and form[key] not in (None, ""):
            if key == "x" and copy.get("kind") == "columns":
                raw = form[key]
                if isinstance(raw, list):
                    columns = [str(item).strip() for item in raw if str(item).strip()]
                elif isinstance(raw, str):
                    try:
                        decoded = json.loads(raw)
                    except json.JSONDecodeError:
                        decoded = None
                    if isinstance(decoded, list):
                        columns = [str(item).strip() for item in decoded if str(item).strip()]
                    else:
                        columns = [item.strip() for item in raw.split(",") if item.strip()]
                else:
                    columns = [str(raw).strip()]
                copy["value"] = columns
                copy["options"] = columns
            else:
                copy["value"] = form[key]
        out.append(copy)
    return out


def _inject_focal_x_control(
    editable_schema: list[dict[str, Any]],
    form: Mapping[str, Any],
    model_type: str,
) -> list[dict[str, Any]]:
    if model_type in _STRUCTURAL_FOCAL_FAMILIES:
        return editable_schema
    if any(item.get("key") == "focal_x" for item in editable_schema):
        return editable_schema
    try:
        x_columns = parse_column_selector(form.get("x", ""), "x")
    except ValueError:
        return editable_schema
    if not x_columns:
        return editable_schema
    value = _parse_focal_x(form.get("focal_x", ""), x_columns)
    return [
        *editable_schema,
        {
            "key": "focal_x",
            "kind": "multiselect",
            "label": "Focal explanatory variable(s)",
            "options": list(x_columns),
            "value": value,
        },
    ]


def _source_params_from_schema(editable_schema: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: item.get("value") for item in editable_schema if item.get("key")}


def normalize_ols_genesis_model_params(model_params: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the historical nested covariance spelling for OLS Genesis.

    OLS owns the legacy top-level ``covariance`` form, not the generic
    ``model_options`` contract. Early Notebook providers nevertheless put
    ``{"covariance": ...}`` in ``model_options``. Keep this adapter narrow and
    explicit: only that one known field is migrated; every other nested option
    remains fail-closed instead of being guessed or forwarded to execution.
    """
    normalized = dict(model_params)
    if normalized.get("model_type") != "ols" or "model_options" not in normalized:
        return normalized
    options = normalized.get("model_options")
    if not isinstance(options, Mapping):
        raise ValueError("MODEL_OPTIONS_UNSUPPORTED_FOR_OLS_GENESIS")
    unknown = set(options) - {"covariance"}
    if unknown:
        raise ValueError("MODEL_OPTIONS_UNSUPPORTED_FOR_OLS_GENESIS")
    if "covariance" in options:
        nested_covariance = options["covariance"]
        current_covariance = normalized.get("covariance")
        if current_covariance is not None and current_covariance != nested_covariance:
            raise ValueError("MODEL_OPTIONS_COVARIANCE_CONFLICT")
        normalized["covariance"] = nested_covariance
    normalized.pop("model_options", None)
    return normalized


def _read_indexed_node_hash(run_root: Path, node_id: str) -> str | None:
    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return None
    index = read_json(index_path)
    entry = index.get(node_id) if isinstance(index, dict) else None
    if not isinstance(entry, dict):
        return None
    value = entry.get("node_hash")
    return str(value) if value else None


def _provenance_payload(provenance: Mapping[str, str] | None) -> dict[str, str] | None:
    if provenance is None:
        return None
    if not provenance or any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in provenance.items()
    ):
        raise ValueError("notebook_provenance must contain nonempty string values")
    return {str(key): str(value) for key, value in provenance.items()}


def create_rerun_draft_from_node(
    project_root: Path,
    *,
    source_run_id: str,
    source_model_node_id: str,
    source_op_node_id: str,
    source_node_hash: str,
    source_forest_node_key: str | None,
    source_context_fingerprint: str,
    notebook_provenance: Mapping[str, str] | None = None,
    persist: bool = True,
) -> StoredDraft:
    """Create one source-pinned rerun-child Draft without executing it."""

    root = Path(project_root)
    runs_root = _resolve_project_runs_dir(str(root))
    run_root = _resolve_run_root(str(root), source_run_id)
    manifest = _read_manifest(run_root)
    if manifest.get("status") not in _TERMINAL_RUN_STATUSES:
        raise ValueError("SOURCE_RUN_NOT_TERMINAL")

    graph = GraphStore(runs_root=runs_root).read(source_run_id)
    node = graph.nodes.get(source_op_node_id)
    if node is None:
        raise ValueError("SOURCE_MODEL_NODE_NOT_FOUND")
    if source_model_node_id != source_op_node_id:
        raise ValueError("SOURCE_MODEL_NODE_MISMATCH")
    indexed_hash = _read_indexed_node_hash(run_root, source_op_node_id)
    if indexed_hash is None:
        raise ValueError("SOURCE_NODE_HASH_UNAVAILABLE")
    if indexed_hash != source_node_hash:
        raise ValueError("SOURCE_NODE_HASH_MISMATCH")

    try:
        request = NodeWriteOperationRequestV1(
            request_id="notebook_option_materialization",
            operation="rerun",
            context_version="node-operation-context/v1",
            context_fingerprint=source_context_fingerprint,
            owner_run_id=source_run_id,
            op_node_id=source_op_node_id,
            node_hash=source_node_hash,
            forest_node_key=source_forest_node_key or source_node_hash,
            owner_resolution="single_candidate",
            active_head_run_id=source_run_id,
        )
        validate_rerun_operation_target(runs_root, request)
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"SOURCE_CONTEXT_MISMATCH: {exc}") from exc

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise ValueError("MODEL_NODE_NOT_ELIGIBLE")
    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
    upload = inputs.get("upload") or {}
    source_input_fingerprint = upload.get("sha256")
    if not source_input_fingerprint:
        raise ValueError("SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")

    form = inputs.get("form") or {}
    editable_schema = _backfill_schema_values(contract.editable_schema, form)
    editable_schema = _inject_focal_x_control(editable_schema, form, contract.op_type)
    source_params = _source_params_from_schema(editable_schema)
    now = utc_now()
    draft: dict[str, Any] = {
        "draft_id": new_draft_id(),
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": source_run_id,
            "source_model_node_id": source_model_node_id,
            "source_op_node_id": source_op_node_id,
            "source_node_hash": source_node_hash,
            "source_context_fingerprint": source_context_fingerprint,
            "source_input_fingerprint": source_input_fingerprint,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": source_run_id,
                    "schema_fingerprint": inputs.get("dag_hash") or source_input_fingerprint,
                    "input_fingerprint": source_input_fingerprint,
                    "columns_summary": [{"name": key} for key in sorted(form)],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": contract.op_type,
                    "schema_id": contract.schema_id,
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": source_run_id,
                        "source_model_node_id": source_model_node_id,
                        "source_op_node_id": source_op_node_id,
                        "source_node_hash": source_node_hash,
                        "source_context_fingerprint": source_context_fingerprint,
                    },
                    "source_params": source_params,
                    "params": dict(source_params),
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    provenance = _provenance_payload(notebook_provenance)
    if provenance is not None:
        draft["notebook_provenance"] = provenance
    candidate = StoredDraft(
        draft=draft,
        draft_hash=compute_executable_draft_hash(draft),
    )
    if not persist:
        return candidate
    try:
        return PipelineDraftStore(root).create(draft)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def create_genesis_draft(
    project_root: Path,
    *,
    upload_sha256: str,
    filename: str,
    sheet_names: tuple[str, ...],
    columns: tuple[str, ...],
    model_params: Mapping[str, Any] | None = None,
    exploration_context: Mapping[str, Any] | None = None,
    notebook_provenance: Mapping[str, str] | None = None,
) -> StoredDraft:
    """Create one parentless, upload-bound genesis Draft without executing it."""

    root = Path(project_root)
    _resolve_project_runs_dir(str(root))
    if not re.fullmatch(r"[0-9a-f]{64}", upload_sha256):
        raise ValueError("UPLOAD_NOT_FOUND")
    try:
        verify_upload(root, upload_sha256)
    except (OSError, ValueError) as exc:
        raise ValueError("UPLOAD_NOT_FOUND") from exc
    if not filename or Path(filename).name != filename:
        raise ValueError("FILENAME_INVALID")
    safe_columns = tuple(str(column) for column in columns if str(column))
    requested_model_type = (model_params or {}).get("model_type") if model_params else None
    model_node: dict[str, Any] = {
        "node_id": "model_1",
        "node_type": "model",
        "model_family": "regression",
        "model_type": requested_model_type if isinstance(requested_model_type, str) else None,
        "params": dict(model_params or {}),
        "status": "pending",
    }
    draft: dict[str, Any] = {
        "draft_id": new_draft_id(),
        "schema_version": "pipeline_draft.v1",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": upload_sha256,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "source_1",
                    "node_type": "input.upload",
                    "upload": {"sha256": upload_sha256, "filename": filename},
                    "sheet_names": list(sheet_names),
                    "status": "bound",
                },
                {
                    "node_id": "table_1",
                    "node_type": "table",
                    "params": {"sheet_name": None, "transpose": False},
                    "columns": list(safe_columns),
                    "status": "pending",
                },
                model_node,
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
        "default_execution_mode": "genesis",
    }
    if exploration_context is not None:
        draft["exploration_context"] = dict(exploration_context)
    provenance = _provenance_payload(notebook_provenance)
    if provenance is not None:
        draft["notebook_provenance"] = provenance
    try:
        return PipelineDraftStore(root).create(draft)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


__all__ = ["create_genesis_draft", "create_rerun_draft_from_node"]
