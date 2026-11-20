"""Figures drawn when first read, not while the run computes.

Drawing took up to half a run (2026-11-02: 0.6 s of a 1.1 s Agent tool call, 3.4 s of a wide
OLS) for pictures nobody may open. Everything the drawing reads is already persisted by the
run: the cleaned dataset and each model result. So the run records a plan; the first reader of
figures draws them from those files, with the same code, and registers them as before. This
module stays light: Matplotlib loads only when something is drawn.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .artifacts import read_json, read_model_result_without_row_set, write_json

FIGURE_PLAN = "figures/plan.json"
_PLAN_SCHEMA = "workbench.figures.plan/v1"
_DRAWN = "figures/rendered.json"
_LOG = logging.getLogger(__name__)


def _artifact_paths(run_root: Path) -> dict[str, Path]:
    try:
        records = read_json(run_root / "artifacts_index.json").get("artifacts", [])
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return {}
    return {str(record.get("artifact_id")): run_root / str(record.get("path"))
            for record in records if isinstance(record, dict) and record.get("path")}


def defer_figures(run_root: Path, *, model_result_ids: list[str], **options) -> bool:
    """Record what create_figures needs. False when an input is not on disk: draw now."""
    paths = _artifact_paths(run_root)
    if any(name not in paths or not paths[name].is_file() for name in ["cleaned_dataset", *model_result_ids]):
        return False
    try:
        options = json.loads(json.dumps(options, allow_nan=False))
    except (TypeError, ValueError):
        return False
    (run_root / "figures").mkdir(parents=True, exist_ok=True)
    write_json(run_root / FIGURE_PLAN, {"schema": _PLAN_SCHEMA, "model_result_ids": list(model_result_ids),
                                        "options": options})
    return True


def ensure_figures(run_root: Path | str) -> None:
    """Draw a run's deferred figures once; later and concurrent callers find them drawn."""
    run_root = Path(run_root)
    if not (run_root / FIGURE_PLAN).is_file() or (run_root / _DRAWN).is_file():
        return
    from filelock import FileLock

    with FileLock(str(run_root / "figures" / ".render.lock")):
        if (run_root / _DRAWN).is_file():
            return
        try:
            import pandas as pd

            from .visualization import create_figures

            plan = read_json(run_root / FIGURE_PLAN)
            paths = _artifact_paths(run_root)
            frame = pd.read_parquet(paths["cleaned_dataset"])
            model_results = [(name, read_model_result_without_row_set(paths[name])) for name in plan["model_result_ids"]]
            figures = create_figures(frame, run_root, model_results=model_results, **plan["options"])
            write_json(run_root / _DRAWN, {"schema": _PLAN_SCHEMA, "figures": sorted(figures)})
        except Exception as exc:  # A figure that cannot be drawn must not make the run unreadable.
            _LOG.warning("deferred figures for %s failed: %s", run_root.name, type(exc).__name__)
            write_json(run_root / _DRAWN, {"schema": _PLAN_SCHEMA, "figures": [], "error": type(exc).__name__})
