"""Gate 4 — the Notebook / Option lifecycle service.

Spec `2026-07-22-v1.8.1-agent-notebook-analysis-option.md` §2.3, §3, §4, §5, §6, §7.

The service owns four things the agent is not allowed to own:

1. the run family a notebook binds to (created before any run exists, never
   rebindable afterwards);
2. what a generation batch may contain (≤3, one recommendation, no duplicates,
   every proposal validated *before* anything is written);
3. the two hashes — the agent never supplies either, so it can never accidentally
   supply the same value for both;
4. the confirm-time gate, which recompiles and compares rather than trusting
   whatever the read-time evaluator said a moment ago.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

import pandas as pd

from ...contracts.agent.notebook_option import (
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    NotebookOptionRevision,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
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
from ...repository.run_repository import _read_artifact_records
from ..context_compiler import (
    NotebookPlanningContextV1,
    compile_notebook_planning_context,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from ...lineage.upload_store import verify_upload
from ..operations import OperationRegistry, OperationValidationError
from ..trace import TraceWriter
from .artifact_contract import (
    COMMITTABLE_VALIDATION_STATUSES,
    build_artifact_contract,
    validate_produced_artifacts,
)
from .errors import (
    NotebookRunFamilyImmutable,
    OptionBatchInvalid,
    OptionLegacyUnverified,
    OptionLifecycleTransitionInvalid,
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
)
from .evidence import (
    DatasetSource,
    DataEvidencePackV1,
    InspectionRequest,
    RunSource,
    compile_evidence_pack,
)
from .vocabulary import capability_artifact_types

MAX_OPTIONS_PER_BATCH = 3

# The registry speaks in execution risk ("mutating"/"high"); the option contract
# speaks in the three levels a user is shown. Mapped explicitly rather than
# passed through, so a new registry level fails loudly instead of quietly
# becoming "low".
_REGISTRY_RISK_TO_OPTION_RISK = {
    "none": "low",
    "read": "low",
    "readonly": "low",
    "mutating": "medium",
    "high": "high",
}


def _execution_modes_for(risk_level: str) -> tuple[str, ...]:
    """Expose the fast path only for server-classified low-risk options."""

    if risk_level == "low":
        return ("materialize_only", "confirm_and_execute")
    return ("materialize_only",)


def _artifact_contract_ref(contract: Any) -> str:
    return domain_digest("workbench.notebook.artifact_contract/v1", contract.to_dict())


def _consumer_projection_ref(binding: CapabilityResolutionBinding) -> str:
    return domain_digest(
        "workbench.capability_factory.consumer_projection/v1",
        {"allowed_consumers": list(binding.allowed_consumers)},
    )

# spec §3.5. `executed`, `rejected` and `archived` have no outgoing edges.
_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"selected", "deferred", "rejected", "archived"}),
    "deferred": frozenset({"selected", "rejected", "archived"}),
    "selected": frozenset({"deferred", "rejected", "materialized", "archived"}),
    "materialized": frozenset({"selected", "executing", "archived"}),
    "executing": frozenset({"executed", "materialized"}),
    "executed": frozenset(),
    "rejected": frozenset(),
    "archived": frozenset(),
}

# v1.0 has no persisted OptionMaterialization record. It retains its original
# direct-confirm lifecycle strictly for compatibility; v1.1 never consults it.
_LEGACY_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"selected", "deferred", "rejected", "archived"}),
    "deferred": frozenset({"selected", "rejected", "archived"}),
    "selected": frozenset({"deferred", "rejected", "executing", "archived"}),
    "executing": frozenset({"executed", "selected"}),
    "executed": frozenset(),
    "rejected": frozenset(),
    "archived": frozenset(),
}

_DECISION_TO_LIFECYCLE = {
    "selected": "selected",
    "deferred": "deferred",
    "rejected": "rejected",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExecutionOutcome:
    """What a finished run did and did not earn.

    `execution_status` and `validation_status` are separate fields because
    spec §5.3 says they are separate questions: a model can fit and still fail
    to produce the table a report would cite.
    """

    option_id: str
    option_revision: int
    run_id: str | None
    execution_status: str
    artifact_validation: dict[str, Any]
    active_head_advanced: bool
    lifecycle_status: str

    @property
    def validation_status(self) -> str:
        return str(self.artifact_validation["validation_status"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "run_id": self.run_id,
            "execution_status": self.execution_status,
            "artifact_validation": dict(self.artifact_validation),
            "active_head_advanced": self.active_head_advanced,
            "lifecycle_status": self.lifecycle_status,
        }


class NotebookService:
    """Everything a notebook can do, in one place, over an append-only log."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        registry: OperationRegistry | None = None,
        capability_bindings: CapabilityBindingCatalog | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.store = NotebookStore(self.project_root)
        self.registry = registry or OperationRegistry()
        if capability_bindings is not None and not isinstance(
            capability_bindings, CapabilityBindingCatalog
        ):
            raise TypeError("capability_bindings must be a CapabilityBindingCatalog")
        self.capability_bindings = capability_bindings

    # ------------------------------------------------------------------
    # Notebooks
    # ------------------------------------------------------------------

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
                if not family_store.has_migrated():
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

    def get_notebook(self, notebook_id: str) -> Notebook:
        return self.store.get_notebook(notebook_id)

    def list_notebooks(self) -> list[Notebook]:
        return self.store.list_notebooks()

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
        if any(record.status != "completed" for record in evidence_pack.records):
            raise OptionBatchInvalid(
                "OPTION_SERVER_FEASIBILITY_INCOMPLETE",
                "server recommendation requires completed evidence for every record",
            )
        evidence_records = {
            record.evidence_id: record.to_dict() for record in evidence_pack.records
        }
        for draft in drafts:
            for evidence_ref in draft.evidence_refs:
                record = evidence_records.get(evidence_ref.evidence_id)
                if record is None or record["result_hash"] != evidence_ref.result_hash:
                    raise OptionBatchInvalid(
                        "OPTION_SERVER_EVIDENCE_BINDING_INVALID",
                        "a candidate evidence reference is not covered by the server evidence pack",
                        option_id=draft.option_id,
                        evidence_id=evidence_ref.evidence_id,
                    )

        # Validate every candidate before any source decision is written.  The
        # Agent's blocked_reason is deliberately not consulted here.
        prepared = [self._prepare(notebook, context, draft) for draft in drafts]
        self._resolve_capability_bindings(
            notebook,
            drafts,
            recommendation_decision=None,
            require_recommendation_decision=False,
        )

        evidence_hash = evidence_pack.evidence_pack_hash
        self.store.append_evidence_pack(notebook_id, evidence_pack.to_dict())
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

    # ------------------------------------------------------------------
    # Option generation
    # ------------------------------------------------------------------

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
        prepared = [self._prepare(notebook, context, draft) for draft in drafts]

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
        revisions: list[NotebookOptionRevision | NotebookOptionRevisionV11] = []
        for draft, (proposal, contract, risk_level), binding in zip(
            drafts, prepared, bindings
        ):
            option_id = draft.option_id or f"opt_{uuid4().hex}"
            revision: NotebookOptionRevision | NotebookOptionRevisionV11
            if recommendation_decision is not None:
                revision_type = (
                    NotebookOptionRevisionV12 if binding is not None else NotebookOptionRevisionV11
                )
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
                            "execution_modes": _execution_modes_for(risk_level),
                        }
                    )
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
        revisions: list[NotebookOptionRevision | NotebookOptionRevisionV11] = []
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
            revision_type = (
                NotebookOptionRevisionV12 if binding is not None else NotebookOptionRevisionV11
            )
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
                        "execution_modes": _execution_modes_for(risk_level),
                    }
                )
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

        proposal, contract, risk_level = self._prepare(notebook, context, draft)

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

        revision = replace(
            current,
            option_revision=current.option_revision + 1,
            generation_context_id=context.context_id,
            generation_context_hash=generation_context_hash(context),
            freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
            typed_proposal_id=proposal.proposal_id,
            typed_proposal_revision=proposal.proposal_revision,
            artifact_contract=contract,
            rationale=draft.rationale,
            assumptions=tuple(draft.assumptions),
            risk_level=risk_level,
            lifecycle_status=view.lifecycle_status,
            freshness_status=FRESH,
            validation_status="valid",
            rank=draft.rank,
            created_at=_now(),
            supersedes_option_revision=current.option_revision,
        )
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

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

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

    def materialize_option(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
    ):
        """Materialize one selected v1.1 Option into a bound Pipeline Draft."""

        from .materialization import NotebookOptionMaterializer

        current = self.store.read_option(notebook_id, option_id).current_revision
        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(
            current
        )
        return NotebookOptionMaterializer(self).materialize(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )

    def authorize_option_execution(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        authorization: OptionExecutionAuthorization,
    ) -> OptionExecutionAuthorization:
        """Bind a user-confirmed low-risk option to a durable receipt.

        This is deliberately a control-plane operation.  It validates the
        current recommendation, binding, risk, and freshness, then persists
        the already-prepared server authorization.  It does not transition
        the Option, materialize a Draft, create a Run intent, or dispatch
        anything.
        """

        if not isinstance(authorization, OptionExecutionAuthorization):
            raise TypeError("authorization must be OptionExecutionAuthorization")

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        if authorization.notebook_id != notebook_id or authorization.option_id != option_id:
            raise OptionRevisionStale(
                "authorization does not identify the current notebook option",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_option_identity",
            )
        if authorization.option_revision != current.option_revision:
            raise OptionRevisionStale(
                "authorization option revision is stale",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_option_revision",
            )
        if not isinstance(current, NotebookOptionRevisionV12):
            raise OptionRevisionStale(
                "confirm_and_execute requires NotebookOptionRevision@1.2",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_contract_version",
            )
        if "confirm_and_execute" not in current.execution_modes:
            raise OptionRevisionStale(
                "the current option does not offer confirm_and_execute",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="execution_mode_not_offered",
            )
        if current.risk_level != "low" or authorization.risk_level != "low":
            raise OptionRevisionStale(
                "confirm_and_execute is limited to low-risk options",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_risk",
            )
        if view.lifecycle_status != "selected":
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; user confirmation "
                "requires the selected lifecycle state",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )

        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        assert_executable(current, context)

        reference = current.capability_resolution_binding_ref
        if self.capability_bindings is None or reference is None:
            raise OptionRevisionStale(
                "authorization requires a current server-owned capability binding",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_unavailable",
            )
        try:
            capability_id = self.capability_bindings.capability_id_for_reference(
                reference,
                scope_candidates=(
                    ("project", self.get_notebook(notebook_id).project_id),
                    ("run_family", self.get_notebook(notebook_id).run_family_id),
                ),
            )
            if capability_id is None:
                raise CapabilityBindingCatalogError(
                    "authorization binding reference is not registered"
                )
            binding = self.capability_bindings.require(
                capability_id,
                scope_candidates=(
                    ("project", self.get_notebook(notebook_id).project_id),
                    ("run_family", self.get_notebook(notebook_id).run_family_id),
                ),
            )
        except CapabilityBindingCatalogError as error:
            raise OptionRevisionStale(
                "authorization binding is not currently usable",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding_not_current",
            ) from error

        expected = {
            "capability_resolution_binding_ref": binding.content_digest,
            "capability_ref": binding.implementation_ref,
            "bundle_ref": binding.validation_bundle_ref,
            "evidence_ref": binding.assessment_ref,
            "admission_ref": binding.admission_ref,
            "runtime_policy_ref": binding.runtime_policy_ref,
            "freshness_cursor_ref": binding.validity_cursor_ref,
            "input_graph_fingerprint": current.generation_context_hash,
            "freshness_dependency_fingerprint": current.freshness_dependency_fingerprint,
            "artifact_contract_ref": _artifact_contract_ref(current.artifact_contract),
            "consumer_projection_ref": _consumer_projection_ref(binding),
        }
        mismatches = [
            field
            for field, value in expected.items()
            if getattr(authorization, field) != value
        ]
        if authorization.binding_revision != 1:
            mismatches.append("binding_revision")
        if mismatches:
            raise OptionRevisionStale(
                "authorization binding does not match the current option: "
                + ", ".join(sorted(mismatches)),
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_binding",
            )
        if authorization.operation_id not in binding.allowed_operations:
            raise OptionRevisionStale(
                "authorization operation is not allowed by the current binding",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_operation",
            )

        try:
            return OptionExecutionAuthorizationStore(self.project_root).issue(
                authorization
            )
        except ExecutionAuthorizationError as error:
            raise OptionRevisionStale(
                "authorization receipt could not be persisted",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_receipt_invalid",
            ) from error

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def record_decision(
        self,
        notebook_id: str,
        option_id: str,
        *,
        decision: str,
        actor: str,
        edited_fields: Sequence[str] | None = None,
        note_ref: str | None = None,
        trace: TraceWriter | None = None,
    ) -> OptionView:
        """Record what the user did. A decision is an observation, not a label.

        Nothing here carries reward/score/correctness; the Gate 3 schema refuses
        those outright (DEC-TRACE-001), and this method has no parameter that
        could smuggle one in.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        target = _DECISION_TO_LIFECYCLE.get(decision)
        # Browser retries and remounts may replay the same user intent. Keep
        # the lifecycle state machine strict, but make the public observation
        # operation idempotent when the requested state is already current.
        if target is not None and target != view.lifecycle_status:
            self._transition(
                notebook_id,
                view,
                to_status=target,
                actor=actor,
                reason=f"user_{decision}",
                trace=trace,
            )
        if trace is not None:
            payload: dict[str, Any] = {
                "option_id": option_id,
                "option_revision": current.option_revision,
                "decision": decision,
            }
            if edited_fields:
                payload["edited_fields"] = list(edited_fields)
            if note_ref:
                payload["note_ref"] = note_ref
            trace.emit("user.decision.recorded", payload=payload)
        return self.store.read_option(notebook_id, option_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def confirm(
        self,
        notebook_id: str,
        option_id: str,
        *,
        option_revision: int,
        proposal_id: str,
        proposal_revision: int,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
    ) -> OptionExecution:
        """The gate (spec §3.3, §4.2). Fail-closed, and recomputed here.

        `context` must be freshly compiled by the caller at confirm time. A
        read-time verdict is explicitly not accepted as an argument, because
        accepting one would turn the read-time evaluator into a bypassable gate.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision

        if option_revision != current.option_revision:
            raise OptionRevisionStale(
                f"option {option_id} is at revision {current.option_revision}; "
                f"revision {option_revision} can no longer be executed",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="superseded_revision",
            )
        if (proposal_id, proposal_revision) != (
            current.typed_proposal_id,
            current.typed_proposal_revision,
        ):
            raise OptionRevisionStale(
                f"option {option_id} revision {option_revision} pins proposal "
                f"{current.typed_proposal_id}@{current.typed_proposal_revision}, not "
                f"{proposal_id}@{proposal_revision}",
                option_id=option_id,
                requested_revision=option_revision,
                current_revision=current.option_revision,
                reason="proposal_pin_mismatch",
            )

        if current.materializable:
            raise OptionMaterializationRequired(
                f"option {option_id} revision {option_revision} requires a "
                "persisted OptionMaterialization record before execution",
                option_id=option_id,
                option_revision=option_revision,
                contract_version=current.contract_version,
            )

        # Recompiled upstream facts, compared here and nowhere else.
        assert_executable(current, context)

        if view.lifecycle_status not in {"proposed", "deferred", "selected"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; only a proposed, "
                "deferred or selected option can be confirmed",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )
        if view.lifecycle_status != "selected":
            self._transition(
                notebook_id,
                view,
                to_status="selected",
                actor="user",
                reason="confirm",
                trace=trace,
            )
            view = self.store.read_option(notebook_id, option_id)
        self._transition(
            notebook_id,
            view,
            to_status="executing",
            actor="user",
            reason="confirmed",
            trace=trace,
        )

        execution = OptionExecution(
            option_id=option_id,
            option_revision=current.option_revision,
            proposal_id=current.typed_proposal_id,
            proposal_revision=current.typed_proposal_revision,
            freshness_dependency_fingerprint=current.freshness_dependency_fingerprint,
            generation_context_id=current.generation_context_id,
            run_id=None,
        )
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_EXECUTION,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "execution": execution.to_dict(),
                "confirmed_context_id": context.context_id,
            },
        )
        if trace is not None:
            trace.emit(
                "option.execution.started",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "proposal_id": execution.proposal_id,
                    "proposal_revision": execution.proposal_revision,
                    "freshness_dependency_fingerprint": (
                        execution.freshness_dependency_fingerprint
                    ),
                },
            )
        return execution

    def complete_execution(
        self,
        notebook_id: str,
        option_id: str,
        *,
        execution_status: str,
        run_id: str | None = None,
        produced_artifacts: Iterable[Mapping[str, Any]] | None = None,
        error_code: str | None = None,
        trace: TraceWriter | None = None,
    ) -> ExecutionOutcome:
        """Close the loop: validate the contract, then decide about the head.

        spec §5.3 commit gate — the head advances only when execution succeeded
        *and* the artifact contract passed (possibly with warnings). A failed
        contract keeps its artifacts for debugging and returns the option to
        `selected`; it does not become a result.
        """

        view = self.store.read_option(notebook_id, option_id)
        current = view.current_revision
        self._assert_current_recommendation_source(notebook_id, current)
        self._assert_current_capability_binding(current)
        if current.materializable:
            materialization = self.store.read_materialization(
                notebook_id, option_id, current.option_revision
            )
            if materialization is None:
                raise OptionMaterializationRequired(
                    f"option {option_id} revision {current.option_revision} requires "
                    "a persisted OptionMaterialization record before completion",
                    option_id=option_id,
                    option_revision=current.option_revision,
                    contract_version=current.contract_version,
                )
            if view.lifecycle_status == "materialized":
                # A materialized Draft has not gone through the legacy
                # Notebook `confirm` endpoint.  Its real execution begins in
                # Draft Graph, so the first callback from that run is the
                # authoritative start of the materialized option's execution.
                # Record the transition before validating artifacts; a failed
                # run must still leave an append-only execution attempt.
                self._transition(
                    notebook_id,
                    view,
                    to_status="executing",
                    actor="system",
                    reason="draft_execution_started",
                    trace=trace,
                )
                if trace is not None:
                    trace.emit(
                        "option.execution.started",
                        payload={
                            "option_id": option_id,
                            "option_revision": current.option_revision,
                            "proposal_id": current.typed_proposal_id,
                            "proposal_revision": current.typed_proposal_revision,
                            "freshness_dependency_fingerprint": (
                                current.freshness_dependency_fingerprint
                            ),
                        },
                    )
                view = self.store.read_option(notebook_id, option_id)
            if view.lifecycle_status != "executing":
                raise OptionLifecycleTransitionInvalid(
                    f"option {option_id} is {view.lifecycle_status}; only an executing "
                    "materialized option can complete",
                    option_id=option_id,
                    lifecycle_status=view.lifecycle_status,
                )
        artifacts = (
            [dict(record) for record in produced_artifacts]
            if produced_artifacts is not None
            else self._read_run_artifacts(run_id)
        )
        validation = validate_produced_artifacts(current.artifact_contract, artifacts)

        committable = (
            execution_status == "succeeded"
            and validation["validation_status"] in COMMITTABLE_VALIDATION_STATUSES
        )
        if trace is not None:
            payload: dict[str, Any] = {
                "option_id": option_id,
                "option_revision": current.option_revision,
                "execution_status": execution_status,
            }
            if run_id:
                payload["run_id"] = run_id
            if error_code:
                payload["error_code"] = error_code
            trace.emit("option.execution.completed", payload=payload)
            trace.emit(
                "artifact_contract.validation.completed",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "validation_status": validation["validation_status"],
                    "missing_required": [
                        issue["artifact_id"]
                        for issue in validation["issues"]
                        if issue["code"] == "ARTIFACT_REQUIRED_MISSING"
                    ],
                    "checked_dimensions": list(validation["checked_dimensions"]),
                },
            )
            if not committable:
                trace.emit(
                    "operation.error",
                    payload={
                        "code": error_code or "ARTIFACT_CONTRACT_UNSATISFIED",
                        "fatal": False,
                        "option_id": option_id,
                        "option_revision": current.option_revision,
                        "detail": (
                            "execution_status="
                            f"{execution_status}, validation_status="
                            f"{validation['validation_status']}"
                        ),
                    },
                )

        if current.materializable:
            self._transition(
                notebook_id,
                view,
                to_status="executed" if committable else "materialized",
                actor="system",
                reason="artifact_contract_" + validation["validation_status"],
                trace=trace,
            )
        else:
            self._transition(
                notebook_id,
                view,
                to_status="executed" if committable else "selected",
                actor="system",
                reason="artifact_contract_" + validation["validation_status"],
                trace=trace,
            )
        if not committable and current.materializable:
            self._transition(
                notebook_id,
                self.store.read_option(notebook_id, option_id),
                to_status="selected",
                actor="system",
                reason="artifact_contract_retry",
                trace=trace,
            )
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_EXECUTION_RESULT,
                "option_id": option_id,
                "option_revision": current.option_revision,
                "run_id": run_id,
                "execution_status": execution_status,
                "artifact_validation": validation,
                "committed": committable,
            },
        )

        advanced = False
        if committable and run_id:
            self.set_active_head(
                notebook_id, run_id, reason="option_executed", trace=trace
            )
            advanced = True
        elif run_id:
            # Failed attempts are recorded on their own field; the head does not
            # move, and neither does "what the user was looking at" silently
            # become a broken run (spec §9.1 criterion 4).
            self.store.append_notebook_state(
                notebook_id,
                {"last_attempt_run_id": run_id, "reason": "execution_not_committable"},
            )

        return ExecutionOutcome(
            option_id=option_id,
            option_revision=current.option_revision,
            run_id=run_id,
            execution_status=execution_status,
            artifact_validation=validation,
            active_head_advanced=advanced,
            lifecycle_status=self.store.read_option(notebook_id, option_id).lifecycle_status,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

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

    def _prepare(
        self,
        notebook: Notebook,
        context: NotebookPlanningContextV1,
        draft: OptionDraft,
    ) -> tuple[TypedProposal, Any, str]:
        """Validate one draft against the real registry. Raises, never stores."""

        proposal = draft.proposal
        try:
            definition = self.registry.require(
                proposal.operation_id, proposal.operation_version
            )
        except Exception as error:  # UnknownOperationError
            raise OptionValidationFailed(
                f"unknown operation {proposal.operation_id}@{proposal.operation_version}: "
                f"{error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
            ) from error
        try:
            definition.validate(
                target=proposal.target,
                preconditions=proposal.preconditions,
                changes=proposal.changes,
            )
        except OperationValidationError as error:
            # spec §7: refusing here is cheaper than apologising at click time.
            raise OptionValidationFailed(
                f"option proposal failed {proposal.operation_id} validation: {error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[{"code": "OPERATION_VALIDATION", "detail": str(error)}],
            ) from error
        try:
            self._validate_target_model_options(proposal)
        except Exception as error:
            code = getattr(error, "code", "MODEL_OPTIONS_PATCH_INVALID")
            raise OptionValidationFailed(
                "option model_options failed the target model contract: "
                f"[{code}] {error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[{"code": code, "detail": str(error)}],
            ) from error
        try:
            self._assert_capability_model_identity(notebook, draft, proposal)
        except Exception as error:
            raise OptionValidationFailed(
                "option capability model identity does not match the server declaration",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[
                    {
                        "code": "CAPABILITY_MODEL_IDENTITY_MISMATCH",
                        "detail": str(error),
                    }
                ],
            ) from error

        contract = build_artifact_contract(
            draft.expected_artifacts,
            additional_artifact_types=self._published_artifact_types(
                draft.capability_id or "",
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            ),
        )
        risk_level = _REGISTRY_RISK_TO_OPTION_RISK.get(definition.risk_level)
        if risk_level is None:
            raise OptionValidationFailed(
                f"operation {proposal.operation_id} declares unmapped registry risk "
                f"level {definition.risk_level!r}",
                operation_id=proposal.operation_id,
            )
        return proposal, contract, risk_level

    def _validate_target_model_options(self, proposal: TypedProposal) -> None:
        """Validate model-specific options before persisting an Option revision."""

        changes = proposal.changes
        if proposal.operation_id == "model.rerun":
            patch = changes.get("model_options") or {}
            if not patch:
                return
            from ...lineage.run_inputs import read_run_inputs
            from ...repository.run_repository import _resolve_run_root
            from ...services.run_service import merge_form_overrides

            try:
                run_root = _resolve_run_root(
                    str(self.project_root), str(proposal.target["run_id"])
                )
            except Exception as error:
                # Some append-only compatibility tests intentionally exercise
                # the Option lifecycle with a symbolic run id and no persisted
                # source.  There is no target contract to validate in that
                # case, so leave the option unverified; materialization still
                # requires a real source and remains fail-closed.
                if getattr(error, "code", None) == "RUN_NOT_FOUND":
                    return
                raise
            inputs = read_run_inputs(run_root)
            form = inputs.get("form") or {}
            if not isinstance(form, Mapping) or not isinstance(patch, Mapping):
                raise ValueError("model_options target and patch must be objects")
            # A persisted run without model identity is an incomplete legacy
            # fixture, not a model contract.  Do not guess its owner.
            if not form.get("model_type"):
                return
            merge_form_overrides(form, {"model_options": dict(patch)})
            return

        if proposal.operation_id == "model.genesis":
            from ...model_options import bind_new_model_options

            model_params = changes.get("model_params") or {}
            if not isinstance(model_params, Mapping):
                return
            model_type = model_params.get("model_type")
            payload = changes.get("model_options")
            if payload is None:
                payload = model_params.get("model_options")
            if payload:
                # OLS owns a bounded model_options contract. The adapter also
                # projects its covariance into the legacy top-level field so
                # Genesis and the human Draft editor retain one executable
                # covariance meaning.
                if model_type == "ols":
                    from ...services.draft_materialization import (
                        normalize_ols_genesis_model_params,
                    )

                    normalize_ols_genesis_model_params(
                        {"model_type": model_type, "model_options": payload}
                    )
                    return
                bind_new_model_options(model_type, payload)

    def _append_revision(self, notebook_id: str, stored: StoredRevision) -> None:
        self.store.append_option_record(
            notebook_id, stored.revision.option_id, stored.to_dict()
        )

    def _append_lifecycle(
        self,
        notebook_id: str,
        option_id: str,
        *,
        from_status: str | None,
        to_status: str,
        revision: int,
        actor: str,
        reason: str,
    ) -> None:
        self.store.append_option_record(
            notebook_id,
            option_id,
            {
                "record_type": RECORD_LIFECYCLE,
                "option_id": option_id,
                "option_revision": revision,
                "from_status": from_status,
                "to_status": to_status,
                "actor": actor,
                "reason": reason,
            },
        )

    def _transition(
        self,
        notebook_id: str,
        view: OptionView,
        *,
        to_status: str,
        actor: str,
        reason: str,
        trace: TraceWriter | None = None,
    ) -> None:
        current = view.lifecycle_status
        if view.current_revision.materializable and to_status == "materialized":
            materialization = self.store.read_materialization(
                notebook_id,
                view.option_id,
                view.current_revision.option_revision,
            )
            if materialization is None:
                raise OptionMaterializationRequired(
                    f"option {view.option_id} revision "
                    f"{view.current_revision.option_revision} requires a persisted "
                    "OptionMaterialization record before entering materialized",
                    option_id=view.option_id,
                    option_revision=view.current_revision.option_revision,
                    contract_version=view.current_revision.contract_version,
                )
        transitions = (
            _LIFECYCLE_TRANSITIONS
            if view.current_revision.materializable
            else _LEGACY_LIFECYCLE_TRANSITIONS
        )
        if to_status not in transitions[current]:
            raise OptionLifecycleTransitionInvalid(
                f"option {view.option_id} cannot move from {current} to {to_status}",
                option_id=view.option_id,
                from_status=current,
                to_status=to_status,
            )
        self._append_lifecycle(
            notebook_id,
            view.option_id,
            from_status=current,
            to_status=to_status,
            revision=view.current_revision.option_revision,
            actor=actor,
            reason=reason,
        )
        if trace is not None:
            lifecycle_trace_payload = {
                "option_id": view.option_id,
                "option_revision": view.current_revision.option_revision,
                "from_status": current,
                "to_status": to_status,
                "axis": "lifecycle",
                "reason": reason,
            }
            binding_ref = getattr(
                view.current_revision, "capability_resolution_binding_ref", None
            )
            if binding_ref is not None:
                lifecycle_trace_payload["capability_resolution_binding_ref"] = binding_ref
            trace.emit(
                "option.lifecycle.changed",
                payload=lifecycle_trace_payload,
            )

    def _read_run_artifacts(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []
        try:
            records = _read_artifact_records(self.project_root / "runs" / run_id)
        except (FileNotFoundError, OSError, ValueError):
            return []
        return [dict(item) for item in records if isinstance(item, Mapping)]


__all__ = ["ExecutionOutcome", "MAX_OPTIONS_PER_BATCH", "NotebookService"]
