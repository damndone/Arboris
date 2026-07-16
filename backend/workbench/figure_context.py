"""Serve-time figure → numeric-source context for AI interpretation (G2).

A chart is a rendering of numbers. Asking a text model to "explain a figure"
by shipping the PNG is both lossy and outside the packet's safe-preview policy
(binaries are excluded). Instead, for a figure we resolve, at serve time, the
authoritative chart type and the numeric artifact that produced it, and return a
bounded safe preview of those numbers. The model interprets the chart from the
data it was drawn from — never from pixels.

This is decorate-only: it reads the existing artifacts index and produces a
context on demand. It does not change how figures are generated or registered,
so golden 0-drift on the visualization pipeline is unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import read_json, sha256_file

MAX_SOURCE_PREVIEW_CHARS = 6_000

# figure artifact_id (matched by exact id or longest prefix) → chart semantics.
# ``reads`` names the kind of numeric source that backs the chart; the concrete
# artifact is resolved against the run's artifacts index.
_FIGURE_SPECS: dict[str, dict[str, str]] = {
    "histograms": {"chart_type": "per-variable histogram grid", "reads": "profile"},
    "kde_plots": {"chart_type": "per-variable density (KDE) grid", "reads": "profile"},
    "boxplots": {"chart_type": "per-variable boxplot grid", "reads": "profile"},
    "scatter_plots": {"chart_type": "pairwise scatter grid", "reads": "correlations"},
    "correlation_heatmap": {"chart_type": "correlation heatmap", "reads": "correlations"},
    "coef_plot": {"chart_type": "coefficient (forest) plot with confidence intervals", "reads": "model"},
    "residuals_fitted": {"chart_type": "residuals-vs-fitted diagnostic scatter", "reads": "diagnostics"},
    "qq_residuals": {"chart_type": "normal Q-Q plot of residuals", "reads": "diagnostics"},
}


class FigureContextError(ValueError):
    """Raised when a figure or its numeric source cannot be resolved."""


def _spec_for(artifact_id: str) -> dict[str, str] | None:
    if artifact_id in _FIGURE_SPECS:
        return _FIGURE_SPECS[artifact_id]
    # per-model figures may carry a suffix (e.g. "coef_plot_ols_1"); match the
    # longest known prefix so new model ids still resolve to a chart type.
    best: str | None = None
    for key in _FIGURE_SPECS:
        if artifact_id.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return _FIGURE_SPECS[best] if best else None


def _resolve_source_artifact(records: list[dict[str, Any]], reads: str) -> dict[str, Any] | None:
    def by_id(artifact_id: str) -> dict[str, Any] | None:
        return next((r for r in records if r.get("artifact_id") == artifact_id), None)

    if reads == "profile":
        return by_id("data_profile")
    if reads == "correlations":
        return by_id("statistical_tests_correlations")
    if reads == "diagnostics":
        return next(
            (r for r in records if str(r.get("path", "")).startswith("model_results/diagnostics")),
            None,
        )
    if reads == "model":
        return next(
            (
                r
                for r in records
                if str(r.get("path", "")).startswith("model_results/")
                and "diagnostics" not in str(r.get("path", ""))
            ),
            None,
        )
    return None


def _bounded_preview(payload: Any) -> tuple[str, bool]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(text) <= MAX_SOURCE_PREVIEW_CHARS:
        return text, False
    return text[:MAX_SOURCE_PREVIEW_CHARS], True


def resolve_figure_ai_context(
    project_root: Path | str,
    *,
    run_id: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Build the AI interpretation context for one figure of a run."""

    root = Path(project_root).expanduser().resolve()
    runs_root = root / "runs"
    run_root = (runs_root / run_id).resolve()
    try:
        run_root.relative_to(runs_root.resolve())
    except ValueError as exc:
        raise FigureContextError("run is outside project runs") from exc
    if not run_root.is_dir():
        raise FigureContextError("run was not found")

    index = read_json(run_root / "artifacts_index.json")
    records = index.get("artifacts", [])
    figure = next((r for r in records if r.get("artifact_id") == artifact_id), None)
    if figure is None:
        raise FigureContextError("figure artifact was not found")
    if figure.get("artifact_type") != "figure":
        raise FigureContextError("artifact is not a figure")

    spec = _spec_for(artifact_id)
    chart_type = spec["chart_type"] if spec else "chart"
    reads = spec["reads"] if spec else ""

    source_record = _resolve_source_artifact(records, reads) if reads else None
    source: dict[str, Any] | None = None
    if source_record is not None:
        source_path = (run_root / str(source_record.get("path"))).resolve()
        try:
            source_path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise FigureContextError("source artifact escapes run root") from exc
        if source_path.is_file() and source_path.suffix.lower() == ".json":
            preview, truncated = _bounded_preview(read_json(source_path))
            source = {
                "artifact_id": source_record.get("artifact_id"),
                "path": source_record.get("path"),
                "kind": reads,
                "sha256": source_record.get("sha256"),
                "preview_json": preview,
                "preview_truncated": truncated,
            }

    figure_path = (run_root / str(figure.get("path"))).resolve()
    return {
        "figure_context_version": "figure-ai-context/v1",
        "run_id": run_id,
        "figure": {
            "artifact_id": artifact_id,
            "path": figure.get("path"),
            "chart_type": chart_type,
            "sha256": (
                figure.get("sha256")
                or (sha256_file(figure_path) if figure_path.is_file() else None)
            ),
        },
        "source": source,
        "guidance": (
            f"This is a {chart_type}. You cannot see the image; interpret it only "
            "from the numeric source below, which is the data the chart was drawn "
            "from. Ground every statement in those numbers and name any limitation."
        ),
        "context_visibility_notice": {
            "artifact_policy": "metadata_and_safe_preview_only",
            "binary_artifacts_included": False,
            "image_pixels_included": False,
            "max_source_preview_chars": MAX_SOURCE_PREVIEW_CHARS,
        },
        "response_guardrails": {
            "advisory_text_only": True,
            "executable_actions_allowed": False,
            "graph_mutations_allowed": False,
            "must_interpret_from_numeric_source": True,
        },
    }


__all__ = ["FigureContextError", "resolve_figure_ai_context", "MAX_SOURCE_PREVIEW_CHARS"]
