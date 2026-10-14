"""Datasets: bounded read-only context projection."""

from __future__ import annotations
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from ...artifacts import read_json, sha256_file
from ...graph_store import GraphStore
from ...data_operations import _read_frame
from ...graph_model import NodeKind
from ..tools import ToolVisibleError
from ..bounds import _public_positive_int, _public_stat_number
from .coefficients import (
    _MAX_VALUE_LABELS_PER_COLUMN,
    _bounded_declared_metadata,
    _run_declared_labels,
)
from .requests import (
    InspectDataSchemaRequest,
    InspectProjectDatasetSchemaRequest,
    InspectProjectNumericSummaryRequest,
    ListProjectDatasetsRequest,
)
from .summaries import (
    _bounded_node,
)



class DatasetsMixin:
    def list_project_datasets(
        self,
        request: ListProjectDatasetsRequest,
    ) -> dict[str, Any]:
        """Return real materialized dataset identities from graph and index evidence."""

        detail_keys = {(item["run_id"], item["node_id"]) for item in request.detail_for}
        runs_root = self.project_root / "runs"
        datasets: list[dict[str, Any]] = []
        unavailable: list[dict[str, str]] = []
        omitted_sections: list[str] = []
        if runs_root.is_dir():
            run_dirs = sorted(item for item in runs_root.iterdir() if item.is_dir())
        else:
            run_dirs = []

        for run_root in run_dirs:
            run_id = run_root.name
            try:
                graph = GraphStore(runs_root).read(run_id)
            except Exception as exc:  # noqa: BLE001 - convert corrupt evidence to a visible record
                unavailable.append(
                    {
                        "run_id": run_id,
                        "node_id": "*",
                        "reason": f"graph_unavailable: {exc}",
                    }
                )
                continue
            dataset_nodes = [
                node
                for node in graph.nodes.values()
                if node.kind == NodeKind.DATASET_STAGE
            ]
            if not dataset_nodes:
                continue
            try:
                index_payload = read_json(run_root / "artifacts_index.json")
            except (OSError, ValueError) as exc:
                for node in sorted(dataset_nodes, key=lambda item: item.id):
                    unavailable.append(
                        {
                            "run_id": run_id,
                            "node_id": node.id,
                            "reason": f"artifact_index_unavailable: {exc}",
                        }
                    )
                continue
            records = index_payload.get("artifacts") if isinstance(index_payload, Mapping) else None
            if not isinstance(records, list):
                for node in sorted(dataset_nodes, key=lambda item: item.id):
                    unavailable.append(
                        {
                            "run_id": run_id,
                            "node_id": node.id,
                            "reason": "artifact_index_invalid: artifacts is not a list",
                        }
                    )
                continue

            for node in sorted(dataset_nodes, key=lambda item: item.id):
                artifact, reason = self._dataset_artifact_record(run_root, node, records)
                if artifact is None:
                    unavailable.append(
                        {"run_id": run_id, "node_id": node.id, "reason": reason or "unavailable"}
                    )
                    continue
                relative = artifact["path"]
                path = (run_root / relative).resolve()
                try:
                    frame = _read_frame(path)
                except Exception as exc:  # noqa: BLE001 - expose unusable materialized evidence
                    unavailable.append(
                        {
                            "run_id": run_id,
                            "node_id": node.id,
                            "reason": f"dataset_read_failed: {exc}",
                        }
                    )
                    continue
                columns = [str(column) for column in frame.columns]
                public_columns = columns[:64]
                columns_omitted = max(0, len(columns) - len(public_columns))
                if columns_omitted:
                    omitted_sections.append(f"{run_id}:{node.id}:columns")
                no_missing = [
                    column for column in columns if not bool(frame[column].isna().any())
                ]
                public_no_missing = no_missing[:64]
                if len(no_missing) > len(public_no_missing):
                    omitted_sections.append(f"{run_id}:{node.id}:columns_without_missing")
                entry: dict[str, Any] = {
                    "run_id": run_id,
                    "node_id": node.id,
                    "artifact_id": artifact["artifact_id"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(columns)),
                    "columns": public_columns,
                    "columns_omitted": columns_omitted,
                    "columns_without_missing": public_no_missing,
                }
                declared_metadata = _bounded_declared_metadata(_run_declared_labels(run_root))
                if declared_metadata is not None:
                    entry["declared_metadata"] = declared_metadata
                if (run_id, node.id) in detail_keys:
                    entry["column_details"] = [
                        self._dataset_column_detail(frame, column)
                        for column in public_columns
                    ]
                datasets.append(entry)

        missing_details = detail_keys - {
            (entry["run_id"], entry["node_id"])
            for entry in datasets
        }
        if missing_details:
            known_unavailable = {
                (entry["run_id"], entry["node_id"])
                for entry in unavailable
            }
            unresolved = sorted(missing_details - known_unavailable)
            if unresolved:
                raise ToolVisibleError(
                    "PROJECT_DATASET_DETAIL_UNAVAILABLE: no graph-backed dataset exists for "
                    + ", ".join(f"{run_id}/{node_id}" for run_id, node_id in unresolved)
                )

        return {
            "datasets": datasets,
            "datasets_omitted": 0,
            "unavailable": unavailable,
            "omitted_sections": omitted_sections,
        }

    @staticmethod
    def _dataset_artifact_record(
        run_root: Path,
        node: Any,
        records: list[Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        if node.payload_ref:
            candidates = [
                item
                for item in records
                if isinstance(item, Mapping) and item.get("path") == node.payload_ref
            ]
        elif node.id in {"stage:raw", "stage:source"}:
            candidates = [
                item
                for item in records
                if isinstance(item, Mapping)
                and item.get("artifact_type") == "raw_data"
                and str(item.get("path") or "").startswith("raw_snapshot/")
            ]
        else:
            return None, "dataset_node_has_no_materialized_payload"
        if len(candidates) != 1:
            return None, f"dataset_artifact_identity_ambiguous: {len(candidates)} matching records"
        candidate = candidates[0]
        artifact_id = candidate.get("artifact_id")
        relative = candidate.get("path")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            return None, "dataset_artifact_has_no_id"
        if not isinstance(relative, str) or not relative.strip():
            return None, "dataset_artifact_has_no_path"
        path = (run_root / relative).resolve()
        try:
            path.relative_to(run_root.resolve())
        except ValueError:
            return None, "dataset_artifact_escapes_run_root"
        if not path.is_file():
            return None, "dataset_artifact_file_missing"
        expected_sha = candidate.get("sha256")
        if not isinstance(expected_sha, str) or not expected_sha:
            return None, "dataset_artifact_has_no_hash"
        if sha256_file(path) != expected_sha:
            return None, "dataset_artifact_hash_mismatch"
        return {"artifact_id": artifact_id, "path": relative}, None

    @staticmethod
    def _dataset_column_detail(frame: Any, column: str) -> dict[str, Any]:
        series = frame[column]
        detail: dict[str, Any] = {
            "name": column,
            "dtype": str(series.dtype),
            "unique_count": int(series.nunique(dropna=True)),
        }
        missing_rate = float(series.isna().mean()) if len(series) else 0.0
        if missing_rate > 0:
            detail["missing_rate"] = missing_rate
        return detail

    def inspect_project_dataset_schema(
        self,
        request: InspectProjectDatasetSchemaRequest,
    ) -> dict[str, Any]:
        """Return bounded column metadata without raw rows or profile statistics."""

        run_root = self._project_run_root(request.run_id)
        try:
            profile = read_json(run_root / "staged" / "data_profile.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: no persisted dataset schema is "
                f"available for {request.run_id!r}."
            ) from exc
        if not isinstance(profile, dict):
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: the persisted dataset schema is invalid."
            )

        source_columns = profile.get("columns")
        if not isinstance(source_columns, dict):
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: the persisted dataset schema has no columns."
            )
        declared = _run_declared_labels(run_root)
        columns: list[dict[str, Any]] = []
        for name, metadata in sorted(source_columns.items(), key=lambda item: str(item[0])):
            if not isinstance(name, str) or not name or not isinstance(metadata, dict):
                continue
            column: dict[str, Any] = {
                "name": name,
                "dtype": metadata.get("dtype") if isinstance(metadata.get("dtype"), str) else None,
                "missing_rate": _public_stat_number(metadata.get("missing_rate")),
                "unique_count": _public_positive_int(metadata.get("unique_count")),
            }
            for field, key in (
                ("variable_labels", "variable_label"),
                ("measurement_level", "measurement_level"),
                ("user_missing_values", "user_missing_values"),
            ):
                mapping = declared.get(field)
                if isinstance(mapping, dict) and name in mapping:
                    column[key] = mapping[name]
            value_labels = declared.get("value_labels")
            if isinstance(value_labels, dict) and isinstance(value_labels.get(name), dict):
                mapping = value_labels[name]
                column["value_labels"] = {
                    key: mapping[key] for key in sorted(mapping)[:_MAX_VALUE_LABELS_PER_COLUMN]
                }
            columns.append(column)
        public_columns = columns[:64]
        return {
            "run_id": request.run_id,
            "row_count": _public_positive_int(profile.get("row_count")),
            "column_count": _public_positive_int(profile.get("column_count")),
            "columns": public_columns,
            "columns_omitted": max(len(columns) - len(public_columns), 0),
            "evidence_ref": {
                "run_id": request.run_id,
                "profile_ref": "staged/data_profile.json",
            },
            "omitted_sections": [
                "raw_rows",
                "correlations",
                "column_descriptives",
            ],
        }

    def inspect_project_numeric_summary(
        self,
        request: InspectProjectNumericSummaryRequest,
    ) -> dict[str, Any]:
        """Return persisted numeric aggregates for explicitly requested columns.

        The profile is already a server-produced aggregate.  This reader keeps
        that boundary intact: it discloses no rows, values, correlations, or
        unrequested columns, and it distinguishes an unavailable statistic from
        a zero-valued one.
        """

        run_root = self._project_run_root(request.run_id)
        try:
            profile = read_json(run_root / "staged" / "data_profile.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ToolVisibleError(
                "PROJECT_NUMERIC_SUMMARY_UNAVAILABLE: no persisted numeric summary is "
                f"available for {request.run_id!r}."
            ) from exc
        source_columns = profile.get("columns") if isinstance(profile, dict) else None
        if not isinstance(source_columns, dict):
            raise ToolVisibleError(
                "PROJECT_NUMERIC_SUMMARY_UNAVAILABLE: the persisted dataset profile is invalid."
            )

        numeric_summary: list[dict[str, Any]] = []
        unavailable_columns: list[str] = []
        for column in sorted(set(request.columns)):
            metadata = source_columns.get(column)
            mean = _public_stat_number(metadata.get("mean")) if isinstance(metadata, dict) else None
            if mean is None:
                unavailable_columns.append(column)
                continue
            numeric_summary.append(
                {
                    "column": column,
                    "mean": mean,
                    "std": _public_stat_number(metadata.get("std")),
                }
            )
        return {
            "run_id": request.run_id,
            "numeric_summary": numeric_summary,
            "unavailable_columns": unavailable_columns,
            "evidence_ref": {
                "run_id": request.run_id,
                "profile_ref": "staged/data_profile.json",
            },
            "omitted_sections": ["raw_rows", "correlations"],
        }

    def inspect_data_schema(
        self,
        request: InspectDataSchemaRequest,
    ) -> dict[str, Any]:
        """Return a dataset node's columns and dtypes, read-only.

        The Agent needs this to propose a data operation at all: without it the
        only way to name a column is to guess one out of display text. It
        deliberately does NOT return the artifact id — that stays a backend
        fact bound during proposal canonicalization, so a model can never point
        an operation at an artifact it named itself.
        """

        from ...data_operations import (
            DataColumnCastValidationError,
            resolve_data_column_cast_context,
        )

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        try:
            context = resolve_data_column_cast_context(
                self.project_root,
                source_run_id=request.owner_run_id,
                source_node_id=request.op_node_id,
            )
        except DataColumnCastValidationError as exc:
            return {
                **canonical,
                "node": _bounded_node(node),
                "data_schema": {"available": False, "reason": str(exc)},
            }
        return {
            **canonical,
            "node": _bounded_node(node),
            "data_schema": {
                "available": True,
                "row_count": context["row_count"],
                "columns": context["columns"],
                "downstream_invalidation": context["downstream_invalidation"],
                **(
                    {"declared_metadata": declared_metadata}
                    if (
                        declared_metadata := _bounded_declared_metadata(
                            _run_declared_labels(self.project_root / "runs" / request.owner_run_id)
                        )
                    )
                    is not None
                    else {}
                ),
            },
            "omitted_sections": ["source_artifact_id", "raw_rows"],
        }

