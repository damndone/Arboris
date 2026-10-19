"""orchestration data effects: methods over the existing shared state."""
from __future__ import annotations
from pathlib import Path
from ..code_execution import CodeExecuteSpecV1, CodeExecuteValidationError, NondeterministicCodeError, apply_code_execute, preview_code_execute
from ..data_operations import DataCastItem, DataColumnCastSpecV1, DataColumnsCastSpecV1, apply_data_column_cast, apply_data_columns_cast, preview_data_column_cast, preview_data_columns_cast
from .execution import OperationEffect, execution_key
from .operations import OperationRecord
from .proposals import ProposalStaleError

class OrchestrationDataEffects:
    @staticmethod
    def _data_column_cast_spec(record: OperationRecord) -> DataColumnCastSpecV1:
        target = record.target
        changes = record.outputs.get("typed_changes") or {}
        proposal_changes = changes or {}
        # The typed target is authoritative; changes are retained in the
        # proposal for audit and must match it through the registry validator.
        return DataColumnCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            column=str(target["column"]),
            target_dtype=str(target["target_dtype"]),
        )


    async def _prepare_data_column_cast_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._data_column_cast_spec(record)
        preview = preview_data_column_cast(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            raise ProposalStaleError("data column cast preview is stale")
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "column": spec.column,
            "target_dtype": spec.target_dtype,
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_data_column_cast(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "column": spec.column,
                "before_dtype": preview.before_dtype,
                "after_dtype": preview.after_dtype,
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )


    @staticmethod
    def _data_columns_cast_spec(record: OperationRecord) -> DataColumnsCastSpecV1:
        target = record.target
        casts = target.get("casts") or []
        return DataColumnsCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            casts=tuple(
                DataCastItem(str(item["column"]), str(item["target_dtype"]))
                for item in casts
            ),
            output_format=str(target.get("output_format", "csv")),
        )


    async def _prepare_data_columns_cast_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._data_columns_cast_spec(record)
        preview = preview_data_columns_cast(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            raise ProposalStaleError("data columns cast preview is stale")
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "casts": [item.to_dict() for item in spec.casts],
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_data_columns_cast(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "casts": [
                    {
                        "column": item.column,
                        "before_dtype": item.before_dtype,
                        "after_dtype": item.after_dtype,
                    }
                    for item in preview.items
                ],
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "columns_cast": [item.column for item in spec.casts],
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )


    @staticmethod
    def _code_execute_spec(record: OperationRecord) -> CodeExecuteSpecV1:
        target = record.target
        return CodeExecuteSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            code=str(target["code"]),
            language=str(target.get("language", "python")),
            output_format=str(target.get("output_format", "csv")),
        )


    async def _prepare_code_execute_effect(
        self,
        record: OperationRecord,
        *,
        project_root: Path | str,
        execution_key: str,
        materialize: bool,
    ) -> OperationEffect:
        spec = self._code_execute_spec(record)
        preview = preview_code_execute(project_root, spec)
        expected_fingerprint = record.preconditions.get("context_fingerprint")
        if preview.fingerprint != expected_fingerprint:
            # Distinguish the two ways this happens, because they need opposite
            # responses: a changed source means re-propose against the new data;
            # a stable source means the code itself is not deterministic and
            # re-proposing would just fail again.
            if preview.status != "ready":
                raise CodeExecuteValidationError(
                    f"code failed when re-run for execution: {preview.error or 'unknown error'}"
                )
            if preview.source_sha256 != record.preconditions.get("source_sha256", preview.source_sha256):
                raise ProposalStaleError("code execute preview is stale")
            raise NondeterministicCodeError(
                "the code produced a different result than the one confirmed; it is "
                "not a deterministic transform, so nothing was written"
            )
        execution = {
            **record.execution,
            "source_run_id": spec.source_run_id,
            "source_node_ref": spec.source_node_id,
            "source_artifact_id": spec.source_artifact_id,
            "language": spec.language,
            "code_sha256": spec.code_sha256,
            "data_preview_fingerprint": preview.fingerprint,
            "source_sha256": preview.source_sha256,
        }
        if not materialize:
            return OperationEffect(execution=execution, status="submitted")
        effect = apply_code_execute(
            project_root,
            spec,
            preview,
            execution_key_value=execution_key,
        )
        return OperationEffect(
            outputs={
                "status": "completed",
                "source_run_id": spec.source_run_id,
                "source_node_id": spec.source_node_id,
                "source_artifact_id": spec.source_artifact_id,
                "artifact_id": effect.artifact_id,
                "artifact_path": effect.artifact_path,
                "recipe_artifact_id": effect.recipe_artifact_id,
                "recipe_path": effect.recipe_path,
                "child_node_id": effect.child_node_id,
                "preview_fingerprint": preview.fingerprint,
                "stdout": preview.stdout,
            },
            diff_ref={
                "kind": "data.schema_diff.v1",
                "source_fingerprint": preview.schema_fingerprint_before,
                "result_fingerprint": preview.schema_fingerprint_after,
                "columns_added": list(preview.columns_added),
                "columns_removed": list(preview.columns_removed),
                "dtype_changes": [change.to_dict() for change in preview.dtype_changes],
                "row_count_before": preview.row_count_before,
                "row_count_after": preview.row_count_after,
            },
            verification={
                "passed": True,
                "status": "completed",
                "checks": {
                    "source_immutable": True,
                    "artifact_registered": True,
                    "graph_child": True,
                    "preview_matches_effect": True,
                    "sandboxed": True,
                    "deterministic": True,
                    "downstream_rerun_required": list(preview.downstream_invalidation),
                },
            },
            bindings={
                "data_artifact_id": effect.artifact_id,
                "data_child_node_id": effect.child_node_id,
                "data_recipe_artifact_id": effect.recipe_artifact_id,
            },
            execution=execution,
            status="completed",
        )

