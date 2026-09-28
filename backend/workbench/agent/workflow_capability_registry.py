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


# ── declaration-derived Agent/Notebook cutover catalog ─────────────────

from dataclasses import dataclass


@dataclass(frozen=True)
class CutoverCapabilityDescriptorV1:
    provider_id: str
    path_id: str
    capability_id: str
    exposure: str
    adapter_id: str
    executor_ref: str
    operation_ref: str | None
    projection_keys: tuple[str, ...]
    renderer_ref_ids: tuple[str, ...]
    effect: str
    execution_allowed: bool
    provider_digest: str

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "path_id",
            "capability_id",
            "exposure",
            "adapter_id",
            "executor_ref",
            "effect",
            "provider_digest",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise WorkflowCapabilityRegistryError(f"cutover descriptor {name} is required")
        if self.operation_ref is not None and (type(self.operation_ref) is not str or not self.operation_ref):
            raise WorkflowCapabilityRegistryError("cutover descriptor operation_ref is invalid")
        if type(self.projection_keys) is not tuple or any(type(item) is not str or not item for item in self.projection_keys):
            raise WorkflowCapabilityRegistryError("cutover descriptor projection keys are invalid")
        if type(self.renderer_ref_ids) is not tuple or any(type(item) is not str or not item for item in self.renderer_ref_ids):
            raise WorkflowCapabilityRegistryError("cutover descriptor renderer refs are invalid")
        if type(self.execution_allowed) is not bool:
            raise WorkflowCapabilityRegistryError("cutover descriptor execution policy is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "path_id": self.path_id,
            "capability_id": self.capability_id,
            "exposure": self.exposure,
            "adapter_id": self.adapter_id,
            "executor_ref": self.executor_ref,
            "operation_ref": self.operation_ref,
            "projection_keys": list(self.projection_keys),
            "renderer_ref_ids": list(self.renderer_ref_ids),
            "effect": self.effect,
            "execution_allowed": self.execution_allowed,
            "provider_digest": self.provider_digest,
        }


