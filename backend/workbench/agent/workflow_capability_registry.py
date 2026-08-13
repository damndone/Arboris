"""Live declaration registry for workflow-executable capability gaps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


WORKFLOW_CAPABILITY_DISPATCHER = "workbench.agent.workflow_runtime.workflow_capability"


class WorkflowCapabilityRegistryError(ValueError):
    """A capability declaration cannot be safely published or resolved."""


@dataclass(frozen=True)
class WorkflowCapabilityOperation:
    operation_id: str
    kind: str
    summary: str
    adapter_key: str
    input_mode: str = "frame"
    request_schema: Mapping[str, Any] = None  # type: ignore[assignment]
    output_schema_ref: str = ""
    produces_dataset: bool = False
    dataset_kind: str | None = None
    accepted_dataset_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise WorkflowCapabilityRegistryError("workflow capability operation_id is required")
        if not isinstance(self.adapter_key, str) or not self.adapter_key:
            raise WorkflowCapabilityRegistryError("workflow capability adapter is required")
        if self.input_mode != "frame":
            raise WorkflowCapabilityRegistryError("workflow capability input_mode must be frame")
        from .workflow_capability_adapters import get_workflow_capability_adapter

        try:
            get_workflow_capability_adapter(self.adapter_key)
        except KeyError as exc:
            raise WorkflowCapabilityRegistryError(str(exc)) from exc
        if not isinstance(self.request_schema, Mapping):
            raise WorkflowCapabilityRegistryError("workflow capability request_schema is required")
        if not self.output_schema_ref:
            raise WorkflowCapabilityRegistryError("workflow capability output_schema_ref is required")
        if self.produces_dataset != (self.dataset_kind is not None):
            raise WorkflowCapabilityRegistryError(
                "workflow capability dataset producer must declare exactly one dataset_kind"
            )
    def _adapter(self):
        from .workflow_capability_adapters import get_workflow_capability_adapter

        return get_workflow_capability_adapter(self.adapter_key)

    def validate_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._adapter().validate_request(self.operation_id, request)

    def validate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.validate_request(request)

    def execute(self, frame: Any, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._adapter().execute(frame, request).payload

    def validate_result(self, result: Mapping[str, Any]) -> None:
        self._adapter().validate_result(self.operation_id, result)

    def execute_with_context(self, frame: Any, request: Mapping[str, Any]):
        from .workflow_capability_adapters import (
            WorkflowCapabilityExecution,
            get_workflow_capability_adapter,
        )

        adapter = get_workflow_capability_adapter(self.adapter_key)
        normalized = adapter.validate_request(self.operation_id, request)
        execution = adapter.execute(frame, normalized)
        if not isinstance(execution, WorkflowCapabilityExecution):
            raise WorkflowCapabilityRegistryError(
                f"workflow capability {self.operation_id} adapter returned an invalid execution"
            )
        adapter.validate_result(self.operation_id, execution.payload)
        if self.produces_dataset:
            if execution.output_frame is None:
                raise WorkflowCapabilityRegistryError(
                    f"workflow capability {self.operation_id} declares a dataset but returned no frame"
                )
            if execution.dataset_kind != self.dataset_kind:
                raise WorkflowCapabilityRegistryError(
                    f"workflow capability {self.operation_id} returned dataset kind "
                    f"{execution.dataset_kind!r}, expected {self.dataset_kind!r}"
                )
            if execution.payload.get("dataset_kind") != self.dataset_kind:
                raise WorkflowCapabilityRegistryError(
                    f"workflow capability {self.operation_id} payload dataset kind is inconsistent"
                )
        elif execution.output_frame is not None or execution.dataset_kind is not None:
            raise WorkflowCapabilityRegistryError(
                f"workflow capability {self.operation_id} is not a dataset producer"
            )
        return normalized, execution


class WorkflowCapabilityRegistry:
    """Immutable-by-convention registry with duplicate and adapter checks."""

    def __init__(self, operations: Mapping[str, WorkflowCapabilityOperation]):
        values = dict(operations)
        if set(values) != {operation.operation_id for operation in values.values()}:
            raise WorkflowCapabilityRegistryError("workflow capability registry keys must match operation ids")
        self._operations = values

    def operation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    def require(self, operation_id: str) -> WorkflowCapabilityOperation:
        try:
            return self._operations[operation_id]
        except KeyError as exc:
            raise WorkflowCapabilityRegistryError(
                f"unknown workflow capability operation: {operation_id}"
            ) from exc


def _live_declarations() -> tuple[dict[str, Any], ...]:
    """Read every public source registry and derive this seam's entries."""

    from ..statistical_tests import TEST_FAMILIES
    from ..engine.packs.builtin_declarations import BUILTIN_PACK_DECLARATIONS
    from ..engine.capabilities import build_capabilities

    # Capability discovery is part of app import.  It must not bootstrap every
    # executable pack just to publish a typed workflow contract: ARMA-GARCH's
    # optional ``arch`` dependency loads Matplotlib and can block legacy graph
    # startup on font-cache initialization.  The builtin declaration manifest
    # supplies the pack identities; the execution adapters remain the final
    # owner of runtime imports and validation.
    manifest = build_capabilities(bootstrap_packs=False)
    declarations: list[dict[str, Any]] = []
    for family, contract in sorted(TEST_FAMILIES.items()):
        declarations.append({
            "operation_id": f"test.{family}",
            "kind": "statistical_test",
            "summary": contract.summary,
            "adapter_key": "statistical_test",
            "produces_dataset": False,
        })
    for entry in manifest["prediction_models"]:
        key = str(entry["key"])
        declarations.append({
            "operation_id": f"prediction.{key}",
            "kind": "prediction_model",
            "summary": (
                f"{str(entry['description']).rstrip('.')}. Execute the bounded "
                "out-of-sample prediction protocol."
            ),
            "adapter_key": "prediction_model",
            "produces_dataset": False,
            "accepted_dataset_kinds": (
                "derived_data",
                "prepared_data",
                "prediction_training_data",
            ),
        })
    for entry in manifest["sampling_methods"]:
        key = str(entry["key"])
        declarations.append({
            "operation_id": f"resample.{key}",
            "kind": "data_preparation",
            "summary": f"Resample prediction-training data with {entry['label']}.",
            "adapter_key": "resampling",
            "produces_dataset": True,
            "dataset_kind": "prediction_training_data",
            "accepted_dataset_kinds": ("derived_data", "prepared_data"),
        })
    for entry in manifest["imputation_methods"]:
        key = str(entry["key"])
        declarations.append({
            "operation_id": f"imputation.{key}",
            "kind": "data_preparation",
            "summary": str(entry["description"]),
            "adapter_key": "imputation",
            "produces_dataset": True,
            "dataset_kind": "prepared_data",
            "accepted_dataset_kinds": ("derived_data", "prepared_data"),
        })
    model_entries = list(manifest["model_types"])
    model_entry_keys = {str(entry.get("key")) for entry in model_entries}
    for pack in BUILTIN_PACK_DECLARATIONS:
        if pack.model_type.startswith("time_series.") and pack.model_type not in model_entry_keys:
            model_entries.append({"key": pack.model_type})
            model_entry_keys.add(pack.model_type)

    from .workflow_capability_adapters import (
        get_workflow_capability_adapter,
        workflow_capability_request_schema,
    )

    for entry in model_entries:
        key = str(entry["key"])
        if key != "auto" and not key.startswith("time_series."):
            continue
        adapter_key = "auto_model" if key == "auto" else key.removeprefix("time_series.")
        try:
            get_workflow_capability_adapter(adapter_key)
            workflow_capability_request_schema(adapter_key)
        except KeyError as exc:
            raise WorkflowCapabilityRegistryError(
                f"{key} has no declared generic workflow adapter"
            ) from exc
        declarations.append({
            "operation_id": f"model.{key}",
            "kind": "selector" if key == "auto" else "model_family",
            "summary": str(entry.get("description") or f"Execute {key} through its registered model pack."),
            "adapter_key": adapter_key,
            "produces_dataset": False,
            "accepted_dataset_kinds": ("derived_data", "prepared_data"),
        })
    unique: dict[str, dict[str, Any]] = {}
    for declaration in declarations:
        operation_id = declaration["operation_id"]
        if operation_id in unique:
            raise WorkflowCapabilityRegistryError(
                f"duplicate live workflow capability declaration: {operation_id}"
            )
        unique[operation_id] = declaration
    return tuple(unique[key] for key in sorted(unique))


