"""service planning: methods over the existing shared state."""
from __future__ import annotations
import time
from typing import Any, Sequence
from uuid import uuid4
from ...contracts.agent.notebook_option import NotebookOptionRevision, NotebookOptionRevisionV11, NotebookOptionRevisionV12, NotebookOptionRevisionV13, NotebookOptionRevisionV14, RecommendationDecision, RecommendationDecisionV11
from ...capability_factory.notebook_binding import CapabilityResolutionBinding
from ..context_compiler import NotebookPlanningContextV1, freshness_dependency_fingerprint, generation_context_hash
from ..trace import TraceWriter
from .errors import OptionBatchInvalid, OptionNotFound
from .freshness import FRESH
from .proposal import OptionDraft, TypedProposal
from .store import RECORD_OPTION, Notebook, OptionView, StoredRevision
from .service_contracts import (_execution_modes_for, _now)

class ServicePlanning:
    def propose_batch(
        self,
        notebook_id: str,
        *,
        context: NotebookPlanningContextV1,
        drafts: Sequence[OptionDraft],
        trace: TraceWriter | None = None,
        batch_id: str | None = None,
        recommendation_decision: RecommendationDecision | RecommendationDecisionV11 | None = None,
        revalidate_existing: bool = False,
    ) -> tuple[NotebookOptionRevision, ...]:
        """Validate a whole batch, then write it. Never the other way round.

        Everything is checked before the first `append`, so a batch that breaks
        §6 or §7 leaves no partial trace of itself in the option log — a half
        written batch would show the user options that were never approved.
        """

        notebook = self.get_notebook(notebook_id)
        started = time.monotonic()
        if trace is not None:
            trace.emit(
                "agent.plan.requested",
                payload={
                    "context_id": context.context_id,
                    "requested_option_count": len(drafts),
                },
            )

        self._assert_batch_shape(drafts)
        self._validate_recommendation_decision(
            notebook_id,
            recommendation_decision,
        )
        bindings = self._resolve_capability_bindings(
            notebook,
            drafts,
            recommendation_decision=recommendation_decision,
        )
        prepared = [
            self._prepare(notebook, context, draft, binding=binding)
            for draft, binding in zip(drafts, bindings)
        ]

        # An explicit Agent replan is a revalidation episode for any provider
        # option ids that already exist.  Stable option_id means a new
        # append-only option_revision, not a second object with the same
        # identity and not a silent overwrite.  Keep the ordinary public
        # propose_batch path strict so callers that did not explicitly request
        # revalidation still receive OPTION_ID_REUSE_CONFLICT.
        if revalidate_existing and any(draft.option_id for draft in drafts):
            existing = []
            for draft in drafts:
                if not draft.option_id:
                    existing.append(None)
                    continue
                try:
                    existing.append(self.store.read_option(notebook_id, draft.option_id))
                except OptionNotFound:
                    existing.append(None)
            if any(item is not None for item in existing):
                return self._revalidate_planning_batch(
                    notebook=notebook,
                    context=context,
                    drafts=drafts,
                    prepared=prepared,
                    existing=existing,
                    bindings=bindings,
                    batch_id=batch_id,
                    recommendation_decision=recommendation_decision,
                    trace=trace,
                )

        # Browser remounts and request retries can submit the same typed batch
        # more than once.  A stable option_id is an identity, not permission to
        # append another option@rev1; replay the exact same semantic revision
        # and reject a conflicting reuse so the append-only log stays foldable.
        replayed: list[NotebookOptionRevision] = []
        for draft, (proposal, contract, risk_level), binding in zip(
            drafts, prepared, bindings
        ):
            if not draft.option_id:
                replayed = []
                break
            try:
                existing = self.store.read_option(notebook_id, draft.option_id)
            except OptionNotFound:
                replayed = []
                break
            current = existing.current_revision
            same_semantics = (
                current.generation_context_hash == generation_context_hash(context)
                and existing.current_stored_revision.canonical_proposal_hash
                == proposal.canonical_hash()
                and current.rank == draft.rank
                and current.rationale == draft.rationale
                and current.assumptions == tuple(draft.assumptions)
                and current.risk_level == risk_level
                and current.artifact_contract == contract
                and current.evidence_refs == tuple(draft.evidence_refs)
                and current.comparative_claims == tuple(draft.comparative_claims)
                and getattr(current, "recommendation_status", None)
                == (
                    recommendation_decision.outcome
                    if recommendation_decision is not None
                    else draft.recommendation_status
                )
                and getattr(current, "capability_resolution_binding_ref", None)
                == (binding.content_digest if binding is not None else None)
                and tuple(getattr(current, "memory_default_sources", ()))
                == proposal.memory_default_sources
            )
            if not same_semantics:
                raise OptionBatchInvalid(
                    "OPTION_ID_REUSE_CONFLICT",
                    "an existing option_id is already bound to a different typed revision; revalidate it instead",
                    option_id=draft.option_id,
                )
            replayed.append(current)
        if replayed and len(replayed) == len(drafts):
            if trace is not None:
                trace.emit(
                    "agent.plan.completed",
                    payload={
                        "context_id": context.context_id,
                        "generated_option_count": len(replayed),
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "stop_reason": "idempotent_replay",
                    },
                )
            return tuple(replayed)

        if recommendation_decision is not None:
            option_ids = tuple(draft.option_id or "" for draft in drafts)
            if batch_id is not None and batch_id != recommendation_decision.batch_id:
                raise OptionBatchInvalid(
                    "OPTION_BATCH_DECISION_MISMATCH",
                    "the recommendation decision batch_id must match the persisted option batch",
                )
            if (
                any(not option_id for option_id in option_ids)
                or option_ids != recommendation_decision.candidate_option_ids
                or any(
                    draft.recommendation_decision_id != recommendation_decision.recommendation_decision_id
                    or draft.recommendation_status != recommendation_decision.outcome
                    for draft in drafts
                )
            ):
                raise OptionBatchInvalid(
                    "OPTION_BATCH_DECISION_MISMATCH",
                    "the persisted recommendation decision must name and classify every option in the batch",
                )
        batch = batch_id or (
            recommendation_decision.batch_id
            if recommendation_decision is not None
            else f"batch_{uuid4().hex}"
        )
        created_at = _now()
        revisions: list[
            NotebookOptionRevision
            | NotebookOptionRevisionV11
            | NotebookOptionRevisionV12
            | NotebookOptionRevisionV13
            | NotebookOptionRevisionV14
        ] = []
        for draft, (proposal, contract, risk_level), binding in zip(
            drafts, prepared, bindings
        ):
            option_id = draft.option_id or f"opt_{uuid4().hex}"
            revision: NotebookOptionRevision | NotebookOptionRevisionV11
            if recommendation_decision is not None:
                if binding is not None:
                    revision_type = NotebookOptionRevisionV12
                elif proposal.memory_default_sources:
                    revision_type = (
                        NotebookOptionRevisionV14
                        if all(source.has_display_metadata for source in proposal.memory_default_sources)
                        else NotebookOptionRevisionV13
                    )
                else:
                    revision_type = NotebookOptionRevisionV11
                revision_kwargs = {
                    "option_id": option_id,
                    "option_revision": 1,
                    "notebook_id": notebook.notebook_id,
                    "run_family_id": notebook.run_family_id,
                    "generation_context_id": context.context_id,
                    "generation_context_hash": generation_context_hash(context),
                    "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
                    "typed_proposal_id": proposal.proposal_id,
                    "typed_proposal_revision": proposal.proposal_revision,
                    "artifact_contract": contract,
                    "rationale": draft.rationale,
                    "assumptions": tuple(draft.assumptions),
                    "risk_level": risk_level,
                    "lifecycle_status": "proposed",
                    "freshness_status": FRESH,
                    "validation_status": "valid",
                    "rank": draft.rank,
                    "batch_id": batch,
                    "created_at": created_at,
                    "evidence_refs": tuple(draft.evidence_refs),
                    "comparative_claims": tuple(draft.comparative_claims),
                    "recommendation_decision_id": recommendation_decision.recommendation_decision_id,
                    "recommendation_status": recommendation_decision.outcome,
                }
                if binding is not None:
                    revision_kwargs.update(
                        {
                            "capability_resolution_binding_ref": binding.content_digest,
                            "execution_modes": _execution_modes_for(
                                risk_level, proposal.operation_id
                            ),
                        }
                    )
                if proposal.memory_default_sources:
                    revision_kwargs["memory_default_sources"] = proposal.memory_default_sources
                revision = revision_type(**revision_kwargs)
            else:
                revision = NotebookOptionRevision(
                    option_id=option_id,
                    option_revision=1,
                    notebook_id=notebook.notebook_id,
                    run_family_id=notebook.run_family_id,
                    generation_context_id=context.context_id,
                    generation_context_hash=generation_context_hash(context),
                    freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                    typed_proposal_id=proposal.proposal_id,
                    typed_proposal_revision=proposal.proposal_revision,
                    artifact_contract=contract,
                    rationale=draft.rationale,
                    assumptions=tuple(draft.assumptions),
                    risk_level=risk_level,
                    lifecycle_status="proposed",
                    freshness_status=FRESH,
                    validation_status="valid",
                    rank=draft.rank,
                    batch_id=batch,
                    created_at=created_at,
                )
            revisions.append(revision)

        # All contract construction is complete before the first append. This
        # keeps the decision and option logs from diverging on a malformed v1.1
        # revision.
        if recommendation_decision is not None:
            self.store.append_decision(notebook_id, recommendation_decision)

        for draft, revision, (proposal, _contract, risk_level) in zip(
            drafts, revisions, prepared
        ):
            option_id = revision.option_id
            self.store.append_option_record(
                notebook_id,
                option_id,
                {
                    "record_type": RECORD_OPTION,
                    "option_id": option_id,
                    "notebook_id": notebook_id,
                    "batch_id": batch,
                    "rank": draft.rank,
                    "created_at": created_at,
                },
            )
            self._append_revision(
                notebook_id,
                StoredRevision(
                    revision=revision,
                    proposal=proposal,
                    canonical_proposal_hash=proposal.canonical_hash(),
                ),
            )
            self._append_lifecycle(
                notebook_id,
                option_id,
                from_status=None,
                to_status="proposed",
                revision=1,
                actor="agent",
                reason="generated",
            )
            if trace is not None:
                revision_trace_payload = {
                    "option_id": option_id,
                    "option_revision": 1,
                    "generation_context_hash": revision.generation_context_hash,
                    "freshness_dependency_fingerprint": (
                        revision.freshness_dependency_fingerprint
                    ),
                    "rank": draft.rank,
                    "risk_level": risk_level,
                }
                if binding is not None:
                    revision_trace_payload["capability_resolution_binding_ref"] = (
                        binding.content_digest
                    )
                trace.emit(
                    "option.revision.created",
                    payload=revision_trace_payload,
                )
                trace.emit(
                    "proposal.validation.completed",
                    payload={
                        "option_id": option_id,
                        "option_revision": 1,
                        "proposal_id": proposal.proposal_id,
                        "validation_status": "valid",
                    },
                )

        if trace is not None:
            plan_payload = {
                "context_id": context.context_id,
                "generated_option_count": len(revisions),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "stop_reason": "complete",
            }
            if recommendation_decision is not None:
                plan_payload.update(
                    {
                        "recommendation_decision_id": recommendation_decision.recommendation_decision_id,
                        "recommendation_outcome": recommendation_decision.outcome,
                        "recommended_option_id": recommendation_decision.recommended_option_id,
                        "evidence_pack_hashes": list(recommendation_decision.evidence_pack_hashes),
                        "comparison_protocol_refs": list(
                            getattr(recommendation_decision, "comparison_protocol_refs", ())
                        ),
                    }
                )
            trace.emit(
                "agent.plan.completed",
                payload=plan_payload,
            )
        return tuple(revisions)


    def _revalidate_planning_batch(
        self,
        *,
        notebook: Notebook,
        context: NotebookPlanningContextV1,
        drafts: Sequence[OptionDraft],
        prepared: Sequence[tuple[TypedProposal, Any, str]],
        existing: Sequence[OptionView | None],
        bindings: Sequence[CapabilityResolutionBinding | None],
        batch_id: str | None,
        recommendation_decision: RecommendationDecision | RecommendationDecisionV11 | None,
        trace: TraceWriter | None,
    ) -> tuple[NotebookOptionRevision, ...]:
        """Persist one explicit replan as revisions of existing option ids.

        This is intentionally separate from ``propose_batch``'s idempotent
        replay path.  A replan may change the typed proposal and evidence, so
        it must receive a fresh recommendation decision and a higher option
        revision while retaining the stable option identity.
        """

        if recommendation_decision is None:
            raise OptionBatchInvalid(
                "OPTION_REVALIDATION_DECISION_REQUIRED",
                "an explicit planning revalidation must carry a recommendation decision",
            )
        option_ids = tuple(draft.option_id or "" for draft in drafts)
        if (
            any(not option_id for option_id in option_ids)
            or option_ids != recommendation_decision.candidate_option_ids
            or any(
                draft.recommendation_decision_id
                != recommendation_decision.recommendation_decision_id
                or draft.recommendation_status != recommendation_decision.outcome
                for draft in drafts
            )
        ):
            raise OptionBatchInvalid(
                "OPTION_BATCH_DECISION_MISMATCH",
                "the revalidated recommendation decision must name and classify every option in the batch",
            )
        batch = batch_id or recommendation_decision.batch_id
        created_at = _now()
        revisions: list[
            NotebookOptionRevision
            | NotebookOptionRevisionV11
            | NotebookOptionRevisionV12
            | NotebookOptionRevisionV13
            | NotebookOptionRevisionV14
        ] = []
        stored: list[StoredRevision | None] = []
        for draft, (proposal, contract, risk_level), prior, binding in zip(
            drafts, prepared, existing, bindings
        ):
            if prior is None:
                option_id = draft.option_id or f"opt_{uuid4().hex}"
                revision_number = 1
                lifecycle_status = "proposed"
                supersedes = None
            else:
                if prior.lifecycle_status not in {"proposed", "deferred", "selected"}:
                    # Replans are allowed to include the provider's previous
                    # candidate set, but terminal options are immutable. Keep
                    # their last revision exactly as-is and let the eligible
                    # siblings receive fresh revisions. This avoids turning a
                    # remount/replan into a lifecycle transition out of
                    # materialized, executed, rejected, or archived state.
                    revisions.append(prior.current_revision)
                    stored.append(None)
                    continue
                current = prior.current_revision
                previous_binding_ref = getattr(
                    current, "capability_resolution_binding_ref", None
                )
                if previous_binding_ref is not None and (
                    binding is None or binding.content_digest != previous_binding_ref
                ):
                    raise OptionBatchInvalid(
                        "OPTION_CAPABILITY_BINDING_REVALIDATION_MISMATCH",
                        "a bound capability option cannot be revalidated without the same current binding",
                        option_id=prior.option_id,
                        option_revision=current.option_revision,
                    )
                option_id = prior.option_id
                revision_number = current.option_revision + 1
                lifecycle_status = prior.lifecycle_status
                supersedes = current.option_revision
            if binding is not None:
                revision_type = NotebookOptionRevisionV12
            elif proposal.memory_default_sources:
                revision_type = (
                    NotebookOptionRevisionV14
                    if all(source.has_display_metadata for source in proposal.memory_default_sources)
                    else NotebookOptionRevisionV13
                )
            else:
                revision_type = NotebookOptionRevisionV11
            revision_kwargs = {
                "option_id": option_id,
                "option_revision": revision_number,
                "notebook_id": notebook.notebook_id,
                "run_family_id": notebook.run_family_id,
                "generation_context_id": context.context_id,
                "generation_context_hash": generation_context_hash(context),
                "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
                "typed_proposal_id": proposal.proposal_id,
                "typed_proposal_revision": proposal.proposal_revision,
                "artifact_contract": contract,
                "rationale": draft.rationale,
                "assumptions": tuple(draft.assumptions),
                "risk_level": risk_level,
                "lifecycle_status": lifecycle_status,
                "freshness_status": FRESH,
                "validation_status": "valid",
                "rank": draft.rank,
                "batch_id": batch,
                "created_at": created_at,
                "evidence_refs": tuple(draft.evidence_refs),
                "comparative_claims": tuple(draft.comparative_claims),
                "recommendation_decision_id": recommendation_decision.recommendation_decision_id,
                "recommendation_status": recommendation_decision.outcome,
                "supersedes_option_revision": supersedes,
            }
            if binding is not None:
                revision_kwargs.update(
                    {
                        "capability_resolution_binding_ref": binding.content_digest,
                        "execution_modes": _execution_modes_for(
                            risk_level, proposal.operation_id
                        ),
                    }
                )
            if proposal.memory_default_sources:
                revision_kwargs["memory_default_sources"] = proposal.memory_default_sources
            revision = revision_type(**revision_kwargs)
            revisions.append(revision)
            stored.append(
                StoredRevision(
                    revision=revision,
                    proposal=proposal,
                    canonical_proposal_hash=proposal.canonical_hash(),
                )
            )

        # All revisions are constructed and validated before the first append.
        self.store.append_decision(notebook.notebook_id, recommendation_decision)
        for draft, revision, stored_revision, prior in zip(
            drafts, revisions, stored, existing
        ):
            if stored_revision is None:
                if trace is not None:
                    trace.emit(
                        "option.replan.skipped_terminal",
                        payload={
                            "option_id": revision.option_id,
                            "option_revision": revision.option_revision,
                            "lifecycle_status": revision.lifecycle_status,
                        },
                    )
                continue
            if prior is None:
                self.store.append_option_record(
                    notebook.notebook_id,
                    revision.option_id,
                    {
                        "record_type": RECORD_OPTION,
                        "option_id": revision.option_id,
                        "notebook_id": notebook.notebook_id,
                        "batch_id": batch,
                        "rank": draft.rank,
                        "created_at": created_at,
                    },
                )
                self._append_lifecycle(
                    notebook.notebook_id,
                    revision.option_id,
                    from_status=None,
                    to_status="proposed",
                    revision=revision.option_revision,
                    actor="agent",
                    reason="generated",
                )
            self._append_revision(notebook.notebook_id, stored_revision)
            if trace is not None:
                revision_trace_payload = {
                    "option_id": revision.option_id,
                    "option_revision": revision.option_revision,
                    "generation_context_hash": revision.generation_context_hash,
                    "freshness_dependency_fingerprint": revision.freshness_dependency_fingerprint,
                    "rank": revision.rank,
                    "risk_level": revision.risk_level,
                    "supersedes_option_revision": revision.supersedes_option_revision,
                }
                if binding is not None:
                    revision_trace_payload["capability_resolution_binding_ref"] = (
                        binding.content_digest
                    )
                trace.emit(
                    "option.revision.created",
                    payload=revision_trace_payload,
                )
                trace.emit(
                    "proposal.validation.completed",
                    payload={
                        "option_id": revision.option_id,
                        "option_revision": revision.option_revision,
                        "proposal_id": revision.typed_proposal_id,
                        "validation_status": "valid",
                    },
                )
        return tuple(revisions)

