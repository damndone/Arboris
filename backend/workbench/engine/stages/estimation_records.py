"""Estimation run records: OLS contract metadata, model-options execution bindings, LMM input sealing and design prechecks."""

from __future__ import annotations

from typing import Any
from ..registry import ModelOptionsValidationError


def _persist_ols_contract_metadata(run_root, result: dict[str, Any]) -> None:
    """Append terminal OLS evidence while leaving executable payload immutable."""
    from ...lineage.run_inputs import read_run_inputs, update_run_inputs_metadata

    if not (run_root / "run_inputs.json").is_file():
        return
    fingerprint_fields = (
        "dataset_snapshot_fingerprint",
        "analysis_sample_fingerprint",
        "point_estimation_fingerprint",
        "coefficient_schema_fingerprint",
        "inference_config_fingerprint",
    )
    inputs = read_run_inputs(run_root)
    existing_payload = inputs.get("executed_payload")
    executable_payload = inputs.get("executable_payload")
    persisted_form = inputs.get("form")
    model_options = (
        existing_payload.get("model_options")
        if isinstance(existing_payload, dict)
        else executable_payload.get("model_options")
        if isinstance(executable_payload, dict)
        else persisted_form.get("model_options")
        if isinstance(persisted_form, dict)
        else None
    )
    model_options_binding = (
        existing_payload.get("model_options_binding")
        if isinstance(existing_payload, dict)
        else executable_payload.get("model_options_binding")
        if isinstance(executable_payload, dict)
        else persisted_form.get("model_options_binding")
        if isinstance(persisted_form, dict)
        else None
    )
    executed_payload = {
        "model_type": "ols",
        "covariance": result.get("covariance_wire"),
        "entity_col": result.get("entity_col"),
        "y": result.get("y_column"),
        "x": result.get("x_columns", []),
    }
    if isinstance(model_options, dict):
        executed_payload["model_options"] = model_options
    if isinstance(model_options_binding, dict):
        executed_payload["model_options_binding"] = model_options_binding
    update_run_inputs_metadata(
        run_root,
        executed_payload=executed_payload,
        contract_metadata={
            "contract_version": result.get("contract_version"),
            "model": result.get("model"),
            "model_type": result.get("model_type"),
            "covariance": result.get("covariance_wire"),
            "entity_col": result.get("entity_col"),
            "stable_result_ids": result.get("stable_result_ids", []),
            "candidate_result_ids": result.get("candidate_result_ids", []),
            "primary_estimand": result.get("primary_estimand"),
            "fingerprints": {
                field: result.get(field)
                for field in fingerprint_fields
            },
            "covariance_evidence": result.get("covariance_evidence", {}),
        },
    )


def _persist_model_options_execution_binding(
    run_root,
    *,
    model_type: str,
    model_options: dict[str, object],
    model_options_binding: object,
) -> None:
    """Write generic terminal evidence for a successfully bound options payload."""

    if not model_options or not isinstance(model_options_binding, dict):
        return
    from ...lineage.run_inputs import read_run_inputs, update_run_inputs_metadata

    if not (run_root / "run_inputs.json").is_file():
        return
    run_inputs = read_run_inputs(run_root)
    confirmed_payload = run_inputs.get("confirmed_payload")
    existing = run_inputs.get("executed_payload")
    # The analysis loop compares these two logical payloads by canonical hash.
    # Start from the server-confirmed transport rather than a smaller generic
    # subset, so a successful future model handler preserves covariance and
    # selector facts as well as its bound model options.
    has_confirmed_payload = isinstance(confirmed_payload, dict)
    executed_payload = (
        dict(confirmed_payload)
        if has_confirmed_payload
        else dict(existing)
        if isinstance(existing, dict)
        else {}
    )
    if not has_confirmed_payload:
        # `model_type` is a wire-level fact. A confirmed payload (when
        # present) may intentionally retain an alias such as glm:poisson,
        # while the resolved handler uses the registry key glm.
        executed_payload["model_type"] = model_type
    executed_payload.update(
        {
            "model_options": model_options,
            "model_options_binding": model_options_binding,
        }
    )
    update_run_inputs_metadata(run_root, executed_payload=executed_payload)


def _seal_lmm_executed_input_before_fit(
    *, run_root, run_id: str, model_options: object, model_options_binding: object
):
    """Create LMM's immutable pre-fit input proof, never a post-fit repair."""

    from ...services.pinned_run_directory import (
        open_pinned_run_directory,
        seal_executed_input_v1,
    )
    from ...contracts.model.linear_mixed_effects import validate_lmm_executed_options_v1

    if run_root.name != run_id:
        raise ModelOptionsValidationError(
            "LMM_EXECUTION_BINDING_REQUIRED",
            "LMM run root does not match its trusted run identifier.",
        )
    # The sealed artifact is the dedicated LMM execution record.  Do not use
    # generic run-input metadata mutation here or after fitting.
    model_input = validate_lmm_executed_options_v1(model_options, model_options_binding)
    pinned = open_pinned_run_directory(run_root.parent, run_id)
    try:
        representation = {
            "schema_version": 1,
            "model_type": "linear_mixed_effects",
            "model_options": model_input.to_dict(),
            "model_options_binding": dict(model_options_binding),
        }
        return pinned, seal_executed_input_v1(pinned, representation)
    except BaseException:
        pinned.close()
        raise


def _write_design_precheck(ctx, env, model_results) -> None:
    """Raise sampling-design questions the run itself can answer (v1.8.7 A2b).

    Written after estimation because the design effect only exists once a design
    has been fitted. Emitted only when there is something to ask about: a note on
    every run is one users learn to close unread.
    """
    from ...artifacts import register_artifact, write_json
    from ...design_precheck import build_precheck, collect_design_findings

    survey_design = None
    for _model_id, payload in model_results:
        if isinstance(payload, dict) and payload.get("survey_design"):
            survey_design = payload["survey_design"]
            break

    declared = {
        key: ctx.artifacts.get(f"_{key}")
        for key in ("survey_strata_col", "survey_psu_col")
    }
    findings = collect_design_findings(
        ctx.data.frame,
        declared=declared,
        survey_design=survey_design,
        weight_column=(ctx.artifacts.get("_sampling_weight") or None),
        modelled_columns=[
            ctx.artifacts.get("_normalized_y") or "",
            *(ctx.artifacts.get("_normalized_x") or []),
        ],
        rows_before_cleaning=ctx.artifacts.get("_raw_row_count"),
    )
    if not findings:
        return

    path = env.run_root / "measurement" / "design_precheck.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, build_precheck(findings))
    register_artifact(
        env.run_root, "design_precheck", path, "design_precheck", "estimation",
        ["cleaned_dataset"],
    )
