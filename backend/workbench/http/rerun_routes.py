"""Rerun route: POST /runs/{id}/rerun + its request model and idempotency helpers.

Extracted from api.py in v1.6.10 (D1 decomposition, Phase 4)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..artifacts import read_json, write_json
from ..events import get_event_manager
from ..graph_store import GraphStore
from ..lineage.manual_patch_validation import ManualPatchValidationError, ManualRerunPatch, validate_manual_patch
from ..lineage.node_write_validation import AcceptedContext, NodeWriteOperationRequestV1, accepted_context_from, validate_rerun_operation_target
from ..lineage.op_contract import OpOverrideError, resolve_operation_contract, resolve_overrides_target, validate_overrides
from ..lineage.rerun_provenance import pending_produced_lineage, run_rerun_from_from_context
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import verify_upload
from ..repository.run_repository import _read_manifest, _resolve_project_runs_dir, _resolve_run_root
from ..services.run_service import _submit_run
from ._deps import _TERMINAL_RUN_STATUSES, _backfill_schema_values

router = APIRouter()


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node: str | None = None
    op_overrides: dict = {}
    rerun_reason: str = "manual_override"
    manual_patch: dict[str, Any] | None = None

    request_id: str | None = None
    operation: str | None = None
    context_version: str | None = None
    context_fingerprint: str | None = None
    owner_run_id: str | None = None
    op_node_id: str | None = None
    node_hash: str | None = None
    forest_node_key: str | None = None
    owner_resolution: str | None = None
    active_head_run_id: str | None = None


@router.post("/runs/{run_id}/rerun")
def rerun_endpoint(run_id: str, project_root: str, body: RerunRequest) -> dict[str, Any]:
    """Create a new immutable run from a parent run's editable node, applying
    structurally-validated overrides. Full-pipeline re-execution; lineage preserved."""
    root = Path(project_root)
    runs_root = _resolve_project_runs_dir(project_root)
    effective_run_id = run_id
    effective_from_node = body.from_node
    accepted_context: AcceptedContext | None = None
    focus_target: dict[str, str] | None = None
    run_level_rerun_from: dict[str, Any] | None = None
    manual_patch: ManualRerunPatch | None = None
    effective_op_overrides = body.op_overrides

    if body.context_version is not None:
        try:
            request = NodeWriteOperationRequestV1(
                request_id=body.request_id,
                operation=body.operation,
                context_version=body.context_version,
                context_fingerprint=body.context_fingerprint,
                owner_run_id=body.owner_run_id,
                op_node_id=body.op_node_id,
                node_hash=body.node_hash,
                forest_node_key=body.forest_node_key,
                owner_resolution=body.owner_resolution,
                active_head_run_id=body.active_head_run_id,
            )
            validate_rerun_operation_target(runs_root, request)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="invalid_operation_target") from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=_node_write_validation_status(str(exc)),
                detail=str(exc),
            ) from exc
        accepted_context = accepted_context_from(request)
        run_level_rerun_from = run_rerun_from_from_context(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            node_hash=request.node_hash,
            context_fingerprint=request.context_fingerprint,
        )
        if body.manual_patch is not None:
            if body.op_overrides:
                raise HTTPException(status_code=400, detail="MANUAL_PATCH_WITH_OP_OVERRIDES")
            try:
                manual_patch = ManualRerunPatch(**body.manual_patch)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail="INVALID_MANUAL_PATCH") from exc
            if manual_patch.source_context_fingerprint != request.context_fingerprint:
                raise HTTPException(status_code=409, detail="SOURCE_CONTEXT_MISMATCH")
            if (
                manual_patch.target.owner_run_id != request.owner_run_id
                or manual_patch.target.op_node_id != request.op_node_id
                or manual_patch.target.node_hash != request.node_hash
            ):
                raise HTTPException(status_code=409, detail="PATCH_TARGET_MISMATCH")
            run_level_rerun_from["patch_id"] = manual_patch.patch_id
        effective_run_id = request.owner_run_id
        effective_from_node = request.op_node_id
        focus_target = None
    elif _has_context_target_fields(body):
        raise HTTPException(
            status_code=400,
            detail="context_version is required for context target fields.",
        )

    if effective_from_node is None:
        raise HTTPException(status_code=422, detail="from_node is required.")

    run_root = _resolve_run_root(project_root, effective_run_id)
    manifest = _read_manifest(run_root)

    # Guardrail #8: parent must be terminal (else 409). Distinct from slot-busy 429.
    status = manifest.get("status")
    if status not in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Parent run not terminal (status={status})."
        )

    # Guardrail #6: from_node must exist in the parent graph.
    graph = GraphStore(runs_root=runs_root).read(effective_run_id)
    node = graph.nodes.get(effective_from_node)
    if node is None:
        raise HTTPException(
            status_code=422, detail=f"from_node not in run graph: {effective_from_node}"
        )

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise HTTPException(
            status_code=422, detail=f"Node {effective_from_node} is not editable."
        )

    # Guardrails #3 + #4: structural validation against the switch-resolved schema.
    try:
        target = resolve_overrides_target(contract, body.op_overrides)
        validate_overrides(target, body.op_overrides)
    except OpOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Parent run has no run_inputs.json (not rerunnable).",
        ) from exc
    parent_sha = (inputs.get("upload") or {}).get("sha256")
    if not parent_sha:
        raise HTTPException(status_code=422, detail="Parent run_inputs.json has no upload sha256.")
    # Guardrails #2 + #5: reuse parent upload by sha256 only; re-verify content hash.
    try:
        upload_bytes = verify_upload(root, parent_sha).read_bytes()
    except (OSError, ValueError) as exc:  # UploadBlobMissing / UploadHashMismatch
        raise HTTPException(
            status_code=422, detail=f"Parent upload unusable: {exc}"
        ) from exc

    # Form params are strings; JSON-encode list/dict overrides (e.g. iv_endog ["x"])
    # so the pipeline's JSON-array parsers accept them. override_hash uses raw values.
    def _encode_override(value: object) -> str:
        return json.dumps(value) if isinstance(value, (list, dict)) else str(value)

    merged_form = {
        **inputs["form"],
        **{k: _encode_override(v) for k, v in body.op_overrides.items()},
    }

    manual_patch_result: dict[str, Any] | None = None
    if manual_patch is not None:
        editable_schema = _backfill_schema_values(contract.editable_schema, inputs["form"])
        current_values = {
            item["key"]: item.get("value")
            for item in editable_schema
            if item.get("key")
        }
        try:
            patch_overrides = validate_manual_patch(
                patch=manual_patch,
                current_values=current_values,
                editable_schema=editable_schema,
                editable_schema_version="run_inputs",
            )
        except ManualPatchValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        merged_form = {
            **inputs["form"],
            **{k: _encode_override(v) for k, v in patch_overrides.items()},
        }
        effective_op_overrides = patch_overrides
        manual_patch_result = _manual_patch_idempotency_result(
            root=root,
            owner_run_id=effective_run_id,
            patch=manual_patch,
        )
        if manual_patch_result is not None:
            return manual_patch_result

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    child_id: str | None = None
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        def _response_for(new_child_id: str) -> dict[str, Any]:
            return {
                "run_id": new_child_id,
                "new_run_id": new_child_id,
                "new_active_head_id": new_child_id,
                "focus": focus_target,
                "produced_lineage": (
                    pending_produced_lineage(
                        produced_owner_run_id=new_child_id,
                        rerun_from=run_level_rerun_from,
                    )
                    if run_level_rerun_from is not None
                    else None
                ),
                "rerun_from": {
                    "owner_run_id": effective_run_id,
                    "op_node_id": effective_from_node,
                    "node_hash": body.node_hash,
                    "forest_node_key": body.forest_node_key,
                },
                "accepted_context": (
                    accepted_context.model_dump() if accepted_context is not None else None
                ),
            }

        def _record_idempotency_before_dispatch(new_child_id: str) -> None:
            if manual_patch is not None:
                _record_manual_patch_idempotency(
                    root=root,
                    owner_run_id=effective_run_id,
                    patch=manual_patch,
                    response=_response_for(new_child_id),
                )

        result = _submit_run(
            root, form=merged_form, upload_bytes=upload_bytes,
            upload_filename=inputs["upload"].get("filename") or "upload.csv",
            started_at=started_at, rerun_of=effective_run_id, from_node=effective_from_node,
            rerun_reason=body.rerun_reason, op_overrides=effective_op_overrides,
            rerun_from=run_level_rerun_from,
            before_dispatch=_record_idempotency_before_dispatch,
        )
        child_id = result["run_id"]
        return _response_for(child_id)
    except ValueError as exc:
        events.release_slot(child_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        events.release_slot(child_id)
        raise


def _node_write_validation_status(message: str) -> int:
    if message.startswith(("unsupported_context_version", "invalid_operation_target")):
        return 400
    if message.startswith(("context_mismatch", "context_stale")):
        return 409
    if message.startswith("operation_not_allowed"):
        return 403
    return 400


def _has_context_target_fields(body: RerunRequest) -> bool:
    return any(
        value is not None
        for value in (
            body.request_id,
            body.operation,
            body.context_fingerprint,
            body.owner_run_id,
            body.op_node_id,
            body.node_hash,
            body.forest_node_key,
            body.owner_resolution,
            body.active_head_run_id,
            body.manual_patch,
        )
    )


def _manual_patch_idempotency_path(root: Path, owner_run_id: str) -> Path:
    return root / "runs" / owner_run_id / "manual_patch_idempotency.json"


def _manual_patch_idempotency_payload(patch: ManualRerunPatch) -> str:
    return json.dumps(patch.model_dump(), sort_keys=True, separators=(",", ":"))


def _manual_patch_idempotency_result(
    *,
    root: Path,
    owner_run_id: str,
    patch: ManualRerunPatch,
) -> dict[str, Any] | None:
    path = _manual_patch_idempotency_path(root, owner_run_id)
    if not path.is_file():
        return None
    try:
        index = read_json(path)
    except (OSError, ValueError):
        return None
    entry = (index.get("patches") or {}).get(patch.patch_id)
    if entry is None:
        return None
    if entry.get("payload") != _manual_patch_idempotency_payload(patch):
        raise HTTPException(status_code=409, detail="PATCH_ID_CONFLICT")
    response = entry.get("response")
    if not isinstance(response, dict):
        return None
    return response


def _record_manual_patch_idempotency(
    *,
    root: Path,
    owner_run_id: str,
    patch: ManualRerunPatch,
    response: dict[str, Any],
) -> None:
    path = _manual_patch_idempotency_path(root, owner_run_id)
    try:
        index = read_json(path) if path.is_file() else {}
    except (OSError, ValueError):
        index = {}
    patches = dict(index.get("patches") or {})
    patches[patch.patch_id] = {
        "payload": _manual_patch_idempotency_payload(patch),
        "response": response,
    }
    write_json(path, {"patches": patches})
