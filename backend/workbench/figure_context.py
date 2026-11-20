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
import math
from pathlib import Path
from typing import Any

from .artifacts import read_json, sha256_file

MAX_SOURCE_PREVIEW_CHARS = 6_000
# A time-trend source is a summary of every row (aggregate) plus a row sample
# (rows); the egress checkpoint classifies each by its protocol, so a remote
# provider gets the rows only where the project allows rows.
SUMMARY_PROTOCOL = "figure-series-summary/v1"
ROWS_PROTOCOL = "figure-rows/v1"
MAX_SUMMARY_BINS = 50
_TREND_PREVIEW_ROWS = 400

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
    "residuals_vs_": {"chart_type": "residuals-vs-predictor diagnostic scatter", "reads": "diagnostics"},
    "qq_residuals": {"chart_type": "normal Q-Q plot of residuals", "reads": "diagnostics"},
    "event_study": {"chart_type": "event-study dynamic effects with confidence bands", "reads": "event_study"},
    "time_trend": {"chart_type": "time trend of numeric variables", "reads": "time_trend"},
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
    if reads == "event_study":
        # CS/SA/DCDH store the numeric event-study source in their model-level
        # JSON artifact; TWFE stores the same shape in did_diagnostics.json.
        return next(
            (
                r
                for r in records
                if r.get("artifact_id") in {"cs_did", "sa_did", "dcdh", "did_diagnostics"}
            ),
            None,
        )
    if reads == "time_trend":
        return by_id("cleaned_dataset")
    return None


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _limited(value: Any, limit: int) -> Any:
    if isinstance(value, list):
        return [_limited(item, limit) for item in value[:limit]]
    if isinstance(value, dict):
        return {key: _limited(item, limit) for key, item in list(value.items())[:limit]}
    return value


def _bounded_preview(payload: Any) -> tuple[str, bool]:
    """The payload as JSON within the bound, cut as structure so it stays parseable.

    Cut text was invalid JSON, which the egress checkpoint could not look inside.
    """

    text = _dumps(payload)
    if len(text) <= MAX_SOURCE_PREVIEW_CHARS:
        return text, False
    for limit in (256, 128, 64, 32, 16, 8, 4, 2, 1):
        text = _dumps(_limited(payload, limit))
        if len(text) <= MAX_SOURCE_PREVIEW_CHARS:
            return text, True
    return _dumps({"preview_omitted": "the numeric source exceeds the context bound"}), True


def _json_scalar(value: Any) -> Any:
    import pandas as pd

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    return None if isinstance(value, float) and math.isnan(value) else value


def series_summary(frame: Any, time_column: str, columns: list[str], *,
                   max_bins: int = MAX_SUMMARY_BINS) -> dict[str, Any]:
    """Every series of a time trend over every row: statistics, a trend and time-ordered bin means.

    Bins group consecutive distinct time values (one bin per value when there are at
    most ``max_bins``), so a panel's several rows per period share a bin. The trend is
    the least-squares slope on the time value, on days for dates, else on the time
    position. A bin carries its count and mean only, and the series no first or last
    observation: those are single rows, not summaries.
    """

    import numpy as np
    import pandas as pd

    ordered = frame.sort_values(time_column, kind="mergesort")
    time = ordered[time_column]
    distinct = pd.Series(pd.unique(time.dropna()))
    if pd.api.types.is_datetime64_any_dtype(time):
        axis, per = (time - time.min()) / pd.Timedelta(days=1), "day"
    elif pd.api.types.is_numeric_dtype(time) and not pd.api.types.is_bool_dtype(time):
        axis, per = time.astype(float), time_column
    else:
        axis, per = time.map({value: position for position, value in enumerate(distinct)}).astype(float), "time position"
    groups = np.array_split(np.arange(len(distinct)), min(max_bins, len(distinct))) if max_bins and len(distinct) else []
    bin_of = {distinct.iloc[index]: number for number, members in enumerate(groups) for index in members}
    series: dict[str, Any] = {}
    for column in columns:
        values = pd.to_numeric(ordered[column], errors="coerce")
        valid = values.notna() & time.notna()
        kept, kept_axis, kept_time = values[valid], axis[valid], time[valid]
        entry: dict[str, Any] = {"n": int(valid.sum()), "missing": int((~valid).sum())}
        if len(kept):
            entry.update({
                "min": _json_scalar(kept.min()), "max": _json_scalar(kept.max()), "mean": _json_scalar(kept.mean()),
                "std": _json_scalar(kept.std()) if len(kept) > 1 else None,
            })
            if kept_axis.nunique() > 1:
                entry["trend"] = {"slope": float(np.polyfit(kept_axis.to_numpy(float), kept.to_numpy(float), 1)[0]),
                                  "per": per}
        if groups:
            numbers = kept_time.map(bin_of)
            entry["bins"] = [
                {"time_start": _json_scalar(distinct.iloc[members[0]]), "time_end": _json_scalar(distinct.iloc[members[-1]]),
                 "n": int(len(part)), "mean": _json_scalar(part.mean()) if len(part) else None}
                for number, members in enumerate(groups) for part in [kept[numbers == number]]
            ]
            means = [entry_bin["mean"] for entry_bin in entry["bins"] if entry_bin["mean"] is not None]
            if len(means) > 1:
                entry["change_in_bin_mean"] = means[-1] - means[0]
        series[column] = entry
    return {"time_column": time_column, "rows_summarized": int(len(frame)), "series": series,
            "bins": "consecutive distinct time values, at most %d bins" % max_bins if groups else "none"}


