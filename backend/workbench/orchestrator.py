from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .cleaning import clean_frame, normalize_column_name
from .config import load_config
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

    frames = ingest_files([Path(path) for path in input_files], run.root, config)
    schema = infer_schema("dataset_1", frames, run.root)
    frame = next(iter(frames.values()))

    cleaned, actions = clean_frame(frame, list(schema.time_candidates))
    write_json(run.root / "processed" / "cleaning_actions.json", {"actions": actions})
    cleaned_path = run.root / "processed" / "cleaned_dataset.parquet"
    cleaned.to_parquet(cleaned_path, index=False)
    register_artifact(
        run.root,
        "cleaned_dataset",
        cleaned_path,
        "processed_data",
        "cleaning",
        [f"raw_{path.name}" for path in input_files],
    )

    profile = profile_frame(cleaned)
    write_json(run.root / "staged" / "data_profile.json", profile)

    issues = validate_profile(profile, config)
    warnings = [issue.to_dict() for issue in issues]
    write_json(run.root / "errors.json", {"issues": warnings})
    if has_blockers(issues):
        _write_manifest(run.root, run.run_id, mode, "blocked", _lineage(input_files))
        return {"run_id": run.run_id, "status": "blocked"}

    time_candidates = _normalized_existing(schema.time_candidates, cleaned)
    id_candidates = _normalized_existing(schema.id_candidates, cleaned)
    routing = classify_dataset(cleaned, id_candidates, time_candidates)
    write_json(run.root / "staged" / "analysis_router.json", routing)

    normalized_y = normalize_column_name(y)
    normalized_x = [normalize_column_name(column) for column in x]
    model_result = run_ols(
        cleaned,
        y=normalized_y,
        x=normalized_x,
        robust=True,
        model_id="regression_1",
    )
    model_path = run.root / "model_results" / "regression_1.json"
    write_json(model_path, model_result)
    register_artifact(
        run.root,
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
        run.root,
        numeric_columns=numeric_columns,
        time_column=time_candidates[0] if time_candidates else None,
    )

    claims = build_claims([model_result], warnings)
    report = {
        "title": "Econometrics Report",
        "facts": [
            f"Rows: {profile['row_count']}",
            f"Columns: {profile['column_count']}",
            f"Dataset kind: {routing['kind']}",
        ],
        "claims": claims,
        "warnings": warnings,
    }
    render_html_report(report, run.root)
    export_pdf(report, run.root)
    export_xlsx({"coefficients": _coefficient_rows(model_result)}, run.root)

    _write_manifest(run.root, run.run_id, mode, "completed", _lineage(input_files))
    return {"run_id": run.run_id, "status": "completed"}


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
