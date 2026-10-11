"""Figures: bounded read-only context projection."""

from __future__ import annotations
import json
import math
from pathlib import Path
import re
from typing import Any
from ...artifacts import read_json
from ...services.results_service import read_model_results
from .summaries import (
    _bounded_public_result_value,
)

def _bounded_run_figure_evidence(
    project_root: Path,
    *,
    run_id: str,
    node: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose numeric figure backing facts, never image pixels or paths."""

    if node.get("stage") != "model":
        return []
    try:
        from ...figure_context import FigureContextError, resolve_figure_ai_context

        run_root = project_root / "runs" / run_id
        try:
            index = read_json(run_root / "artifacts_index.json")
        except (FileNotFoundError, OSError, ValueError):
            return []
        records = index.get("artifacts") if isinstance(index, dict) else None
        if not isinstance(records, list):
            return []
        evidence: list[dict[str, Any]] = []
        for record in records:
            if len(evidence) >= 4 or not isinstance(record, dict):
                break
            artifact_id = record.get("artifact_id")
            if record.get("artifact_type") != "figure" or not isinstance(artifact_id, str):
                continue
            try:
                packet = resolve_figure_ai_context(project_root, run_id=run_id, artifact_id=artifact_id)
            except (FigureContextError, FileNotFoundError, OSError, TypeError, ValueError):
                continue
            source = packet.get("source")
            source_preview = source.get("preview_json") if isinstance(source, dict) else None
            try:
                raw_source = json.loads(source_preview) if isinstance(source_preview, str) else None
            except (TypeError, ValueError):
                raw_source = None
            model_figure_source = _bounded_model_figure_numeric_source(
                run_root,
                node_id=str(node.get("id") or ""),
                artifact_id=artifact_id,
            )
            numeric_source = (
                model_figure_source
                if model_figure_source is not None
                else _bounded_public_result_value(raw_source)
                if raw_source is not None
                else None
            )
            evidence.append(
                {
                    "artifact_id": artifact_id,
                    "chart_type": packet.get("figure", {}).get("chart_type") if isinstance(packet.get("figure"), dict) else None,
                    "numeric_source": numeric_source,
                    "source_available": numeric_source is not None,
                    "scope": "run",
                }
            )
        return evidence
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return []


def _bounded_model_figure_numeric_source(
    run_root: Path,
    *,
    node_id: str,
    artifact_id: str,
) -> dict[str, Any] | None:
    """Aggregate model vectors into chart facts without returning observations."""

    if not artifact_id.startswith(("residuals_fitted", "residuals_vs_", "qq_residuals")):
        return None
    model_key = node_id.split(":", 1)[1] if node_id.startswith("model:") else ""
    candidates = [
        result
        for result in read_model_results(run_root)
        if isinstance(result, dict)
        and (
            not model_key
            or str(result.get("model_id") or result.get("result_id") or "") == model_key
        )
    ]
    if not candidates and model_key:
        return None
    if not candidates:
        candidates = [result for result in read_model_results(run_root) if isinstance(result, dict)]
    if len(candidates) != 1:
        return None
    result = candidates[0]
    model_id = result.get("model_id") or result.get("result_id")
    residuals = _finite_numeric_values(result.get("residuals"))
    if not residuals:
        return None
    nobs = result.get("nobs")
    analysis_observations = nobs if isinstance(nobs, int) and not isinstance(nobs, bool) and nobs >= len(residuals) else len(residuals)
    if artifact_id.startswith("qq_residuals"):
        return {
            "kind": "residual_distribution_quantiles",
            "model_id": model_id if isinstance(model_id, str) else None,
            "analysis_observations": analysis_observations,
            "plotted_observations": len(residuals),
            "residual_mean": _numeric_mean(residuals),
            "residual_standard_deviation": _numeric_standard_deviation(residuals),
            "quantiles": [
                {"quantile": quantile, "residual": _numeric_quantile(residuals, quantile)}
                for quantile in (0.05, 0.25, 0.5, 0.75, 0.95)
            ],
        }
    if artifact_id.startswith("residuals_vs_"):
        return _bounded_residuals_vs_predictor_source(
            run_root,
            result=result,
            artifact_id=artifact_id,
            residuals=residuals,
            analysis_observations=analysis_observations,
        )
    fitted = _finite_numeric_values(result.get("fitted_values"))
    pairs = sorted(zip(fitted, residuals, strict=False), key=lambda pair: pair[0])
    if len(pairs) < 8:
        return None
    bin_count = min(12, max(1, len(pairs) // 5))
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = index * len(pairs) // bin_count
        stop = (index + 1) * len(pairs) // bin_count
        chunk = pairs[start:stop]
        if len(chunk) < 2:
            continue
        fitted_chunk = [pair[0] for pair in chunk]
        residual_chunk = [pair[1] for pair in chunk]
        bins.append(
            {
                "n": len(chunk),
                "fitted_min": min(fitted_chunk),
                "fitted_max": max(fitted_chunk),
                "residual_mean": _numeric_mean(residual_chunk),
                "residual_standard_deviation": _numeric_standard_deviation(residual_chunk),
                "residual_absolute_mean": _numeric_mean([abs(value) for value in residual_chunk]),
            }
        )
    if not bins:
        return None
    return {
        "kind": "residuals_vs_fitted_bins",
        "model_id": model_id if isinstance(model_id, str) else None,
        "analysis_observations": analysis_observations,
        "plotted_observations": len(pairs),
        "binning": "equal_count_by_fitted_value",
        "bins": bins,
    }


def _bounded_residuals_vs_predictor_source(
    run_root: Path,
    *,
    result: dict[str, Any],
    artifact_id: str,
    residuals: list[float],
    analysis_observations: int,
) -> dict[str, Any] | None:
    """Reconstruct one persisted predictor diagnostic as bounded bin statistics.

    The figure renderer aligns the model's residual vector to the cleaned data
    through ``analysis_sample.row_order``.  Reusing that same deterministic
    alignment here lets an Agent describe the chart it is shown without
    releasing any observation-level predictor or residual values.
    """

    suffix = artifact_id.removeprefix("residuals_vs_")
    x_columns = result.get("x_columns")
    if not isinstance(x_columns, list):
        return None
    candidates = [
        str(column)
        for column in x_columns
        if _figure_artifact_suffix(str(column)) == suffix
    ]
    if len(candidates) != 1:
        return None
    predictor = candidates[0]
    frame = _read_cleaned_dataset_for_figure_context(run_root)
    if frame is None or predictor not in frame.columns:
        return None
    aligned = _align_figure_context_rows(frame, result, len(residuals))
    if aligned is None:
        return None
    try:
        import pandas as pd

        values = pd.to_numeric(aligned[predictor], errors="coerce")
    except (ImportError, TypeError, ValueError):
        return None
    pairs = sorted(
        (
            (float(value), residual)
            for value, residual in zip(values, residuals, strict=True)
            if not pd.isna(value) and math.isfinite(float(value))
        ),
        key=lambda pair: pair[0],
    )
    if len(pairs) < 8:
        return None
    bin_count = min(12, max(1, len(pairs) // 5))
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = index * len(pairs) // bin_count
        stop = (index + 1) * len(pairs) // bin_count
        chunk = pairs[start:stop]
        if len(chunk) < 2:
            continue
        predictor_chunk = [pair[0] for pair in chunk]
        residual_chunk = [pair[1] for pair in chunk]
        bins.append(
            {
                "n": len(chunk),
                "predictor_min": min(predictor_chunk),
                "predictor_max": max(predictor_chunk),
                "residual_mean": _numeric_mean(residual_chunk),
                "residual_standard_deviation": _numeric_standard_deviation(residual_chunk),
                "residual_absolute_mean": _numeric_mean([abs(value) for value in residual_chunk]),
            }
        )
    if not bins:
        return None
    return {
        "kind": "residuals_vs_predictor_bins",
        "model_id": result.get("model_id") if isinstance(result.get("model_id"), str) else None,
        "predictor": predictor,
        "analysis_observations": analysis_observations,
        "plotted_observations": len(pairs),
        "binning": "equal_count_by_predictor",
        "bins": bins,
    }


def _figure_artifact_suffix(column: str) -> str:
    suffix = re.sub(r"[^0-9A-Za-z_]+", "_", column).strip("_")
    return suffix or "predictor"


def _read_cleaned_dataset_for_figure_context(run_root: Path) -> Any | None:
    try:
        index = read_json(run_root / "artifacts_index.json")
        records = index.get("artifacts") if isinstance(index, dict) else None
        if not isinstance(records, list):
            return None
        record = next(
            (
                item
                for item in records
                if isinstance(item, dict) and item.get("artifact_id") == "cleaned_dataset"
            ),
            None,
        )
        path_value = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path_value, str) or not path_value:
            return None
        path = (run_root / path_value).resolve()
        path.relative_to(run_root.resolve())
        if not path.is_file():
            return None
        import pandas as pd

        return pd.read_parquet(path)
    except (FileNotFoundError, OSError, ValueError, TypeError, ImportError):
        return None


def _align_figure_context_rows(frame: Any, result: dict[str, Any], size: int) -> Any | None:
    if size < 1 or len(frame) < size:
        return None
    sample = result.get("analysis_sample")
    row_order = sample.get("row_order") if isinstance(sample, dict) else None
    if isinstance(row_order, list) and len(row_order) >= size:
        positions = {str(value): position for position, value in enumerate(frame.index)}
        selected = [positions.get(str(value)) for value in row_order[:size]]
        if any(position is None for position in selected):
            return None
        return frame.iloc[[int(position) for position in selected]]
    # Older persisted results may predate row identities.  Their existing
    # visualization uses the first diagnostic-vector rows, so this retains
    # that explicitly bounded legacy behavior rather than silently inventing
    # a new alignment rule.
    return frame.iloc[:size]


def _finite_numeric_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    values: list[float] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            numeric = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(numeric):
            return []
        values.append(numeric)
    return values


def _numeric_mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _numeric_standard_deviation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _numeric_mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _numeric_quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

