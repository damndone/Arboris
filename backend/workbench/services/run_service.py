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
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, UploadFile

from ..artifacts import write_json
from ..config import load_config
from ..domain import GuardrailIssue, Severity
from ..engine.context import RunInterruptionRequested
from ..events import get_event_manager
from ..lineage.hashing import dag_hash, override_hash
from ..lineage.role_layer import canonicalize_focal_x
from ..lineage.run_family import ensure_run_family_binding
from ..lineage.run_inputs import write_run_inputs
from ..lineage.upload_store import resolve_upload, store_upload_bytes
from ..model_options import (
    ModelOptionsBinding,
    ModelOptionsError,
    bind_new_model_options,
    canonicalize_model_options,
    merge_model_options,
    parse_model_options,
    verify_binding_owner_for_model_type,
    verify_bound_model_options,
)
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
_LMM_MODEL_TYPE = "linear_mixed_effects"


def _normalize_labels(value: object) -> dict[str, object]:
    """Validate the explicit JSON label declaration without touching data values."""

    if value is None or value == "":
        return {}
    payload = canonicalize_model_options(value)
    allowed = {"variable_labels", "value_labels", "measurement_level"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"labels contains unknown field(s): {', '.join(unknown)}")

    variable_labels = payload.get("variable_labels", {})
    value_labels = payload.get("value_labels", {})
    if not isinstance(variable_labels, Mapping) or not isinstance(value_labels, Mapping):
        raise ValueError("labels.variable_labels and labels.value_labels must be objects")

    normalized_variables: dict[str, str] = {}
    for column, label in variable_labels.items():
        if not isinstance(column, str) or not column or not isinstance(label, str) or not label:
            raise ValueError("labels.variable_labels must map non-empty column names to labels")
        normalized_variables[column] = label

    normalized_values: dict[str, dict[str, str]] = {}
    for column, mapping in value_labels.items():
        if not isinstance(column, str) or not column or not isinstance(mapping, Mapping):
            raise ValueError("labels.value_labels must map columns to objects")
        normalized_mapping: dict[str, str] = {}
        for raw_value, label in mapping.items():
            if not isinstance(raw_value, str) or not isinstance(label, str) or not label:
                raise ValueError("labels.value_labels entries must map string values to labels")
            normalized_mapping[raw_value] = label
        normalized_values[column] = normalized_mapping

    # v1.8.7 block 1: measurement_level is carried here as pure transport.  The
    # shape is validated like its siblings, but the level *value* is deliberately
    # not checked against an enum and nothing routes on it yet -- interpretation
    # belongs to the measurement-level work, not to a wiring block.
    measurement_level = payload.get("measurement_level", {})
    if not isinstance(measurement_level, Mapping):
        raise ValueError("labels.measurement_level must be an object")
    normalized_levels: dict[str, str] = {}
    for column, level in measurement_level.items():
        if not isinstance(column, str) or not column or not isinstance(level, str) or not level:
            raise ValueError(
                "labels.measurement_level must map non-empty column names to levels"
            )
        normalized_levels[column] = level

    normalized: dict[str, object] = {
        "variable_labels": normalized_variables,
        "value_labels": normalized_values,
    }
    # Only surface the key when the caller actually declared one.  Emitting it
    # unconditionally would change the labels payload shape for every existing
    # run, which is a behaviour change -- not allowed in a wiring block.
    if normalized_levels:
        normalized["measurement_level"] = normalized_levels
    return normalized


