"""Typed, source-bound statistical exploration contracts. (persist)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import pandas as pd
from .artifacts import read_json, register_artifact, sha256_file, write_json, write_text_durable
from .graph_model import Edge, Graph, Node, NodeKind, Stage, Trust
from .statistical_exploration_compute import (
    _apply_filters,
    _derived_boolean_series,
    _scatter_columns,
)
from .statistical_exploration_spec import (
    ExplorationSpec,
    SCHEMA_VERSION,
    StatisticalExplorationValidationError,
)


def resolve_statistical_source(
    project_root: Path | str,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Resolve a dataset node through the existing data-operation binding."""
    from .data_operations.casts import _resolve_data_column_cast_source

    context, frame = _resolve_data_column_cast_source(
        project_root,
        source_run_id=source_run_id,
        source_node_id=source_node_id,
    )
    if context["source_artifact_id"] != source_artifact_id:
        raise StatisticalExplorationValidationError(
            "source artifact is not owned by the selected dataset node"
        )
    return context, frame


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


def _correlation_table_rows(result: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Render a correlation result as a named square table.

    ``variables`` is a *list* for ``corr`` (not the mapping every other
    operation returns), so the generic branches below skip it and the matrix
    used to reach every surface as an unlabelled JSON array.
    """
    variables = result.get("variables")
    matrix = result.get("matrix")
    if not isinstance(variables, list) or not isinstance(matrix, list):
        return None
    if len(matrix) != len(variables):
        return None
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(variables):
        row = matrix[index]
        if not isinstance(row, list) or len(row) != len(variables):
            return None
        entry: dict[str, Any] = {"variable": str(name)}
        for position, column in enumerate(variables):
            entry[str(column)] = _table_cell(row[position])
        rows.append(entry)
    return rows


def _result_table_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    correlation_rows = _correlation_table_rows(result)
    if correlation_rows is not None:
        return correlation_rows
    variables = result.get("variables")
    if isinstance(variables, Mapping):
        rows: list[dict[str, Any]] = []
        for name, values in variables.items():
            row: dict[str, Any] = {"variable": str(name)}
            if isinstance(values, Mapping):
                for key, value in values.items():
                    row[str(key)] = _table_cell(value)
            else:
                row["value"] = _table_cell(values)
            rows.append(row)
        return rows
    groups = result.get("groups")
    if isinstance(groups, list):
        return [
            {str(key): _table_cell(value) for key, value in item.items()}
            for item in groups
            if isinstance(item, Mapping)
        ]
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


def _table_cell(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _exploration_tables(result: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    tables = {"result": _result_table_rows(result)}
    correlation_rows = _correlation_table_rows(result)
    if correlation_rows is not None:
        tables["correlation_matrix"] = correlation_rows
        pairs = result.get("pairs")
        if isinstance(pairs, list) and pairs:
            # Ranked pairs answer "most correlated with X" directly; the square
            # matrix answers "what is corr(a, b)".  Both are cheap, so ship both.
            tables["correlation_pairs"] = [
                {str(key): _table_cell(value) for key, value in item.items()}
                for item in pairs
                if isinstance(item, Mapping)
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
