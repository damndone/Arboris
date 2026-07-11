"""Pipeline-draft routes: create-from-node / genesis / CRUD / validate / execute.

Extracted from api.py in v1.6.10 (D1 decomposition, Phase 4)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..artifacts import read_json
from ..graph_store import GraphStore
from ..lineage.node_index import NODE_INDEX_FILENAME
from ..lineage.node_write_validation import NodeWriteOperationRequestV1, validate_rerun_operation_target
from ..lineage.op_contract import resolve_operation_contract
from ..lineage.pipeline_drafts import DraftHashConflict, DraftLockedForExecution, DraftNodeNotFound, DraftNodePatchConflict, DraftNotFound, DraftValidationFailure, PipelineDraftStore, new_draft_id, schema_hash, utc_now, validate_draft_for_execution
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import delete_upload_if_unreferenced, verify_upload
from ..repository.run_repository import _read_manifest, _resolve_project_runs_dir, _resolve_run_root
from ..services.run_service import _STRUCTURAL_FOCAL_FAMILIES, _parse_focal_x
from ._deps import _TERMINAL_RUN_STATUSES, _backfill_schema_values

from ..services.draft_service import execute_genesis_draft, execute_rerun_child_draft

router = APIRouter()


def _inject_focal_x_control(
    editable_schema: list[dict[str, Any]],
    form: dict[str, Any],
    model_type: str,
) -> list[dict[str, Any]]:
    """v1.6.5 — add a `focal_x` multiselect to a model node's editable_schema so
    the draft inspector can re-declare the focal explanatory variable(s).

    Omitted for structural-focal families (IV/DID/CS/SA/dCDH), where
    focal/treatment is structural — mirrors the run-POST clear (spec §5). The
    options are the run's x columns; the value is the run's canonicalized
    focal_x. No-op when there are no x columns or the control already exists."""
    if model_type in _STRUCTURAL_FOCAL_FAMILIES:
        return editable_schema
    if any(item.get("key") == "focal_x" for item in editable_schema):
        return editable_schema
    x_columns = [part.strip() for part in form.get("x", "").split(",") if part.strip()]
    if not x_columns:
        return editable_schema
    value = _parse_focal_x(form.get("focal_x", ""), x_columns)
    control = {
        "key": "focal_x",
        "kind": "multiselect",
        "label": "Focal explanatory variable(s)",
        "options": list(x_columns),
        "value": value,
    }
    return [*editable_schema, control]


class PipelineDraftFromNodeRequest(BaseModel):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_forest_node_key: str | None = None
    source_context_fingerprint: str


class PipelineDraftPatchRequest(BaseModel):
    model_node_id: str
    base_draft_hash: str
    params: dict[str, Any]


class PipelineDraftValidateRequest(BaseModel):
    execution_mode: Literal["rerun_child", "new_run", "genesis"] | None = None


class PipelineDraftExecuteRequest(BaseModel):
    validated_draft_hash: str
    execution_mode: Literal["rerun_child", "new_run", "genesis"]
    idempotency_key: str | None = None


def _pipeline_draft_store(project_root: str) -> PipelineDraftStore:
    return PipelineDraftStore(Path(project_root))


def _draft_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DraftNotFound):
        return HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
    if isinstance(exc, DraftNodeNotFound):
        return HTTPException(status_code=404, detail=f"DRAFT_NODE_NOT_FOUND: {exc}")
    if isinstance(exc, DraftNodePatchConflict):
        return HTTPException(status_code=409, detail=f"{DraftNodePatchConflict.code}: {exc}")
    if isinstance(exc, DraftHashConflict):
        return HTTPException(status_code=409, detail="DRAFT_HASH_CONFLICT")
    if isinstance(exc, DraftLockedForExecution):
        return HTTPException(status_code=409, detail="DRAFT_LOCKED_FOR_EXECUTION")
    if isinstance(exc, DraftValidationFailure):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _read_indexed_node_hash(run_root: Path, node_id: str) -> str | None:
    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return None
    index = read_json(index_path)
    entry = index.get(node_id)
    if not isinstance(entry, dict):
        return None
    node_hash = entry.get("node_hash")
    return str(node_hash) if node_hash else None


def _source_params_from_schema(editable_schema: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        item["key"]: item.get("value")
        for item in editable_schema
        if item.get("key")
    }


@router.post("/pipeline-drafts/from-node")
def create_pipeline_draft_from_node(
    project_root: str,
    body: PipelineDraftFromNodeRequest,
) -> dict[str, Any]:
    runs_root = _resolve_project_runs_dir(project_root)
    run_root = _resolve_run_root(project_root, body.source_run_id)
    manifest = _read_manifest(run_root)
    if manifest.get("status") not in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Source run not terminal (status={manifest.get('status')}).",
        )

    graph = GraphStore(runs_root=runs_root).read(body.source_run_id)
    node = graph.nodes.get(body.source_op_node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="SOURCE_MODEL_NODE_NOT_FOUND")
    if body.source_model_node_id != body.source_op_node_id:
        raise HTTPException(status_code=409, detail="SOURCE_MODEL_NODE_MISMATCH")

    indexed_hash = _read_indexed_node_hash(run_root, body.source_op_node_id)
    if indexed_hash is None:
        raise HTTPException(status_code=422, detail="SOURCE_NODE_HASH_UNAVAILABLE")
    if indexed_hash != body.source_node_hash:
        raise HTTPException(status_code=409, detail="SOURCE_NODE_HASH_MISMATCH")

    try:
        request = NodeWriteOperationRequestV1(
            request_id="pipeline_draft_from_node",
            operation="rerun",
            context_version="node-operation-context/v1",
            context_fingerprint=body.source_context_fingerprint,
            owner_run_id=body.source_run_id,
            op_node_id=body.source_op_node_id,
            node_hash=body.source_node_hash,
            forest_node_key=body.source_forest_node_key or body.source_node_hash,
            owner_resolution="single_candidate",
            active_head_run_id=body.source_run_id,
        )
        validate_rerun_operation_target(runs_root, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"SOURCE_CONTEXT_MISMATCH: {exc}") from exc

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise HTTPException(status_code=422, detail="MODEL_NODE_NOT_ELIGIBLE")

    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail="SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
    upload = inputs.get("upload") or {}
    source_input_fingerprint = upload.get("sha256")
    if not source_input_fingerprint:
        raise HTTPException(status_code=422, detail="SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")

    now = utc_now()
    draft_id = new_draft_id()
    _draft_form = inputs.get("form") or {}
    editable_schema = _backfill_schema_values(contract.editable_schema, _draft_form)
    editable_schema = _inject_focal_x_control(editable_schema, _draft_form, contract.op_type)
    source_params = _source_params_from_schema(editable_schema)
    draft = {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": body.source_run_id,
            "source_model_node_id": body.source_model_node_id,
            "source_op_node_id": body.source_op_node_id,
            "source_node_hash": body.source_node_hash,
            "source_context_fingerprint": body.source_context_fingerprint,
            "source_input_fingerprint": source_input_fingerprint,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": body.source_run_id,
                    "schema_fingerprint": inputs.get("dag_hash") or source_input_fingerprint,
                    "input_fingerprint": source_input_fingerprint,
                    "columns_summary": [
                        {"name": key}
                        for key in sorted((inputs.get("form") or {}).keys())
                    ],
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
                        "source_run_id": body.source_run_id,
                        "source_model_node_id": body.source_model_node_id,
                        "source_op_node_id": body.source_op_node_id,
                        "source_node_hash": body.source_node_hash,
                        "source_context_fingerprint": body.source_context_fingerprint,
                    },
                    "source_params": source_params,
                    "params": source_params,
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


class PipelineDraftGenesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_sha256: str
    filename: str
    sheet_names: list[str] = []
    columns: list[str] = []  # client-side SheetJS-parsed column names


@router.post("/pipeline-drafts/genesis")
def create_pipeline_draft_genesis(
    project_root: str,
    body: PipelineDraftGenesisRequest,
) -> dict[str, Any]:
    """v1.6.8: parentless genesis draft chain (source -> table -> model).

    Same store + lifecycle as from-node drafts; created_from.source_type
    distinguishes the branch everywhere downstream (validate / execute).

    Design note: the genesis model node is params-only, NO editable_schema —
    the wizard reuses capabilities-driven RunForm controls (which don't need
    editable_schema); validate stays structural; column checks belong to
    execute (spec F3/F4).
    """
    _resolve_project_runs_dir(project_root)  # 404 PROJECT_NOT_FOUND for bogus roots
    root = Path(project_root)
    if not re.fullmatch(r"[0-9a-f]{64}", body.upload_sha256):
        # Reject before touching the filesystem; do NOT reflect the raw value.
        raise HTTPException(status_code=422, detail="UPLOAD_NOT_FOUND: invalid sha256")
    try:
        verify_upload(root, body.upload_sha256)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"UPLOAD_NOT_FOUND: {exc}") from exc

    now = utc_now()
    draft = {
        "draft_id": new_draft_id(),
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": body.upload_sha256,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "source_1",
                    "node_type": "input.upload",
                    "upload": {"sha256": body.upload_sha256, "filename": body.filename},
                    "sheet_names": body.sheet_names,
                    "status": "bound",
                },
                {
                    "node_id": "table_1",
                    "node_type": "table",
                    "params": {"sheet_name": None, "transpose": False},
                    "columns": body.columns,
                    "status": "pending",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": None,
                    "params": {},
                    "status": "pending",
                },
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
        "default_execution_mode": "genesis",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@router.get("/pipeline-drafts")
def list_pipeline_drafts(project_root: str) -> dict[str, Any]:
    try:
        drafts = _pipeline_draft_store(project_root).list()
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"drafts": drafts}


@router.get("/pipeline-drafts/{draft_id}")
def get_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@router.patch("/pipeline-drafts/{draft_id}")
def patch_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftPatchRequest,
) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).update_params(
            draft_id,
            model_node_id=body.model_node_id,
            base_draft_hash=body.base_draft_hash,
            params=body.params,
        )
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


class DraftNodePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any]
    columns: list[str] | None = None


@router.patch("/pipeline-drafts/{draft_id}/nodes/{node_id}")
def patch_pipeline_draft_node(
    draft_id: str,
    node_id: str,
    project_root: str,
    body: DraftNodePatchRequest,
) -> dict[str, Any]:
    """v1.6.8 genesis wizard step: configure table_1 / model_1 in place.

    Genesis-only (409 otherwise); the bound source node is immutable —
    changing the file means discard the draft and restart genesis.
    `columns` applies to table nodes only and is silently dropped on a
    model-node PATCH.
    """
    store = _pipeline_draft_store(project_root)
    try:
        stored = store.update_node_params(draft_id, node_id, body.params, columns=body.columns)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@router.delete("/pipeline-drafts/{draft_id}")
def delete_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    store = _pipeline_draft_store(project_root)
    # v1.6.8 F6: extract the genesis upload sha BEFORE deleting, defensively —
    # a corrupt/missing draft must still be discardable (just without blob GC).
    genesis_sha: str | None = None
    try:
        draft = store.get(draft_id).draft
        if (draft.get("created_from") or {}).get("source_type") == "genesis":
            source = next(
                (
                    n
                    for n in (draft.get("graph") or {}).get("nodes") or []
                    if n.get("node_id") == "source_1"
                ),
                None,
            )
            sha = ((source or {}).get("upload") or {}).get("sha256")
            if isinstance(sha, str) and sha:
                genesis_sha = sha
    except Exception:
        genesis_sha = None
    try:
        store.delete(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    # GC AFTER delete so the discarded draft's own file no longer counts as a
    # reference. GC failure must never fail the discard.
    upload_reclaimed = False
    if genesis_sha is not None:
        try:
            upload_reclaimed = delete_upload_if_unreferenced(
                Path(project_root), genesis_sha
            )
        except Exception:
            upload_reclaimed = False
    return {"ok": True, "draft_id": draft_id, "upload_reclaimed": upload_reclaimed}


@router.post("/pipeline-drafts/{draft_id}/validate")
def validate_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftValidateRequest,
) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return validate_draft_for_execution(stored.draft, execution_mode=body.execution_mode)


@router.post("/pipeline-drafts/{draft_id}/execute")
def execute_pipeline_draft(
    draft_id: str,
    project_root: str,
    body: PipelineDraftExecuteRequest,
) -> dict[str, Any]:
    if body.execution_mode == "new_run":
        raise HTTPException(status_code=409, detail="NEW_RUN_EXECUTION_NOT_ENABLED")

    root = Path(project_root)
    store = _pipeline_draft_store(project_root)
    try:
        first = store.get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc

    # v1.6.8 genesis drafts dispatch to a PARALLEL branch before any from-node
    # semantics (hash check included, so the cross-mode guard always wins).
    is_genesis = (first.draft.get("created_from") or {}).get("source_type") == "genesis"
    if is_genesis and body.execution_mode != "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_MODE_REQUIRED")
    if not is_genesis and body.execution_mode == "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_ONLY_FOR_GENESIS_DRAFTS")
    if is_genesis:
        return execute_genesis_draft(
            draft_id, root, store, first,
            validated_draft_hash=body.validated_draft_hash,
            execution_mode=body.execution_mode,
            idempotency_key=body.idempotency_key,
        )
    return execute_rerun_child_draft(
        draft_id, project_root, root, store, first,
        validated_draft_hash=body.validated_draft_hash,
        execution_mode=body.execution_mode,
        idempotency_key=body.idempotency_key,
    )
