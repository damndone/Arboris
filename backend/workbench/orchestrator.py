from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .artifacts import read_json, register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
from .diagnostic_summary import build_diagnostic_summary
from .domain import GuardrailIssue, Severity
from .graph_recorder import GraphRecorder
from .graph_store import GraphStore
from . import graph_decision_factory as dpf
from .econometrics.diagnostics import compute_diagnostics
from .econometrics.runner import (
    run_logit,
    run_ols,
    run_poisson,
    run_time_series_diagnostics,
)
from .exports import export_pdf, export_xlsx
from .ingestion import ingest_files
from .metadata import infer_schema
from .narrative import build_claims
from .profiling import profile_frame
from .projects import create_run
from .reporting import render_html_report
from .router import classify_dataset, detect_y_kind
from .statistical_tests import (
    run_statistical_tests,
    summarize_statistical_tests,
    write_statistical_test_artifacts,
)
from .validation import has_blockers, validate_profile
from .variable_roles import infer_variable_roles
from .visualization import create_figures

# ============================================================
# AUTO-DETECTION (computed from data, dataset-agnostic):
#   - Binary variable correlation: checks all binary X pairs
#   - Exposure candidates: matches column name patterns
#   - Suspicious dtype: datetime columns in X
#   - Binary/suspicious variable detection: based on data values
#
# HARDCODED THRESHOLDS (configurable defaults):
#   _BINARY_CORRELATION_WARN = 0.7
#   _BINARY_CORRELATION_INFO = 0.5
#   _EXPOSURE_NAME_PATTERNS = (...)
#   _SUSPICIOUS_NAME_PATTERNS = (...)
# ============================================================


def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
) -> dict[str, str]:
    project_root = Path(project_root)
    config = load_config(project_root / "config.yml")
    run = create_run(project_root, mode=mode)
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root,
        run.run_id,
        mode,
        "running",
        _lineage(input_files),
        started_at=started_at,
        y=y,
        x=x,
        requested_model_type="auto",
    )

    try:
        return _run_workflow(
            run.root,
            run.run_id,
            input_files,
            mode,
            y,
            x,
            config,
            started_at,
        )
    except Exception as exc:
        issue = GuardrailIssue(
            Severity.BLOCKER,
            "WORKFLOW_FAILED",
            "Workflow failed before completion.",
            {"error": str(exc)},
        )
        write_json(run.root / "errors.json", {"issues": [issue.to_dict()]})
        _write_manifest(
            run.root,
            run.run_id,
            mode,
            "failed",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
            requested_model_type="auto",
        )
        raise


def run_batch_y_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y_list: list[str],
    x: list[str],
) -> dict[str, Any]:
    runs: list[dict[str, str | None]] = []
    for y in y_list:
        result = run_workflow(project_root, input_files, mode=mode, y=y, x=x)
        run_id = result["run_id"]
        run_root = Path(project_root) / "runs" / run_id
        model_summary = _primary_model_summary(run_root)
        runs.append(
            {
                "y": y,
                "run_id": run_id,
                "status": result["status"],
                "model_id": model_summary.get("model_id"),
                "model_type": model_summary.get("model_type"),
            }
        )
    status = "completed" if all(item["status"] == "completed" for item in runs) else "partial"
    return {"status": status, "runs": runs}


def _primary_model_summary(run_root: Path) -> dict[str, str | None]:
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return {"model_id": None, "model_type": None}
    for model_file in ("ols_1.json", "logit_1.json", "poisson_1.json"):
        path = model_dir / model_file
        if path.is_file():
            data = read_json(path)
            return {
                "model_id": data.get("model_id"),
                "model_type": data.get("model_type"),
            }
    return {"model_id": None, "model_type": None}


