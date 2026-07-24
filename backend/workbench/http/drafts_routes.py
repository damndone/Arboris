"""Pipeline-draft routes: create-from-node / genesis / CRUD / validate / execute.

Extracted from api.py in v1.6.10 (D1 decomposition, Phase 4)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ..lineage.pipeline_drafts import DraftHashConflict, DraftLockedForExecution, DraftNodeNotFound, DraftNodePatchConflict, DraftNotFound, DraftValidationFailure, PipelineDraftStore, validate_draft_for_execution
from ..lineage.upload_store import delete_upload_if_unreferenced
from ..services.draft_materialization import (
    _inject_focal_x_control,
    create_genesis_draft,
    create_rerun_draft_from_node,
)

from ..services.draft_service import execute_genesis_draft, execute_rerun_child_draft
from ..api_errors import WorkbenchAPIError

router = APIRouter()


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


def _draft_http_error(exc: Exception) -> HTTPException | WorkbenchAPIError:
    if isinstance(exc, WorkbenchAPIError):
        # Repository path resolution already carries the canonical status,
        # error code, and details.  Preserve it instead of flattening it into
        # the generic 422 draft error.
        return exc
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
    message = str(exc)
    if message == "SOURCE_MODEL_NODE_NOT_FOUND":
        return HTTPException(status_code=404, detail=message)
    if message in {"SOURCE_MODEL_NODE_MISMATCH", "SOURCE_NODE_HASH_MISMATCH"}:
        return HTTPException(status_code=409, detail=message)
    if message.startswith("SOURCE_CONTEXT_MISMATCH:"):
        return HTTPException(status_code=409, detail=message)
    if message == "SOURCE_RUN_NOT_TERMINAL":
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/pipeline-drafts/from-node")
def create_pipeline_draft_from_node(
    project_root: str,
    body: PipelineDraftFromNodeRequest,
) -> dict[str, Any]:
    try:
        stored = create_rerun_draft_from_node(
            Path(project_root),
            source_run_id=body.source_run_id,
            source_model_node_id=body.source_model_node_id,
            source_op_node_id=body.source_op_node_id,
            source_node_hash=body.source_node_hash,
            source_forest_node_key=body.source_forest_node_key,
            source_context_fingerprint=body.source_context_fingerprint,
        )
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
    try:
        stored = create_genesis_draft(
            Path(project_root),
            upload_sha256=body.upload_sha256,
            filename=body.filename,
            sheet_names=tuple(body.sheet_names),
            columns=tuple(body.columns),
        )
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