class CutoverCapabilityCatalogV1:
    """A single provider/adapter projection consumed by Agent and Notebook."""

    def __init__(
        self,
        descriptors: tuple[CutoverCapabilityDescriptorV1, ...],
        *,
        catalog_digest: str,
        provider_catalog_digest: str,
    ) -> None:
        if type(descriptors) is not tuple or not descriptors:
            raise WorkflowCapabilityRegistryError("cutover catalog must contain descriptors")
        by_id: dict[str, CutoverCapabilityDescriptorV1] = {}
        by_path: dict[str, CutoverCapabilityDescriptorV1] = {}
        for descriptor in descriptors:
            if descriptor.capability_id in by_id or descriptor.path_id in by_path:
                raise WorkflowCapabilityRegistryError("cutover catalog contains duplicate capability or path")
            by_id[descriptor.capability_id] = descriptor
            by_path[descriptor.path_id] = descriptor
        if type(catalog_digest) is not str or len(catalog_digest) != 64:
            raise WorkflowCapabilityRegistryError("cutover catalog digest is invalid")
        if type(provider_catalog_digest) is not str or len(provider_catalog_digest) != 64:
            raise WorkflowCapabilityRegistryError("provider catalog digest is invalid")
        self._descriptors = tuple(sorted(descriptors, key=lambda item: (item.provider_id, item.path_id)))
        self._by_id = by_id
        self._by_path = by_path
        self.catalog_digest = catalog_digest
        self.provider_catalog_digest = provider_catalog_digest

    @classmethod
    def from_provider_catalog(cls, provider_catalog: object, runtime_registry: object) -> "CutoverCapabilityCatalogV1":
        from workbench.canonical import sha256_canonical
        from workbench.contracts.common.provider import ProviderContributionV1
        from workbench.agent.trusted_executor_registry import TrustedExecutorRegistry

        if type(runtime_registry) is not TrustedExecutorRegistry:
            raise WorkflowCapabilityRegistryError("cutover catalog requires trusted executor registry")
        if not hasattr(provider_catalog, "providers") or not hasattr(provider_catalog, "catalog_digest"):
            raise WorkflowCapabilityRegistryError("cutover catalog requires provider catalog")
        runtime_registry.bind_catalog(provider_catalog)
        descriptors: list[CutoverCapabilityDescriptorV1] = []
        for provider in provider_catalog.providers:
            if type(provider) is not ProviderContributionV1:
                raise WorkflowCapabilityRegistryError("provider catalog contains an invalid provider")
            provider_digest = sha256_canonical(provider.to_dict())
            declarations = {declaration.adapter_id: declaration for declaration in provider.adapter_declarations}
            for path in provider.exposure_paths:
                if path.execution_adapter_ref is None:
                    raise WorkflowCapabilityRegistryError(f"path {path.path_id} has no execution adapter")
                adapter_id = path.execution_adapter_ref.logical_id
                declaration = declarations.get(adapter_id)
                if declaration is None:
                    raise WorkflowCapabilityRegistryError(f"path {path.path_id} has no declared adapter")
                contribution = runtime_registry.require(declaration.executor_ref)
                if contribution.provider_id != provider.provider_id or contribution.adapter_id != adapter_id:
                    raise WorkflowCapabilityRegistryError(f"path {path.path_id} runtime binding does not match provider")
                effect = contribution.effect
                operation_ref = None if path.operation_ref is None else path.operation_ref.logical_id
                descriptors.append(
                    CutoverCapabilityDescriptorV1(
                        provider_id=provider.provider_id,
                        path_id=path.path_id,
                        capability_id=path.capability_ref.logical_id,
                        exposure=path.exposure,
                        adapter_id=adapter_id,
                        executor_ref=declaration.executor_ref,
                        operation_ref=operation_ref,
                        projection_keys=tuple(sorted(path.projection_refs)),
                        renderer_ref_ids=tuple(ref.logical_id for ref in provider.renderer_refs),
                        effect=effect,
                        execution_allowed=contribution.execution_allowed,
                        provider_digest=provider_digest,
                    )
                )
        if not descriptors:
            raise WorkflowCapabilityRegistryError("provider catalog exposes no executable paths")
        descriptor_payload = [descriptor.to_dict() for descriptor in sorted(descriptors, key=lambda item: (item.provider_id, item.path_id))]
        digest = sha256_canonical(
            {
                "provider_catalog_digest": provider_catalog.catalog_digest,
                "descriptors": descriptor_payload,
                "runtime_bindings": [
                    runtime_registry.require(descriptor.executor_ref).binding_payload()
                    for descriptor in sorted(descriptors, key=lambda item: (item.provider_id, item.path_id))
                ],
            }
        )
        return cls(
            tuple(descriptors),
            catalog_digest=digest,
            provider_catalog_digest=provider_catalog.catalog_digest,
        )

    def capability_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def descriptors(self) -> tuple[CutoverCapabilityDescriptorV1, ...]:
        return self._descriptors

    def require(self, capability_or_path_id: str) -> CutoverCapabilityDescriptorV1:
        if type(capability_or_path_id) is not str or not capability_or_path_id:
            raise WorkflowCapabilityRegistryError("capability id is required")
        try:
            return self._by_id.get(capability_or_path_id) or self._by_path[capability_or_path_id]
        except KeyError as exc:
            raise WorkflowCapabilityRegistryError(
                f"unknown cutover capability: {capability_or_path_id}"
            ) from exc

    def search(self, text: str) -> tuple[CutoverCapabilityDescriptorV1, ...]:
        """Conservative discovery by declaration identity, never by family switch."""

        if type(text) is not str or not text.strip():
            return ()
        tokens = {token.casefold() for token in text.replace("/", " ").replace("_", " ").split() if token}
        matches = []
        for descriptor in self._descriptors:
            identity_tokens = {
                token.casefold()
                for token in (
                    descriptor.provider_id.replace("_", " ").replace(".", " "),
                    descriptor.path_id.replace("_", " ").replace(".", " "),
                    descriptor.capability_id.replace("_", " ").replace(".", " "),
                )
                for token in token.split()
                if token
            }
            if tokens & identity_tokens:
                matches.append(descriptor)
        return tuple(matches)


__all__ += [
    "CutoverCapabilityCatalogV1",
    "CutoverCapabilityDescriptorV1",
]