def declared_workflow_capability_ids() -> tuple[str, ...]:
    return tuple(item["operation_id"] for item in _live_declarations())


def _build_registry() -> WorkflowCapabilityRegistry:
    from .workflow_capability_adapters import workflow_capability_request_schema

    operations: dict[str, WorkflowCapabilityOperation] = {}
    for declaration in _live_declarations():
        operation_id = str(declaration["operation_id"])
        adapter_key = str(declaration["adapter_key"])
        operations[operation_id] = WorkflowCapabilityOperation(
            operation_id=operation_id,
            kind=str(declaration["kind"]),
            summary=str(declaration["summary"]),
            adapter_key=adapter_key,
            request_schema=workflow_capability_request_schema(adapter_key),
            output_schema_ref=f"workbench.workflow-capability.{operation_id}/v1",
            produces_dataset=bool(declaration.get("produces_dataset", False)),
            dataset_kind=declaration.get("dataset_kind"),
            accepted_dataset_kinds=tuple(declaration.get("accepted_dataset_kinds", ())),
        )
    return WorkflowCapabilityRegistry(operations)


def workflow_capability_registry() -> WorkflowCapabilityRegistry:
    return _build_registry()


def workflow_capability_step_contracts() -> dict[str, Any]:
    """Project the live adapter declarations into workflow step contracts."""

    from .workflow_contracts import StepSpecContract

    contracts: dict[str, StepSpecContract] = {}
    for operation in workflow_capability_registry()._operations.values():
        contracts[operation.operation_id] = StepSpecContract(
            summary=operation.summary,
            fields={
                "input_mode": "The typed adapter input mode; only frame is executable.",
                "column_bindings": "Server-owned source-column bindings for the selected adapter.",
                "options": "Adapter-owned typed options. Code, formulas, paths, and callbacks are refused.",
            },
            required=("input_mode", "column_bindings", "options"),
            field_types={"input_mode": "string", "column_bindings": "object", "options": "object"},
            field_enums={"input_mode": ("frame",)},
            field_schemas={
                "column_bindings": operation.request_schema["properties"]["column_bindings"],
                "options": operation.request_schema["properties"]["options"],
            },
            semantic_validator_key="workflow_capability",
            column_extractor_key="workflow_capability",
            output_schema_ref=operation.output_schema_ref,
            dispatcher_key=WORKFLOW_CAPABILITY_DISPATCHER,
            scope="typed workflow capability",
            risk_level="mutating" if operation.produces_dataset else "none",
            effect_level="mutation" if operation.produces_dataset else "read_only",
            reconciler_key=WORKFLOW_CAPABILITY_DISPATCHER,
            diff_builder_key="workflow_capability.diff.v1",
            verification_builder_key="workflow_capability.verification.v1",
            ui_description=operation.summary,
            capability_kind=operation.kind,
            natural_language_enabled=False,
            produces_dataset=operation.produces_dataset,
            produced_dataset_kind=operation.dataset_kind,
            accepted_dataset_kinds=operation.accepted_dataset_kinds,
            consumes_input_frame=True,
            replayable_by_recipe=False,
            top_level_exposure_note="Available as a typed step inside operation.multi_step; it is not a separate top-level Agent proposal.",
        )
    return contracts


__all__ = [
    "WORKFLOW_CAPABILITY_DISPATCHER",
    "WorkflowCapabilityOperation",
    "WorkflowCapabilityRegistry",
    "WorkflowCapabilityRegistryError",
    "declared_workflow_capability_ids",
    "workflow_capability_registry",
    "workflow_capability_step_contracts",
]
