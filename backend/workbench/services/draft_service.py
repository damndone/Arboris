"""Pipeline-draft execution orchestration.

The heavy execute paths (genesis first-run, and rerun-child from a source run):
hash check → dedupe → execution lock → re-check + re-validate → synthesize/merge
the run form → dispatch via run_service._submit_run → record snapshot + dedupe.

Takes primitive values (not the HTTP request model) so it depends only downward
(lineage / repository / run_service), never on the http/ layer. Raises
``HTTPException`` for client-facing failures, mirroring run_service.

Extracted from ``http/drafts_routes.py`` in v1.6.10.1 (D1 completion, followup N1)
to keep the route handlers thin (drafts_routes was 819 lines).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..events import get_event_manager
from ..lineage.pipeline_drafts import PipelineDraftStore, StoredDraft, compute_executable_draft_hash, utc_now, validate_draft_for_execution
from ..lineage.rerun_provenance import run_rerun_from_from_context
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import verify_upload
from ..model_options import ModelOptionsError, canonicalize_model_options, parse_model_options
from ..repository.run_repository import _resolve_run_root
from .run_service import _submit_run, merge_form_overrides


def execute_genesis_draft(
    draft_id: str,
    root: Path,
    store: PipelineDraftStore,
    first: StoredDraft,
    *,
    validated_draft_hash: str,
    execution_mode: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """v1.6.8 genesis execute: parentless draft chain -> FIRST run of a project.

    PARALLEL implementation to the from-node branch (same skeleton: hash check
    outside lock -> dedupe -> execution_lock -> re-check + re-validate -> submit),
    but genesis is NOT a rerun: no parent run_inputs to merge, no rerun_of /
    from_node / op_overrides / rerun_from — the full form is synthesized from the
    draft chain and dispatched via _submit_run(rerun_reason='initial')."""
    if first.draft_hash != validated_draft_hash:
        raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

    dedupe_key = (
        idempotency_key
        or f"{draft_id}:{validated_draft_hash}:{execution_mode}"
    )
    existing = store.get_dedupe(draft_id, dedupe_key)
    if existing is not None:
        validation = validate_draft_for_execution(first.draft, execution_mode="genesis")
        return {
            "ok": True,
            "run_id": existing.run_id,
            "draft_id": draft_id,
            "executed_draft_hash": existing.executed_draft_hash,
            "execution_mode": "genesis",
            "deduped": True,
            "produced_lineage": validation["resolved_execution"],
            "focus": {
                "status": "pending_index",
                "run_id": existing.run_id,
                "poll": validation["resolved_execution"],
            },
        }

    with store.execution_lock(draft_id):
        current = store.get(draft_id)
        if current.draft_hash != validated_draft_hash:
            raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

        validation = validate_draft_for_execution(current.draft, execution_mode="genesis")
        if not validation.get("executable"):
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        if validation.get("validated_execution_mode") != "genesis":
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")

        existing = store.get_dedupe(draft_id, dedupe_key)
        if existing is not None:
            return {
                "ok": True,
                "run_id": existing.run_id,
                "draft_id": draft_id,
                "executed_draft_hash": existing.executed_draft_hash,
                "execution_mode": "genesis",
                "deduped": True,
                "produced_lineage": validation["resolved_execution"],
                "focus": {
                    "status": "pending_index",
                    "run_id": existing.run_id,
                    "poll": validation["resolved_execution"],
                },
            }

        draft = current.draft
        # --- genesis: synthesize the full form (no parent run to merge) ---
        nodes = {n["node_id"]: n for n in draft["graph"]["nodes"]}
        sha = nodes["source_1"]["upload"]["sha256"]
        filename = nodes["source_1"]["upload"].get("filename") or "upload.csv"
        try:
            upload_bytes = verify_upload(root, sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"GENESIS_UPLOAD_UNUSABLE: {exc}"
            ) from exc

        tp = nodes["table_1"].get("params") or {}
        mp = dict(nodes["model_1"].get("params") or {})
        if "model_options_binding" in mp:
            raise HTTPException(
                status_code=422,
                detail="MODEL_OPTIONS_BINDING_CLIENT_MANAGED",
            )
        x_val = mp.pop("x", "")
        focal = mp.pop("focal_x", "")
        merged_form = {
            "mode": "auto",
            "model_type": str(mp.pop("model_type", "") or "auto"),
            "y": str(mp.pop("y", "")),
            # x / focal_x wire format is a comma-joined column list (the
            # dispatch comma-splits; see the v1.6.5 note in the from-node branch)
            "x": ",".join(x_val) if isinstance(x_val, list) else str(x_val),
            "sheet_name": str(tp.get("sheet_name") or ""),
            "transpose": "true" if tp.get("transpose") else "false",
            "focal_x": ",".join(focal) if isinstance(focal, list) else str(focal),
            # remaining model params share POST /runs' form field names — pass through:
            **{
                k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
                for k, v in mp.items()
            },
        }
        try:
            raw_model_options = merged_form.get("model_options", "{}")
            merged_form["model_options"] = (
                parse_model_options(raw_model_options)
                if isinstance(raw_model_options, str)
                else canonicalize_model_options(raw_model_options)
            )
        except ModelOptionsError as exc:
            raise HTTPException(status_code=422, detail=exc.code) from exc

        executed_hash = compute_executable_draft_hash(draft)

        def _record_snapshot_before_dispatch(new_run_id: str) -> None:
            run_dir = root / "runs" / new_run_id
            resolved_binding = (read_run_inputs(run_dir).get("form") or {}).get(
                "model_options_binding"
            )
            snapshot = {
                "executed_at": utc_now(),
                "source_draft_id": draft_id,
                "executed_draft_hash": executed_hash,
                "execution_request": {
                    "execution_mode": "genesis",
                    "validated_draft_hash": validated_draft_hash,
                },
                "draft": draft,
            }
            if isinstance(resolved_binding, dict):
                snapshot["model_options_binding"] = resolved_binding
            (run_dir / "executed_pipeline_draft.json").write_text(
                json.dumps(
                    snapshot,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            store.record_dedupe(
                draft_id,
                dedupe_key,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )
            store.record_execution_locked(
                draft_id,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )

        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                root,
                form=merged_form,
                upload_bytes=upload_bytes,
                upload_filename=filename,
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_reason="initial",
                before_dispatch=_record_snapshot_before_dispatch,
            )
        except ModelOptionsError as exc:
            events.release_slot(None)
            raise HTTPException(status_code=422, detail=exc.code) from exc
        except Exception:
            events.release_slot(None)
            raise

        return {
            "ok": True,
            "run_id": result["run_id"],
            "draft_id": draft_id,
            "executed_draft_hash": executed_hash,
            "execution_mode": "genesis",
            "produced_lineage": {"genesis": True},
            "focus": {
                "status": "pending_index",
                "run_id": result["run_id"],
                "poll": {"genesis": True},
            },
        }


def execute_rerun_child_draft(
    draft_id: str,
    project_root: str,
    root: Path,
    store: PipelineDraftStore,
    first: StoredDraft,
    *,
    validated_draft_hash: str,
    execution_mode: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """rerun-child execute: fork a validated draft off its source run.

    Merges the source run_inputs.form with the draft's changed params
    (op_overrides = params that differ from source_params), records provenance,
    and dispatches via _submit_run(rerun_reason='pipeline_draft')."""
    if first.draft_hash != validated_draft_hash:
        raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

    dedupe_key = (
        idempotency_key
        or f"{draft_id}:{validated_draft_hash}:{execution_mode}"
    )
    existing = store.get_dedupe(draft_id, dedupe_key)
    if existing is not None:
        validation = validate_draft_for_execution(first.draft, execution_mode=execution_mode)
        return {
            "ok": True,
            "run_id": existing.run_id,
            "draft_id": draft_id,
            "executed_draft_hash": existing.executed_draft_hash,
            "execution_mode": "rerun_child",
            "deduped": True,
            "produced_lineage": validation["resolved_execution"],
            "focus": {
                "status": "pending_index",
                "run_id": existing.run_id,
                "poll": validation["resolved_execution"],
            },
        }

    with store.execution_lock(draft_id):
        current = store.get(draft_id)
        if current.draft_hash != validated_draft_hash:
            raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")

        validation = validate_draft_for_execution(current.draft, execution_mode=execution_mode)
        if not validation.get("executable"):
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        if validation.get("validated_execution_mode") != execution_mode:
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")

        existing = store.get_dedupe(draft_id, dedupe_key)
        if existing is not None:
            return {
                "ok": True,
                "run_id": existing.run_id,
                "draft_id": draft_id,
                "executed_draft_hash": existing.executed_draft_hash,
                "execution_mode": "rerun_child",
                "deduped": True,
                "produced_lineage": validation["resolved_execution"],
                "focus": {
                    "status": "pending_index",
                    "run_id": existing.run_id,
                    "poll": validation["resolved_execution"],
                },
            }

        draft = current.draft
        source = draft["created_from"]
        model = next(node for node in draft["graph"]["nodes"] if node.get("node_type") == "model")
        run_root = _resolve_run_root(project_root, source["source_run_id"])
        try:
            inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(status_code=422, detail="SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
        parent_sha = (inputs.get("upload") or {}).get("sha256")
        if not parent_sha:
            raise HTTPException(status_code=422, detail="SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")
        try:
            upload_bytes = verify_upload(root, parent_sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Parent upload unusable: {exc}") from exc

        op_overrides = {
            key: value
            for key, value in model["params"].items()
            if (model.get("source_params") or {}).get(key) != value
        }

        try:
            merged_form = merge_form_overrides(inputs["form"], op_overrides)
        except ModelOptionsError as exc:
            raise HTTPException(status_code=422, detail=exc.code) from exc
        run_level_rerun_from = run_rerun_from_from_context(
            request_id=f"draft:{draft_id}",
            owner_run_id=source["source_run_id"],
            op_node_id=source["source_op_node_id"],
            node_hash=source["source_node_hash"],
            context_fingerprint=source["source_context_fingerprint"],
        )
        executed_hash = compute_executable_draft_hash(draft)

        def _record_snapshot_before_dispatch(new_run_id: str) -> None:
            run_dir = root / "runs" / new_run_id
            resolved_binding = (read_run_inputs(run_dir).get("form") or {}).get(
                "model_options_binding"
            )
            snapshot = {
                "executed_at": utc_now(),
                "source_draft_id": draft_id,
                "executed_draft_hash": executed_hash,
                "execution_request": {
                    "execution_mode": "rerun_child",
                    "validated_draft_hash": validated_draft_hash,
                },
                "draft": draft,
            }
            if isinstance(resolved_binding, dict):
                snapshot["model_options_binding"] = resolved_binding
            (run_dir / "executed_pipeline_draft.json").write_text(
                json.dumps(
                    snapshot,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            store.record_dedupe(
                draft_id,
                dedupe_key,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )
            store.record_execution_locked(
                draft_id,
                run_id=new_run_id,
                executed_draft_hash=executed_hash,
            )

        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                root,
                form=merged_form,
                upload_bytes=upload_bytes,
                upload_filename=inputs["upload"].get("filename") or "upload.csv",
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_of=source["source_run_id"],
                from_node=source["source_op_node_id"],
                rerun_reason="pipeline_draft",
                op_overrides=op_overrides,
                rerun_from=run_level_rerun_from,
                before_dispatch=_record_snapshot_before_dispatch,
            )
        except ModelOptionsError as exc:
            events.release_slot(None)
            raise HTTPException(status_code=422, detail=exc.code) from exc
        except Exception:
            events.release_slot(None)
            raise

        return {
            "ok": True,
            "run_id": result["run_id"],
            "draft_id": draft_id,
            "executed_draft_hash": executed_hash,
            "execution_mode": "rerun_child",
            "produced_lineage": {
                "rerun_from_run_id": source["source_run_id"],
                "rerun_from_model_node_id": source["source_model_node_id"],
                "rerun_from_op_node_id": source["source_op_node_id"],
            },
            "focus": {
                "status": "pending_index",
                "run_id": result["run_id"],
                "poll": {
                    "rerun_from_run_id": source["source_run_id"],
                    "rerun_from_model_node_id": source["source_model_node_id"],
                    "rerun_from_op_node_id": source["source_op_node_id"],
                },
            },
        }
