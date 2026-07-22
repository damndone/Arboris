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
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from ...artifacts import read_json
from ...contracts.agent.notebook_option import (
    NotebookOptionRevision,
    OptionExecution,
)
from ...lineage.run_family import (
    RunFamilyStore,
    assert_run_in_family,
    migrate_project_families,
    resolve_run_family,
)
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
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
    OptionLifecycleTransitionInvalid,
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
from .store import (
    RECORD_EXECUTION,
    RECORD_EXECUTION_RESULT,
    RECORD_LIFECYCLE,
    RECORD_OPTION,
    RECORD_REVISION,
    Notebook,
    NotebookStore,
    OptionView,
    StoredRevision,
)

MAX_OPTIONS_PER_BATCH = 3
RECOMMENDED_RANK = 1

# The registry speaks in execution risk ("mutating"/"high"); the option contract
# speaks in the three levels a user is shown. Mapped explicitly rather than
# passed through, so a new registry level fails loudly instead of quietly
# becoming "low".
_REGISTRY_RISK_TO_OPTION_RISK = {
    "read": "low",
    "readonly": "low",
    "mutating": "medium",
    "high": "high",
}

# spec §3.5. `executed`, `rejected` and `archived` have no outgoing edges.
_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
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
    ) -> None:
        self.project_root = Path(project_root)
        self.store = NotebookStore(self.project_root)
        self.registry = registry or OperationRegistry()

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
        )
        return self.store.create_notebook(notebook)

    def get_notebook(self, notebook_id: str) -> Notebook:
        return self.store.get_notebook(notebook_id)

    def list_notebooks(self) -> list[Notebook]:
        return self.store.list_notebooks()

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
        prepared = [self._prepare(notebook, context, draft) for draft in drafts]

        batch = batch_id or f"batch_{uuid4().hex}"
        created_at = _now()
        revisions: list[NotebookOptionRevision] = []
        for draft, (proposal, contract, risk_level) in zip(drafts, prepared):
            option_id = draft.option_id or f"opt_{uuid4().hex}"
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
            revisions.append(revision)
            if trace is not None:
                trace.emit(
                    "option.revision.created",
                    payload={
                        "option_id": option_id,
                        "option_revision": 1,
                        "generation_context_hash": revision.generation_context_hash,
                        "freshness_dependency_fingerprint": (
                            revision.freshness_dependency_fingerprint
                        ),
                        "rank": draft.rank,
                        "risk_level": risk_level,
                    },
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
            trace.emit(
                "agent.plan.completed",
                payload={
                    "context_id": context.context_id,
                    "generated_option_count": len(revisions),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "stop_reason": "complete",
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
        if target is not None:
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

        self._transition(
            notebook_id,
            view,
            to_status="executed" if committable else "selected",
            actor="system",
            reason="artifact_contract_" + validation["validation_status"],
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
        if ranks.count(RECOMMENDED_RANK) > 1:
            raise OptionBatchInvalid(
                "OPTION_BATCH_MULTIPLE_RECOMMENDED",
                f"a batch may contain at most one rank {RECOMMENDED_RANK} option; "
                f"got {ranks.count(RECOMMENDED_RANK)}",
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

        contract = build_artifact_contract(draft.expected_artifacts)
        risk_level = _REGISTRY_RISK_TO_OPTION_RISK.get(definition.risk_level)
        if risk_level is None:
            raise OptionValidationFailed(
                f"operation {proposal.operation_id} declares unmapped registry risk "
                f"level {definition.risk_level!r}",
                operation_id=proposal.operation_id,
            )
        return proposal, contract, risk_level

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
        if to_status not in _LIFECYCLE_TRANSITIONS[current]:
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
            trace.emit(
                "option.lifecycle.changed",
                payload={
                    "option_id": view.option_id,
                    "option_revision": view.current_revision.option_revision,
                    "from_status": current,
                    "to_status": to_status,
                    "axis": "lifecycle",
                    "reason": reason,
                },
            )

    def _read_run_artifacts(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []
        try:
            index = read_json(self.project_root / "runs" / run_id / "artifacts_index.json")
        except (FileNotFoundError, OSError, ValueError):
            return []
        artifacts = index.get("artifacts") if isinstance(index, dict) else None
        return [dict(item) for item in artifacts or [] if isinstance(item, dict)]


__all__ = ["ExecutionOutcome", "MAX_OPTIONS_PER_BATCH", "NotebookService"]
