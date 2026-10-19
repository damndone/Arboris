"""NotebookService: state ownership and public entry point."""
from __future__ import annotations
import time
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4
import pandas as pd
from ...tabular_io import STATISTICAL_FORMATS, read_table
from ...contracts.agent.notebook_option import (
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    NotebookOptionRevision,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
    NotebookOptionRevisionV13,
    NotebookOptionRevisionV14,
    OptionExecution,
    RecommendationDecision,
    RecommendationDecisionV11,
)
from ...capability_factory.execution_authorization import (
    ExecutionAuthorizationError,
    OptionExecutionAuthorization,
    OptionExecutionAuthorizationStore,
)
from ...canonical import sha256_canonical
from ...custom_capability.canonical import domain_digest
from ...capability_factory.notebook_catalog import (
    CapabilityBindingCatalog,
    CapabilityBindingCatalogError,
    NOTEBOOK_OPTION_PLANNER_CONSUMER,
)
from ...capability_factory.contracts import CONSUMER_SLOTS
from ...capability_factory.notebook_bridge import (
    NotebookCapabilityExecutionGateway,
    NotebookExecutionDispatch,
)
from ...capability_factory.notebook_binding import CapabilityResolutionBinding
from ...capability_factory.trace_contracts import (
    CapabilityTraceEvent,
    build_trace_event,
)
from ...lineage.run_family import (
    RunFamilyStore,
    assert_run_in_family,
    migrate_project_families,
    resolve_run_family,
)
from ...data_operations import resolve_data_column_cast_context
from .. import operation_requests
from ..context_compiler import (
    NotebookPlanningContextV1,
    compile_notebook_planning_context,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from ...lineage.upload_store import verify_upload
from ...services.server_run_artifacts import (
    ServerOwnedArtifactManifestError,
    read_server_owned_run_artifacts,
)
from ...services.notebook_source_materialization import (
    materialize_notebook_upload_source,
    read_notebook_upload_frame,
)
from ..operations import OperationRegistry
from ...contracts.common.errors import OperationValidationError
from ..trace import TraceWriter
from ..workflow import compile_workflow, execute_workflow
from .execution_results import (
    ExecutionOutcome,
    _TYPED_WORKFLOW_ERROR_CODE,
    _bounded_workflow_error_code,
    artifact_validation_scope,
    contract_artifact_projection,
    workflow_execution_receipt,
    workflow_produced_artifacts,
)
from .artifact_contract import (
    COMMITTABLE_VALIDATION_STATUSES,
    build_artifact_contract,
    validate_produced_artifacts,
)
from .errors import (
    NotebookRunFamilyImmutable,
    OptionBatchInvalid,
    OptionClientExecutionFactsForbidden,
    OptionExecutionReceiptRequired,
    OptionExecutionGatewayUnavailable,
    OptionLegacyUnverified,
    OptionLifecycleTransitionInvalid,
    OptionMaterializationFailed,
    OptionMaterializationRequired,
    OptionNotFound,
    OptionRevisionStale,
    OptionValidationFailed,
)
from .freshness import (
    FRESH,
    REVALIDATING,
    assert_executable,
    evaluate_option_freshness,
    freshness_details,
)
from .memory_defaults import (
    MemoryDefaultApplicationError,
    validate_memory_default_sources,
)
from .proposal import OptionDraft, TypedProposal
from .recommendation import (
    ComparisonDecisionRecord,
    RecommendationValidator,
    RecommendationValidationError,
    ServerDecisionRegistry,
    candidate_cohort_hash,
)
from .store import (
    RECORD_EXECUTION,
    RECORD_EXECUTION_RESULT,
    RECORD_LIFECYCLE,
    RECORD_OPTION,
    RECORD_REVISION,
    Notebook,
    NotebookStore,
    OptionView,
    ProjectionSource,
    StoredRevision,
    WorkflowSource,
    dataset_workflow_source_pin,
    reserve_dataset_upload_workflow_source,
)
from .evidence import (
    DatasetSource,
    DataEvidencePackV1,
    InspectionRequest,
    RunSource,
    compile_evidence_pack,
)
from .vocabulary import by_group_artifact_types, capability_artifact_types
from .workflow_artifacts import (
    WORKFLOW_RESULT_ARTIFACT_TYPE,
    p7_capability_ids_from_steps,
    persist_workflow_result_manifest,
    workflow_result_artifact_id,
)

# Preserve initialization order before loading the extracted implementation owners.
from .service_recommendations import ServiceRecommendations
from .service_planning import ServicePlanning
from .service_revalidation import ServiceRevalidation
from .service_authorization import ServiceAuthorization
from .service_execution import ServiceExecution
from .service_workflow import ServiceWorkflow
from .service_sources import ServiceSources
from .service_capabilities import ServiceCapabilities
from .service_preparation import ServicePreparation
from .service_lifecycle import ServiceLifecycle
from .service_contracts import MAX_OPTIONS_PER_BATCH, _now
class NotebookService(ServiceRecommendations, ServicePlanning, ServiceRevalidation, ServiceAuthorization, ServiceExecution, ServiceWorkflow, ServiceSources, ServiceCapabilities, ServicePreparation, ServiceLifecycle):
    """Everything a notebook can do, in one place, over an append-only log."""


    def __init__(
        self,
        project_root: Path | str,
        *,
        registry: OperationRegistry | None = None,
        capability_bindings: CapabilityBindingCatalog | None = None,
        execution_gateway: NotebookCapabilityExecutionGateway | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.store = NotebookStore(self.project_root)
        self.registry = registry or OperationRegistry()
        if capability_bindings is not None and not isinstance(
            capability_bindings, CapabilityBindingCatalog
        ):
            raise TypeError("capability_bindings must be a CapabilityBindingCatalog")
        self.capability_bindings = capability_bindings
        if execution_gateway is not None and not callable(
            getattr(execution_gateway, "dispatch", None)
        ):
            raise TypeError("execution_gateway must expose a callable dispatch method")
        self.execution_gateway = execution_gateway


    def create_notebook(
        self,
        *,
        title: str,
        created_by: str,
        from_run_id: str | None = None,
        notebook_id: str | None = None,
        analysis_contract: Mapping[str, Any] | None = None,
        user_focus: Mapping[str, Any] | None = None,
        available_capabilities: Sequence[str] | None = None,
    ) -> Notebook:
        """Create a notebook, binding it to exactly one run family (DEC-NB-001).

        Migration runs first, by decision of 2026-07-22: the notebook needs a
        *persisted* family, and `migrate_project_families()` is the one code path
        allowed to create those for pre-existing runs. Writing a second migration
        here is how two sources of truth about family identity get born.
        """

        migrate_project_families(self.project_root, created_by="notebook_bootstrap")
        store = RunFamilyStore(self.project_root)
        if from_run_id is not None:
            run_family_id = resolve_run_family(self.project_root, from_run_id).run_family_id
            active_head_run_id: str | None = from_run_id
        else:
            run_family_id = store.create_family(
                project_id=self.project_root.name,
                created_by=created_by,
                origin="notebook",
            ).run_family_id
            active_head_run_id = None

        notebook = Notebook(
            notebook_id=notebook_id or f"nb_{uuid4().hex}",
            project_id=self.project_root.name,
            run_family_id=run_family_id,
            title=title,
            created_by=created_by,
            created_at=_now(),
            active_head_run_id=active_head_run_id,
            focused_run_id=active_head_run_id,
            analysis_contract=dict(analysis_contract or {}),
            user_focus=dict(user_focus or {}),
            available_capabilities=tuple(available_capabilities or ()),
        )
        return self.store.create_notebook(notebook)


    def ensure_default_projection(
        self,
        *,
        from_run_id: str | None = None,
        dataset: Mapping[str, Any] | ProjectionSource | None = None,
        created_by: str,
        title: str = "Analysis Notebook",
        available_capabilities: Sequence[str] | None = None,
    ) -> Notebook:
        """Return the one default projection for one immutable source."""

        if (from_run_id is None) == (dataset is None):
            raise ValueError("exactly one projection source is required")

        if from_run_id is not None:
            with self.store.project_lock():
                source = ProjectionSource.from_dict({"kind": "run", "run_id": from_run_id})
                family_store = RunFamilyStore(self.project_root, create=False)
                resolved = resolve_run_family(
                    self.project_root, from_run_id, check_consistency=True
                )
                if resolved.source == "persisted":
                    default_key = f"default-projection:{resolved.run_family_id}"
                    defaults = [
                        notebook
                        for notebook in self.store.list_notebooks()
                        if notebook.projection_key == default_key
                    ]
                    if len(defaults) > 1:
                        raise ValueError(
                            f"multiple default Notebook projections exist for "
                            f"run family {resolved.run_family_id!r}"
                        )
                    if defaults:
                        existing = defaults[0]
                        if existing.projection_source == source:
                            return existing
                        family = family_store.get(resolved.run_family_id)
                        if (
                            existing.projection_source is not None
                            and existing.projection_source.kind == "dataset"
                            and family.origin == "notebook"
                        ):
                            return existing
                elif not family_store.has_migrated():
                    migrate_project_families(self.project_root, created_by="notebook_bootstrap")
                    resolved = resolve_run_family(
                        self.project_root, from_run_id, check_consistency=True
                    )
                if resolved.source != "persisted":
                    raise ValueError("default projection requires a persisted run family")
                return self.store.ensure_default_projection(
                    Notebook(
                        notebook_id=f"nb_{uuid4().hex}",
                        project_id=self.project_root.name,
                        run_family_id=resolved.run_family_id,
                        title=title,
                        created_by=created_by,
                        created_at=_now(),
                        active_head_run_id=from_run_id,
                        focused_run_id=from_run_id,
                        projection_key=f"default-projection:{resolved.run_family_id}",
                        projection_source=source,
                        available_capabilities=tuple(available_capabilities or ()),
                    )
                )

        source = (
            dataset
            if isinstance(dataset, ProjectionSource)
            else ProjectionSource.from_dict(dataset)
        )
        if source.kind != "dataset":
            raise ValueError("projection_source must be a dataset source")
        verify_upload(self.project_root, source.upload_sha256)
        source = reserve_dataset_upload_workflow_source(source)

        def create_dataset_notebook() -> Notebook:
            family = RunFamilyStore(self.project_root).create_family(
                project_id=self.project_root.name,
                created_by=created_by,
                origin="notebook",
            )
            return Notebook(
                notebook_id=f"nb_{uuid4().hex}",
                project_id=self.project_root.name,
                run_family_id=family.run_family_id,
                title=title,
                created_by=created_by,
                created_at=_now(),
                projection_key=f"default-projection:{family.run_family_id}",
                projection_source=source,
                available_capabilities=tuple(available_capabilities or ()),
            )

        return self.store.ensure_dataset_default_projection(source, create_dataset_notebook)


    def ensure_dataset_projection_from_run(
        self,
        *,
        from_run_id: str,
        created_by: str,
        title: str = "Analysis Notebook",
        available_capabilities: Sequence[str] | None = None,
    ) -> Notebook:
        """Create a fresh dataset-backed Notebook from one verified run upload.

        The client selects only an existing run id.  The server resolves its
        persisted upload pin and filename, verifies the content-addressed blob,
        then creates a separate family with no active model head.  This is not
        a rerun and never changes the source run or its Notebook family.
        """

        from ...data_operations import (
            DataColumnCastValidationError,
            resolve_data_column_cast_context,
        )
        from ...lineage.run_inputs import read_run_inputs
        from ...repository.run_repository import _resolve_run_root

        run_root = _resolve_run_root(str(self.project_root), from_run_id)
        inputs = read_run_inputs(run_root)
        upload = inputs.get("upload")
        if not isinstance(upload, Mapping):
            raise ValueError("source run has no persisted upload metadata")
        upload_sha256 = upload.get("sha256")
        filename = upload.get("filename")
        if not isinstance(upload_sha256, str) or not isinstance(filename, str):
            raise ValueError("source run upload metadata is invalid")
        if Path(filename).name != filename:
            raise ValueError("source run upload filename is invalid")
        form = inputs.get("form")
        sheet_name = form.get("sheet_name") if isinstance(form, Mapping) else None
        suffix = Path(filename).suffix.lower()
        sheet_names = (
            [sheet_name]
            if suffix in {".xlsx", ".xls"} and isinstance(sheet_name, str) and sheet_name
            else []
        )
        # A fresh dataset projection has no active result head, but a composed
        # workflow still needs one immutable raw dataset identity.  Resolve it
        # here from the chosen persisted Run; callers never submit node or
        # artifact identifiers.  Older runs may call the source stage either
        # ``stage:raw`` or ``stage:source``; those are compatibility reads of
        # existing persisted graph identities, not new aliases a planner may
        # write.  # legacy-compat
        source_context: Mapping[str, Any] | None = None
        source_node_ref: str | None = None
        for candidate in ("stage:raw", "stage:source"):
            try:
                source_context = resolve_data_column_cast_context(
                    self.project_root,
                    source_run_id=from_run_id,
                    source_node_id=candidate,
                )
                source_node_ref = candidate
                break
            except (DataColumnCastValidationError, KeyError, OSError, ValueError):
                continue
        workflow_source: dict[str, str] | None = None
        if source_context is not None and source_node_ref is not None:
            source_artifact_id = source_context.get("source_artifact_id")
            source_sha256 = source_context.get("source_sha256")
            if not isinstance(source_artifact_id, str) or not isinstance(source_sha256, str):
                raise ValueError("source run raw dataset identity is invalid")
            workflow_source = WorkflowSource(
                run_id=from_run_id,
                node_ref=source_node_ref,
                artifact_id=source_artifact_id,
                source_sha256=source_sha256,
            ).to_dict()
        dataset: dict[str, Any] = {
            "kind": "dataset",
            "upload_sha256": upload_sha256,
            "filename": filename,
            "sheet_names": sheet_names,
        }
        if workflow_source is not None:
            dataset["workflow_source"] = workflow_source
        return self.ensure_default_projection(
            dataset=dataset,
            created_by=created_by,
            title=title,
            available_capabilities=available_capabilities,
        )


    def get_notebook(self, notebook_id: str) -> Notebook:
        return self.store.get_notebook(notebook_id)


    def list_notebooks(self) -> list[Notebook]:
        return self.store.list_notebooks()

__all__ = ["ExecutionOutcome", "MAX_OPTIONS_PER_BATCH", "NotebookService"]
