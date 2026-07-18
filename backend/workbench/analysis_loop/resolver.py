"""Read-only resolution of persisted OLS source facts for the golden flow."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import read_json
from ..lineage.run_inputs import read_run_inputs
from ..services.results_service import read_model_results, validate_result_contract
from .contracts import SourceRunContract
from .preflight import validate_source_contract


class AnalysisLoopSourceResolutionError(ValueError):
    """A persisted source cannot be converted into a trusted flow input."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedAnalysisLoopInputs:
    """Facts resolved from one immutable source run and its model input."""

    source: SourceRunContract
    model_row_ids: tuple[str, ...]
    cluster_values: tuple[Any, ...]
    model_input_artifact: str


def _run_root(project_root: Path | str, run_id: str) -> Path:
    root = Path(project_root).expanduser().resolve()
    runs_root = (root / "runs").resolve()
    candidate = (runs_root / run_id).resolve()
    try:
        candidate.relative_to(runs_root)
    except ValueError as exc:
        raise AnalysisLoopSourceResolutionError(
            "source run is outside the project runs directory",
            code="SOURCE_RUN_INVALID",
        ) from exc
    if not candidate.is_dir():
        raise AnalysisLoopSourceResolutionError(
            "source run directory is missing",
            code="SOURCE_RUN_NOT_FOUND",
        )
    return candidate


