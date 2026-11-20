"""Source-bound planner construction shared by HTTP and an active Agent turn."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
from workbench.agent.context_compiler import NotebookPlanningContextV1
from workbench.agent.workflow_contracts import notebook_workflow_capability_ids, workflow_step_vocabulary
from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
from workbench.agent.p7_pack_registry import p7_pack_registry
from workbench.agent.notebook import NotebookService
from workbench.agent.notebook.evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from workbench.agent.notebook.errors import OptionValidationFailed
from .agent import NotebookPlanningAgent
from .types import NotebookNoEligibleCapability, NotebookPlanningContractError, NotebookPlanningUnavailable
from workbench.agent.trace import TraceWriter
from workbench.engine.capabilities import build_capabilities
from workbench.agent.notebook.vocabulary import capability_artifact_types
from workbench.agent.recipes.registry import build_option_vocabulary
from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalogError

def _notebook_planner_manifest_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Project only fields accepted by the published model-family contract.

    The general engine capability manifest is also used by the manual rerun UI,
    where a covariance selector may be useful for a different handler.  The
    Notebook planner emits ``model.genesis`` proposals, so its provider-facing
    catalog must be narrower: advertising an OLS-only field to a family whose
    contract rejects it creates a provider-visible option that can never become
    a valid Draft.
    """

    projected = dict(entry)
    family = MODEL_FAMILY_CONTRACTS.get(str(entry.get("key")))
    params = entry.get("params")
    if family is not None and isinstance(params, list):
        projected_params = [
            dict(param)
            for param in params
            if not (
                isinstance(param, Mapping)
                and not family.allows_covariance
                and param.get("key") == "covariance"
            )
        ]
        if not any(param.get("key") == "y" for param in projected_params):
            projected_params.insert(
                1,
                {
                    "key": "y",
                    "kind": "columns",
                    "label": "Outcome (Y)",
                    "required": True,
                    "role": "y",
                },
            )
        projected["params"] = projected_params
        published_artifacts = capability_artifact_types(str(entry.get("key")))
        if published_artifacts and not isinstance(projected.get("artifact_types"), Mapping):
            projected["artifact_types"] = dict(published_artifacts)
        option_vocabulary = build_option_vocabulary(str(entry.get("key")))
        if option_vocabulary is not None:
            fields = option_vocabulary.get("fields")
            projected["notebook_model_options_policy"] = {
                "supported": True,
                "allowed_fields": sorted(fields) if isinstance(fields, Mapping) else [],
                "forbidden_fields": [],
                "submission_rule": "use_published_fields",
            }
        else:
            projected["notebook_model_options_policy"] = {
                "supported": False,
                "allowed_fields": [],
                "forbidden_fields": ["covariance", "model_options"],
                "submission_rule": "omit_model_options",
            }
    return projected


def _notebook_p7_capability_catalog() -> dict[str, dict[str, Any]]:
    """Project every live P7 declaration as a composable Notebook choice."""

    step_operations = workflow_step_vocabulary()["step_operations"]
    return {
        operation_id: {
            "key": operation_id,
            "label": operation_id,
            "capability_kind": "pack",
            "ui_description": step_operations[operation_id]["ui_description"],
            "workflow_step_contract": dict(step_operations[operation_id]),
            "notebook_proposal_adapters": ["operation.multi_step"],
        }
        for operation_id in p7_pack_registry.operation_ids()
    }


