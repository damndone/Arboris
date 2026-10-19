"""service capabilities: methods over the existing shared state."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from ...contracts.agent.notebook_option import RecommendationDecision, RecommendationDecisionV11
from ...capability_factory.notebook_catalog import CapabilityBindingCatalogError, NOTEBOOK_OPTION_PLANNER_CONSUMER
from ...capability_factory.notebook_binding import CapabilityResolutionBinding
from ..context_compiler import NotebookPlanningContextV1
from ...services.notebook_source_materialization import read_notebook_upload_frame
from ...contracts.common.errors import OperationValidationError
from .execution_results import _TYPED_WORKFLOW_ERROR_CODE
from .errors import OptionBatchInvalid, OptionRevisionStale
from .memory_defaults import MemoryDefaultApplicationError, validate_memory_default_sources
from .proposal import OptionDraft, TypedProposal
from .recommendation import RecommendationValidationError
from .store import Notebook, OptionView, dataset_workflow_source_pin
from .vocabulary import capability_artifact_types
from .workflow_artifacts import p7_capability_ids_from_steps
from .service_contracts import (MAX_OPTIONS_PER_BATCH)

class ServiceCapabilities:
    def _assert_batch_shape(self, drafts: Sequence[OptionDraft]) -> None:
        if not drafts:
            raise OptionBatchInvalid(
                "OPTION_BATCH_EMPTY", "a generation batch must contain at least one option"
            )
        if len(drafts) > MAX_OPTIONS_PER_BATCH:
            raise OptionBatchInvalid(
                "OPTION_BATCH_LIMIT_EXCEEDED",
                f"a planning pass may produce at most {MAX_OPTIONS_PER_BATCH} options "
                f"(DEC-OPT-002), got {len(drafts)}",
                option_count=len(drafts),
                limit=MAX_OPTIONS_PER_BATCH,
            )
        ranks = [draft.rank for draft in drafts]
        out_of_range = sorted({rank for rank in ranks if rank < 1 or rank > MAX_OPTIONS_PER_BATCH})
        if out_of_range:
            raise OptionBatchInvalid(
                "OPTION_BATCH_RANK_OUT_OF_RANGE",
                f"rank must be 1..{MAX_OPTIONS_PER_BATCH}, got {out_of_range}",
                ranks=ranks,
            )
        if len(set(ranks)) != len(ranks):
            raise OptionBatchInvalid(
                "OPTION_BATCH_DUPLICATE_RANK",
                f"ranks within a batch must be distinct, got {ranks}",
                ranks=ranks,
            )
        hashes = [draft.proposal.canonical_hash() for draft in drafts]
        if len(set(hashes)) != len(hashes):
            duplicated = sorted({h for h in hashes if hashes.count(h) > 1})
            raise OptionBatchInvalid(
                "OPTION_BATCH_DUPLICATE_PROPOSAL",
                "two options in the same batch have the same canonical proposal hash; "
                "a parameter-identical pair is one option, not two (spec §6)",
                canonical_proposal_hashes=duplicated,
            )


    def _resolve_capability_bindings(
        self,
        notebook: Notebook,
        drafts: Sequence[OptionDraft],
        *,
        recommendation_decision: RecommendationDecision | RecommendationDecisionV11 | None,
        require_recommendation_decision: bool = True,
    ) -> tuple[CapabilityResolutionBinding | None, ...]:
        """Resolve Agent names through the server-owned catalog before writes."""

        if self.capability_bindings is None:
            return tuple(None for _ in drafts)

        resolved: list[CapabilityResolutionBinding | None] = []
        for draft in drafts:
            if draft.capability_id is None:
                resolved.append(None)
                continue
            try:
                binding = self.capability_bindings.resolve(
                    draft.capability_id,
                    scope_candidates=(
                        ("project", notebook.project_id),
                        ("run_family", notebook.run_family_id),
                    ),
                )
            except CapabilityBindingCatalogError as error:
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                    "the server-owned capability binding is not currently usable",
                    capability_id=draft.capability_id,
                ) from error
            if binding is not None and "fit" not in binding.allowed_operations:
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                    "the server-owned capability binding is not authorized for fit",
                    capability_id=draft.capability_id,
                )
            if (
                binding is not None
                and NOTEBOOK_OPTION_PLANNER_CONSUMER not in binding.allowed_consumers
            ):
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                    "the server-owned capability binding is not authorized for the Notebook option planner",
                    capability_id=draft.capability_id,
                )
            if binding is not None and require_recommendation_decision:
                if recommendation_decision is None:
                    raise OptionBatchInvalid(
                        "OPTION_CAPABILITY_BINDING_DECISION_REQUIRED",
                        "an admitted capability option requires a recommendation decision",
                        capability_id=draft.capability_id,
                    )
                if not isinstance(recommendation_decision, RecommendationDecisionV11):
                    raise OptionBatchInvalid(
                        "OPTION_CAPABILITY_BINDING_DECISION_VERSION",
                        "an admitted capability option requires the server-owned V1.1 recommendation contract",
                        capability_id=draft.capability_id,
                    )
            resolved.append(binding)
        return tuple(resolved)


    def _validate_recommendation_decision(
        self,
        notebook_id: str,
        decision: RecommendationDecision | RecommendationDecisionV11 | None,
    ) -> None:
        """Validate V1.1 recommendations against the persisted source registry."""

        if decision is None or not isinstance(decision, RecommendationDecisionV11):
            return
        try:
            self.read_server_decision_registry(notebook_id).validate_recommendation(decision)
        except (RecommendationValidationError, ValueError, KeyError, TypeError) as error:
            raise OptionBatchInvalid(
                "OPTION_RECOMMENDATION_DECISION_UNAVAILABLE",
                "the V1.1 recommendation is not backed by a current persisted server decision",
                recommendation_decision_id=decision.recommendation_decision_id,
                batch_id=decision.batch_id,
            ) from error


    def _assert_current_recommendation_source(
        self,
        notebook_id: str,
        revision: Any,
    ) -> None:
        """Recheck the persisted V1.1 source before a downstream consumer."""

        decision_id = getattr(revision, "recommendation_decision_id", None)
        batch_id = getattr(revision, "batch_id", None)
        if not isinstance(decision_id, str) or not decision_id:
            return
        decision = self.store.read_decision(notebook_id, batch_id)
        if isinstance(decision, RecommendationDecisionV11):
            self._validate_recommendation_decision(notebook_id, decision)
            if decision.recommendation_decision_id != decision_id:
                raise OptionBatchInvalid(
                    "OPTION_RECOMMENDATION_DECISION_UNAVAILABLE",
                    "the persisted V1.1 recommendation does not match the option",
                    recommendation_decision_id=decision_id,
                    batch_id=batch_id,
                )


    def _assert_current_memory_default_sources(
        self,
        view: OptionView,
        context: NotebookPlanningContextV1,
    ) -> None:
        """Require a v1.3 default's immutable source to still be current.

        Memory is intentionally excluded from the generic freshness fingerprint:
        a visible hint must not make unrelated option context stale. A source
        that actually changed a Draft is different, so it receives this narrow
        materialization-time fail-closed check.
        """

        proposal = view.current_stored_revision.proposal
        if not proposal.memory_default_sources:
            return
        try:
            validate_memory_default_sources(
                proposal,
                context.domain_memory_projection,
            )
        except MemoryDefaultApplicationError as error:
            raise OptionRevisionStale(
                "a server-applied memory default is no longer current; replan before materializing",
                option_id=view.option_id,
                option_revision=view.current_revision.option_revision,
                reason="memory_default_source_not_current",
            ) from error


    def _published_artifact_types(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[tuple[str, str]] | None = None,
    ) -> Mapping[str, str]:
        """Merge native and current server-owned capability vocabulary."""

        published = dict(capability_artifact_types(capability_id))
        if self.capability_bindings is None:
            return published
        dynamic = self.capability_bindings.planner_artifact_types(
            capability_id,
            scope_candidates=scope_candidates,
        )
        if dynamic is not None:
            published.update(dynamic)
        return published


    def _assert_capability_model_identity(
        self,
        notebook: Notebook,
        draft: OptionDraft,
        proposal: TypedProposal,
    ) -> None:
        """Keep a server-declared capability mapping explicit at the write seam."""

        if self.capability_bindings is None or draft.capability_id is None:
            return
        projection = self.capability_bindings.planner_projection(
            draft.capability_id,
            scope_candidates=(
                ("project", notebook.project_id),
                ("run_family", notebook.run_family_id),
            ),
        )
        if projection is None:
            return
        if proposal.operation_id == "model.custom":
            if "model.custom" not in projection.get("notebook_proposal_adapters", ()):
                raise ValueError("CAPABILITY_CUSTOM_ADAPTER_NOT_DECLARED")
            return
        declared_model_type = projection["model_type"]
        actual_model_type: Any = None
        if proposal.operation_id == "model.genesis":
            actual_model_type = (proposal.changes.get("model_params") or {}).get(
                "model_type"
            )
        elif proposal.operation_id == "model.rerun":
            from ...lineage.run_inputs import read_run_inputs
            from ...repository.run_repository import _resolve_run_root

            inputs = read_run_inputs(
                _resolve_run_root(str(self.project_root), str(proposal.target["run_id"]))
            )
            actual_model_type = (inputs.get("form") or {}).get("model_type")
        if actual_model_type != declared_model_type:
            raise ValueError("CAPABILITY_MODEL_IDENTITY_MISMATCH")


    def _assert_current_capability_binding(self, revision: Any) -> None:
        """Re-check v1.2 authority before materialization or execution callbacks."""

        reference = getattr(revision, "capability_resolution_binding_ref", None)
        if reference is None:
            return
        if self.capability_bindings is None:
            raise OptionRevisionStale(
                "the persisted capability binding cannot be revalidated by this service",
                option_id=revision.option_id,
                option_revision=revision.option_revision,
                reason="capability_binding_authority_unavailable",
            )
        try:
            self.capability_bindings.assert_current_reference(reference)
        except CapabilityBindingCatalogError as error:
            raise OptionRevisionStale(
                "the persisted capability binding is no longer currently usable",
                option_id=revision.option_id,
                option_revision=revision.option_revision,
                reason="capability_binding_not_current",
            ) from error


    def _assert_p7_source_preflight(
        self,
        notebook: Notebook,
        proposal: TypedProposal,
    ) -> None:
        """Run declaration-owned, read-only P7 checks before an option is stored."""

        if proposal.operation_id != "operation.multi_step":
            return
        raw_steps = proposal.changes.get("steps")
        p7_ids = set(p7_capability_ids_from_steps(raw_steps))
        if not p7_ids or not isinstance(raw_steps, list):
            return
        from ...statistical_exploration import (
            StatisticalExplorationValidationError,
            resolve_statistical_source,
        )
        from ..p7_pack_adapters import P7PackAdapterError
        from ..p7_pack_registry import P7PackRegistryError, p7_pack_registry

        try:
            projection = notebook.projection_source
            deferred_upload = (
                projection is not None
                and projection.kind == "dataset"
                and projection.workflow_source is not None
                and projection.workflow_source.source_kind == "dataset_upload"
            )
            if deferred_upload:
                assert projection is not None
                expected_pin = dataset_workflow_source_pin(projection)
                if expected_pin is None or (
                    proposal.target != expected_pin["target"]
                    or proposal.preconditions != expected_pin["preconditions"]
                ):
                    raise ValueError("WORKFLOW_SOURCE_PIN_MISMATCH")
                source_frame = read_notebook_upload_frame(self.project_root, projection)
            else:
                _source_context, source_frame = resolve_statistical_source(
                    self.project_root,
                    source_run_id=str(proposal.target["run_id"]),
                    source_node_id=str(proposal.target["node_ref"]),
                    source_artifact_id=str(proposal.target["artifact_id"]),
                )
            for raw_step in raw_steps:
                if not isinstance(raw_step, Mapping):
                    continue
                operation_id = raw_step.get("operation_id")
                if operation_id not in p7_ids:
                    continue
                spec = raw_step.get("spec")
                if not isinstance(spec, Mapping):
                    continue
                # A derived source does not exist until its producer executes.
                # Runtime invokes the same declaration preflight on the resolved
                # step frame, so this is deferred explicitly rather than guessed.
                if "source" in spec:
                    continue
                operation = p7_pack_registry.get(str(operation_id))
                operation.preflight(
                    source_frame,
                    {
                        "operation_id": operation_id,
                        "input_mode": spec.get("input_mode"),
                        "column_bindings": spec.get("column_bindings"),
                        "options": spec.get("options"),
                    },
                )
        except (
            P7PackAdapterError,
            P7PackRegistryError,
            StatisticalExplorationValidationError,
            OSError,
            ValueError,
        ) as error:
            match = _TYPED_WORKFLOW_ERROR_CODE.search(str(error))
            code = match.group(1) if match is not None else "P7_SOURCE_PREFLIGHT_FAILED"
            raise OperationValidationError(f"{code}: {error}") from error

