"""Typed, source-bound statistical exploration contracts.

This module starts the v1.8.2 exploration seam.  The data-frame operations and
durable artifact writer live below these contracts so the frontend and the
backend share one canonical operation identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Mapping

import pandas as pd

from .artifacts import (
    read_json,
    register_artifact,
    sha256_file,
    write_json,
    write_text_durable,
)


SCHEMA_VERSION = "statistical-exploration.v1"


class StatisticalExplorationValidationError(ValueError):
    """Raised when a typed exploration request cannot be evaluated safely."""


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise StatisticalExplorationValidationError(
        f"filter value has unsupported type: {type(value).__name__}"
    )


@dataclass(frozen=True)
class FilterSpec:
    column: str
    operator: str
    value: Any

    OPERATORS: ClassVar[frozenset[str]] = frozenset(
        {"eq", "neq", "lt", "lte", "gt", "gte", "in", "not_in"}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.column, str) or not self.column.strip():
            raise StatisticalExplorationValidationError("filter column must be non-empty")
        if self.operator not in self.OPERATORS:
            raise StatisticalExplorationValidationError(
                f"filter operator is unsupported: {self.operator}"
            )
        _canonical_value(self.value)
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, (list, tuple)) or not self.value:
                raise StatisticalExplorationValidationError(
                    f"filter operator {self.operator} requires a non-empty list value"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "operator": self.operator,
            "value": _canonical_value(self.value),
        }


@dataclass(frozen=True)
class ExplorationSpec:
    operation: str
    selected_columns: tuple[str, ...]
    filters: tuple[FilterSpec, ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)
    derived_definitions: tuple[Mapping[str, Any], ...] = ()

    OPERATIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "summarize",
            "summarize_detail",
            "misstable",
            "corr",
            "derive_boolean",
            "scatter",
        }
    )

    def __post_init__(self) -> None:
        if self.operation not in self.OPERATIONS:
            raise StatisticalExplorationValidationError(
                f"exploration operation is unsupported: {self.operation}"
            )
        columns = tuple(self.selected_columns)
        if any(not isinstance(column, str) or not column.strip() for column in columns):
            raise StatisticalExplorationValidationError(
                "selected columns must contain non-empty names"
            )
        if len(set(columns)) != len(columns):
            raise StatisticalExplorationValidationError(
                "selected columns must not contain duplicates"
            )
        if not all(isinstance(item, FilterSpec) for item in self.filters):
            raise StatisticalExplorationValidationError("filters must be FilterSpec values")
        if not isinstance(self.options, Mapping):
            raise StatisticalExplorationValidationError("options must be a mapping")
        _canonical_value(self.options)
        if not isinstance(self.derived_definitions, (list, tuple)):
            raise StatisticalExplorationValidationError(
                "derived definitions must be a list"
            )
        _canonical_value(self.derived_definitions)
        object.__setattr__(self, "selected_columns", columns)
        object.__setattr__(self, "filters", tuple(self.filters))
        object.__setattr__(self, "derived_definitions", tuple(self.derived_definitions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "operation": self.operation,
            "selected_columns": list(self.selected_columns),
            "filters": [item.to_dict() for item in self.filters],
            "options": _canonical_value(self.options),
            "derived_definitions": _canonical_value(self.derived_definitions),
        }


def canonical_spec_json(source_sha: str, spec: ExplorationSpec) -> str:
    if not isinstance(source_sha, str) or not source_sha:
        raise StatisticalExplorationValidationError("source SHA must be non-empty")
    return json.dumps(
        {"source_sha": source_sha, "spec": spec.to_dict()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def exploration_fingerprint(source_sha: str, spec: ExplorationSpec) -> str:
    return hashlib.sha256(canonical_spec_json(source_sha, spec).encode("utf-8")).hexdigest()


def execute_exploration(frame: Any, spec: ExplorationSpec) -> dict[str, Any]:
    """Execute one typed operation over an in-memory source frame."""
    _validate_frame(frame)
    filtered = _apply_filters(frame, spec.filters)
    base = {
        "schema_version": SCHEMA_VERSION,
        "operation": spec.operation,
        "filters": [item.to_dict() for item in spec.filters],
        "source_row_count": int(len(frame)),
        "filtered_row_count": int(len(filtered)),
    }

    if spec.operation == "summarize":
        group_by = spec.options.get("group_by")
        if group_by is not None:
            return {
                **base,
                "group_by": _require_column(frame, group_by),
                "groups": _summarize_groups(
                    frame,
                    spec,
                    group_by=group_by,
                    group_values=spec.options.get("group_values"),
                ),
            }
        return {
            **base,
            "missing_policy": "variablewise",
            "variables": _summary_variables(filtered, spec.selected_columns),
        }

    if spec.operation == "summarize_detail":
        return {
            **base,
            "missing_policy": "variablewise",
            "variables": _detail_variables(filtered, spec.selected_columns),
        }

    if spec.operation == "misstable":
        columns = _selected_columns(frame, spec.selected_columns)
        return {
            **base,
            "missing_policy": "variablewise",
            "variables": {
                column: {
                    "missing": int(filtered[column].isna().sum()),
                    "nonmissing": int(filtered[column].notna().sum()),
                }
                for column in columns
            },
        }

    if spec.operation == "corr":
        return _correlation_result(base, filtered, spec.selected_columns, spec.options)

    raise StatisticalExplorationValidationError(
        f"exploration operation is not implemented: {spec.operation}"
    )


def resolve_statistical_source(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Resolve a dataset node through the existing data-operation binding."""
    from .data_operations import _read_frame, resolve_data_column_cast_context

    context = resolve_data_column_cast_context(
        project_root,
        source_run_id=source_run_id,
        source_node_id=source_node_id,
    )
    if context["source_artifact_id"] != source_artifact_id:
        raise StatisticalExplorationValidationError(
            "source artifact is not owned by the selected dataset node"
        )
    root = Path(project_root).expanduser().resolve()
    source_path = root / "runs" / source_run_id / context["source_artifact_path"]
    return context, _read_frame(source_path)