def build_planner(
    root: Path,
    service: NotebookService,
    notebook_id: str,
    context: NotebookPlanningContextV1,
    trace: TraceWriter,
    *,
    adapter,
    phase_runner,
    provider_timeout_s: float,
    planning_timeout_s: float | None,
    operation_adapter: str | None = None,
) -> NotebookPlanningAgent:
    if context.projection_source is None:
        raise NotebookPlanningUnavailable(
            "a source-bound Notebook projection is required before planning"
        )
    admitted_native = set(notebook_workflow_capability_ids())
    manifest = {
        str(entry["key"]): _notebook_planner_manifest_entry(entry)
        for entry in build_capabilities().get("model_types", [])
        if (
            isinstance(entry, dict)
            and entry.get("key") in admitted_native
        )
    }
    proposal_adapter = operation_adapter or (
        "model.genesis"
        if context.projection_source
        and context.projection_source.get("kind") == "dataset"
        else "model.rerun"
    )
    source_model_type = _source_model_type(root, context)
    has_workflow_source = (
        "operation.multi_step" in NotebookPlanningAgent._typed_operation_contracts(context)
    )
    if (
        operation_adapter is None
        and proposal_adapter == "model.rerun"
        and has_workflow_source
        and (
            source_model_type not in context.available_capabilities
            or not _supports_rerun_model_options(manifest.get(source_model_type, {}))
        )
    ):
        # The raw-source workflow accepts model families and the live P7 steps added below.
        proposal_adapter = "operation.multi_step"
        manifest = {
            capability: declaration for capability, declaration in manifest.items()
            if capability in MODEL_FAMILY_CONTRACTS
        }
    server_projections: tuple[dict[str, Any], ...] = ()
    if service.capability_bindings is not None:
        notebook = service.get_notebook(notebook_id)
        try:
            server_projections = service.capability_bindings.planner_projections(
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                )
            )
        except CapabilityBindingCatalogError as error:
            raise NotebookPlanningUnavailable(
                "a server-owned capability planner projection is unavailable"
            ) from error
    server_manifest = {
        str(item["key"]): dict(item)
        for item in server_projections
        if isinstance(item, Mapping) and isinstance(item.get("key"), str)
    }
    server_model_types = {
        capability: str(item["model_type"])
        for capability, item in server_manifest.items()
    }
    dynamic_artifact_types = {
        capability: dict(item["artifact_types"])
        for capability, item in server_manifest.items()
        if capability not in manifest
        and isinstance(item.get("artifact_types"), Mapping)
    }
    candidate_capabilities = tuple(
        dict.fromkeys(
            (
                *(capability for capability in context.available_capabilities if capability in manifest),
                *server_manifest,
            )
        )
    )
    catalog = {
        capability: {
            **(
                manifest[capability]
                if capability in manifest
                else server_manifest[capability]
            ),
            "model_type": server_model_types.get(capability, capability),
            "notebook_proposal_adapters": (
                server_manifest[capability]["notebook_proposal_adapters"]
                if capability in server_manifest and "model.custom" in server_manifest[capability].get("notebook_proposal_adapters", [])
                else [proposal_adapter]),
            **_model_options_catalog_metadata(root, context, capability),
        }
        for capability in candidate_capabilities
        if (
            capability in manifest
            or capability in server_manifest
        )
        and (
            capability_artifact_types(capability)
            or capability in dynamic_artifact_types
        )
        and (
            capability not in server_manifest
            or "model.custom" in server_manifest[capability].get("notebook_proposal_adapters", [])
            or proposal_adapter in server_manifest[capability].get(
                "notebook_proposal_adapters", [proposal_adapter]
            )
        )
        and (
            proposal_adapter in {"model.genesis", "operation.multi_step"}
            or source_model_type is None
            or server_model_types.get(capability, capability) == source_model_type
        )
        and (
            proposal_adapter in {"model.genesis", "operation.multi_step"}
            or capability not in manifest
            or _supports_rerun_model_options(manifest[capability])
        )
    }
    if has_workflow_source:
        catalog.update(_notebook_p7_capability_catalog())
    if not catalog:
        raise NotebookNoEligibleCapability(
            _no_eligible_capability_message(
                proposal_adapter=proposal_adapter,
                source_model_type=source_model_type,
            )
        )

    def execute_inspections(requests, current):
        return service.compile_evidence_pack(
            notebook_id,
            requests=requests,
            trace=trace,
        )

    def validate_proposal(_context, submission) -> None:
        """Validate the provider packet against the server-owned model contract.

        The operation registry is intentionally provider-neutral. This second
        seam resolves the actual source handler and validates the merged
        payload, so a provider cannot turn a model-specific alias into a Draft
        that only fails after the user confirms it.
        """

        proposal = submission.proposal
        changes = proposal.changes
        if proposal.operation_id == "model.rerun":
            from workbench.lineage.run_inputs import read_run_inputs
            from workbench.repository.run_repository import _resolve_run_root
            from workbench.services.run_service import merge_form_overrides

            source_root = _resolve_run_root(str(root), str(proposal.target["run_id"]))
            inputs = read_run_inputs(source_root)
            source_form = inputs.get("form") or {}
            patch = changes.get("model_options") or {}
            if not isinstance(source_form, Mapping):
                raise ValueError("SOURCE_RUN_FORM_INVALID")
            if not isinstance(patch, Mapping):
                raise ValueError("MODEL_OPTIONS_PATCH_NOT_OBJECT")
            merge_form_overrides(source_form, {"model_options": dict(patch)})
            return

        if proposal.operation_id == "model.genesis":
            from workbench.agent.recipe_contracts import recipe_contract_for_model_type
            from workbench.model_options import bind_new_model_options

            model_params = changes.get("model_params") or {}
            if not isinstance(model_params, Mapping):
                return
            model_type = model_params.get("model_type")
            payload = changes.get("model_options")
            if payload is None:
                payload = model_params.get("model_options")
            if payload:
                if not isinstance(model_type, str) or not model_type:
                    raise ValueError("MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED")
                recipe_contract = recipe_contract_for_model_type(model_type)
                if recipe_contract is not None:
                    source = _context.projection_source or {}
                    source_hash = source.get("upload_sha256") if isinstance(source, Mapping) else None
                    if not isinstance(source_hash, str) or not source_hash:
                        raise ValueError("RECIPE_SOURCE_BINDING_INVALID")
                    payload = recipe_contract.bind_server_owned_options(
                        payload,
                        source_reference=f"upload:{source_hash}",
                    )
                bind_new_model_options(model_type, payload)
            try:
                service.validate_dataset_recipe_preflight(notebook_id, proposal)
            except OptionValidationFailed as error:
                raise NotebookPlanningContractError(str(error)) from error

    return NotebookPlanningAgent(
        adapter=adapter,
        phase_runner=phase_runner,
        capability_catalog=catalog,
        capability_artifact_types=dynamic_artifact_types,
        inspection_executor=execute_inspections,
        proposal_validator=validate_proposal,
        available_inspections=tuple(INSPECTIONS),
        model_timeout_s=provider_timeout_s,
        planning_timeout_s=planning_timeout_s,
    )


