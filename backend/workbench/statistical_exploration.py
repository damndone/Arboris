"""Typed, source-bound statistical exploration contracts.

This module starts the v1.8.2 exploration seam.  The data-frame operations and
durable artifact writer live below these contracts so the frontend and the
backend share one canonical operation identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, ClassVar, Mapping

import pandas as pd

from .artifacts import (
    read_json,
    register_artifact,
    sha256_file,
    write_json,
    write_text_durable,
)
from .graph_model import Edge, Graph, Node, NodeKind, Stage, Trust


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

    if spec.operation == "derive_boolean":
        return {
            **base,
            "missing_policy": "variablewise",
            "derived": _derived_boolean_result(filtered, spec),
        }

    if spec.operation == "scatter":
        x_column, y_column = _scatter_columns(frame, spec)
        aligned = pd.concat(
            [
                pd.to_numeric(filtered[x_column], errors="coerce").rename("x"),
                pd.to_numeric(filtered[y_column], errors="coerce").rename("y"),
            ],
            axis=1,
        ).dropna()
        return {
            **base,
            "missing_policy": "complete_case_for_plot",
            "plot": {
                "x_column": x_column,
                "y_column": y_column,
                "plotted_row_count": int(len(aligned)),
            },
        }

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
    source_node_id: str,
    source_artifact_id: str,
    source_sha256: str,
    spec: ExplorationSpec,
    result: dict[str, Any],
    fingerprint: str,
    source_frame: pd.DataFrame | None = None,
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
    exports = _persist_exploration_exports(
        run_root,
        artifact_id=artifact_id,
        fingerprint=fingerprint,
        spec=spec,
        result=result,
    )
    record = {
        "artifact_id": artifact_id,
        "path": result_rel,
        "transcript_artifact_id": transcript_artifact_id,
        "transcript_path": transcript_rel,
        "fingerprint": fingerprint,
        "source_sha256": source_sha256,
        "exports": exports,
    }
    if spec.operation == "derive_boolean":
        if source_frame is None:
            raise StatisticalExplorationValidationError(
                "derive_boolean requires the resolved source frame"
            )
        record["derived"] = _persist_derived_boolean(
            run_root,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            source_sha256=source_sha256,
            source_frame=source_frame,
            spec=spec,
            fingerprint=fingerprint,
            result=result,
        )
    if spec.operation == "scatter":
        if source_frame is None:
            raise StatisticalExplorationValidationError(
                "scatter requires the resolved source frame"
            )
        record["plot"] = _persist_statistical_scatter(
            run_root,
            source_artifact_id=source_artifact_id,
            source_frame=source_frame,
            spec=spec,
            fingerprint=fingerprint,
            result=result,
        )
    return record


def _persist_exploration_exports(
    run_root: Path,
    *,
    artifact_id: str,
    fingerprint: str,
    spec: ExplorationSpec,
    result: dict[str, Any],
) -> list[dict[str, str]]:
    """Persist inspectable report files for one confirmed exploration.

    The JSON result remains authoritative.  These are presentation/export
    views of that bounded result, each keyed by the same exploration
    fingerprint so repeated confirmation cannot overwrite another action.
    """
    from .exports import export_pdf, export_xlsx

    stem = f"statistical_exploration_{fingerprint[:24]}"
    report = _exploration_report(spec, result)
    inputs = [artifact_id]

    html_rel = f"reports/{stem}.html"
    html_path = run_root / html_rel
    html_artifact_id = f"{stem}_html"
    from .reporting import render_html_report
    if not _artifact_is_registered(run_root, html_artifact_id):
        render_html_report(
            report,
            run_root,
            filename=f"{stem}.html",
            artifact_id=html_artifact_id,
            inputs=inputs,
        )
    else:
        _ensure_exploration_artifact(
            run_root,
            artifact_id=html_artifact_id,
            path=html_path,
            artifact_type="report",
            step="statistical_exploration.export",
            inputs=inputs,
        )

    pdf_rel = f"reports/{stem}.pdf"
    pdf_path = run_root / pdf_rel
    pdf_artifact_id = f"{stem}_pdf"
    if not _artifact_is_registered(run_root, pdf_artifact_id):
        export_pdf(
            report,
            run_root,
            filename=f"{stem}.pdf",
            artifact_id=pdf_artifact_id,
            inputs=inputs,
        )
    else:
        _ensure_exploration_artifact(
            run_root,
            artifact_id=pdf_artifact_id,
            path=pdf_path,
            artifact_type="report",
            step="statistical_exploration.export",
            inputs=inputs,
        )

    xlsx_rel = f"exports/{stem}.xlsx"
    xlsx_path = run_root / xlsx_rel
    xlsx_artifact_id = f"{stem}_xlsx"
    if not _artifact_is_registered(run_root, xlsx_artifact_id):
        export_xlsx(
            _exploration_tables(result),
            run_root,
            filename=f"{stem}.xlsx",
            artifact_id=xlsx_artifact_id,
            inputs=inputs,
        )
    else:
        _ensure_exploration_artifact(
            run_root,
            artifact_id=xlsx_artifact_id,
            path=xlsx_path,
            artifact_type="table_export",
            step="statistical_exploration.export",
            inputs=inputs,
        )

    return [
        {"format": "html", "artifact_id": html_artifact_id, "path": html_rel},
        {"format": "pdf", "artifact_id": pdf_artifact_id, "path": pdf_rel},
        {"format": "xlsx", "artifact_id": xlsx_artifact_id, "path": xlsx_rel},
    ]


def _artifact_is_registered(run_root: Path, artifact_id: str) -> bool:
    index = read_json(run_root / "artifacts_index.json")
    return any(item.get("artifact_id") == artifact_id for item in index.get("artifacts", []))


def _exploration_report(spec: ExplorationSpec, result: dict[str, Any]) -> dict[str, Any]:
    facts = [
        f"Operation: {spec.operation}",
        f"Source rows: {result.get('source_row_count', 0)}",
        f"Rows after filters: {result.get('filtered_row_count', 0)}",
    ]
    return {
        "title": f"Statistical exploration — {spec.operation}",
        "facts": facts,
        "descriptive_stats": _exploration_descriptive_rows(result),
        "exploration": {
            "operation": spec.operation,
            "source_row_count": result.get("source_row_count", 0),
            "filtered_row_count": result.get("filtered_row_count", 0),
            "missing_policy": result.get("missing_policy"),
            "rows": _result_table_rows(result),
        },
        "claims": [],
        "warnings": [],
    }


def _exploration_descriptive_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    variables = result.get("variables")
    if not isinstance(variables, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for name, values in variables.items():
        if not isinstance(values, Mapping):
            continue
        obs = values.get("obs")
        missing = values.get("missing")
        rows.append(
            {
                "column": str(name),
                "dtype": "exploration",
                "count": obs if isinstance(obs, (int, float)) else 0,
                "missing_rate": (
                    float(missing) / (float(obs) + float(missing))
                    if isinstance(missing, (int, float)) and isinstance(obs, (int, float)) and obs + missing
                    else 0.0
                ),
                "mean": values.get("mean"),
                "std": values.get("std_dev"),
                "min": values.get("min"),
                "max": values.get("max"),
            }
        )
    return rows


def _result_table_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    variables = result.get("variables")
    if isinstance(variables, Mapping):
        rows: list[dict[str, Any]] = []
        for name, values in variables.items():
            row: dict[str, Any] = {"variable": str(name)}
            if isinstance(values, Mapping):
                for key, value in values.items():
                    row[str(key)] = value if isinstance(value, (str, int, float, bool)) or value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                row["value"] = values
            rows.append(row)
        return rows
    groups = result.get("groups")
    if isinstance(groups, list):
        return [dict(item) for item in groups if isinstance(item, Mapping)]
    matrix = result.get("matrix")
    if isinstance(matrix, list):
        return [
            {"row": index, "values": json.dumps(row, ensure_ascii=False)}
            for index, row in enumerate(matrix)
        ]
    return [
        {
            "operation": result.get("operation"),
            "filtered_row_count": result.get("filtered_row_count"),
            "correlation_n": result.get("correlation_n"),
        }
    ]


def _exploration_tables(result: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tables = {"result": _result_table_rows(result)}
    if isinstance(result.get("matrix"), list):
        tables["correlation_matrix"] = [
            {"row": index, "values": json.dumps(row, ensure_ascii=False)}
            for index, row in enumerate(result["matrix"])
        ]
    return tables


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


def _persist_derived_boolean(
    run_root: Path,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
    source_sha256: str,
    source_frame: pd.DataFrame,
    spec: ExplorationSpec,
    fingerprint: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    from .data_operations import (
        _ensure_node_index_entry,
        _ensure_registered_artifact,
        _graph_store_for,
        _mark_downstream_invalidation,
        _write_frame_artifact,
    )
    from .graph_model import BranchRef

    filtered = _apply_filters(source_frame, spec.filters)
    _filtered_derived, definition = _derived_boolean_series(filtered, spec)
    source_column = definition["source_column"]
    output_name = definition["output_name"]
    output = pd.Series(pd.NA, index=source_frame.index, dtype="boolean")
    source = source_frame[source_column]
    if definition["comparison"] == "lte":
        output.loc[source.notna()] = source.loc[source.notna()] <= definition["threshold"]
    else:
        output.loc[source.notna()] = source.loc[source.notna()] >= definition["threshold"]
    output_frame = source_frame.copy()
    output_frame[output_name] = output

    relative_dir = Path("derived") / "statistical_exploration" / fingerprint
    artifact_rel = (relative_dir / "data.csv").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel
    _write_frame_artifact(artifact_path, output_frame, "csv")
    artifact_id = f"derived_data_{fingerprint[:24]}"
    recipe_artifact_id = f"derived_data_recipe_{fingerprint[:24]}"
    recipe = {
        "schema_version": "statistical-derived-boolean.v1",
        "spec": spec.to_dict(),
        "source": {
            "artifact_id": source_artifact_id,
            "sha256": source_sha256,
        },
        "definition": definition,
        "result": {
            "artifact_id": artifact_id,
            "path": artifact_rel,
            "child_node_id": f"data-derive:{fingerprint[:24]}",
        },
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe:
        raise StatisticalExplorationValidationError(
            "deterministic derived recipe path is occupied"
        )
    if not recipe_path.exists():
        write_json(recipe_path, recipe)
    _ensure_registered_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step="data.derive.boolean",
        inputs=[source_artifact_id],
    )
    _ensure_registered_artifact(
        run_root,
        artifact_id=recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="data.derive.boolean",
        inputs=[source_artifact_id, artifact_id],
    )

    child_node_id = f"data-derive:{fingerprint[:24]}"
    execution_key = f"derive_{fingerprint[:24]}"
    branch_id = f"data-derive:{fingerprint[:20]}"

    def commit_graph_child(current: Graph) -> Graph:
        if child_node_id in current.nodes:
            return current
        child = Node(
            id=child_node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label=f"Derive {output_name}",
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_stage_id=source_node_id,
            branch_id=branch_id,
            trust=Trust.OK,
            payload_ref=artifact_rel,
            summary=(
                f"{output_name} = {source_column} {definition['comparison']} "
                f"p{definition['percentile']:.0f} ({definition['threshold']:.6g}); "
                f"{len(output_frame)} rows"
            ),
            annotations=(
                {
                    "type": "data_operation",
                    "operation_id": "data.derive.boolean",
                    "execution_key": execution_key,
                    "recipe_path": recipe_rel,
                    "source_fingerprint": fingerprint,
                    "definition": definition,
                },
            ),
            stage=Stage.TRANSFORM,
        )
        nodes = _mark_downstream_invalidation(
            {**current.nodes, child_node_id: child},
            reason="data_derive_boolean",
            source_node_id=source_node_id,
            child_node_id=child_node_id,
        )
        edges = dict(current.edges)
        edges[f"edge:{child_node_id}"] = Edge(
            id=f"edge:{child_node_id}",
            source_id=source_node_id,
            target_id=child_node_id,
            op="data.derive.boolean",
            params={"definition": definition, "execution_key": execution_key},
        )
        branches = dict(current.branches)
        branches[branch_id] = BranchRef(
            id=branch_id,
            forked_from_node_id=source_node_id,
            head_node_ids=(child_node_id,),
        )
        return Graph(
            schema_version=current.schema_version,
            run_id=current.run_id,
            nodes=nodes,
            edges=edges,
            branches=branches,
            legacy=current.legacy,
        )

    _graph_store_for(run_root).mutate(source_run_id, commit_graph_child)
    _ensure_node_index_entry(
        run_root,
        child_node_id=child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
        producing_stage="data.derive.boolean",
    )
    return {
        "child_node_id": child_node_id,
        "artifact_id": artifact_id,
        "artifact_path": artifact_rel,
        "recipe_artifact_id": recipe_artifact_id,
        "recipe_path": recipe_rel,
        "threshold": definition["threshold"],
        "output_name": output_name,
    }


def _scatter_columns(frame: pd.DataFrame, spec: ExplorationSpec) -> tuple[str, str]:
    x_column = spec.options.get("x_column")
    y_column = spec.options.get("y_column")
    if not isinstance(x_column, str) or not isinstance(y_column, str):
        raise StatisticalExplorationValidationError(
            "scatter requires x_column and y_column"
        )
    for column in (x_column, y_column):
        _require_column(frame, column)
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise StatisticalExplorationValidationError(
                f"scatter column must be numeric: {column}"
            )
    if x_column == y_column:
        raise StatisticalExplorationValidationError("scatter x_column and y_column must differ")
    return x_column, y_column


def _persist_statistical_scatter(
    run_root: Path,
    *,
    source_artifact_id: str,
    source_frame: pd.DataFrame,
    spec: ExplorationSpec,
    fingerprint: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    from .visualization import write_statistical_scatter

    filtered = _apply_filters(source_frame, spec.filters)
    x_column, y_column = _scatter_columns(filtered, spec)
    artifact_id = f"statistical_scatter_{fingerprint[:24]}"
    artifact_rel = f"figures/statistical_scatter_{fingerprint[:24]}.png"
    artifact_path = run_root / artifact_rel
    plotted_n = write_statistical_scatter(
        filtered,
        artifact_path,
        x_column=x_column,
        y_column=y_column,
    )
    _ensure_exploration_artifact(
        run_root,
        artifact_id=artifact_id,
        path=artifact_path,
        artifact_type="figure",
        step="statistical_exploration",
        inputs=[source_artifact_id],
    )
    return {
        "artifact_id": artifact_id,
        "path": artifact_rel,
        "x_column": x_column,
        "y_column": y_column,
        "plotted_row_count": plotted_n,
        "fingerprint": fingerprint,
    }


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


def _derived_definition(spec: ExplorationSpec) -> tuple[str, float, str, str]:
    source_column = spec.options.get("source_column")
    if source_column is None and len(spec.selected_columns) == 1:
        source_column = spec.selected_columns[0]
    percentile = spec.options.get("percentile")
    comparison = spec.options.get("comparison")
    output_name = spec.options.get("output_name")
    if not isinstance(source_column, str) or not source_column.strip():
        raise StatisticalExplorationValidationError(
            "derive_boolean requires a source_column"
        )
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)) or not 0 <= percentile <= 100:
        raise StatisticalExplorationValidationError(
            "derive_boolean percentile must be between 0 and 100"
        )
    if comparison not in {"lte", "gte"}:
        raise StatisticalExplorationValidationError(
            "derive_boolean comparison must be lte or gte"
        )
    if not isinstance(output_name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", output_name) is None:
        raise StatisticalExplorationValidationError(
            "derive_boolean output_name must be a valid column name"
        )
    return source_column, float(percentile), comparison, output_name


def _derived_boolean_series(
    frame: pd.DataFrame,
    spec: ExplorationSpec,
) -> tuple[pd.Series, dict[str, Any]]:
    source_column, percentile, comparison, output_name = _derived_definition(spec)
    _require_column(frame, source_column)
    if not pd.api.types.is_numeric_dtype(frame[source_column]):
        raise StatisticalExplorationValidationError(
            f"derive_boolean source column must be numeric: {source_column}"
        )
    source = frame[source_column]
    complete = source.dropna()
    if complete.empty:
        raise StatisticalExplorationValidationError(
            f"derive_boolean source column has no nonmissing values: {source_column}"
        )
    threshold = float(complete.quantile(percentile / 100, interpolation="linear"))
    derived = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    if comparison == "lte":
        derived.loc[source.notna()] = source.loc[source.notna()] <= threshold
    else:
        derived.loc[source.notna()] = source.loc[source.notna()] >= threshold
    counts = {
        "true": int((derived == True).sum()),  # noqa: E712
        "false": int((derived == False).sum()),  # noqa: E712
        "missing": int(derived.isna().sum()),
    }
    definition = {
        "source_column": source_column,
        "percentile": percentile,
        "comparison": comparison,
        "output_name": output_name,
        "threshold": threshold,
        "counts": counts,
        "preview": [None if pd.isna(value) else bool(value) for value in derived.tolist()[:20]],
    }
    return derived, definition


def _derived_boolean_result(frame: pd.DataFrame, spec: ExplorationSpec) -> dict[str, Any]:
    _derived, definition = _derived_boolean_series(frame, spec)
    return definition


__all__ = [
    "SCHEMA_VERSION",
    "ExplorationSpec",
    "FilterSpec",
    "StatisticalExplorationValidationError",
    "canonical_spec_json",
    "execute_exploration",
    "exploration_fingerprint",
]
