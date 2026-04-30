from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
from .domain import GuardrailIssue, Severity
from .econometrics.runner import run_ols
from .exports import export_pdf, export_xlsx
from .ingestion import ingest_files
from .metadata import infer_schema
from .narrative import build_claims
from .profiling import profile_frame
from .projects import create_run
from .reporting import render_html_report
from .router import classify_dataset
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

    try:
        return _run_workflow(run.root, run.run_id, input_files, mode, y, x, config)
    except Exception as exc:
        issue = GuardrailIssue(
            Severity.BLOCKER,
            "WORKFLOW_FAILED",
            "Workflow failed before completion.",
            {"error": str(exc)},
        )
        write_json(run.root / "errors.json", {"issues": [issue.to_dict()]})
        _write_manifest(run.root, run.run_id, mode, "failed", _lineage(input_files))
        raise


def _run_workflow(
    run_root: Path,
    run_id: str,
    input_files: list[Path],
    mode: str,
    y: str,
    x: list[str],
    config: Any,
) -> dict[str, str]:
    frames = ingest_files([Path(path) for path in input_files], run_root, config)
    schema = infer_schema("dataset_1", frames, run_root)
    frame = next(iter(frames.values()))

    cleaned, actions = clean_frame(frame, list(schema.time_candidates))
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

    profile = profile_frame(cleaned)
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

    issues = validate_profile(profile, config)
    issue_dicts = [issue.to_dict() for issue in issues]
    write_json(run_root / "errors.json", {"issues": issue_dicts})
    if has_blockers(issues):
        _write_manifest(run_root, run_id, mode, "blocked", _lineage(input_files))
        return {"run_id": run_id, "status": "blocked"}

    time_candidates = _normalized_existing(schema.time_candidates, cleaned)
    id_candidates = _normalized_existing(schema.id_candidates, cleaned)
    routing = classify_dataset(cleaned, id_candidates, time_candidates)
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

    normalized_y = normalize_column_name(y)
    normalized_x = [normalize_column_name(column) for column in x]
    model_issue = _model_column_issue(cleaned, normalized_y, normalized_x, y, x)
    if model_issue is not None:
        issue_dicts.append(model_issue.to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
        _write_manifest(run_root, run_id, mode, "blocked", _lineage(input_files))
        return {"run_id": run_id, "status": "blocked"}

    model_result = run_ols(
        cleaned,
        y=normalized_y,
        x=normalized_x,
        robust=True,
        model_id="regression_1",
    )
    model_path = run_root / "model_results" / "regression_1.json"
    write_json(model_path, model_result)
    register_artifact(
        run_root,
        "regression_1",
        model_path,
        "model_result",
        "econometrics",
        ["cleaned_dataset"],
    )

    numeric_columns = [
        str(column)
        for column in cleaned.select_dtypes(include="number").columns
    ]
    create_figures(
        cleaned,
        run_root,
        numeric_columns=numeric_columns,
        time_column=time_candidates[0] if time_candidates else None,
    )

    claims = build_claims([model_result], issue_dicts)
    report = {
        "title": "Econometrics Report",
        "facts": [
            f"Rows: {profile['row_count']}",
            f"Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ],
        "claims": claims,
        "warnings": issue_dicts,
    }
    render_html_report(report, run_root)
    export_pdf(report, run_root)
    export_xlsx({"coefficients": _coefficient_rows(model_result)}, run_root)

    _write_manifest(run_root, run_id, mode, "completed", _lineage(input_files))
    return {"run_id": run_id, "status": "completed"}


def _normalized_existing(candidates: tuple[str, ...], frame: pd.DataFrame) -> list[str]:
    columns = set(frame.columns)
    return [
        normalized
        for candidate in candidates
        if (normalized := normalize_column_name(candidate)) in columns
    ]


def _coefficient_rows(model_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coefficients = model_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return rows
    for term, values in coefficients.items():
        if isinstance(values, dict):
            rows.append({"term": term, **values})
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
) -> None:
    write_json(
        run_root / "run_manifest.json",
        {"run_id": run_id, "mode": mode, "status": status, "lineage": lineage},
    )
