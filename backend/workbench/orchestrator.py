from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .artifacts import register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
from .domain import GuardrailIssue, Severity
from .econometrics.runner import (
    run_fixed_effects,
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
    CATEGORY_MAX_UNIQUE,
    run_statistical_tests,
    summarize_statistical_tests,
    write_statistical_test_artifacts,
)
from .validation import has_blockers, validate_profile
from .visualization import create_figures


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
        )
        raise


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
) -> dict[str, str]:
    _s = on_step  # shorthand

    if _s: _s("ingestion", "start", "Ingesting files...")
    frames = ingest_files([Path(path) for path in input_files], run_root, config)
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
    if model_type != "auto":
        y_type = _map_model_type(model_type)
    elif normalized_y in cleaned.columns:
        y_type = detect_y_kind(cleaned, normalized_y).value
    else:
        y_type = "continuous"
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
        return {"run_id": run_id, "status": "blocked"}
    if _s: _s("model_check", "complete", "Model columns valid")

    if _s:
        _s("statistical_tests", "start", "Running statistical tests...")
    stat_analysis_columns = [normalized_y, *normalized_x, *_extra_categorical_columns(
        cleaned, {normalized_y, *normalized_x},
    )]
    statistical_tests = run_statistical_tests(
        cleaned,
        analysis_columns=stat_analysis_columns,
    )
    write_statistical_test_artifacts(run_root, statistical_tests)
    statistical_test_summaries = summarize_statistical_tests(statistical_tests)
    if _s:
        _s("statistical_tests", "complete", "Statistical tests completed")

    model_results: list[tuple[str, dict[str, Any]]] = []

    if _s: _s("estimation", "start", f"Fitting {y_type} model (y type: {y_type})...")
    try:
        if y_type == "binary":
            primary = run_logit(cleaned, y=normalized_y, x=normalized_x, model_id="logit_1")
            _write_model_result(run_root, "logit_1", primary)
            model_results.append(("logit_1", primary))
        elif y_type == "count":
            primary = run_poisson(cleaned, y=normalized_y, x=normalized_x, model_id="poisson_1")
            _write_model_result(run_root, "poisson_1", primary)
            model_results.append(("poisson_1", primary))
        else:
            primary = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1")
            _write_model_result(run_root, "ols_1", primary)
            model_results.append(("ols_1", primary))
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
        # Fall back to OLS
        ols_result = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1")
        _write_model_result(run_root, "ols_1", ols_result)
        model_results.append(("ols_1", ols_result))

    # Fixed effects only for continuous y with panel data
    if routing["kind"] == "panel" and id_candidates and y_type == "continuous":
        if _s:
            _s("estimation", "start", "Attempting fixed effects...")
        try:
            fe_result = run_fixed_effects(
                cleaned,
                y=normalized_y,
                x=normalized_x,
                entity=id_candidates[0],
                time=time_candidates[0] if time_candidates else None,
                model_id="fe_1",
            )
            _write_model_result(run_root, "fe_1", fe_result)
            model_results.append(("fe_1", fe_result))
        except Exception:
            fe_issue = GuardrailIssue(
                Severity.WARNING,
                "FE_ESTIMATION_FAILED",
                "Fixed effects estimation failed; results include primary model only.",
                {"y": normalized_y, "x": normalized_x},
            )
            issue_dicts.append(fe_issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            if _s:
                _s("estimation", "complete", "FE failed, primary model retained")
    elif routing["kind"] == "panel" and not id_candidates:
        panel_issue = GuardrailIssue(
            Severity.WARNING,
            "PANEL_NO_ENTITY",
            "Panel dataset detected but no entity identifier available; running primary model only.",
            {"kind": routing["kind"]},
        )
        issue_dicts.append(panel_issue.to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})

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
    claims = build_claims([result for _, result in model_results], issue_dicts)
    if _s: _s("narrative", "complete", f"Built {len(claims)} claims")
    descriptive_stats = _build_descriptive_stats(cleaned)
    report = {
        "title": "Econometrics Report",
        "facts": [
            f"Rows: {profile['row_count']}",
            f"Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ],
        "claims": claims,
        "warnings": issue_dicts,
        "descriptive_stats": descriptive_stats,
        "statistical_tests": statistical_test_summaries,
    }
    if _s: _s("reporting", "start", "Rendering report...")
    render_html_report(report, run_root)
    if _s: _s("reporting", "complete", "Rendered HTML report")

    if _s: _s("export", "start", "Exporting files...")
    export_pdf(report, run_root)
    export_xlsx(
        {"coefficients": _coefficient_rows_for_models(model_results)},
        run_root,
    )
    if _s: _s("export", "complete", "Exported PDF and XLSX")

    _write_manifest(
        run_root,
        run_id,
        mode,
        "completed",
        _lineage(input_files),
        started_at=started_at,
        y=y,
        x=x,
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
    if not isinstance(coefficients, dict):
        return rows
    for term, values in coefficients.items():
        if isinstance(values, dict):
            rows.append({"term": term, **values})
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
) -> None:
    write_json(
        run_root / "run_manifest.json",
        {
            "run_id": run_id,
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "y": y,
            "x": list(x),
            "lineage": lineage,
        },
    )


def _extra_categorical_columns(
    frame: pd.DataFrame, existing: set[str],
) -> list[str]:
    extras: list[str] = []
    for column in frame.columns:
        col_str = str(column)
        if col_str in existing:
            continue
        series = frame[column]
        nunique = int(series.dropna().nunique())
        if nunique < 2 or nunique > CATEGORY_MAX_UNIQUE:
            continue
        if pd.api.types.is_numeric_dtype(series):
            if nunique < int(series.dropna().shape[0]):
                extras.append(col_str)
        else:
            extras.append(col_str)
    return extras


_MODEL_TYPE_MAP = {"ols": "continuous", "logit": "binary", "poisson": "count"}


def _map_model_type(model_type: str) -> str:
    y_type = _MODEL_TYPE_MAP.get(model_type)
    if y_type is None:
        return "continuous"
    return y_type


def _build_descriptive_stats(frame: pd.DataFrame) -> list[dict[str, Any]]:
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
        if pd.api.types.is_numeric_dtype(series):
            row["mean"] = round(float(series.mean()), 4)
            row["std"] = round(float(series.std()), 4)
            row["min"] = round(float(series.min()), 4)
            row["max"] = round(float(series.max()), 4)
        else:
            row["mean"] = None
            row["std"] = None
            row["min"] = None
            row["max"] = None
        stats.append(row)
    return stats