class LmmExecutionAdmissionError(RuntimeError):
    """Closed pre-fit LMM admission failure with no path or parser detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require_lmm_frozen_containment(model_type: object) -> dict[str, object] | None:
    """Require the explicit local profile before any LMM materialisation.

    The default keeps the prior early rejection.  A deliberately selected
    local profile is admitted only after its real OS-sandbox canary succeeds;
    it is local-development execution, not C2 candidate-evaluation evidence.
    """

    if model_type == _LMM_MODEL_TYPE:
        from .execution_profile import ExecutionProfileError, current_execution_profile

        try:
            current_execution_profile().require_lmm_admission()
        except ExecutionProfileError as error:
            message = (
                "Linear mixed-effects execution is unavailable until explicit "
                "local containment is admitted."
            )
            raise ModelOptionsError(error.code, message) from None
        return {
            "execution_profile": "local_contained",
            "containment_evidence": "local_startup_canary",
            "release_evaluation_eligible": False,
        }
    return None


def _record_lmm_persistence_failure(*, admission: object, code: str, retryable: bool) -> None:
    """Use the admission-bound sink; generic lifecycle files are forbidden."""

    from ..services.pinned_run_directory import _persist_lmm_lifecycle_failure

    _persist_lmm_lifecycle_failure(
        admission=admission, code=code, retryable=retryable
    )


def _safe_lmm_lifecycle_failure(exc: Exception) -> tuple[str, bool]:
    """Normalize every admitted LMM failure without examining exception text."""

    from ..services.pinned_run_directory import LmmPersistenceError, PinnedRunError

    if isinstance(exc, LmmPersistenceError):
        return exc.code, exc.retryable
    if isinstance(exc, (PinnedRunError, LmmExecutionAdmissionError)):
        code = exc.code
        return (code if code.startswith("LMM_") else "LMM_LIFECYCLE_FAILED", False)
    return "LMM_LIFECYCLE_FAILED", False


def _admit_lmm_execution_for_bg_run(
    *, run_root: Path, run_id: str, model_type: str,
    model_options: dict[str, object] | None, model_options_binding: dict[str, str] | None,
) -> object | None:
    """Create the one pre-fit LMM handoff from a pinned, matching input snapshot."""

    if model_type != "linear_mixed_effects":
        return None
    from ..canonical import canonical_json_v1
    from ..services.pinned_run_directory import _new_lmm_execution_admission, open_pinned_run_directory, seal_executed_input_v1

    if run_root.name != run_id or not isinstance(model_options, dict) or not isinstance(model_options_binding, dict):
        raise LmmExecutionAdmissionError("LMM_EXECUTION_BINDING_REQUIRED")
    pinned = open_pinned_run_directory(run_root.parent, run_id)
    lmm_execution_admission: _BgLmmExecutionAdmission | None = None
    try:
        snapshot = pinned.read_run_inputs_snapshot().value
        form = snapshot.get("form")
        if not isinstance(form, dict) or form.get("model_type") != "linear_mixed_effects":
            raise LmmExecutionAdmissionError("LMM_EXECUTION_BINDING_REQUIRED")
        if canonical_json_v1(form.get("model_options")) != canonical_json_v1(model_options) or canonical_json_v1(form.get("model_options_binding")) != canonical_json_v1(model_options_binding):
            raise LmmExecutionAdmissionError("LMM_EXECUTION_BINDING_REQUIRED")
        seal = seal_executed_input_v1(pinned, {
            "schema_version": 1,
            "model_type": "linear_mixed_effects",
            "model_options": model_options,
            "model_options_binding": model_options_binding,
        })
        return _new_lmm_execution_admission(pinned, seal)
    except BaseException:
        pinned.close()
        raise


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


#: Form fields persisted as objects rather than as JSON text. `model_options`
#: is handled separately by the merge itself; these are the rest.
_STRUCTURED_FORM_OVERRIDES = frozenset({"labels"})


def encode_form_override(key: str, value: object) -> object:
    """Encode an operation override using the run form's wire format.

    Column selectors are submitted as comma-separated form fields, while other
    list/dict overrides use JSON so the engine's typed parsers can consume them.
    """
    if key in {"x", "focal_x"} and isinstance(value, list):
        return ",".join(str(item) for item in value)
    # `labels` is persisted in the form as an object, not as JSON text -- see
    # `_submit_run`, which stores the normalized mapping. Encoding an override
    # to a string here would hand `_normalize_labels` a str and fail with
    # MODEL_OPTIONS_NOT_OBJECT, which names the wrong field entirely.
    if key in _STRUCTURED_FORM_OVERRIDES and isinstance(value, dict):
        return value
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def merge_form_overrides(
    source_form: Mapping[str, Any], overrides: Mapping[str, object]
) -> dict[str, Any]:
    """Merge a rerun patch while keeping model_options one level deep.

    Existing form keys retain their historical wire encoding. ``model_options``
    is deliberately the sole structured value: it is canonicalized, merged one
    level, and persisted as an object for the model handler.
    """

    if "model_options_binding" in overrides:
        raise ModelOptionsError(
            "MODEL_OPTIONS_BINDING_CLIENT_MANAGED",
            "model_options_binding is generated only by the server.",
        )

    has_replacement = "model_options" in overrides
    patch_options = overrides.get("model_options", {})
    if not isinstance(patch_options, Mapping):
        raise ModelOptionsError(
            "MODEL_OPTIONS_NOT_OBJECT", "model_options must be a JSON object."
        )

    # Keep the ordinary form wire values, but never carry the server-owned
    # binding forward from a parent. A new non-empty payload is bound again at
    # submission time for the current target handler.
    merged: dict[str, Any] = {
        key: source_form[key]
        for key in source_form
        if key not in {"model_options", "model_options_binding"}
    }
    source_model_type = str(source_form.get("model_type", "auto"))
    target_model_type = str(overrides.get("model_type", source_model_type))
    target_changed = source_model_type != target_model_type

    if target_changed and has_replacement:
        # A cross-model replacement is target-owned input. Do not parse,
        # hash, validate, or otherwise read the source options/binding: an old
        # owner can be retired, malformed, or unavailable without contaminating
        # a complete new target payload.
        next_options = canonicalize_model_options(patch_options)
    elif target_changed:
        source_has_options = _has_nonempty_model_options(
            source_form.get("model_options", {})
        )
        if source_has_options:
            # A non-empty cross-model payload is never inherited. The only
            # safe path is an explicit target-owned replacement.
            raise ModelOptionsError(
                "MODEL_OPTIONS_REPLACEMENT_REQUIRED",
                "changing model_type requires an explicit model_options replacement.",
            )
        # Empty legacy source payloads retain v1.7.2 behavior.
        next_options = canonicalize_model_options(patch_options)
    else:
        source_binding = source_form.get("model_options_binding")
        if source_binding is not None:
            # Compare owner metadata before reading the source payload. A
            # resolved id/contract change is a model identity change, so a
            # complete replacement must not be tainted by an old payload or
            # its hash (even when the public model_type text is unchanged).
            source_owner = ModelOptionsBinding.from_dict(source_binding)
            try:
                verify_binding_owner_for_model_type(source_owner, target_model_type)
            except ModelOptionsError as exc:
                if exc.code != "MODEL_OPTIONS_OWNER_MISMATCH":
                    raise
                if not has_replacement:
                    raise ModelOptionsError(
                        "MODEL_OPTIONS_REPLACEMENT_REQUIRED",
                        "changing resolved model identity requires an explicit model_options replacement.",
                    ) from exc
                next_options = canonicalize_model_options(patch_options)
            else:
                # Same-owner reuse is the only path that reads source options,
                # so it must first prove payload/hash integrity.
                source_bound = verify_bound_model_options(
                    source_form.get("model_options", {}), source_binding
                )
                assert source_bound.binding is not None
                next_options = merge_model_options(source_bound.payload, patch_options)
        else:
            source_options_raw = source_form.get("model_options", {})
            source_has_options = _has_nonempty_model_options(source_options_raw)
            if source_has_options and not has_replacement:
                raise ModelOptionsError(
                    "MODEL_OPTIONS_OWNER_MISSING",
                    "non-empty source model_options require an explicit replacement or migration.",
                )
            # An old, unbound payload can be discarded only by a complete
            # replacement, which is validated by the current target below.
            next_options = canonicalize_model_options(patch_options)

    if next_options:
        # A replacement is only meaningful when the target can fully validate
        # it; this also prevents an unbound source patch from masquerading as
        # a complete model input.
        next_options = bind_new_model_options(target_model_type, next_options).payload

    merged["model_options"] = next_options
    merged.update(
        {
            key: encode_form_override(key, value)
            for key, value in overrides.items()
            if key not in {"model_options", "model_options_binding"}
        }
    )
    return merged


def _has_nonempty_model_options(value: object) -> bool:
    """Check whether a persisted source carries options without normalizing it."""

    if isinstance(value, str):
        return value.strip() not in {"", "{}"}
    if isinstance(value, Mapping):
        return bool(value)
    return value is not None


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
    form: dict[str, Any],
    upload_bytes: bytes,
    upload_filename: str,
    started_at: str,
    rerun_of: str | None = None,
    from_node: str | None = None,
    rerun_reason: str = "initial",
    op_overrides: dict | None = None,
    rerun_from: dict[str, Any] | None = None,
    workbench_context: dict[str, Any] | None = None,
    run_family_id: str | None = None,
    before_dispatch: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Single dispatch path shared by POST /runs and POST /runs/{id}/rerun.

    Stores the upload content-addressably, writes run_inputs.json, materializes the
    blob into the run dir for the engine (which reads a path), and dispatches the full
    pipeline via _bg_run. The caller MUST already hold the run slot. Input parsing that
    can fail (imputation / iv arrays) happens BEFORE any run is created, so a bad request
    raises without leaving a junk run behind."""
    form = {
        key: value for key, value in form.items() if key != "model_options_binding"
    }
    raw_model_options = form.get("model_options", {})
    model_options = (
        parse_model_options(raw_model_options)
        if isinstance(raw_model_options, str)
        else canonicalize_model_options(raw_model_options)
    )
    bound_model_options = bind_new_model_options(
        form.get("model_type", "auto"), model_options
    )
    model_options = bound_model_options.payload
    model_options_binding = (
        bound_model_options.binding.to_dict()
        if bound_model_options.binding is not None
        else None
    )
    labels = _normalize_labels(form.get("labels", {}))
    statistical_tests_request = form.get("statistical_tests") or None
    if form.get("model_type", "auto") == "ols" and model_options:
        from ..contracts.model.ols import effective_ols_covariance

        # A rerun patch arrives in the Agent-owned envelope while the legacy
        # form still carries the source run's top-level default. Materialize
        # the effective choice into that legacy field before dispatch so the
        # estimator, metadata, and Draft reader all observe the same value.
        form = {
            **form,
            "covariance": effective_ols_covariance(
                form.get("covariance", ""), model_options
            ),
        }
    # This must happen before uploads or runs are materialized.  A rejected
    # LMM request therefore leaves neither executable evidence nor a run that
    # another boundary could later mistake for a C2-approved candidate.
    execution_profile = _require_lmm_frozen_containment(form.get("model_type", "auto"))
    form = {**form, "model_options": model_options}
    if labels:
        form["labels"] = labels
    else:
        form.pop("labels", None)
    if model_options_binding is not None:
        form["model_options_binding"] = model_options_binding

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
    # Gate 1: a run in a migrated project carries its family membership from
    # birth. A child inherits; a root run adopts a new family. Nothing here
    # re-derives a family from ancestry.
    ensure_run_family_binding(
        root,
        run.root,
        rerun_of=rerun_of,
        created_by="run_service",
        run_family_id=run_family_id,
    )

    model_type = form_for_persist.get("model_type", "auto")
    requested_covariance = str(form_for_persist.get("covariance", "")).strip().lower()
    wire_covariance = requested_covariance or "robust"
    executable_payload = {
        "model_type": model_type,
        "covariance": wire_covariance,
        "entity_col": form_for_persist.get("entity_col", ""),
        "y": form_for_persist.get("y", ""),
        "x": list(x_columns),
        "model_options": model_options,
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
        "model_options": model_options,
    }
    if model_options_binding is not None:
        executable_payload["model_options_binding"] = model_options_binding
        confirmed_payload["model_options_binding"] = model_options_binding
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
        execution_profile=execution_profile,
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
        form.get("prediction_data_structure"), form.get("prediction_entity_column", ""),
        form.get("prediction_group_column", ""),
        form.get("prediction_time_column", ""), _safe_float(form.get("prediction_final_holdout_fraction")),
        _safe_bool(form.get("prediction_shuffle")),
        iv_endog_list, iv_instruments_list,
        form.get("did_mode", ""), form.get("did_cohort_col", ""), form.get("did_treat_col", ""),
        form.get("did_post_col", ""), form.get("did_status_col", ""), form.get("did_treatment_path", ""),
        form.get("cs_control_group", ""), form.get("cs_est_method", ""), form.get("cs_base_period", ""),
        form.get("cs_cluster_var", ""), _safe_int(str(form.get("cs_anticipation", "0"))),
        str(form.get("honest_did", "false")).lower() == "true",
        model_options,
        model_options_binding,
        form.get("frequency_weight", ""),
        form.get("analysis_weight", ""),
        form.get("sampling_weight", ""),
        labels,
        statistical_tests_request,
        # Appended positionally at the tail, matching the order in _bg_run.
        # executor.submit is called positionally throughout, and existing test
        # doubles spy it as ``fake_submit(fn, *args)``; appending keeps both the
        # argument order and those doubles intact, while inserting next to the
        # weights would have shifted every argument after them.
        form.get("survey_strata_col", ""),
        form.get("survey_psu_col", ""),
        form.get("survey_fpc_col", ""),
        _parse_json_str_array(
            form.get("survey_replicate_weights", ""), "survey_replicate_weights"
        ),
        form.get("survey_replicate_type", ""),
        form.get("survey_lonely_psu", ""),
        form.get("survey_weight_frame", ""),
        form.get("survey_subpop", ""),
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
    prediction_data_structure: str | None = None,
    prediction_entity_column: str = "",
    prediction_group_column: str = "",
    prediction_time_column: str = "",
    prediction_final_holdout_fraction: float | None = None,
    prediction_shuffle: bool | None = None,
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
    model_options: dict[str, object] | None = None,
    model_options_binding: dict[str, str] | None = None,
    frequency_weight: str = "",
    analysis_weight: str = "",
    sampling_weight: str = "",
    labels: dict[str, object] | None = None,
    statistical_tests_request: dict | None = None,
    # v1.8.7 block 1.  Appended at the tail and passed by keyword at the submit
    # site: the executor.submit call above is fully positional, so inserting
    # these next to the weights would silently shift every argument after them.
    survey_strata_col: str = "",
    survey_psu_col: str = "",
    survey_fpc_col: str = "",
    survey_replicate_weights: list[str] | None = None,
    survey_replicate_type: str = "",
    survey_lonely_psu: str = "",
    survey_weight_frame: str = "",
    survey_subpop: str = "",
) -> None:
    events = get_event_manager()
    config = load_config(_resolve_project_root(run_root) / "config.yml")
    deadline = time.monotonic() + float(getattr(config, "run_timeout_s", 1800.0))

    def _stop_reason() -> str | None:
        if events.is_cancel_requested(run_id):
            return "cancelled"
        if time.monotonic() >= deadline:
            return "timeout"
        return None

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

    lmm_execution_admission: object | None = None
    try:
        lmm_execution_admission = _admit_lmm_execution_for_bg_run(
            run_root=run_root, run_id=run_id, model_type=model_type,
            model_options=model_options, model_options_binding=model_options_binding,
        )
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
            prediction_data_structure=prediction_data_structure,
            prediction_entity_column=prediction_entity_column,
            prediction_group_column=prediction_group_column,
            prediction_time_column=prediction_time_column,
            prediction_final_holdout_fraction=prediction_final_holdout_fraction,
            prediction_shuffle=prediction_shuffle,
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
            model_options=model_options,
            model_options_binding=model_options_binding,
            frequency_weight=frequency_weight,
            analysis_weight=analysis_weight,
            sampling_weight=sampling_weight,
            survey_strata_col=survey_strata_col,
            survey_psu_col=survey_psu_col,
            survey_fpc_col=survey_fpc_col,
            survey_replicate_weights=survey_replicate_weights,
            survey_replicate_type=survey_replicate_type,
            survey_lonely_psu=survey_lonely_psu,
            survey_weight_frame=survey_weight_frame,
            survey_subpop=survey_subpop,
            labels=labels,
            statistical_tests=statistical_tests_request,
            lmm_execution_admission=lmm_execution_admission,
            stop_reason=_stop_reason,
        )
        status = result["status"]
        events.emit_terminal(run_id, status, f"Workflow {status}")
    except RunInterruptionRequested as exc:
        reason = exc.reason
        code = "WORKFLOW_CANCELLED" if reason == "cancelled" else "WORKFLOW_TIMEOUT"
        if model_type == "linear_mixed_effects" and lmm_execution_admission is not None:
            # An admitted LMM owns its lifecycle persistence.  A cooperative
            # interruption is not allowed to escape into legacy manifest or
            # errors.json writers, because those writers are not bound to the
            # sealed input/admission capability.
            lmm_code = (
                "LMM_EXECUTION_CANCELLED"
                if reason == "cancelled"
                else "LMM_EXECUTION_TIMEOUT"
            )
            try:
                _record_lmm_persistence_failure(
                    admission=lmm_execution_admission,
                    code=lmm_code,
                    retryable=False,
                )
            except Exception:
                # A failed private sink cannot authorize generic fallback.
                pass
            events.emit_terminal(
                run_id,
                "PERSISTENCE_INCOMPLETE",
                f"LMM persistence incomplete: {lmm_code}",
            )
            return
        message = (
            "Workflow interrupted by user cancellation."
            if reason == "cancelled"
            else "Workflow interrupted after exceeding the configured run timeout."
        )
        _write_manifest(
            run_root, run_id, mode, "interrupted",
            _lineage([saved_path]),
            started_at=started_at, y=y, x=x_columns,
            requested_model_type=model_type,
        )
        write_json(run_root / "errors.json", {
            "issues": [GuardrailIssue(Severity.BLOCKER, code, message, {}).to_dict()],
        })
        events.emit_terminal(run_id, "interrupted", message)
    except Exception as exc:
        if model_type == "linear_mixed_effects":
            code, retryable = _safe_lmm_lifecycle_failure(exc)
            if lmm_execution_admission is not None:
                try:
                    _record_lmm_persistence_failure(
                        admission=lmm_execution_admission,
                        code=code,
                        retryable=retryable,
                    )
                except Exception:
                    # No generic fallback is authorized when the private sink
                    # is itself unavailable; the event remains incomplete.
                    pass
            events.emit_terminal(
                run_id,
                "PERSISTENCE_INCOMPLETE",
                f"LMM persistence incomplete: {code}",
            )
            return
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
        close = getattr(lmm_execution_admission, "_close_for_test", None)
        if callable(close):
            close()
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
