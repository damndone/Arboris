"""service sources: methods over the existing shared state."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from ...data_operations import resolve_data_column_cast_context
from ..context_compiler import NotebookPlanningContextV1
from .execution_results import artifact_validation_scope, contract_artifact_projection, workflow_execution_receipt, workflow_produced_artifacts
from .errors import OptionRevisionStale, OptionValidationFailed
from .store import Notebook

class ServiceSources:
    def _workflow_source_pin(
        self, notebook: Notebook, context: NotebookPlanningContextV1
    ) -> dict[str, dict[str, str]]:
        """Rebuild the current server-owned source pin for a workflow option."""

        # Keeping publication and confirmation on this one pin builder avoids
        # a planner accepting a source identity that the executor later
        # interprets differently.  This import stays local to keep the
        # planning service independent at module initialization.
        from ..planning.normalize import _execution_pins

        pin = _execution_pins(context).get("workflow_source")
        if not isinstance(pin, Mapping):
            raise OptionValidationFailed(
                "the Notebook has no server-resolved raw source for a composed workflow",
                notebook_id=notebook.notebook_id,
            )
        target = pin.get("target")
        preconditions = pin.get("preconditions")
        if not isinstance(target, Mapping) or not isinstance(preconditions, Mapping):
            raise OptionValidationFailed(
                "the Notebook workflow source pin is incomplete",
                notebook_id=notebook.notebook_id,
            )
        return {
            "target": {str(key): str(value) for key, value in target.items()},
            "preconditions": {
                str(key): str(value) for key, value in preconditions.items()
            },
        }


    def _assert_dataset_workflow_source_current(self, notebook: Notebook) -> None:
        """Detect a changed or detached persisted raw artifact before execution."""

        source = notebook.projection_source
        if source is None or source.kind != "dataset" or source.workflow_source is None:
            return
        pinned = source.workflow_source
        try:
            current = resolve_data_column_cast_context(
                self.project_root,
                source_run_id=pinned.run_id,
                source_node_id=pinned.node_ref,
            )
        except Exception as error:
            raise OptionRevisionStale(
                "the Notebook raw workflow source is no longer available",
                notebook_id=notebook.notebook_id,
                reason="workflow_source_unavailable",
            ) from error
        if (
            current.get("source_artifact_id") != pinned.artifact_id
            or current.get("source_sha256") != pinned.source_sha256
        ):
            raise OptionRevisionStale(
                "the Notebook raw workflow source changed after planning",
                notebook_id=notebook.notebook_id,
                reason="workflow_source_changed",
            )


    def _workflow_execution_receipt(self, workflow: Any, state: Any) -> dict[str, Any]:
        return workflow_execution_receipt(
            self.project_root, workflow, state, read_run_artifacts=self._read_run_artifacts
        )


    def _workflow_produced_artifacts(self, workflow: Any, state: Any) -> list[dict[str, Any]]:
        return workflow_produced_artifacts(
            workflow, state, read_run_artifacts=self._read_run_artifacts
        )


    @staticmethod
    def _contract_artifact_projection(contract: Any, ambient_records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return contract_artifact_projection(contract, ambient_records)


    @staticmethod
    def _artifact_validation_scope(mode: str, ambient_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return artifact_validation_scope(mode, ambient_records)

