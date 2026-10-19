"""service recommendations: methods over the existing shared state."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import pandas as pd
from ...tabular_io import STATISTICAL_FORMATS, read_table
from ...contracts.agent.notebook_option import FeasibilityCandidateDecision, FeasibilityDecision, RecommendationDecisionV11
from ...canonical import sha256_canonical
from ...capability_factory.trace_contracts import CapabilityTraceEvent, build_trace_event
from ...lineage.run_family import assert_run_in_family
from ..context_compiler import NotebookPlanningContextV1, compile_notebook_planning_context, freshness_dependency_fingerprint, generation_context_hash
from ...lineage.upload_store import verify_upload
from ..trace import TraceWriter
from .errors import NotebookRunFamilyImmutable, OptionBatchInvalid, OptionMaterializationFailed, OptionValidationFailed
from .proposal import OptionDraft, TypedProposal
from .recommendation import ComparisonDecisionRecord, RecommendationValidator, ServerDecisionRegistry, candidate_cohort_hash
from .store import Notebook, ProjectionSource
from .evidence import DatasetSource, DataEvidencePackV1, InspectionRequest, RunSource, compile_evidence_pack

class ServiceRecommendations:
    def persist_server_decision(
        self,
        notebook_id: str,
        decision: FeasibilityDecision | ComparisonDecisionRecord,
    ) -> None:
        """Persist one trusted recommendation source decision for a Notebook.

        This is a control-plane seam for Workbench-owned validators.  Agent
        payloads still cannot register a decision, and the append-only store is
        the only source used when a later recommendation is validated.
        """

        self.get_notebook(notebook_id)
        self.store.append_server_decision(notebook_id, decision)


    def derive_server_recommendation(
        self,
        notebook_id: str,
        *,
        context: NotebookPlanningContextV1,
        drafts: Sequence[OptionDraft],
        batch_id: str,
        evidence_pack: DataEvidencePackV1,
        capability_trace_sink: Callable[[CapabilityTraceEvent], None] | None = None,
    ) -> tuple[tuple[OptionDraft, ...], RecommendationDecisionV11]:
        """Revalidate an Agent cohort and derive one server-owned decision.

        The Agent can propose typed drafts and bounded evidence, but it cannot
        decide feasibility.  This stage validates every draft against the
        operation and capability registries, persists the complete cohort, and
        only then asks the V1.1 validator to create a recommendation.  This
        first server protocol is intentionally structural: when more than one
        candidate is valid it reports ``insufficient_evidence`` until an
        independent comparison protocol is registered.
        """

        notebook = self.get_notebook(notebook_id)
        self._assert_batch_shape(drafts)
        if type(batch_id) is not str or not batch_id:
            raise OptionBatchInvalid(
                "OPTION_SERVER_BATCH_ID_INVALID",
                "the server recommendation batch id must be a non-empty string",
            )
        option_ids = tuple(draft.option_id or "" for draft in drafts)
        if any(not option_id for option_id in option_ids):
            raise OptionBatchInvalid(
                "OPTION_SERVER_OPTION_ID_REQUIRED",
                "server recommendation requires a stable option id for every candidate",
            )
        if len(set(option_ids)) != len(option_ids):
            raise OptionBatchInvalid(
                "OPTION_SERVER_OPTION_ID_DUPLICATE",
                "server recommendation candidate option ids must be unique",
            )
        if not isinstance(evidence_pack, DataEvidencePackV1) or not evidence_pack.records:
            raise OptionBatchInvalid(
                "OPTION_SERVER_FEASIBILITY_UNAVAILABLE",
                "server recommendation requires a non-empty evidence pack",
            )
        evidence_records = {
            record.evidence_id: record for record in evidence_pack.records
        }
        referenced_evidence_ids: set[str] = set()
        for draft in drafts:
            for evidence_ref in draft.evidence_refs:
                record = evidence_records.get(evidence_ref.evidence_id)
                if record is None or record.result_hash != evidence_ref.result_hash:
                    raise OptionBatchInvalid(
                        "OPTION_SERVER_EVIDENCE_BINDING_INVALID",
                        "a candidate evidence reference is not covered by the server evidence pack",
                        option_id=draft.option_id,
                        evidence_id=evidence_ref.evidence_id,
                    )
                if record.status != "completed":
                    raise OptionBatchInvalid(
                        "OPTION_SERVER_FEASIBILITY_INCOMPLETE",
                        "server recommendation requires completed evidence for every referenced record",
                        option_id=draft.option_id,
                        evidence_id=evidence_ref.evidence_id,
                    )
                referenced_evidence_ids.add(evidence_ref.evidence_id)
        decision_evidence_ids = referenced_evidence_ids or {
            record.evidence_id
            for record in evidence_pack.records
            if record.status == "completed"
        }
        if not decision_evidence_ids:
            raise OptionBatchInvalid(
                "OPTION_SERVER_FEASIBILITY_UNAVAILABLE",
                "server recommendation requires at least one completed evidence record",
            )
        decision_evidence_pack = DataEvidencePackV1(
            source_id=evidence_pack.source_id,
            records=tuple(
                record
                for record in evidence_pack.records
                if record.evidence_id in decision_evidence_ids
            ),
        )

        # Validate every candidate before any source decision is written.  The
        # Agent's blocked_reason is deliberately not consulted here.
        bindings = self._resolve_capability_bindings(
            notebook,
            drafts,
            recommendation_decision=None,
            require_recommendation_decision=False,
        )
        prepared = [
            self._prepare(notebook, context, draft, binding=binding)
            for draft, binding in zip(drafts, bindings)
        ]

        evidence_hash = decision_evidence_pack.evidence_pack_hash
        self.store.append_evidence_pack(notebook_id, evidence_pack.to_dict())
        if decision_evidence_pack.evidence_pack_hash != evidence_pack.evidence_pack_hash:
            self.store.append_evidence_pack(
                notebook_id, decision_evidence_pack.to_dict()
            )
        context_hash = generation_context_hash(context)
        freshness_hash = freshness_dependency_fingerprint(context)
        cohort_hash = candidate_cohort_hash(option_ids)
        feasibility_seed = {
            "protocol": "notebook.server.preflight/v1",
            "batch_id": batch_id,
            "candidate_option_ids": option_ids,
            "candidate_cohort_hash": cohort_hash,
            "generation_context_hash": context_hash,
            "freshness_dependency_fingerprint": freshness_hash,
            "evidence_pack_hashes": (evidence_hash,),
        }
        feasibility_id = f"feasibility_{sha256_canonical(feasibility_seed)[:24]}"
        candidates = tuple(
            FeasibilityCandidateDecision(
                option_id=option_id,
                protocol_id="notebook.server.preflight",
                protocol_version="v1",
                inspection_refs=(
                    "server_validation:"
                    + sha256_canonical(
                        {
                            "option_id": option_id,
                            "proposal_hash": proposal.canonical_hash(),
                        }
                    )[:24],
                ),
                evidence_refs=(evidence_hash,),
                outcome="feasible",
                reason_code="SERVER_VALIDATED",
            )
            for option_id, (proposal, _contract, _risk) in zip(option_ids, prepared)
        )
        feasibility = FeasibilityDecision(
            feasibility_decision_id=feasibility_id,
            batch_id=batch_id,
            generation_context_hash=context_hash,
            freshness_dependency_fingerprint=freshness_hash,
            evidence_pack_hashes=(evidence_hash,),
            candidate_option_ids=option_ids,
            candidate_cohort_hash=cohort_hash,
            candidates=candidates,
            validator_revision="notebook.server.preflight/v1",
        )
        self.persist_server_decision(notebook_id, feasibility)
        decision = RecommendationValidator().decide_v11(
            batch_id=batch_id,
            candidate_option_ids=option_ids,
            generation_context_hash=context_hash,
            freshness_dependency_fingerprint=freshness_hash,
            evidence_pack_hashes=(evidence_hash,),
            decision_registry=self.read_server_decision_registry(notebook_id),
            feasibility_decision_ref=feasibility.feasibility_decision_id,
        )
        if capability_trace_sink is not None:
            capability_trace_sink(
                build_trace_event(
                    event_type="option.feasibility.decided",
                    payload={
                        "decision_ref": sha256_canonical(decision.to_dict()),
                        "candidate_cohort_ref": feasibility.candidate_cohort_hash,
                        "outcome": decision.outcome,
                    },
                )
            )
        normalized = tuple(
            replace(
                draft,
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
            for draft in drafts
        )
        return normalized, decision


    def read_server_decision_registry(self, notebook_id: str) -> ServerDecisionRegistry:
        """Rebuild the recommendation source registry from persisted records."""

        self.get_notebook(notebook_id)
        return self.store.read_server_decision_registry(notebook_id)


    def rebind_run_family(self, notebook_id: str, *, run_family_id: str) -> None:
        """Always refuses. Present so the refusal is explicit, not an omission."""

        notebook = self.get_notebook(notebook_id)
        raise NotebookRunFamilyImmutable(
            f"notebook {notebook_id} is bound to {notebook.run_family_id}; a notebook "
            "belongs to exactly one analysis line for its whole life (spec §2.3). "
            "Create another notebook for another family.",
            notebook_id=notebook_id,
            run_family_id=notebook.run_family_id,
            requested_run_family_id=run_family_id,
        )


    def validate_dataset_recipe_preflight(
        self,
        notebook_id: str,
        proposal: TypedProposal,
    ) -> None:
        """Validate a dataset Recipe against its complete source without writing.

        The Recipe owner remains the only authority for input eligibility.  The
        service exposes this read-only bridge so both Agent planning and Option
        admission reject a source before a supposedly executable option is
        persisted.
        """

        notebook = self.get_notebook(notebook_id)
        payload = proposal.to_dict() if isinstance(proposal, TypedProposal) else proposal
        if not isinstance(payload, Mapping):
            return
        from .materialization import NotebookOptionMaterializer

        try:
            NotebookOptionMaterializer(self).validate_dataset_recipe_preflight(
                notebook, payload
            )
        except OptionMaterializationFailed as error:
            raise OptionValidationFailed(
                f"option dataset Recipe input preflight failed: {error}",
                operation_id=payload.get("operation_id"),
                validation_issues=[
                    {
                        "code": "RECIPE_INPUT_PREFLIGHT_FAILED",
                        "detail": str(error),
                    }
                ],
            ) from error


    def set_focus(
        self, notebook_id: str, *, user_focus: Mapping[str, Any]
    ) -> Notebook:
        """Record what the user is now looking at (spec §4.2 upstream input).

        `user_focus` is a freshness dependency: changing it between a read and a
        confirm is exactly the race the fail-closed gate exists to catch. The
        write goes to the notebook log, never to any option log, so it does not
        touch an option's append-only revision history.
        """

        self.get_notebook(notebook_id)  # existence check
        self.store.append_notebook_state(
            notebook_id, {"user_focus": dict(user_focus), "reason": "set_focus"}
        )
        return self.get_notebook(notebook_id)


    def compile_context(
        self, notebook_id: str, *, focused_run_id: str | None = None
    ) -> NotebookPlanningContextV1:
        """Compile the bounded planning context for this notebook (Gate 2).

        Reads the notebook's persisted premises (analysis contract, user focus,
        capabilities, active head) and the options that already exist, then hands
        them to the one deterministic compiler. The existing options ride in the
        generation view but never in the freshness fingerprint — that separation
        is what lets a batch of siblings stay fresh (spec §4.0).
        """

        notebook = self.get_notebook(notebook_id)
        source = notebook.projection_source
        comparison_run_id: str | None = None
        dataset_profile_override: dict[str, Any] | None = None
        if source is not None and source.kind == "run":
            comparison_run_id = focused_run_id or notebook.focused_run_id
            if comparison_run_id is not None:
                assert_run_in_family(
                    self.project_root,
                    run_id=comparison_run_id,
                    run_family_id=notebook.run_family_id,
                )
        elif source is not None and source.kind == "dataset":
            if focused_run_id is not None:
                raise ValueError("dataset projection does not accept focused_run_id")
            dataset_profile_override = self._dataset_header_profile(source)
        elif focused_run_id is not None:
            raise ValueError("source-less notebook does not accept focused_run_id")
        return compile_notebook_planning_context(
            self.project_root,
            notebook_id=notebook.notebook_id,
            run_family_id=notebook.run_family_id,
            active_head_run_id=notebook.active_head_run_id,
            analysis_contract=dict(notebook.analysis_contract),
            user_focus=dict(notebook.user_focus),
            existing_option_summaries=self._existing_option_summaries(notebook_id),
            available_capabilities=list(notebook.available_capabilities),
            projection_source=source.to_dict() if source is not None else None,
            current_family_head_run_id=comparison_run_id,
            dataset_profile_override=dataset_profile_override,
            evidence_pack_refs=self.store.list_evidence_pack_hashes(notebook_id),
        )


    def compile_evidence_pack(
        self,
        notebook_id: str,
        *,
        requests: tuple[InspectionRequest, ...],
        source: RunSource | DatasetSource | None = None,
        capabilities: Mapping[str, Any] | None = None,
        trace: TraceWriter | None = None,
    ) -> DataEvidencePackV1:
        """Compile and durably append a source-bound, read-only evidence pack."""

        notebook = self.get_notebook(notebook_id)
        if source is None:
            projection = notebook.projection_source
            if projection is None:
                raise ValueError("evidence requires a persisted projection source")
            if projection.kind == "run":
                source = RunSource(projection.run_id or notebook.active_head_run_id or "")
            else:
                source = DatasetSource(
                    projection.upload_sha256 or "",
                    projection.filename or "dataset.csv",
                    tuple(projection.sheet_names),
                )
        pack = compile_evidence_pack(
            self.project_root,
            source=source,
            requests=requests,
            capabilities=capabilities,
            trace=trace,
        )
        self.store.append_evidence_pack(notebook_id, pack.to_dict())
        return pack


    def _dataset_header_profile(self, source: ProjectionSource) -> dict[str, Any]:
        """Read only bounded schema metadata from a verified upload, never rows."""

        path = verify_upload(self.project_root, source.upload_sha256)
        suffix = Path(source.filename or "").suffix.lower()
        if suffix == ".csv":
            frame = pd.read_csv(path, nrows=0)
        elif suffix in {".xlsx", ".xls"}:
            with pd.ExcelFile(path) as workbook:
                sheet = source.sheet_names[0] if source.sheet_names else workbook.sheet_names[0]
                frame = pd.read_excel(workbook, sheet_name=sheet, nrows=0)
        elif suffix in STATISTICAL_FORMATS:
            frame = read_table(path, suffix=suffix, nrows=0)
        else:
            raise ValueError(f"unsupported dataset upload type: {suffix or 'unknown'}")
        return {
            "columns": [
                {"name": str(column), "dtype": str(dtype)}
                for column, dtype in frame.dtypes.items()
            ],
            "source_kind": "verified_upload",
        }


    def _existing_option_summaries(self, notebook_id: str) -> list[dict[str, Any]]:
        """A deterministic, content-only digest of every option already stored.

        No timestamps and no freshness verdict: the summary is hashed into the
        generation context, so anything volatile here would make the generation
        hash move for reasons unrelated to the analysis premises.
        """

        summaries: list[dict[str, Any]] = []
        for option_id in self.store.option_ids(notebook_id):
            view = self.store.read_option(notebook_id, option_id)
            current = view.current_revision
            summaries.append(
                {
                    "option_id": option_id,
                    "batch": view.batch_id,
                    "rank": view.rank,
                    "option_revision": current.option_revision,
                    "lifecycle_status": view.lifecycle_status,
                    "canonical_proposal_hash": (
                        view.current_stored_revision.canonical_proposal_hash
                    ),
                }
            )
        return summaries


    def set_active_head(
        self,
        notebook_id: str,
        run_id: str,
        *,
        reason: str,
        trace: TraceWriter | None = None,
    ) -> Notebook:
        """Advance the head, refusing any run from another family.

        DEC-NB-001: cross-family runs may be *referenced*; they may never become
        the head. `assert_run_in_family` raises `RunFamilyMismatch`.
        """

        notebook = self.get_notebook(notebook_id)
        assert_run_in_family(
            self.project_root, run_family_id=notebook.run_family_id, run_id=run_id
        )
        previous = notebook.active_head_run_id
        self.store.append_notebook_state(
            notebook_id,
            {"active_head_run_id": run_id, "focused_run_id": run_id, "reason": reason},
        )
        if trace is not None:
            trace.emit(
                "active_head.changed",
                payload={"from_run_id": previous, "to_run_id": run_id, "reason": reason},
            )
        return self.get_notebook(notebook_id)

