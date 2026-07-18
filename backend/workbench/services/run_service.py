"""Run lifecycle: submit → dispatch → background execution → SSE framing.

Owns the single dispatch path shared by ``POST /runs`` and
``POST /runs/{id}/rerun`` (``_submit_run``), the background worker that drives
the pipeline (``_bg_run``), the dead-run reconciliation (``_mark_interrupted_if_dead``),
upload byte-reading, and small form-parsing helpers used by the dispatch path.

No FastAPI routing here — only the request-agnostic orchestration. The HTTP layer
(``api.py`` / ``http/*``) calls into this module; this module never imports it.

Tests patch ``workbench.services.run_service._run_workflow`` to inject a slow /
recording workflow — that is the seam ``_bg_run`` actually calls, so a positional
mistake in ``executor.submit(_bg_run, ...)`` is caught.

Extracted from ``api.py`` in v1.6.10 (D1 decomposition, Phase 3).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, UploadFile

from ..artifacts import write_json
from ..config import load_config
from ..domain import GuardrailIssue, Severity
from ..events import get_event_manager
from ..lineage.hashing import dag_hash, override_hash
from ..lineage.role_layer import canonicalize_focal_x
from ..lineage.run_inputs import write_run_inputs
from ..lineage.upload_store import resolve_upload, store_upload_bytes
from ..orchestrator import (
    _lineage,
    _run_workflow,
    _write_manifest,
    parse_imputation_request,
)
from ..projects import create_run
from ..repository.run_repository import _resolve_project_root

UPLOAD_CHUNK_BYTES = 1024 * 1024

# Estimator families whose focal/treatment variable is structural (not user-declared
# via focal_x). For these, persisted focal_x MUST be empty (spec §5).
_STRUCTURAL_FOCAL_FAMILIES = {"iv_2sls", "did", "cs_did", "sa_did", "dcdh"}


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_json_str_array(raw: str, label: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {label} JSON: {exc}")
    if not isinstance(parsed, list) or not all(isinstance(c, str) for c in parsed):
        raise HTTPException(status_code=422, detail=f"{label} must be a JSON array of column-name strings.")
    return parsed


def _parse_focal_x(raw: str, x_columns: list[str]) -> list[str]:
    """Canonicalize the form's focal_x against the run's x columns."""
    return canonicalize_focal_x(raw, x_columns)


async def _read_upload_bytes(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload fully into memory, enforcing the project size cap."""
    buf = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file exceeds project size limit.",
            )
    return bytes(buf)


async def _write_upload(file: UploadFile, target: Path, max_bytes: int) -> None:
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="Uploaded file exceeds project size limit.",
                )
            handle.write(chunk)


