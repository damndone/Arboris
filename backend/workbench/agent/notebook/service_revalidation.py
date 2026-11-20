"""service revalidation: methods over the existing shared state."""
from __future__ import annotations
from dataclasses import replace
from ...contracts.agent.notebook_option import NotebookOptionRevision, NotebookOptionRevisionV11, NotebookOptionRevisionV12, NotebookOptionRevisionV13, NotebookOptionRevisionV14
from ...capability_factory.notebook_catalog import CapabilityBindingCatalogError
from ..context_compiler import NotebookPlanningContextV1, freshness_dependency_fingerprint, generation_context_hash
from ..trace import TraceWriter
from .errors import OptionBatchInvalid, OptionLegacyUnverified, OptionValidationFailed
from .freshness import FRESH, REVALIDATING, evaluate_option_freshness, freshness_details
from .proposal import OptionDraft
from .store import OptionView, StoredRevision
from .service_contracts import (_now)

class ServiceRevalidation:
    def revalidate_option(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        draft: OptionDraft,
        trace: TraceWriter | None = None,
    ) -> NotebookOptionRevision:
        """Produce a new revision against the current context (spec §4.3).

        Never an in-place refresh: the upstream changed, so the *reasoning* may
        no longer hold. Only the agent can decide it still does, and its decision
        becomes a new immutable snapshot that supersedes the old one.
        """

        notebook = self.get_notebook(notebook_id)
        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        current_binding_ref = getattr(current, "capability_resolution_binding_ref", None)
        if current_binding_ref is not None:
            if self.capability_bindings is None:
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                    "a bound capability option requires a current server-owned binding",
                    capability_id=draft.capability_id,
                )
            effective_draft = draft
            if effective_draft.capability_id is None:
                try:
                    capability_id = self.capability_bindings.capability_id_for_reference(
                        current_binding_ref,
                        scope_candidates=(
                            ("project", notebook.project_id),
                            ("run_family", notebook.run_family_id),
                        ),
                    )
                except CapabilityBindingCatalogError as error:
                    raise OptionBatchInvalid(
                        "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                        "the persisted capability binding cannot be resolved",
                    ) from error
                if capability_id is None:
                    raise OptionBatchInvalid(
                        "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                        "the persisted capability binding cannot be resolved",
                    )
                effective_draft = replace(draft, capability_id=capability_id)
            else:
                capability_id = effective_draft.capability_id
            try:
                current_binding = self.capability_bindings.resolve(
                    capability_id,
                    scope_candidates=(
                        ("project", notebook.project_id),
                        ("run_family", notebook.run_family_id),
                    ),
                )
            except CapabilityBindingCatalogError as error:
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_UNAVAILABLE",
                    "the server-owned capability binding is not currently usable",
                    capability_id=capability_id,
                ) from error
            if (
                current_binding is None
                or current_binding.content_digest != current_binding_ref
            ):
                raise OptionBatchInvalid(
                    "OPTION_CAPABILITY_BINDING_REVALIDATION_MISMATCH",
                    "a bound capability option must retain the same current binding",
                    option_id=option_id,
                    option_revision=current.option_revision,
                )
            draft = effective_draft

        proposal, contract, risk_level = self._prepare(
            notebook, context, draft, binding=current_binding if current_binding_ref else None
        )

        if trace is not None:
            trace.emit(
                "option.lifecycle.changed",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "from_status": current.freshness_status,
                    "to_status": REVALIDATING,
                    "axis": "freshness",
                },
            )

        revision_values = {
            "option_revision": current.option_revision + 1,
            "generation_context_id": context.context_id,
            "generation_context_hash": generation_context_hash(context),
            "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
            "typed_proposal_id": proposal.proposal_id,
            "typed_proposal_revision": proposal.proposal_revision,
            "artifact_contract": contract,
            "rationale": draft.rationale,
            "assumptions": tuple(draft.assumptions),
            "risk_level": risk_level,
            "lifecycle_status": view.lifecycle_status,
            "freshness_status": FRESH,
            "validation_status": "valid",
            "rank": draft.rank,
            "created_at": _now(),
            "supersedes_option_revision": current.option_revision,
        }
        if isinstance(current, NotebookOptionRevisionV12):
            revision = replace(current, **revision_values)
        elif isinstance(current, NotebookOptionRevisionV11):
            v11_values = {
                "option_id": current.option_id,
                "notebook_id": current.notebook_id,
                "run_family_id": current.run_family_id,
                "batch_id": current.batch_id,
                "evidence_refs": current.evidence_refs,
                "comparative_claims": current.comparative_claims,
                "recommendation_decision_id": current.recommendation_decision_id,
                "recommendation_status": current.recommendation_status,
                **revision_values,
            }
            if proposal.memory_default_sources:
                revision_type = (
                    NotebookOptionRevisionV14
                    if all(source.has_display_metadata for source in proposal.memory_default_sources)
                    else NotebookOptionRevisionV13
                )
                revision = revision_type(
                    **v11_values,
                    memory_default_sources=proposal.memory_default_sources,
                )
            else:
                revision = NotebookOptionRevisionV11(**v11_values)
        else:
            if proposal.memory_default_sources:
                raise OptionValidationFailed(
                    "a legacy option cannot adopt a memory-derived default through revalidation",
                    option_id=option_id,
                    operation_id=proposal.operation_id,
                    validation_issues=[
                        {
                            "code": "MEMORY_DEFAULT_LEGACY_REVISION_UNSUPPORTED",
                            "detail": "generate a new evidence-backed option instead",
                        }
                    ],
                )
            revision = replace(current, **revision_values)
        self._append_revision(
            notebook_id,
            StoredRevision(
                revision=revision,
                proposal=proposal,
                canonical_proposal_hash=proposal.canonical_hash(),
            ),
        )
        if trace is not None:
            trace.emit(
                "option.revision.created",
                payload={
                    "option_id": option_id,
                    "option_revision": revision.option_revision,
                    "generation_context_hash": revision.generation_context_hash,
                    "freshness_dependency_fingerprint": (
                        revision.freshness_dependency_fingerprint
                    ),
                    "supersedes_option_revision": current.option_revision,
                },
            )
            trace.emit(
                "proposal.validation.completed",
                payload={
                    "option_id": option_id,
                    "option_revision": revision.option_revision,
                    "proposal_id": proposal.proposal_id,
                    "validation_status": "valid",
                },
            )
        return revision


    def list_options(
        self, notebook_id: str, *, context: NotebookPlanningContextV1 | None = None
    ) -> list[OptionView]:
        return [
            self.option_view(notebook_id, option_id, context=context)
            for option_id in self.store.option_ids(notebook_id)
        ]


    def option_view(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1 | None = None,
    ) -> OptionView:
        """Read one option. With a context, also evaluate freshness — read-only.

        Evaluating does not write, does not bump the revision and does not grant
        permission to execute (spec §4.2). Repeated reads of an unchanged context
        are therefore free and leave the log untouched.
        """

        view = self.store.read_option(notebook_id, option_id)
        if context is None:
            return view
        details = freshness_details(view.current_revision, context)
        return replace(
            view,
            freshness_status=details["freshness_status"],
            freshness=details,
        )


    def evaluate_freshness(
        self, notebook_id: str, option_id: str, *, context: NotebookPlanningContextV1
    ) -> str:
        view = self.store.read_option(notebook_id, option_id)
        return evaluate_option_freshness(view.current_revision, context)


    def assert_materializable(self, notebook_id: str, option_id: str) -> None:
        """Refuse legacy option revisions before any Draft or record is created."""

        current = self.store.read_option(notebook_id, option_id).current_revision
        if not current.materializable:
            raise OptionLegacyUnverified(
                f"option {option_id} revision {current.option_revision} is legacy and "
                "cannot be materialized without verified evidence",
                option_id=option_id,
                option_revision=current.option_revision,
                contract_version=current.contract_version,
            )