def _read_result(run_root: Path) -> dict[str, Any]:
    try:
        results = read_model_results(run_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisLoopSourceResolutionError(
            "source result artifacts cannot be read",
            code="SOURCE_RESULT_ARTIFACT_MISSING",
        ) from exc
    candidates: list[dict[str, Any]] = []
    for result in results:
        if result.get("model") == "ols":
            candidates.append(result)
    if len(candidates) != 1:
        raise AnalysisLoopSourceResolutionError(
            "exactly one OLS result contract is required",
            code="SOURCE_CONTRACT_UNSUPPORTED",
        )
    result = candidates[0]
    try:
        return validate_result_contract(result)
    except (TypeError, ValueError) as exc:
        raise AnalysisLoopSourceResolutionError(
            "source OLS result contract is unsupported",
            code="SOURCE_CONTRACT_UNSUPPORTED",
        ) from exc


def _read_source_contract(project_root: Path | str, run_id: str) -> tuple[Path, SourceRunContract, dict[str, Any]]:
    run_root = _run_root(project_root, run_id)
    try:
        manifest = read_json(run_root / "run_manifest.json")
        run_inputs = read_run_inputs(run_root)
        result = _read_result(run_root)
    except AnalysisLoopSourceResolutionError:
        raise
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisLoopSourceResolutionError(
            "source run is missing a required persisted contract",
            code="SOURCE_CONTRACT_UNSUPPORTED",
        ) from exc
    if not isinstance(manifest, dict) or not isinstance(run_inputs, dict):
        raise AnalysisLoopSourceResolutionError(
            "source run manifest or inputs are malformed",
            code="SOURCE_CONTRACT_UNSUPPORTED",
        )
    sample = result.get("analysis_sample")
    row_order = sample.get("row_order") if isinstance(sample, dict) else None
    stable_ids = result.get("stable_result_ids")
    if (
        not isinstance(row_order, list)
        or any(type(value) is not str or not value for value in row_order)
        or not isinstance(stable_ids, list)
    ):
        raise AnalysisLoopSourceResolutionError(
            "source analysis sample or result IDs are not stable",
            code="SOURCE_ANALYSIS_ROWS_UNSTABLE",
        )
    lineage = run_inputs.get("source_lineage")
    if not isinstance(lineage, dict):
        lineage = {
            "source_run_id": run_inputs.get("rerun_of"),
            "from_node": run_inputs.get("from_node"),
        }
    source = SourceRunContract(
        run_id=run_id,
        status=str(manifest.get("status") or "unknown"),
        model="ols",
        covariance=str(result.get("covariance") or result.get("covariance_wire") or ""),
        result_artifact=result,
        run_inputs=run_inputs,
        lineage=lineage,
        contract_version=result.get("contract_version"),
        result_ids=tuple(stable_ids),
        primary_estimand=(
            result.get("primary_estimand")
            if isinstance(result.get("primary_estimand"), dict)
            else None
        ),
        result_labels={
            str(coefficient.get("result_id")): str(
                coefficient.get("display_name") or coefficient.get("term") or result_id
            )
            for result_id, coefficient in (result.get("coefficients") or {}).items()
            if isinstance(coefficient, dict) and isinstance(coefficient.get("result_id"), str)
        },
        dataset_schema={
            "y_column": result.get("y_column"),
            "x_columns": result.get("x_columns", []),
            "analysis_sample_fingerprint": result.get("analysis_sample_fingerprint"),
        },
        analysis_row_ids=tuple(row_order),
    )
    return run_root, source, result


def _model_input_path(run_root: Path, result: dict[str, Any]) -> tuple[str, Path]:
    declared = result.get("dataset_snapshot")
    artifact_id = declared.get("model_input_artifact") if isinstance(declared, dict) else None
    if not isinstance(artifact_id, str) or not artifact_id:
        try:
            index = read_json(run_root / "artifacts_index.json")
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            index = {}
        for record in index.get("artifacts", []) if isinstance(index, dict) else []:
            if not isinstance(record, dict) or record.get("artifact_id") != "ols_1":
                continue
            inputs = record.get("inputs")
            if isinstance(inputs, list):
                artifact_id = next(
                    (item for item in inputs if item in {"cleaned_dataset", "imputed_dataset"}),
                    None,
                )
                if artifact_id:
                    break
    if not isinstance(artifact_id, str) or not artifact_id:
        for candidate_id in ("imputed_dataset", "cleaned_dataset"):
            candidate = run_root / "processed" / f"{candidate_id}.parquet"
            if candidate.is_file():
                artifact_id = candidate_id
                break
    if not isinstance(artifact_id, str) or not artifact_id:
        raise AnalysisLoopSourceResolutionError(
            "the model input artifact cannot be resolved",
            code="SOURCE_DATASET_ARTIFACT_MISSING",
        )
    path = (run_root / "processed" / f"{artifact_id}.parquet").resolve()
    try:
        path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise AnalysisLoopSourceResolutionError(
            "the model input artifact resolved outside the source run",
            code="SOURCE_DATASET_ARTIFACT_INVALID",
        ) from exc
    if not path.is_file():
        raise AnalysisLoopSourceResolutionError(
            "the model input artifact is missing",
            code="SOURCE_DATASET_ARTIFACT_MISSING",
        )
    return artifact_id, path


def resolve_analysis_loop_inputs(
    project_root: Path | str,
    *,
    run_id: str,
    cluster_variable: str,
) -> ResolvedAnalysisLoopInputs:
    """Resolve source, analysis rows and exact cluster values without writes."""

    if type(cluster_variable) is not str or not cluster_variable:
        raise AnalysisLoopSourceResolutionError(
            "cluster_variable must be a non-empty exact string",
            code="CLUSTER_VARIABLE_REQUIRED",
        )
    run_root, source, result = _read_source_contract(project_root, run_id)
    artifact_id, path = _model_input_path(run_root, result)
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as exc:
        raise AnalysisLoopSourceResolutionError(
            "the model input artifact cannot be read",
            code="SOURCE_DATASET_ARTIFACT_INVALID",
        ) from exc
    if cluster_variable not in frame.columns:
        raise AnalysisLoopSourceResolutionError(
            "cluster_variable is not an exact model-input column",
            code="CLUSTER_VARIABLE_NOT_FOUND",
        )
    source = replace(
        source,
        dataset_schema={
            "columns": {
                str(column): {"dtype": str(frame[column].dtype)}
                for column in frame.columns
            }
        },
    )
    validation = validate_source_contract(source)
    if not validation.valid:
        raise AnalysisLoopSourceResolutionError(
            "source run does not satisfy the OLS golden-flow contract",
            code=validation.code,
        )
    positions: list[int] = []
    by_id = {str(index): position for position, index in enumerate(frame.index)}
    for row_id in source.analysis_row_ids:
        if row_id in by_id:
            positions.append(by_id[row_id])
            continue
        if row_id.startswith("position:"):
            try:
                position = int(row_id.removeprefix("position:"))
            except ValueError:
                position = -1
            if 0 <= position < len(frame):
                positions.append(position)
                continue
        raise AnalysisLoopSourceResolutionError(
            "source analysis row IDs cannot be aligned to the model input artifact",
            code="SOURCE_ANALYSIS_ROWS_UNRESOLVED",
        )
    values = tuple(frame.iloc[positions][cluster_variable].tolist())
    if len(values) != len(source.analysis_row_ids):
        raise AnalysisLoopSourceResolutionError(
            "cluster vector is not aligned to the source analysis rows",
            code="CLUSTER_ROW_ALIGNMENT_INVALID",
        )
    return ResolvedAnalysisLoopInputs(
        source=source,
        model_row_ids=source.analysis_row_ids,
        cluster_values=values,
        model_input_artifact=artifact_id,
    )


__all__ = [
    "AnalysisLoopSourceResolutionError",
    "ResolvedAnalysisLoopInputs",
    "resolve_analysis_loop_inputs",
]