def encode_form_override(key: str, value: object) -> str:
    """Encode an operation override using the run form's wire format.

    Column selectors are submitted as comma-separated form fields, while other
    list/dict overrides use JSON so the engine's typed parsers can consume them.
    """
    if key in {"x", "focal_x"} and isinstance(value, list):
        return ",".join(str(item) for item in value)
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def parse_column_selector(raw: str, field: str = "x") -> list[str]:
    """Parse a column-selector form field.

    Accepts BOTH wire formats explicitly: comma-separated names (the historical
    `x` format the frontend sends) and a JSON string array (the format
    iv_endog/iv_instruments already use). A JSON array previously "worked" only
    because normalize_column_name stripped the brackets downstream, and `[]`
    turned into a bogus one-column request that blocked the run with
    `missing_columns: [""]`. An empty value is a legal empty selector so
    zero-covariate DID/CS families can be submitted over HTTP.

    Raises ValueError for malformed JSON or non-string entries; _submit_run
    callers convert that to a 422 before any run is created.
    """
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{field} must be a comma-separated list or a JSON array of column names."
            ) from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f"{field} JSON array must contain only column-name strings.")
        return [item.strip() for item in parsed if item.strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _submit_run(
    root: Path,
    *,
    form: dict[str, str],
    upload_bytes: bytes,
    upload_filename: str,
    started_at: str,
    rerun_of: str | None = None,
    from_node: str | None = None,
    rerun_reason: str = "initial",
    op_overrides: dict | None = None,
    rerun_from: dict[str, Any] | None = None,
    workbench_context: dict[str, Any] | None = None,
    before_dispatch: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Single dispatch path shared by POST /runs and POST /runs/{id}/rerun.

    Stores the upload content-addressably, writes run_inputs.json, materializes the
    blob into the run dir for the engine (which reads a path), and dispatches the full
    pipeline via _bg_run. The caller MUST already hold the run slot. Input parsing that
    can fail (imputation / iv arrays) happens BEFORE any run is created, so a bad request
    raises without leaving a junk run behind."""
    x_columns = parse_column_selector(form.get("x", ""), "x")
    imputation_request = parse_imputation_request(form.get("imputation", ""))
    iv_endog_list = _parse_json_str_array(form.get("iv_endog", ""), "iv_endog")
    iv_instruments_list = _parse_json_str_array(form.get("iv_instruments", ""), "iv_instruments")

    # focal_x: canonicalize against x; clear for families whose focal/treatment is
    # structural. Persist into run_inputs (the engine reads it back at recording).
    # Only mutate the form when there is something to set/clear, so runs that never
    # declare a focal keep byte-identical run_inputs (spec §5 backward compat).
    focal_x = _parse_focal_x(form.get("focal_x", ""), x_columns)
    if form.get("model_type", "auto") in _STRUCTURAL_FOCAL_FAMILIES:
        focal_x = []
    form_for_persist = form
    if focal_x:
        form_for_persist = {**form, "focal_x": ",".join(focal_x)}
    elif form.get("focal_x"):
        form_for_persist = {**form, "focal_x": ""}

    sha = store_upload_bytes(root, upload_bytes, filename=upload_filename)
    run = create_run(root, mode=form.get("mode", "auto"))

    model_type = form_for_persist.get("model_type", "auto")
    requested_covariance = str(form_for_persist.get("covariance", "")).strip().lower()
    wire_covariance = requested_covariance or "robust"
    executable_payload = {
        "model_type": model_type,
        "covariance": wire_covariance,
        "entity_col": form_for_persist.get("entity_col", ""),
        "y": form_for_persist.get("y", ""),
        "x": list(x_columns),
        "form": dict(form_for_persist),
        "rerun_of": rerun_of,
        "from_node": from_node,
    }
    confirmed_payload = {
        "model_type": model_type,
        "covariance": wire_covariance,
        "entity_col": form_for_persist.get("entity_col", ""),
        "y": form_for_persist.get("y", ""),
        "x": list(x_columns),
    }
    contract_summary = {
        "contract_version": "ols_result_contract_v1" if model_type == "ols" else None,
        "model": "ols" if model_type == "ols" else model_type,
        "model_type": model_type,
        "covariance": wire_covariance,
        "covariance_explicit": bool(requested_covariance),
        "entity_col": form_for_persist.get("entity_col", ""),
        "y": form_for_persist.get("y", ""),
        "x": list(x_columns),
        "source_eligible": model_type == "ols" and requested_covariance == "unadjusted",
    }
    source_lineage = {
        "source_run_id": rerun_of,
        "from_node": from_node,
        "rerun_from": rerun_from,
    }

    write_run_inputs(
        run.root,
        form=form_for_persist,
        upload={"sha256": sha, "filename": upload_filename},
        rerun_of=rerun_of, from_node=from_node, rerun_reason=rerun_reason,
        override_hash=override_hash(op_overrides) if op_overrides else None,
        dag_hash=dag_hash(sha, form_for_persist),
        rerun_from=rerun_from,
        source_lineage=source_lineage,
        workbench_context=workbench_context,
        contract_summary=contract_summary,
        executable_payload=executable_payload,
        rerun_inputs={
            "rerun_of": rerun_of,
            "from_node": from_node,
            "rerun_reason": rerun_reason,
            "override_hash": override_hash(op_overrides) if op_overrides else None,
        },
        confirmed_payload=confirmed_payload if rerun_of is not None else None,
    )

    uploads_dir = run.root / "_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_dir / Path(upload_filename or "upload.csv").name
    saved_path.write_bytes(resolve_upload(root, sha).read_bytes())

    _write_manifest(
        run.root, run.run_id, form.get("mode", "auto"), "running",
        _lineage([saved_path]), started_at=started_at,
        y=form.get("y", ""), x=x_columns,
        requested_model_type=form.get("model_type", "auto"),
        rerun_of=rerun_of,
        from_node=from_node,
        rerun_reason=rerun_reason if rerun_of is not None else None,
        source_lineage=source_lineage if rerun_of is not None else None,
        rerun_from=rerun_from,
        source_run_id=rerun_of,
    )
    if before_dispatch is not None:
        before_dispatch(run.run_id)

    events = get_event_manager()
    events.register_run(run.run_id, run.root / "workflow_log.jsonl")
    events.mark_active(run.run_id)
    events.executor.submit(
        _bg_run, run.root, run.run_id, saved_path,
        form.get("mode", "auto"), form.get("y", ""), x_columns, started_at,
        form.get("model_type", "auto"),
        (form.get("sheet_name") or None), form.get("transpose") == "true",
        imputation_request,
        form.get("entity_col", ""), form.get("time_col", ""), form.get("covariance", ""),
        form.get("prediction_model_type", ""), _safe_int(form.get("prediction_cv_folds", "0")),
        form.get("prediction_sampling_method", ""),
        iv_endog_list, iv_instruments_list,
        form.get("did_mode", ""), form.get("did_cohort_col", ""), form.get("did_treat_col", ""),
        form.get("did_post_col", ""), form.get("did_status_col", ""), form.get("did_treatment_path", ""),
        form.get("cs_control_group", ""), form.get("cs_est_method", ""), form.get("cs_base_period", ""),
        form.get("cs_cluster_var", ""), _safe_int(str(form.get("cs_anticipation", "0"))),
        str(form.get("honest_did", "false")).lower() == "true",
    )
    return {"run_id": run.run_id, "status": "running"}


def _bg_run(
    run_root: Path,
    run_id: str,
    saved_path: Path,
    mode: str,
    y: str,
    x_columns: list[str],
    started_at: str,
    model_type: str = "auto",
    sheet_name: str | None = None,
    transpose: bool = False,
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
    iv_endog: list[str] | None = None,
    iv_instruments: list[str] | None = None,
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
    did_treatment_path: str = "",
    cs_control_group: str = "",
    cs_est_method: str = "",
    cs_base_period: str = "",
    cs_cluster_var: str = "",
    cs_anticipation: int = 0,
    honest_did: bool = False,
) -> None:
    events = get_event_manager()
    config = load_config(_resolve_project_root(run_root) / "config.yml")

    def _on_step(step: str, status: str, message: str) -> None:
        if status == "blocked":
            event_name = "step_blocked"
        elif status in ("start", "complete"):
            event_name = f"step_{status}"
        else:
            event_name = f"step_{status}"
        events.emit(run_id, {
            "event": event_name,
            "step": step,
            "message": message,
            "status": status if status not in ("start", "complete") else None,
        })

    try:
        result = _run_workflow(
            run_root, run_id, [saved_path],
            mode, y, x_columns, config, started_at,
            on_step=_on_step,
            model_type=model_type,
            sheet_name=sheet_name,
            transpose=transpose,
            imputation=imputation,
            entity_col=entity_col,
            time_col=time_col,
            covariance=covariance,
            prediction_model_type=prediction_model_type,
            prediction_cv_folds=prediction_cv_folds,
            prediction_sampling_method=prediction_sampling_method,
            iv_endog=iv_endog,
            iv_instruments=iv_instruments,
            did_mode=did_mode,
            did_cohort_col=did_cohort_col,
            did_treat_col=did_treat_col,
            did_post_col=did_post_col,
            did_status_col=did_status_col,
            did_treatment_path=did_treatment_path,
            cs_control_group=cs_control_group,
            cs_est_method=cs_est_method,
            cs_base_period=cs_base_period,
            cs_cluster_var=cs_cluster_var,
            cs_anticipation=cs_anticipation,
            honest_did=honest_did,
        )
        status = result["status"]
        events.emit_terminal(run_id, status, f"Workflow {status}")
    except Exception as exc:
        _write_manifest(
            run_root, run_id, mode, "failed",
            _lineage([saved_path]),
            started_at=started_at, y=y, x=x_columns,
            requested_model_type=model_type,
        )
        write_json(run_root / "errors.json", {
            "issues": [GuardrailIssue(
                Severity.BLOCKER, "WORKFLOW_FAILED",
                str(exc), {},
            ).to_dict()],
        })
        events.emit_terminal(run_id, "failed", f"Workflow failed: {exc}")
    finally:
        events.release_slot(run_id)


def _mark_interrupted_if_dead(run_root: Path, manifest: dict) -> str | None:
    run_id = manifest.get("run_id")
    if manifest.get("status") != "running":
        return None
    events = get_event_manager()
    if events.is_active(run_id):
        return None
    issue = GuardrailIssue(
        Severity.BLOCKER, "WORKFLOW_INTERRUPTED",
        "Workflow interrupted because the server process stopped before completion.",
        {},
    )
    write_json(run_root / "errors.json", {"issues": [issue.to_dict()]})
    _write_manifest(
        run_root, run_id,
        manifest.get("mode", "auto"), "interrupted",
        manifest.get("lineage", []),
        started_at=manifest.get("started_at"),
        y=manifest.get("y"),
        x=manifest.get("x") or [],
        requested_model_type=manifest.get("requested_model_type"),
    )
    manifest["status"] = "interrupted"
    return "interrupted"


def _sse_frame(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
