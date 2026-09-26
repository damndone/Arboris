"""Read a run's dataset nodes for the Data view: rows by page, variables.

Rows are served as stored, including declared missing codes, so the grid shows
what the file holds; each variable reports how many values its declared codes
match. Frames are cached by file identity so paging does not re-read the file.
"""

from __future__ import annotations

import functools
import math
from pathlib import Path
from typing import Any

import pandas as pd

from ..data_operations import _read_frame, resolve_data_column_cast_context
from ..egress import EgressPolicyError, load_policy
from ..graph_model import NodeKind
from ..graph_store import GraphStore
from ..lineage.run_inputs import read_run_inputs
from ..repository.run_repository import _resolve_run_root
from ..user_missing import code_mask

MAX_PAGE_ROWS = 500
_TOP_VALUES = 12


def json_cell(value: object) -> object:
    """A pandas cell as a JSON value; missing becomes null."""

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    return value


def json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {str(column): json_cell(value) for column, value in zip(frame.columns, row)}
        for row in frame.itertuples(index=False, name=None)
    ]


def list_dataset_nodes(project_root: Path | str, run_id: str) -> list[dict[str, Any]]:
    run_root = _resolve_run_root(str(project_root), run_id)
    graph = GraphStore(runs_root=run_root.parent).read(run_id)
    nodes = []
    for node_id, node in graph.nodes.items():
        if node.kind != NodeKind.DATASET_STAGE:
            continue
        nodes.append(
            {
                "node_id": node_id,
                "label": node.display_label or node_id,
                "stage": node.stage.value if node.stage is not None else None,
                "parent_stage_id": node.parent_stage_id,
            }
        )
    order = {"stage:raw": 0, "stage:cleaned": 1}
    return sorted(nodes, key=lambda item: (order.get(item["node_id"], 2), item["node_id"]))


@functools.lru_cache(maxsize=8)
def _cached_frame(path: str, _mtime_ns: int, _size: int) -> pd.DataFrame:
    return _read_frame(Path(path))


def load_dataset(project_root: Path | str, run_id: str, node_id: str) -> tuple[dict[str, Any], pd.DataFrame]:
    context = resolve_data_column_cast_context(
        project_root, source_run_id=run_id, source_node_id=node_id
    )
    run_root = _resolve_run_root(str(project_root), run_id)
    path = run_root / context["source_artifact_path"]
    stat = path.stat()
    return context, _cached_frame(str(path), stat.st_mtime_ns, stat.st_size)


def run_labels(project_root: Path | str, run_id: str) -> dict[str, Any]:
    run_root = _resolve_run_root(str(project_root), run_id)
    labels = (read_run_inputs(run_root).get("form") or {}).get("labels") or {}
    return labels if isinstance(labels, dict) else {}


def dataset_page(
    project_root: Path | str,
    run_id: str,
    node_id: str,
    *,
    offset: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    descending: bool = False,
) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= MAX_PAGE_ROWS:
        raise ValueError(f"offset must be >= 0 and limit between 1 and {MAX_PAGE_ROWS}")
    context, frame = load_dataset(project_root, run_id, node_id)
    view = frame
    if sort_by is not None:
        if sort_by not in frame.columns:
            raise ValueError(f"cannot sort by unknown column {sort_by!r}")
        # A view-only order: the dataset itself is not changed.
        view = frame.sort_values(sort_by, ascending=not descending, kind="mergesort", na_position="last")
    page = view.iloc[offset : offset + limit]
    return {
        "run_id": run_id,
        "node_id": node_id,
        "artifact_id": context["source_artifact_id"],
        "columns": [str(column) for column in frame.columns],
        "total_rows": int(len(frame)),
        "offset": offset,
        # Row numbers are positions in the stored dataset, stable under sort.
        "row_numbers": [int(position) + 1 for position in frame.index.get_indexer(page.index)],
        "rows": json_records(page),
    }


def _kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "string"


def dataset_variables(project_root: Path | str, run_id: str, node_id: str) -> dict[str, Any]:
    context, frame = load_dataset(project_root, run_id, node_id)
    labels = run_labels(project_root, run_id)
    variable_labels = labels.get("variable_labels") or {}
    value_labels = labels.get("value_labels") or {}
    levels = labels.get("measurement_level") or {}
    missing_codes = labels.get("user_missing_values") or {}
    try:
        policy = load_policy(Path(project_root))
        sensitivity_error = None
    except EgressPolicyError as exc:
        policy, sensitivity_error = None, str(exc)
    variables = []
    for position, column in enumerate(frame.columns):
        name = str(column)
        series = frame[column]
        kind = _kind(series)
        codes = missing_codes.get(name) or []
        coded = int(code_mask(series, codes).sum()) if codes else 0
        entry: dict[str, Any] = {
            "position": position + 1,
            "name": name,
            "type": kind,
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "declared_missing_matches": coded,
            "unique": int(series.nunique(dropna=True)),
            "variable_label": variable_labels.get(name),
            "value_labels": value_labels.get(name) or {},
            "measurement_level": levels.get(name),
            "user_missing_values": codes,
        }
        if policy is not None:
            # Project-wide: who may see this column's values (workbench.egress).
            entry["sensitivity"] = policy.column_level(name)
            entry["sensitivity_source"] = "project" if name in policy.columns else "suggested"
        valid = series[~code_mask(series, codes)] if codes else series
        if kind == "numeric":
            numbers = valid.dropna()
            entry["min"] = json_cell(numbers.min()) if len(numbers) else None
            entry["max"] = json_cell(numbers.max()) if len(numbers) else None
            entry["mean"] = json_cell(float(numbers.mean())) if len(numbers) else None
        if entry["unique"] <= _TOP_VALUES:
            counts = valid.value_counts(dropna=True).head(_TOP_VALUES)
            entry["values"] = [
                {"value": json_cell(value), "count": int(count)} for value, count in counts.items()
            ]
        variables.append(entry)
    return {
        "run_id": run_id,
        "node_id": node_id,
        "artifact_id": context["source_artifact_id"],
        "total_rows": int(len(frame)),
        "variables": variables,
        "sensitivity_error": sensitivity_error,
    }