def persist_exploration(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_artifact_id: str,
    source_sha256: str,
    spec: ExplorationSpec,
    result: dict[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    """Write one idempotent result and transcript pair into the source run."""
    root = Path(project_root).expanduser().resolve()
    run_root = root / "runs" / source_run_id
    result_rel = f"artifacts/statistical_exploration/{fingerprint}.json"
    transcript_rel = f"artifacts/statistical_exploration/{fingerprint}.txt"
    result_path = run_root / result_rel
    transcript_path = run_root / transcript_rel
    result_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        result_path,
        {
            "schema_version": SCHEMA_VERSION,
            "fingerprint": fingerprint,
            "source_artifact_id": source_artifact_id,
            "source_sha256": source_sha256,
            "spec": spec.to_dict(),
            "result": result,
        },
    )
    artifact_id = f"statistical_exploration_{fingerprint[:24]}"
    transcript_artifact_id = f"statistical_exploration_transcript_{fingerprint[:24]}"
    transcript = "\n".join(
        [
            "# Statistical exploration transcript",
            f"source_artifact_id: {source_artifact_id}",
            f"source_sha256: {source_sha256}",
            f"operation: {spec.operation}",
            f"filters: {json.dumps(spec.to_dict()['filters'], ensure_ascii=False, sort_keys=True)}",
            f"filtered_row_count: {result.get('filtered_row_count')}",
            f"result_artifact_id: {artifact_id}",
        ]
    ) + "\n"
    write_text_durable(transcript_path, transcript)
    _ensure_exploration_artifact(
        run_root,
        artifact_id=artifact_id,
        path=result_path,
        artifact_type="statistical_exploration",
        step="statistical_exploration",
        inputs=[source_artifact_id],
    )
    _ensure_exploration_artifact(
        run_root,
        artifact_id=transcript_artifact_id,
        path=transcript_path,
        artifact_type="transcript",
        step="statistical_exploration",
        inputs=[artifact_id],
    )
    return {
        "artifact_id": artifact_id,
        "path": result_rel,
        "transcript_artifact_id": transcript_artifact_id,
        "transcript_path": transcript_rel,
        "fingerprint": fingerprint,
        "source_sha256": source_sha256,
    }


def _ensure_exploration_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    index_path = run_root / "artifacts_index.json"
    index = read_json(index_path)
    records = [item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id]
    digest = sha256_file(path)
    if records:
        if len(records) != 1 or records[0].get("sha256") != digest:
            raise StatisticalExplorationValidationError(
                "statistical exploration artifact binding is not deterministic"
            )
        return
    register_artifact(run_root, artifact_id, path, artifact_type, step, inputs)


def _validate_frame(frame: Any) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise StatisticalExplorationValidationError("source frame must be a pandas DataFrame")


def _require_column(frame: pd.DataFrame, column: Any) -> str:
    if not isinstance(column, str) or column not in frame.columns:
        raise StatisticalExplorationValidationError(
            f"source column was not found: {column}"
        )
    return column


def _selected_columns(frame: pd.DataFrame, selected: tuple[str, ...]) -> list[str]:
    columns = list(selected) if selected else list(frame.columns)
    for column in columns:
        _require_column(frame, column)
    return columns


def _numeric_columns(frame: pd.DataFrame, selected: tuple[str, ...]) -> list[str]:
    columns = _selected_columns(frame, selected)
    invalid = [column for column in columns if not pd.api.types.is_numeric_dtype(frame[column])]
    if invalid:
        raise StatisticalExplorationValidationError(
            "statistical operation requires numeric columns: " + ", ".join(invalid)
        )
    return columns


def _apply_filters(frame: pd.DataFrame, filters: tuple[FilterSpec, ...]) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    for item in filters:
        column = _require_column(frame, item.column)
        series = frame[column]
        try:
            if item.operator == "eq":
                current = series.eq(item.value)
            elif item.operator == "neq":
                current = series.ne(item.value)
            elif item.operator == "lt":
                current = series.lt(item.value)
            elif item.operator == "lte":
                current = series.le(item.value)
            elif item.operator == "gt":
                current = series.gt(item.value)
            elif item.operator == "gte":
                current = series.ge(item.value)
            elif item.operator == "in":
                current = series.isin(item.value)
            else:
                current = series.notna() & ~series.isin(item.value)
        except (TypeError, ValueError) as exc:
            raise StatisticalExplorationValidationError(
                f"filter value is incompatible with column: {item.column}"
            ) from exc
        mask &= series.notna() & current.fillna(False)
    return frame.loc[mask]


def _safe_number(value: Any) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    converted = value.item() if hasattr(value, "item") else value
    if isinstance(converted, bool):
        return int(converted)
    if isinstance(converted, int):
        return int(converted)
    if isinstance(converted, float):
        return float(converted)
    return float(converted)


def _summary_variables(frame: pd.DataFrame, selected: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    columns = _numeric_columns(frame, selected)
    summaries: dict[str, dict[str, Any]] = {}
    for column in columns:
        series = frame[column].dropna()
        summaries[column] = {
            "obs": int(series.size),
            "mean": _safe_number(series.mean()),
            "std_dev": _safe_number(series.std(ddof=1)),
            "min": _safe_number(series.min()),
            "max": _safe_number(series.max()),
        }
    return summaries


def _detail_variables(frame: pd.DataFrame, selected: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    columns = _numeric_columns(frame, selected)
    percentiles = (1, 5, 10, 25, 50, 75, 90, 95, 99)
    details: dict[str, dict[str, Any]] = {}
    for column, summary in _summary_variables(frame, tuple(columns)).items():
        series = frame[column].dropna()
        details[column] = {
            **summary,
            "percentiles": {
                f"p{percentile}": _safe_number(
                    series.quantile(percentile / 100, interpolation="linear")
                )
                for percentile in percentiles
            },
        }
    return details


def _summarize_groups(
    frame: pd.DataFrame,
    spec: ExplorationSpec,
    *,
    group_by: Any,
    group_values: Any,
) -> list[dict[str, Any]]:
    if not isinstance(group_values, (list, tuple)) or not group_values:
        raise StatisticalExplorationValidationError(
            "group_values must be a non-empty list when group_by is set"
        )
    groups: list[dict[str, Any]] = []
    for value in group_values:
        group_filter = FilterSpec(column=group_by, operator="eq", value=value)
        group_spec = ExplorationSpec(
            operation="summarize",
            selected_columns=spec.selected_columns,
            filters=(*spec.filters, group_filter),
            options={key: item for key, item in spec.options.items() if key not in {"group_by", "group_values"}},
        )
        result = execute_exploration(frame, group_spec)
        groups.append(
            {
                "value": value,
                "filters": result["filters"],
                "filtered_row_count": result["filtered_row_count"],
                "missing_policy": result["missing_policy"],
                "variables": result["variables"],
            }
        )
    return groups


def _correlation_result(
    base: dict[str, Any],
    frame: pd.DataFrame,
    selected: tuple[str, ...],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    missing_policy = options.get("missing_policy", "listwise")
    if missing_policy != "listwise":
        raise StatisticalExplorationValidationError(
            "corr supports only listwise missing_policy"
        )
    columns = _numeric_columns(frame, selected)
    complete = frame[columns].dropna(how="any")
    matrix = complete.corr().to_numpy().tolist()
    return {
        **base,
        "missing_policy": missing_policy,
        "variables": columns,
        "correlation_n": int(len(complete)),
        "matrix": [[_safe_number(value) for value in row] for row in matrix],
    }


__all__ = [
    "SCHEMA_VERSION",
    "ExplorationSpec",
    "FilterSpec",
    "StatisticalExplorationValidationError",
    "canonical_spec_json",
    "execute_exploration",
    "exploration_fingerprint",
]
