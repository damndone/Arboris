from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .artifacts import register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
from .domain import GuardrailIssue, Severity
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
    sheet_name: str | None = None,
    transpose: bool = False,
) -> dict[str, str]:
    _s = on_step  # shorthand

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
    stat_analysis_columns = [normalized_y, *normalized_x]
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
    try:
        if y_type == "binary":
            primary, primary_fitted = run_logit(cleaned, y=normalized_y, x=normalized_x, model_id="logit_1")
            _write_model_result(run_root, "logit_1", primary)
            model_results.append(("logit_1", primary))
            fitted_models["logit_1"] = primary_fitted
        elif y_type == "count":
            primary, primary_fitted = run_poisson(cleaned, y=normalized_y, x=normalized_x, model_id="poisson_1")
            _write_model_result(run_root, "poisson_1", primary)
            model_results.append(("poisson_1", primary))
            fitted_models["poisson_1"] = primary_fitted
        else:
            primary, primary_fitted = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1")
            _write_model_result(run_root, "ols_1", primary)
            model_results.append(("ols_1", primary))
            fitted_models["ols_1"] = primary_fitted
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
        ols_result, ols_fitted = run_ols(cleaned, y=normalized_y, x=normalized_x, robust=True, model_id="ols_1")
        _write_model_result(run_root, "ols_1", ols_result)
        model_results.append(("ols_1", ols_result))
        fitted_models["ols_1"] = ols_fitted

    if _s: _s("diagnostics", "start", "Running regression diagnostics...")
    exog = cleaned[normalized_x] if normalized_x else pd.DataFrame(index=cleaned.index)
    diagnostic_artifacts: dict[str, dict[str, Any]] = {}
    for model_id, fitted in fitted_models.items():
        result_dict = dict(model_results)
        model_type = next(
            (r.get("model_type", "ols") for mid, r in model_results if mid == model_id),
            "ols",
        )
        family = "ols" if model_type in ("ols", "ols_robust", "fixed_effects") else model_type
        diag = compute_diagnostics(fitted, exog, model_id, model_family=family)
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
    suspicious_vars = _detect_suspicious_vars(normalized_x)
    claims = build_claims(
        [result for _, result in model_results], issue_dicts,
        binary_vars=binary_vars, suspicious_vars=suspicious_vars,
    )
    if _s: _s("narrative", "complete", f"Built {len(claims)} claims")
    _check_suspicious_dtypes(cleaned, normalized_x, issue_dicts, run_root)
    descriptive_stats = _build_descriptive_stats(cleaned)
    model_family_display = {"ols": "OLS", "ols_robust": "OLS (robust SE)", "logit": "Logit", "poisson": "Poisson"}
    primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
    report = {
        "title": "Econometrics Report",
        "facts": [
            f"Model: {model_family_display.get(primary_type, primary_type)}",
            f"y = {normalized_y};  X = {', '.join(normalized_x)}",
            f"Rows used: {profile['row_count']} · Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ],
        "claims": claims,
        "warnings": issue_dicts,
        "descriptive_stats": descriptive_stats,
        "statistical_tests": statistical_test_summaries,
        "variable_importance": _build_variable_importance(
            statistical_tests, normalized_y, normalized_x, model_results,
            cleaned,
        ),
        "diagnostics": diagnostic_artifacts,
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
) -> list[dict[str, Any]]:
    importance: dict[str, dict[str, Any]] = {}
    for var in x_vars:
        importance[var] = {
            "variable": var, "correlation": None, "best_p_value": None, "test_type": None
        }
    if frame is not None:
        cols = [y] + [v for v in x_vars if v in frame.columns]
        if len(cols) >= 2:
            corr = frame[cols].corr(numeric_only=True)
            if y in corr.columns:
                for var in x_vars:
                    if var in corr.columns:
                        c = corr[y].get(var)
                        if pd.notna(c):
                            importance[var]["correlation"] = round(float(c), 3)
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
            imp = importance[var]
            if imp["best_p_value"] is not None:
                continue
            coeff = coefficients.get(var)
            if isinstance(coeff, dict) and coeff.get("p_value") is not None:
                imp["best_p_value"] = coeff["p_value"]
                imp["test_type"] = "ols_coefficient"
    for var in x_vars:
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


_SUSPICIOUS_NAME_PATTERNS = {"noise", "random", "placebo", "check", "fake", "test"}


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


def _detect_suspicious_vars(x_vars: list[str]) -> set[str]:
    suspicious: set[str] = set()
    for var in x_vars:
        name_lower = var.lower()
        for pattern in _SUSPICIOUS_NAME_PATTERNS:
            if pattern in name_lower:
                suspicious.add(var)
                break
    return suspicious


def _check_suspicious_dtypes(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    for col in frame.columns:
        if col in x_vars:
            continue
        if pd.api.types.is_datetime64_any_dtype(frame[col]):
            nunique = int(frame[col].nunique())
            if nunique <= 5:
                issue = GuardrailIssue(
                    Severity.INFO,
                    "SUSPICIOUS_DTYPE",
                    f"Column '{col}' has datetime dtype with only {nunique} unique value(s). "
                    f"It may be a binary/categorical variable misread as datetime. "
                    f"Verify before using it as a predictor.",
                    {"column": col, "dtype": str(frame[col].dtype), "nunique": nunique},
                )
                issue_dicts.append(issue.to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})


def _importance_sort_key(item: dict[str, Any]) -> float:
    p = item.get("best_p_value")
    if p is None:
        return 2.0
    return float(p)


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