def _run_workflow(
    run_root: Path,
    run_id: str,
    input_files: list[Path],
    mode: str,
    y: str,
    x: list[str],
    config: Any,
    started_at: str,
    on_step: Callable[[str, str, str], None] | None = None,
    model_type: str = "auto",
    sheet_name: str | None = None,
    transpose: bool = False,
) -> dict[str, str]:
    _s = on_step  # shorthand

    _graph_store = GraphStore(runs_root=run_root.parent)
    _recorder = GraphRecorder(run_id=run_id, store=_graph_store)
    _recorder.record_stage(
        node_id="stage:raw",
        display_label="Raw input data",
        payload_ref=None,
    )

    if _s: _s("ingestion", "start", "Ingesting files...")
    frames = ingest_files([Path(path) for path in input_files], run_root, config, sheet_name, transpose)
    if _s: _s("ingestion", "complete", f"Ingested {len(frames)} file(s)")

    if _s: _s("schema", "start", "Inferring schema...")
    schema = infer_schema("dataset_1", frames, run_root)
    if _s: _s("schema", "complete", f"Inferred schema with {len(schema.columns)} columns")
    frame = next(iter(frames.values()))

    if _s: _s("cleaning", "start", "Cleaning data...")
    cleaned, actions = clean_frame(frame, list(schema.time_candidates))
    if _s: _s("cleaning", "complete", f"Applied {len(actions)} cleaning actions")
    raw_inputs = [f"raw_{path.name}" for path in input_files]
    cleaning_path = run_root / "processed" / "cleaning_actions.json"
    write_json(cleaning_path, {"actions": actions})
    register_artifact(
        run_root,
        "cleaning_actions",
        cleaning_path,
        "metadata",
        "cleaning",
        raw_inputs,
    )
    cleaned_path = run_root / "processed" / "cleaned_dataset.parquet"
    cleaned.to_parquet(cleaned_path, index=False)
    register_artifact(
        run_root,
        "cleaned_dataset",
        cleaned_path,
        "processed_data",
        "cleaning",
        raw_inputs,
    )

    if _s: _s("profiling", "start", "Profiling data...")
    profile = profile_frame(cleaned)
    if _s: _s("profiling", "complete", f"Profiled {profile['row_count']} rows")
    profile_path = run_root / "staged" / "data_profile.json"
    write_json(profile_path, profile)
    register_artifact(
        run_root,
        "data_profile",
        profile_path,
        "profile",
        "profiling",
        ["cleaned_dataset"],
    )

    if _s: _s("validation", "start", "Validating profile...")
    issues = validate_profile(profile, config)
    issue_dicts = [issue.to_dict() for issue in issues]
    write_json(run_root / "errors.json", {"issues": issue_dicts})
    if has_blockers(issues):
        if _s: _s("validation", "blocked", "Validation found blocker issues")
        _write_manifest(
            run_root,
            run_id,
            mode,
            "blocked",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
        )
        _recorder.flush()
        return {"run_id": run_id, "status": "blocked"}
    if _s: _s("validation", "complete", "Validation passed")

    if _s: _s("routing", "start", "Classifying dataset...")
    time_candidates = _normalized_existing(schema.time_candidates, cleaned)
    id_candidates = _normalized_existing(schema.id_candidates, cleaned)
    routing = classify_dataset(cleaned, id_candidates, time_candidates)
    if _s: _s("routing", "complete", f"Classified as {routing['kind']}")
    routing_path = run_root / "staged" / "analysis_router.json"
    write_json(routing_path, routing)
    register_artifact(
        run_root,
        "analysis_router",
        routing_path,
        "metadata",
        "analysis_router",
        ["data_profile"],
    )

    if _s: _s("y_type", "start", "Detecting y variable type...")
    normalized_y = normalize_column_name(y)
    normalized_x = [normalize_column_name(column) for column in x]

    _missing_values_dp = dpf.handle_missing_values(
        variables=[normalized_y, *normalized_x],
    )

    if normalized_y in cleaned.columns:
        data_detected_y_type = detect_y_kind(cleaned, normalized_y).value
    else:
        data_detected_y_type = "continuous"
    if model_type != "auto":
        y_type = _map_model_type(model_type)
        _model_type_dp = None
    else:
        y_type = data_detected_y_type
        _model_type_dp = dpf.model_type_auto_select(
            selected=y_type,
            y_unique=int(cleaned[normalized_y].nunique()) if normalized_y in cleaned.columns else 0,
            y_dtype=str(cleaned[normalized_y].dtype) if normalized_y in cleaned.columns else "unknown",
        )
    if _s: _s("y_type", "complete", f"y classified as {y_type}")

    if _s: _s("model_check", "start", "Checking model columns...")
    model_issue = _model_column_issue(cleaned, normalized_y, normalized_x, y, x)
    if model_issue is not None:
        issue_dicts.append(model_issue.to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
        if _s: _s("model_check", "blocked", "Requested model columns not found")
        _write_manifest(
            run_root,
            run_id,
            mode,
            "blocked",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
        )
        _recorder.flush()
        return {"run_id": run_id, "status": "blocked"}
    if _s: _s("model_check", "complete", "Model columns valid")

    coercion_actions = _coerce_x_columns_to_numeric(cleaned, normalized_x, run_root)

    _coerce_dps: dict[str, Any] = {}
    for action in coercion_actions:
        col = action["column"]
        _coerce_dps[col] = dpf.auto_coerce_to_numeric(
            variable=col,
            conversion_rate=action["conversion_rate"],
        )

    # Detect categorical X variables for C() encoding in model formula
    categorical_vars = _detect_categorical_x_vars(cleaned, normalized_x)

    _categorical_dummy_dps: dict[str, Any] = {}
    for cat_var in categorical_vars:
        ref = sorted(cleaned[cat_var].dropna().unique())[0] if cat_var in cleaned.columns else "?"
        _categorical_dummy_dps[cat_var] = dpf.categorical_auto_dummy(
            variable=cat_var,
            n_unique=int(cleaned[cat_var].nunique()) if cat_var in cleaned.columns else 0,
            reference_level=str(ref),
        )

    variable_roles = infer_variable_roles(cleaned, normalized_x, y_type=y_type)

    # Detect exposure variable early for count models (needed before statistical tests and VIF)
    exposure_col = None
    if y_type == "count":
        exposure_candidates = _detect_exposure_candidates(normalized_x)
        if exposure_candidates:
            exposure_col = _select_valid_exposure_col(cleaned, exposure_candidates)

    if _s:
        _s("statistical_tests", "start", "Running statistical tests...")
    stat_analysis_columns = [normalized_y] + [v for v in normalized_x if v != (exposure_col or "")]
    statistical_tests = run_statistical_tests(
        cleaned,
        analysis_columns=stat_analysis_columns,
    )
    write_statistical_test_artifacts(run_root, statistical_tests)
    statistical_test_summaries = summarize_statistical_tests(statistical_tests, y=normalized_y)
    if _s:
        _s("statistical_tests", "complete", "Statistical tests completed")

    model_results: list[tuple[str, dict[str, Any]]] = []
    fitted_models: dict[str, Any] = {}

    if _s: _s("estimation", "start", f"Fitting {y_type} model (y type: {y_type})...")

    poisson_x = list(normalized_x)
    if exposure_col:
        poisson_x = [v for v in normalized_x if v != exposure_col]

    _robust_se_dp = None

    try:
        if y_type == "binary":
            primary, primary_fitted = run_logit(cleaned, y=normalized_y, x=normalized_x, model_id="logit_1", categorical_x=categorical_vars)
            _write_model_result(run_root, "logit_1", primary)
            model_results.append(("logit_1", primary))
            fitted_models["logit_1"] = primary_fitted
        elif y_type == "count":
            poisson_cat = {v for v in categorical_vars if v in poisson_x}
            primary, primary_fitted = run_poisson(
                cleaned, y=normalized_y, x=poisson_x, model_id="poisson_1",
                exposure_col=exposure_col,
                categorical_x=poisson_cat,
            )
            _write_model_result(run_root, "poisson_1", primary)
            model_results.append(("poisson_1", primary))
            fitted_models["poisson_1"] = primary_fitted
        else:
            primary, primary_fitted = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1", categorical_x=categorical_vars)
            _write_model_result(run_root, "ols_1", primary)
            model_results.append(("ols_1", primary))
            fitted_models["ols_1"] = primary_fitted
            _robust_se_dp = dpf.ols_default_robust_se(variant="HC1")
    except ValueError as exc:
        model_issue = GuardrailIssue(
            Severity.WARNING,
            "MODEL_FIT_FAILED",
            str(exc),
            {"y": normalized_y, "x": normalized_x, "y_type": y_type},
        )
        issue_dicts.append(model_issue.to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
        if _s: _s("estimation", "blocked", f"Model fit failed: {exc}")
        # Fall back to OLS — clear auto model_type DP since it no longer applies
        _model_type_dp = None
        ols_result, ols_fitted = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1", categorical_x=categorical_vars)
        _robust_se_dp = dpf.ols_default_robust_se(variant="HC1")
        _write_model_result(run_root, "ols_1", ols_result)
        model_results.append(("ols_1", ols_result))
        fitted_models["ols_1"] = ols_fitted

    primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
    drop_check_x = poisson_x if primary_type == "poisson_rate" else normalized_x
    dropped_vars = _check_dropped_variables(drop_check_x, model_results, cleaned, issue_dicts, run_root, categorical_vars=categorical_vars)

    _dropped_dps: dict[str, Any] = {}
    for entry in dropped_vars:
        parsed = _parse_dropped_var_entry(entry)
        _dropped_dps[parsed["variable"]] = dpf.variable_silently_dropped(
            variable=parsed["variable"],
            drop_reason=parsed["reason"],
        )

    # -- Record lineage graph nodes with accumulated DecisionPoints ----------
    _recorder.record_stage(
        node_id="stage:cleaned",
        display_label="Cleaned data",
        payload_ref="processed/cleaned_dataset.parquet",
        decision_point=_missing_values_dp,
    )
    _recorder.record_edge(
        edge_id="e:raw-cleaned",
        source_id="stage:raw",
        target_id="stage:cleaned",
        op="clean_frame",
        params={"cleaning_actions_count": len(actions)},
    )

    for var in [normalized_y, *normalized_x]:
        _cat_dp = _categorical_dummy_dps.get(var)
        _coer_dp = _coerce_dps.get(var)
        if _cat_dp is not None and _coer_dp is not None:
            import warnings as _warnings
            _warnings.warn(
                f"Variable {var!r} has both categorical_dummy and auto_coerce "
                f"DecisionPoints. Using categorical_dummy (coerce DP ignored). "
                f"This is unexpected — a column should not be both categorical "
                f"and coerced-to-numeric.",
                UserWarning, stacklevel=2,
            )
        _dp_for_var = _cat_dp or _coer_dp
        _recorder.record_variable(
            node_id=f"var:{var}:cleaned",
            display_label=f"{var} (cleaned)",
            parent_stage_id="stage:cleaned",
            decision_point=_dp_for_var,
        )

    for var_name, dropped_dp in _dropped_dps.items():
        _recorder.record_variable(
            node_id=f"var:{var_name}:dropped",
            display_label=f"{var_name} (dropped)",
            parent_stage_id="stage:cleaned",
            decision_point=dropped_dp,
        )

    if model_results:
        primary_model_id = model_results[0][0]
        primary_model_type = model_results[0][1].get("model_type", "ols")
        # Attach one DecisionPoint per node for V1.4.0:
        # model_type_auto_select (data-driven) > ols_default_robust_se
        _primary_dp = _model_type_dp or _robust_se_dp
        _recorder.record_model(
            node_id=f"model:{primary_model_id}",
            display_label=f"{primary_model_type} (primary)",
            payload_ref=f"model_results/{primary_model_id}.json",
            decision_point=_primary_dp,
        )
        _recorder.record_edge(
            edge_id="e:cleaned-model-primary",
            source_id="stage:cleaned",
            target_id=f"model:{primary_model_id}",
            op=f"{primary_model_type}.fit",
        )

        _recorder.record_report(
            node_id="report:html",
            display_label="HTML report",
            payload_ref="reports/report.html",
        )
        _recorder.record_edge(
            edge_id="e:model-report",
            source_id=f"model:{primary_model_id}",
            target_id="report:html",
            op="render_report",
        )

    if _s: _s("diagnostics", "start", "Running regression diagnostics...")
    diag_x = [v for v in normalized_x if v != exposure_col] if exposure_col else normalized_x
    exog = cleaned[diag_x] if diag_x else pd.DataFrame(index=cleaned.index)
    diagnostic_artifacts: dict[str, dict[str, Any]] = {}
    for model_id, fitted in fitted_models.items():
        result_dict = dict(model_results)
        fitted_model_type = next(
            (r.get("model_type", "ols") for mid, r in model_results if mid == model_id),
            "ols",
        )
        family = "poisson" if fitted_model_type == "poisson_rate" else ("ols" if fitted_model_type in ("ols", "ols_robust", "fixed_effects") else fitted_model_type)
        diag = compute_diagnostics(fitted, exog, model_id, model_family=family)
        diag["model_type"] = fitted_model_type
        diag_path = run_root / "model_results" / f"diagnostics_{model_id}.json"
        write_json(diag_path, diag)
        register_artifact(
            run_root,
            f"diagnostics_{model_id}",
            diag_path,
            "model_diagnostic",
            "econometrics",
            ["cleaned_dataset"],
        )
        diagnostic_artifacts[model_id] = diag
        _check_model_validity(diag, model_id, issue_dicts, run_root)
        if fitted_model_type in ("poisson", "poisson_rate"):
            _check_overdispersion_issue(diag, model_id, issue_dicts, run_root)
        sep = diag.get("separation", {})
        if isinstance(sep, dict) and sep.get("warning"):
            issue_dicts.append(GuardrailIssue(
                Severity.WARNING,
                "SEPARATION_WARNING",
                f"Model {model_id}: {sep['warning']} "
                f"(converged={sep.get('converged')}, max|coef|={sep.get('max_abs_coef')}, "
                f"max SE={sep.get('max_std_error')}). "
                f"Consider Firth penalized likelihood or removing problematic predictors.",
                {"model_id": model_id, **{k: v for k, v in sep.items() if v is not None}},
            ).to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
    if _s: _s("diagnostics", "complete", f"Diagnostics computed for {len(fitted_models)} model(s)")

    if routing["kind"] == "time_series" and time_candidates:
        diagnostics = run_time_series_diagnostics(
            cleaned, normalized_y, time_candidates[0]
        )
        diagnostics_path = run_root / "model_results" / "time_series_diagnostics.json"
        write_json(diagnostics_path, diagnostics)
        register_artifact(
            run_root,
            "time_series_diagnostics",
            diagnostics_path,
            "model_diagnostic",
            "econometrics",
            ["cleaned_dataset"],
        )

    if _s:
        primary_result = model_results[0][1] if model_results else {}
        r2 = primary_result.get("r_squared") or primary_result.get("pseudo_r2")
        if r2 is not None:
            kind_label = "pseudo-R²" if primary_result.get("pseudo_r2") is not None else "R²"
            _s("estimation", "complete", f"Model(s) fitted, {kind_label}={r2:.4f}")
        else:
            _s("estimation", "complete", "Model(s) fitted")

    if _s: _s("visualization", "start", "Creating figures...")
    numeric_columns = [
        str(column)
        for column in cleaned.select_dtypes(include="number").columns
    ]
    create_figures(
        cleaned,
        run_root,
        numeric_columns=numeric_columns,
        time_column=time_candidates[0] if time_candidates else None,
        model_results=model_results,
    )
    if _s: _s("visualization", "complete", "Created diagnostic figures")

    if _s: _s("narrative", "start", "Building claims...")
    binary_vars = _detect_binary_vars(cleaned, normalized_x)
    _check_binary_correlations(cleaned, binary_vars, issue_dicts, run_root)
    _check_treatment_proxy_correlations(cleaned, normalized_x, issue_dicts, run_root)
    suspicious_vars = _detect_suspicious_vars(normalized_x)
    primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
    effective_exposure_col = exposure_col if primary_type == "poisson_rate" else None
    reliability_info = _check_rare_event(cleaned, normalized_y, primary_type, len(normalized_x), issue_dicts, run_root)
    caveat = ""
    if reliability_info and reliability_info.get("reliability", "").startswith("Low"):
        caveat = "Reliability is limited due to rare events; interpret with caution"
    claims = build_claims(
        [result for _, result in model_results], issue_dicts,
        binary_vars=binary_vars, suspicious_vars=suspicious_vars,
        model_type=primary_type, reliability_caveat=caveat,
        categorical_vars=categorical_vars,
    )
    if _s: _s("narrative", "complete", f"Built {len(claims)} claims")
    _check_suspicious_dtypes(cleaned, normalized_x, issue_dicts, run_root)
    _check_categorical_candidates(
        cleaned,
        issue_dicts,
        run_root,
        encoded_categorical_vars=categorical_vars,
    )
    if routing["kind"] == "panel" and primary_type != "fixed_effects":
        issue_dicts.append(GuardrailIssue(
            Severity.INFO,
            "PANEL_POOLED_MODEL",
            f"Dataset detected as panel-like, but this run used a pooled {primary_type} model "
            f"without fixed effects or clustered standard errors.",
            {"kind": routing["kind"], "model_type": primary_type},
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
    descriptive_stats = _build_descriptive_stats(cleaned, categorical_vars=categorical_vars)
    model_family_display = {"ols": "OLS", "ols_robust": "OLS (robust SE)", "logit": "Logit", "poisson": "Poisson", "poisson_rate": "Poisson (rate model)"}
    primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
    if effective_exposure_col:
        facts = [
            f"Model: Poisson rate model with log({effective_exposure_col}) as offset",
            f"y = {normalized_y};  X = {', '.join(poisson_x)}",
            f"Exposure/offset: log({effective_exposure_col}), coefficient fixed at 1",
            f"Model formula: {normalized_y} ~ {' + '.join(poisson_x)} + offset(log({effective_exposure_col}))",
            f"Rows used: {profile['row_count']} · Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ]
    else:
        facts = [
            f"Model: {model_family_display.get(primary_type, primary_type)}",
        ]
        facts.extend([
            f"y = {normalized_y};  X = {', '.join(normalized_x)}",
            f"Rows used: {profile['row_count']} · Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ])
    if dropped_vars:
        facts.append(f"Variables dropped from model: {'; '.join(dropped_vars)}")
    if categorical_vars:
        facts.append(f"Categorical variable(s): {', '.join(sorted(categorical_vars))} (dummy-coded in model)")
    if reliability_info:
        facts.append(
            f"Model reliability: {reliability_info['reliability']} "
            f"(positive rate: {reliability_info['positive_rate']:.1%}, "
            f"events per predictor: {reliability_info['events_per_predictor']:.1f})"
        )
    if primary_type in ("poisson", "poisson_rate"):
        poisson_diag = diagnostic_artifacts.get("poisson_1", {})
        overdisp = poisson_diag.get("overdispersion", {})
        if isinstance(overdisp, dict):
            zero_rate = overdisp.get("zero_rate")
            if zero_rate is not None:
                facts.append(f"Zero rate in outcome: {float(zero_rate):.1%}")
            zih = overdisp.get("zero_inflation_hint")
            if zih:
                facts.append(zih)
            ow = overdisp.get("warning")
            if ow:
                facts.append(f"Overdispersion: {ow}")
            else:
                od_ratio = overdisp.get("overdispersion_ratio")
                if od_ratio is not None:
                    facts.append(f"Overdispersion: not detected (ratio={float(od_ratio):.2f})")
    variable_importance = _build_variable_importance(
        statistical_tests, normalized_y, normalized_x, model_results,
        cleaned, primary_type, exposure_col=effective_exposure_col,
        categorical_vars=categorical_vars,
    )
    facts.append(
        "Note: variable importance is based on marginal (univariate) association "
        "with the outcome and may differ from multivariable regression results "
        "after controlling for other predictors."
    )
    report = {
        "title": "Econometrics Report",
        "facts": facts,
        "claims": claims,
        "warnings": issue_dicts,
        "descriptive_stats": descriptive_stats,
        "statistical_tests": statistical_test_summaries,
        "variable_importance": variable_importance,
        "diagnostics": diagnostic_artifacts,
    }
    if primary_type in ("poisson", "poisson_rate"):
        poisson_diag = diagnostic_artifacts.get("poisson_1", {})
        overdisp = poisson_diag.get("overdispersion", {})
        if isinstance(overdisp, dict) and overdisp:
            report["overdispersion"] = overdisp
    # Generate issue IDs for all collected issues
    for idx, issue in enumerate(issue_dicts):
        if not issue.get("issue_id"):
            issue["issue_id"] = f"diag_{idx + 1:03d}"

    # Build diagnostic_summary.json
    primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
    effective_exposure_col = exposure_col if primary_type == "poisson_rate" else None
    diagnostic_summary = build_diagnostic_summary(
        issue_dicts=issue_dicts,
        model_results=[result for _, result in model_results],
        routing=routing,
        normalized_y=normalized_y,
        normalized_x=normalized_x,
        profile=profile,
        categorical_vars=categorical_vars,
        y_type=y_type,
        primary_type=primary_type,
        variable_roles=variable_roles,
        run_id=run_id,
        exposure_col=effective_exposure_col,
        dropped_vars=dropped_vars,
        coercions=coercion_actions,
    )
    write_json(run_root / "diagnostic_summary.json", diagnostic_summary)
    register_artifact(run_root, "diagnostic_summary", run_root / "diagnostic_summary.json", "metadata", "diagnostics", [])

    # Write legacy errors.json with superseded_by pointer
    write_json(run_root / "errors.json", {
        "schema_version": "legacy",
        "run_id": run_id,
        "issues": issue_dicts,
        "superseded_by": "diagnostic_summary.json",
    })

    # Render HTML report via view_model
    if _s: _s("reporting", "start", "Rendering report...")
    try:
        from .report_view_model import build_report_view_model
        view_model = build_report_view_model(
            diagnostic_summary, run_root,
            descriptive_stats=descriptive_stats,
            statistical_tests=statistical_test_summaries,
        )
        render_html_report(view_model, run_root)
        if _s: _s("reporting", "complete", "Rendered HTML report")
    except Exception as exc:
        issue_dicts.append(GuardrailIssue(
            Severity.WARNING,
            "REPORT_RENDER_FAILED",
            f"HTML report generation failed: {exc}. Model results are still available.",
            {"error": str(exc)},
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
        if _s: _s("reporting", "complete", "Report render failed — model results available")

    if _s: _s("export", "start", "Exporting files...")
    try:
        export_pdf(report, run_root)
        export_xlsx(
            {"coefficients": _coefficient_rows_for_models(model_results)},
            run_root,
        )
        if _s: _s("export", "complete", "Exported PDF and XLSX")
    except Exception as exc:
        issue_dicts.append(GuardrailIssue(
            Severity.WARNING,
            "EXPORT_FAILED",
            f"File export failed: {exc}. Model results are still available.",
            {"error": str(exc)},
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
        if _s: _s("export", "complete", "Export failed — model results available")

    _recorder.flush()

    _write_manifest(
        run_root,
        run_id,
        mode,
        "completed",
        _lineage(input_files),
        started_at=started_at,
        y=y,
        x=x,
        requested_model_type=model_type,
        model_routing=_build_model_routing_summary(
            cleaned,
            normalized_y,
            requested_model_type=model_type,
            data_detected_y_type=data_detected_y_type,
            effective_y_type=y_type,
            model_results=model_results,
        ),
    )
    return {"run_id": run_id, "status": "completed"}


def _normalized_existing(candidates: tuple[str, ...], frame: pd.DataFrame) -> list[str]:
    columns = set(frame.columns)
    return [
        normalized
        for candidate in candidates
        if (normalized := normalize_column_name(candidate)) in columns
    ]


def _write_model_result(run_root: Path, model_id: str, model_result: dict[str, Any]) -> None:
    model_path = run_root / "model_results" / f"{model_id}.json"
    write_json(model_path, model_result)
    register_artifact(
        run_root,
        model_id,
        model_path,
        "model_result",
        "econometrics",
        ["cleaned_dataset"],
    )


def _coefficient_rows(model_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coefficients = model_result.get("coefficients", {})
    irr_dict = model_result.get("irr", {})
    if not isinstance(coefficients, dict):
        return rows
    for term, values in coefficients.items():
        if isinstance(values, dict):
            row: dict[str, Any] = {"term": term, **values}
            if isinstance(irr_dict, dict) and term in irr_dict:
                term_irr = irr_dict[term]
                if isinstance(term_irr, dict):
                    row.setdefault("irr", term_irr.get("irr"))
                    row.setdefault("irr_ci_lower", term_irr.get("irr_ci_lower"))
                    row.setdefault("irr_ci_upper", term_irr.get("irr_ci_upper"))
            rows.append(row)
    return rows


def _coefficient_rows_for_models(
    model_results: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id, model_result in model_results:
        for row in _coefficient_rows(model_result):
            rows.append({"model_id": model_id, **row})
    return rows


def _model_column_issue(
    frame: pd.DataFrame,
    normalized_y: str,
    normalized_x: list[str],
    requested_y: str,
    requested_x: list[str],
) -> GuardrailIssue | None:
    columns = set(frame.columns)
    requested = [normalized_y, *normalized_x]
    missing = [column for column in requested if column not in columns]
    if not missing:
        return None
    return GuardrailIssue(
        Severity.BLOCKER,
        "MODEL_COLUMNS_NOT_FOUND",
        "Requested model columns are not available after cleaning.",
        {
            "missing_columns": missing,
            "available_columns": sorted(str(column) for column in frame.columns),
            "requested_y": requested_y,
            "requested_x": requested_x,
        },
    )


def _lineage(input_files: list[Path]) -> list[dict[str, str]]:
    return [
        {"source": str(path), "artifact_id": f"raw_{Path(path).name}"}
        for path in input_files
    ]


def _build_model_routing_summary(
    frame: pd.DataFrame,
    y: str,
    *,
    requested_model_type: str,
    data_detected_y_type: str,
    effective_y_type: str,
    model_results: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    series = frame[y].dropna() if y in frame.columns else pd.Series(dtype="float64")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_present = numeric.dropna()
    integer_like = False
    if not numeric_present.empty:
        integer_like = bool((numeric_present == numeric_present.astype(int)).all())
    effective_model_id = model_results[0][0] if model_results else None
    effective_model_type = (
        model_results[0][1].get("model_type") if model_results else None
    )
    return {
        "requested_model_type": requested_model_type,
        "current_y": y,
        "dtype": str(series.dtype),
        "min": float(numeric_present.min()) if not numeric_present.empty else None,
        "max": float(numeric_present.max()) if not numeric_present.empty else None,
        "unique": int(series.nunique()),
        "integer_like": integer_like,
        "data_detected_y_type": data_detected_y_type,
        "effective_y_type": effective_y_type,
        "effective_model_id": effective_model_id,
        "effective_model_type": effective_model_type,
    }


def _write_manifest(
    run_root: Path,
    run_id: str,
    mode: str,
    status: str,
    lineage: list[dict[str, str]],
    *,
    started_at: str,
    y: str,
    x: list[str],
    requested_model_type: str | None = None,
    model_routing: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "started_at": started_at,
        "y": y,
        "x": list(x),
        "lineage": lineage,
    }
    if requested_model_type is not None:
        payload["requested_model_type"] = requested_model_type
    if model_routing is not None:
        payload["model_routing"] = model_routing
    write_json(
        run_root / "run_manifest.json",
        payload,
    )


_BINARY_CORRELATION_WARN = 0.7  # |r| > 0.7 > Severity.WARNING
_BINARY_CORRELATION_INFO = 0.5  # 0.5 < |r| <= 0.7 > Severity.INFO
_TREATMENT_PROXY_CORRELATION_WARN = 0.7
_MODEL_TYPE_MAP = {"ols": "continuous", "logit": "binary", "poisson": "count"}


def _map_model_type(model_type: str) -> str:
    y_type = _MODEL_TYPE_MAP.get(model_type)
    if y_type is None:
        return "continuous"
    return y_type


def _build_variable_importance(
    statistical_tests: dict[str, dict[str, Any]],
    y: str,
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]] | None = None,
    frame: pd.DataFrame | None = None,
    primary_type: str = "ols",
    exposure_col: str | None = None,
    categorical_vars: set[str] | None = None,
) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    importance: dict[str, dict[str, Any]] = {}
    for var in x_vars:
        if var == exposure_col:
            continue
        importance[var] = {
            "variable": var, "correlation": None, "best_p_value": None, "test_type": None
        }
    if frame is not None:
        cols = [y] + [v for v in x_vars if v in frame.columns]
        if len(cols) >= 2:
            corr = frame[cols].corr(numeric_only=True)
            if y in corr.columns:
                for var in x_vars:
                    if var == exposure_col:
                        continue
                    if var in corr.columns:
                        c = corr[y].get(var)
                        if pd.notna(c):
                            importance[var]["correlation"] = round(float(c), 3)
                            if var in cat_set:
                                importance[var]["correlation_note"] = "Pearson r on categorical codes — prefer ANOVA"
    for row in statistical_tests.get("correlations", {}).get("results", []):
        variables = row.get("variables", [])
        if isinstance(variables, list) and y in variables:
            for var in variables:
                if var != y and var in importance:
                    importance[var]["correlation"] = row.get("effect", {}).get("r")
                    p = row.get("p_value")
                    if p is not None:
                        importance[var]["best_p_value"] = p
                        importance[var]["test_type"] = "correlation"
    for family in ("t_tests", "anova"):
        for row in statistical_tests.get(family, {}).get("results", []):
            outcome = row.get("outcome")
            if outcome != y:
                continue
            group = row.get("group", "")
            if group in importance:
                p = row.get("p_value")
                existing = importance[group]["best_p_value"]
                if p is not None and (existing is None or p < existing):
                    importance[group]["best_p_value"] = p
                    importance[group]["test_type"] = family
    if model_results:
        primary = model_results[0][1] if model_results else {}
        coefficients = primary.get("coefficients", {})
        for var in x_vars:
            if var not in importance:
                continue
            imp = importance[var]
            if imp["best_p_value"] is not None:
                continue
            coeff = coefficients.get(var)
            if isinstance(coeff, dict) and coeff.get("p_value") is not None:
                imp["best_p_value"] = coeff["p_value"]
                imp["test_type"] = f"{primary_type}_coefficient" if primary_type else "model_coefficient"
    for var in x_vars:
        if var not in importance:
            continue
        imp = importance[var]
        corr = imp["correlation"]
        p = imp["best_p_value"]
        if corr is not None and abs(corr) >= 0.3:
            imp["strength"] = "strong"
        elif corr is not None and abs(corr) >= 0.1:
            imp["strength"] = "moderate"
        elif corr is not None:
            imp["strength"] = "weak"
        elif p is not None and p < 0.05:
            imp["strength"] = "significant (no correlation data)"
        else:
            imp["strength"] = ""
    return sorted(importance.values(), key=_importance_sort_key)


def _check_model_validity(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    cd = diag.get("cooks_distance", {})
    if isinstance(cd, dict):
        if cd.get("max") is None and cd.get("leverage_max") is not None:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_DIAGNOSTIC_ANOMALY",
                f"Model {model_id}: Cook's distance could not be computed. "
                f"Derived results (influence diagnostics) may be unreliable.",
                {"model_id": model_id, "leverage_max": cd.get("leverage_max")},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        if cd.get("leverage_max") is not None and float(cd["leverage_max"]) >= 1.0:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_OVERPARAMETERIZED",
                f"Model {model_id}: max leverage is {cd['leverage_max']:.4f}. "
                f"Model may be over-parameterized or contain near-singular design matrix.",
                {"model_id": model_id, "leverage_max": cd["leverage_max"]},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_overdispersion_issue(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    od = diag.get("overdispersion", {})
    if not isinstance(od, dict):
        return
    od_ratio = od.get("overdispersion_ratio")
    if od_ratio is not None and float(od_ratio) > 2.0:
        warning = od.get(
            "warning",
            f"Severe overdispersion detected (ratio={float(od_ratio):.2f}). "
            f"Poisson model is unreliable.",
        )
        issue_dicts.append(GuardrailIssue(
            Severity.WARNING,
            "OVERDISPERSION_DETECTED",
            warning,
            {
                "model_id": model_id,
                "overdispersion_ratio": float(od_ratio),
                "recommended_action": (
                    "Switch to Negative Binomial regression or use "
                    "robust standard errors."
                ),
            },
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
    zero_rate = od.get("zero_rate")
    if zero_rate is not None and float(zero_rate) > 0.5:
        od["zero_inflation_hint"] = (
            f"Outcome has {float(zero_rate):.0%} zeros. Consider comparing with "
            f"zero-inflated Poisson or hurdle model if zeros may arise from a separate process."
        )


_EXPOSURE_NAME_PATTERNS = (
    "exposure", "exposure_months", "policy_months", "person_years",
    "risk_time", "offset", "time_at_risk", "months", "years_at_risk",
)


def _detect_exposure_candidates(x_vars: list[str]) -> list[str]:
    """Detect column names that look like exposure/offset variables."""
    detected: list[str] = []
    for var in x_vars:
        var_lower = var.lower()
        if any(pat == var_lower or var_lower.endswith(f"_{pat}") or var_lower.startswith(f"{pat}_")
               for pat in _EXPOSURE_NAME_PATTERNS):
            detected.append(var)
    return detected


def _select_valid_exposure_col(
    frame: pd.DataFrame,
    exposure_candidates: list[str],
) -> str | None:
    """Return the first candidate that can validly be used as a GLM exposure."""
    for candidate in exposure_candidates:
        if candidate not in frame.columns:
            continue
        values = pd.to_numeric(frame[candidate], errors="coerce").dropna()
        if values.empty:
            continue
        if (values > 0).all():
            return candidate
    return None


_SUSPICIOUS_NAME_PATTERNS = {"noise", "random", "placebo", "check", "fake", "test"}


def _check_rare_event(
    frame: pd.DataFrame,
    y: str,
    model_type: str,
    n_predictors: int,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> dict[str, Any] | None:
    if model_type not in ("logit",):
        return None
    if y not in frame.columns:
        return None
    series = frame[y].dropna()
    if len(series) == 0:
        return None
    positive_rate = float(series.astype(float).mean())
    n_positive = int(positive_rate * len(series))
    epv = n_positive / max(n_predictors, 1)
    if positive_rate >= 0.05 and epv >= 5:
        return None
    reliability = "Low / exploratory only" if (positive_rate < 0.05 or epv < 5) else "Caution advised"
    issue_dicts.append(GuardrailIssue(
        Severity.WARNING if reliability.startswith("Low") else Severity.INFO,
        "RARE_EVENT_WARNING",
        f"The positive class for '{y}' accounts for {positive_rate:.1%} ({n_positive} of {len(series)}). "
        f"Events per predictor: {epv:.1f}. "
        f"Standard MLE Logit reliability is reduced. "
        f"Consider Firth penalized likelihood or exact logistic regression (not yet available in this MVP).",
        {"positive_rate": positive_rate, "n_positive": n_positive, "n_total": int(len(series)), "events_per_predictor": round(epv, 1)},
    ).to_dict())
    write_json(run_root / "errors.json", {"issues": issue_dicts})
    return {"reliability": reliability, "events_per_predictor": round(epv, 1), "positive_rate": positive_rate}


def _detect_binary_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    binary: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        unique = sorted(frame[var].dropna().unique())
        if len(unique) == 2:
            try:
                if set(unique) <= {0, 1, 0.0, 1.0, True, False}:
                    binary.add(var)
            except Exception:
                pass
    return binary


def _check_binary_correlations(
    frame: pd.DataFrame,
    binary_vars: set[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    """Check for highly correlated binary X variables and add INFO/WARNING issues."""
    binary_list = sorted(binary_vars)
    for i in range(len(binary_list)):
        for j in range(i + 1, len(binary_list)):
            var1, var2 = binary_list[i], binary_list[j]
            if var1 not in frame.columns or var2 not in frame.columns:
                continue
            col1 = frame[var1].astype(float)
            col2 = frame[var2].astype(float)
            r = col1.corr(col2)
            abs_r = abs(r)
            if pd.isna(r):
                continue
            evidence: dict[str, Any] = {
                "var1": var1, "var2": var2, "correlation": round(float(r), 4),
            }
            if abs_r > _BINARY_CORRELATION_WARN:
                severity = Severity.WARNING
                message = (
                    f"{var1} and {var2} are strongly correlated (r={r:.2f}). "
                    f"This may inflate standard errors. "
                    f"Consider removing or combining one."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            elif abs_r > _BINARY_CORRELATION_INFO:
                severity = Severity.INFO
                message = (
                    f"{var1} and {var2} are moderately correlated (r={r:.2f}). "
                    f"The model can still be used, but be cautious when interpreting "
                    f"individual binary coefficients."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            else:
                continue
            issue = GuardrailIssue(severity, "BINARY_CORRELATION", message, evidence)
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_treatment_proxy_correlations(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    treatment_vars = [
        var for var in x_vars
        if var in frame.columns and "treatment" in var.lower()
    ]
    proxy_vars = [
        var for var in x_vars
        if var in frame.columns
        and any(token in var.lower() for token in ("proxy", "interaction"))
    ]
    for treatment in treatment_vars:
        for proxy in proxy_vars:
            if treatment == proxy:
                continue
            pair = frame[[treatment, proxy]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(pair) < 3:
                continue
            r = pair[treatment].corr(pair[proxy])
            if pd.isna(r) or abs(r) <= _TREATMENT_PROXY_CORRELATION_WARN:
                continue
            issue = GuardrailIssue(
                Severity.WARNING,
                "TREATMENT_PROXY_CORRELATION",
                f"{treatment} and {proxy} are highly correlated (r={r:.3f}). "
                "Interpret their coefficients jointly; individual treatment-effect "
                "interpretation may be unstable.",
                {
                    "treatment": treatment,
                    "proxy": proxy,
                    "correlation": round(float(r), 4),
                    "action_suggestions": [
                        "Compare models with and without the proxy term.",
                        "Interpret treatment and proxy coefficients jointly.",
                    ],
                },
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _detect_suspicious_vars(x_vars: list[str]) -> set[str]:
    suspicious: set[str] = set()
    for var in x_vars:
        name_lower = var.lower()
        for pattern in _SUSPICIOUS_NAME_PATTERNS:
            if pattern in name_lower:
                suspicious.add(var)
                break
    return suspicious


def _coerce_x_columns_to_numeric(
    frame: pd.DataFrame,
    x_vars: list[str],
    run_root: Path,
) -> list[dict[str, Any]]:
    """Coerce X columns from datetime/object to numeric if appropriate.

    Returns a list of coercion action dicts and writes a summary artifact.
    """
    heuristics = {
        "year", "month", "age", "miles", "density", "score", "count",
        "claims", "days", "number", "num", "amount", "rate", "price",
        "cost", "value", "size", "weight", "volume", "sum",
    }
    actions: list[dict[str, Any]] = []
    for var in x_vars:
        if var not in frame.columns:
            continue
        if pd.api.types.is_numeric_dtype(frame[var]):
            continue
        is_likely_numeric = any(pat in var.lower() for pat in heuristics)
        threshold = 0.80 if is_likely_numeric else 0.90
        numeric = pd.to_numeric(frame[var], errors="coerce")
        good = numeric.notna().sum()
        total = len(numeric)
        if total > 0 and (good / total) >= threshold:
            original_dtype = str(frame[var].dtype)
            frame[var] = numeric
            actions.append({
                "column": var,
                "original_dtype": original_dtype,
                "conversion_rate": round(good / total, 4),
            })
    if actions:
        path = run_root / "staged" / "x_coercion_summary.json"
        write_json(path, {"coerced_columns": actions})
        try:
            register_artifact(
                run_root,
                "x_coercion_summary",
                path,
                "metadata",
                "cleaning",
                ["cleaned_dataset"],
            )
        except Exception:
            pass
    return actions


def _check_suspicious_dtypes(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    x_set = set(x_vars)
    for col in frame.columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[col]):
            continue
        nunique = int(frame[col].nunique())
        is_x = col in x_set
        severity = Severity.WARNING if is_x else Severity.INFO
        if nunique <= 5:
            issue = GuardrailIssue(
                severity,
                "SUSPICIOUS_DTYPE",
                f"Column '{col}' has datetime dtype with only {nunique} unique value(s). "
                f"It may be a binary/categorical variable misread as datetime. "
                f"{'It is used as a predictor — verify its dtype.' if is_x else 'Verify before using it as a predictor.'}",
                {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique, "is_x": is_x},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        elif is_x and nunique > 5:
            numeric = pd.to_numeric(frame[col], errors="coerce")
            good = numeric.notna().sum()
            total = len(numeric)
            if total > 0 and (good / total) >= 0.9:
                frame[col] = numeric
                issue = GuardrailIssue(
                    Severity.INFO,
                    "COERCED_X_DTYPE",
                    f"Column '{col}' was datetime dtype with {nunique} unique values; "
                    f"auto-coerced to numeric ({good}/{total}, {good/total:.0%} conversion rate).",
                    {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique},
                )
                issue_dicts.append(issue.to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})


_CATEGORICAL_NAME_PATTERNS = {"code", "region", "category", "group", "type", "class", "level", "tier", "rank"}


def _detect_categorical_x_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    """Detect X variables that should use C() encoding in the model formula.

    Name-suggestive numeric columns with 3-20 unique values and non-numeric
    columns with 2-20 unique values are flagged as categorical. Binary 0/1
    columns are excluded since they are handled by _detect_binary_vars.
    """
    categorical: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        series = frame[var].dropna()
        if len(series) < 2:
            continue
        nunique = int(series.nunique())
        if nunique > 20 or nunique >= len(series):
            continue
        name_lower = str(var).lower()
        name_suggests_category = any(
            pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS
        )
        if pd.api.types.is_numeric_dtype(series):
            if nunique >= 3 and name_suggests_category:
                categorical.add(var)
        else:
            if nunique >= 2:
                categorical.add(var)
    return categorical


def _check_categorical_candidates(
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    encoded_categorical_vars: set[str] | None = None,
) -> None:
    """Report categorical handling using the final model preprocessing state."""
    encoded = encoded_categorical_vars or set()
    for col in sorted(encoded):
        col_str = str(col)
        if col_str not in frame.columns:
            continue
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "CATEGORICAL_AUTO_DUMMY_CODED",
                f"Column '{col_str}' was detected as categorical and automatically dummy-coded.",
                {"column": col_str, "preprocessing": "dummy_coded"},
            ).to_dict()
        )
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    for col in frame.columns:
        col_str = str(col)
        if col_str in encoded:
            continue
        name_lower = col_str.lower()
        if not any(pat in name_lower for pat in _CATEGORICAL_NAME_PATTERNS):
            continue
        nunique = int(frame[col].nunique())
        if 1 < nunique <= 10:
            issue_dicts.append(
                GuardrailIssue(
                    Severity.INFO,
                    "CATEGORICAL_CANDIDATE",
                    f"Column '{col_str}' may be categorical ({nunique} unique values). Consider one-hot encoding.",
                    {"column": col_str, "nunique": nunique},
                ).to_dict()
            )
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _importance_sort_key(item: dict[str, Any]) -> float:
    p = item.get("best_p_value")
    if p is None:
        return 2.0
    return float(p)


def _build_descriptive_stats(frame: pd.DataFrame, *, categorical_vars: set[str] | None = None) -> list[dict[str, Any]]:
    cat_set = categorical_vars or set()
    stats: list[dict[str, Any]] = []
    for column in frame.columns:
        col_str = str(column)
        series = frame[column]
        present = int(series.notna().sum())
        total = len(series)
        row: dict[str, Any] = {
            "column": col_str,
            "dtype": str(series.dtype),
            "count": present,
            "missing": total - present,
            "missing_rate": round((total - present) / total, 4) if total > 0 else 0.0,
            "unique_count": int(series.nunique()),
        }
        is_categorical = col_str in cat_set
        if pd.api.types.is_numeric_dtype(series) and not is_categorical:
            row["mean"] = round(float(series.mean()), 4)
            row["std"] = round(float(series.std()), 4)
            row["min"] = round(float(series.min()), 4)
            row["max"] = round(float(series.max()), 4)
        else:
            row["mean"] = None
            row["std"] = None
            row["min"] = None
            row["max"] = None
            if is_categorical:
                row["note"] = "categorical — mean/std not meaningful"
        stats.append(row)
    return stats


def _parse_dropped_var_entry(entry: str) -> dict[str, str]:
    """Parse a dropped-variable string like 'x4 (dropped due to zero variance)'.

    Returns {'variable': 'x4', 'reason': 'dropped_due_to_zero_variance'}.
    Handles edge cases: no parentheses, nested parens, empty string.
    """
    entry = entry.strip()
    if not entry:
        return {"variable": "", "reason": "unknown"}
    # Find the last " (" to split variable name from reason.
    # Using rfind avoids problems with variable names containing " (".
    idx = entry.rfind(" (")
    if idx == -1 or not entry.endswith(")"):
        return {"variable": entry, "reason": "unknown"}
    var_name = entry[:idx]
    reason_text = entry[idx + 2:-1]  # strip " (" prefix and ")" suffix
    normalized_reason = reason_text.strip().replace(" ", "_").lower()
    return {"variable": var_name, "reason": normalized_reason}


def _check_dropped_variables(
    x_vars: list[str],
    model_results: list[tuple[str, dict[str, Any]]],
    frame: pd.DataFrame,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
    categorical_vars: set[str] | None = None,
) -> list[str]:
    """Check for user-specified X variables dropped from the model silently.

    Respects C()-encoded categorical variables whose terms appear as
    C(Q('var'))[T.val] in the coefficient names rather than bare 'var'.

    Returns a list of human-readable strings like "x4 (dropped due to zero variance)".
    """
    if categorical_vars is None:
        categorical_vars = set()

    if not model_results:
        return []

    primary_result = model_results[0][1]
    coefficients = primary_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return []

    def _in_coefficients(var: str) -> bool:
        if var in coefficients:
            return True
        if var in categorical_vars:
            # Check for C(Q('var'))[T.*] or C(Q("var"))[T.*] pattern
            sq = f"C(Q('{var}'))[T."
            dq = f'C(Q("{var}"))[T.'
            for cterm in coefficients:
                if isinstance(cterm, str) and (sq in cterm or dq in cterm):
                    return True
        return False

    dropped: list[str] = []
    for var in x_vars:
        if _in_coefficients(var):
            continue
        if var not in frame.columns:
            reason = "dropped due to all-missing after cleaning"
        elif frame[var].isna().all():
            reason = "dropped due to all-missing after cleaning"
        elif frame[var].nunique() <= 1:
            reason = "dropped due to zero variance"
        elif var in categorical_vars:
            # C()-encoded but not in coefficients — likely collinear categories
            reason = "dropped due to perfect collinearity (categories may overlap with other predictors)"
        else:
            reason = "dropped due to perfect collinearity"

        dropped.append(f"{var} ({reason})")
        issue_dicts.append(
            GuardrailIssue(
                Severity.INFO,
                "VARIABLE_DROPPED",
                f"Variable '{var}' was {reason}.",
                {"variable": var, "reason": reason},
            ).to_dict()
        )

    if dropped:
        write_json(run_root / "errors.json", {"issues": issue_dicts})

    return dropped