def _event_study_payload(payload: Any) -> Any:
    """Select only the numeric series that produced the event-study figure."""

    if not isinstance(payload, dict):
        return payload
    dynamic = payload.get("aggregations", {}).get("dynamic")
    if isinstance(dynamic, dict):
        return {
            key: dynamic.get(key)
            for key in (
                "label_kind", "event_time", "label", "estimate", "se",
                "pointwise_ci", "uniform_band", "uniform_crit",
            )
            if key in dynamic
        }
    event_study = payload.get("event_study")
    if isinstance(event_study, dict):
        return event_study
    return payload


def _time_trend_payload(run_root: Path, source_record: dict[str, Any]) -> Any | None:
    """Reconstruct the numeric series used by ``visualization._plot_time_trend``.

    This is intentionally serve-time decoration: the immutable artifact index and
    the visualization output remain untouched. The chart plots each numeric column
    against the configured time column, so the cleaned parquet is the authoritative
    source rather than a lossy image or a guessed summary statistic.
    """

    source_path = (run_root / str(source_record.get("path"))).resolve()
    try:
        source_path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise FigureContextError("time-trend source escapes run root") from exc
    if not source_path.is_file():
        return None
    try:
        import pandas as pd

        frame = pd.read_parquet(source_path)
        run_inputs = read_json(run_root / "run_inputs.json")
        form = run_inputs.get("form") if isinstance(run_inputs, dict) else {}
        time_column = str((form or {}).get("time_col") or "").strip()
        if not time_column or time_column not in frame.columns:
            return None
        columns = [
            str(column)
            for column in frame.select_dtypes(include="number").columns
            if str(column) != time_column
        ]
        if not columns:
            return None
        preview_frame = frame[[time_column, *columns]].sort_values(time_column).head(_TREND_PREVIEW_ROWS)
        rows = json.loads(preview_frame.to_json(orient="records", date_format="iso"))

        def payload(summary: dict[str, Any], sample: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "time_column": time_column, "series": columns, "row_count_total": int(len(frame)),
                "summary": {"protocol_version": SUMMARY_PROTOCOL, "observations": summary},
                "rows": {"protocol_version": ROWS_PROTOCOL, "observations": {
                    "rows": sample, "row_count_sample": len(sample), "selection": "first rows in time order"}},
            }

        # The summary covers every row and keeps as many bins as fit; the row sample
        # takes the space left.
        for bins in (MAX_SUMMARY_BINS, 25, 12, 6, 3, 1, 0):
            summary = series_summary(frame, time_column, columns, max_bins=bins)
            if len(_dumps(payload(summary, []))) <= MAX_SOURCE_PREVIEW_CHARS:
                break
        low, high = 0, len(rows)
        while low < high:
            middle = (low + high + 1) // 2
            if len(_dumps(payload(summary, rows[:middle]))) <= MAX_SOURCE_PREVIEW_CHARS:
                low = middle
            else:
                high = middle - 1
        result = payload(summary, rows[:low])
        if bins < min(MAX_SUMMARY_BINS, len(frame[time_column].dropna().unique())) or low < len(rows):
            result["_preview_cut"] = True
        return result
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


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
        source_payload: Any | None = None
        if reads == "event_study" and source_path.is_file() and source_path.suffix.lower() == ".json":
            source_payload = _event_study_payload(read_json(source_path))
        elif reads == "time_trend":
            source_payload = _time_trend_payload(run_root, source_record)
        elif source_path.is_file() and source_path.suffix.lower() == ".json":
            source_payload = read_json(source_path)
        if source_payload is not None:
            cut = isinstance(source_payload, dict) and bool(source_payload.pop("_preview_cut", False))
            preview, truncated = _bounded_preview(source_payload)
            truncated = truncated or cut
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