def _baseline_planning_evidence(
    service: NotebookService,
    notebook_id: str,
    context: NotebookPlanningContextV1,
    trace: TraceWriter,
) -> DataEvidencePackV1:
    """Compile one bounded source profile before asking the provider to plan."""

    if context.projection_source is None:
        return DataEvidencePackV1(source_id="notebook", records=())
    target_ref = (
        "run:active"
        if context.projection_source
        and context.projection_source.get("kind") == "run"
        else "dataset:active"
    )
    requests = tuple(
        InspectionRequest(inspection_id, target_ref, {})
        for inspection_id in ("profile.v1", "quality.v1", "time_index.v1", "sample.v1")
    )
    return service.compile_evidence_pack(
        notebook_id,
        requests=requests,
        trace=trace,
    )


def _supports_rerun_model_options(declaration: Mapping[str, Any]) -> bool:
    """Whether a registered model pack owns the rerun ``model_options`` envelope.

    ``model.rerun`` is intentionally narrower than Genesis: it may only patch
    a model pack's server-owned options. A capability is eligible only when
    its declaration explicitly publishes that envelope; this keeps the Agent
    catalog aligned with the Draft materialization seam.
    """

    params = declaration.get("params") if isinstance(declaration, Mapping) else None
    return any(
        isinstance(item, Mapping) and item.get("key") == "model_options"
        for item in (params or ())
    )


def _no_eligible_capability_message(
    *,
    proposal_adapter: str,
    source_model_type: str | None,
) -> str:
    """Explain an empty planner catalog without weakening fail-closed admission."""

    if proposal_adapter == "model.rerun" and source_model_type:
        return (
            f"the active run model {source_model_type!r} has no editable "
            "model_options contract, so no rerun capability is eligible; "
            "choose Start new analysis from source data to plan a new typed analysis"
        )
    if proposal_adapter == "model.rerun":
        return (
            "the active run has no server-pinned model capability eligible for rerun; "
            "choose Start new analysis from source data to plan a new typed analysis"
        )
    return "the Notebook has no server-registered executable capability"


def _source_model_type(root: Path, context: NotebookPlanningContextV1) -> str | None:
    source = context.projection_source or {}
    if source.get("kind") != "run" or not context.active_head_run_id:
        return None
    try:
        from workbench.lineage.run_inputs import read_run_inputs
        from workbench.repository.run_repository import _resolve_run_root

        inputs = read_run_inputs(_resolve_run_root(str(root), context.active_head_run_id))
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return None
    model_type = (inputs.get("form") or {}).get("model_type")
    return model_type if isinstance(model_type, str) and model_type else None


def _model_options_catalog_metadata(
    root: Path,
    context: NotebookPlanningContextV1,
    capability: str,
) -> dict[str, Any]:
    """Expose only bounded, server-owned option shape facts to the provider."""

    metadata: dict[str, Any] = {}
    vocabulary = build_option_vocabulary(capability)
    if vocabulary:
        metadata["model_options_vocabulary"] = vocabulary
    source = context.projection_source or {}
    if source.get("kind") == "run" and context.active_head_run_id:
        try:
            from workbench.lineage.run_inputs import read_run_inputs
            from workbench.repository.run_repository import _resolve_run_root

            inputs = read_run_inputs(_resolve_run_root(str(root), context.active_head_run_id))
            form = inputs.get("form") or {}
            if form.get("model_type") == capability and isinstance(
                form.get("model_options"), Mapping
            ):
                metadata["notebook_model_options_contract"] = {
                    "model_type": capability,
                    "current_payload": dict(form["model_options"]),
                    "patch_rule": "Use exact existing top-level and nested field names; server validates the merged payload.",
                }
        except (FileNotFoundError, OSError, TypeError, ValueError):
            pass
    return metadata
