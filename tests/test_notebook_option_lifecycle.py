"""Gate 4 acceptance — Notebook creation, option batches and the option lifecycle.

Spec `2026-07-22-v1.8.1-agent-notebook-analysis-option.md` §2.3, §3, §6, §7, §9.1.

Every assertion here names the value it expects. "a record exists" is not an
acceptance criterion in this repo — a prior release passed one and shipped three
unusable spreadsheet sheets.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.notebook import (
    NotebookService,
    OptionDraft,
    TypedProposal,
)
from workbench.agent.notebook.errors import (
    NotebookOptionError,
    OptionBatchInvalid,
    OptionValidationFailed,
)
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    RecommendationDecision,
)
from workbench.lineage.run_family import RunFamilyStore

from tests.test_notebook_support import (
    make_context,
    make_project,
    make_run,
    model_rerun_proposal,
)


def _draft(
    rank: int,
    *,
    covariance: str,
    proposal_id: str = "prop_1",
    option_id: str | None = None,
    expected: tuple[ExpectedArtifact, ...] | None = None,
) -> OptionDraft:
    return OptionDraft(
        rank=rank,
        rationale=f"covariance={covariance}",
        assumptions=("residuals are serially uncorrelated",),
        proposal=TypedProposal.from_dict(
            model_rerun_proposal(proposal_id, covariance=covariance)
        ),
        expected_artifacts=expected
        or (
            ExpectedArtifact(
                artifact_id="ts.parameters",
                artifact_type="time_series_json",
                required=True,
                count=1,
            ),
        ),
        option_id=option_id,
    )


# ----------------------------------------------------------------------
# §9.1 criterion 1 — a notebook exists before any run
# ----------------------------------------------------------------------


def test_notebook_created_without_any_run_persists_family_and_null_head(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)

    notebook = service.create_notebook(title="Volatility", created_by="user_1")

    assert notebook.active_head_run_id is None
    assert notebook.focused_run_id is None
    assert notebook.last_attempt_run_id is None
    assert notebook.run_family_id.startswith("run-family:")
    family = RunFamilyStore(project, create=False).get(notebook.run_family_id)
    assert family.origin == "notebook"
    assert family.project_id == project.name
    assert family.legacy_anchor_run_id is None
    # DEC-NB-001: creating a notebook migrates the project rather than inventing
    # a second migration path (work order §关键约束 1).
    assert RunFamilyStore(project, create=False).has_migrated() is True
    # Reload from disk: the notebook is durable, not just an in-memory object.
    assert NotebookService(project).get_notebook(notebook.notebook_id).run_family_id == (
        notebook.run_family_id
    )


def test_a_runless_notebook_can_compile_generate_and_confirm_with_a_null_head(
    tmp_path: Path,
) -> None:
    """§9.1 criterion 1, end to end: no run has to exist for the loop to work.

    This is the acceptance the run-family lane pins with an xfail(strict=True)
    for "notebook without a run"; here it is proven positively on the owned
    surface. A notebook with zero runs must still compile a bounded context,
    generate an option against it and confirm that option — the head only moves
    when a real run is committed, which never happens on this path.
    """
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(
        title="Runless",
        created_by="user_1",
        analysis_contract={"revision": 1, "target": "y"},
        user_focus={"selected_text_hash": "sha256:seed"},
        available_capabilities=["arma_garch_1"],
    )

    assert (project / "runs").is_dir()
    assert list((project / "runs").iterdir()) == []

    context = service.compile_context(notebook.notebook_id)
    assert context.active_head_run_id is None
    assert context.run_family_id == notebook.run_family_id
    assert context.active_run_summary == {}
    assert context.artifact_summaries == []
    assert context.source_manifest == []
    assert context.user_focus == {"selected_text_hash": "sha256:seed"}

    (option,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_draft(1, covariance="robust", proposal_id="p1")],
    )

    execution = service.confirm(
        notebook.notebook_id,
        option.option_id,
        option_revision=1,
        proposal_id="p1",
        proposal_revision=1,
        context=service.compile_context(notebook.notebook_id),
    )

    assert execution.run_id is None
    assert execution.freshness_dependency_fingerprint == (
        option.freshness_dependency_fingerprint
    )
    reloaded = NotebookService(project).get_notebook(notebook.notebook_id)
    assert reloaded.active_head_run_id is None
    assert reloaded.last_attempt_run_id is None
    assert (
        service.option_view(notebook.notebook_id, option.option_id).lifecycle_status
        == "executing"
    )


def test_notebook_created_from_a_run_binds_that_runs_persisted_family(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_run(project, "run_001")
    make_run(project, "run_002", rerun_of="run_001")
    service = NotebookService(project)

    notebook = service.create_notebook(
        title="Adopted", created_by="user_1", from_run_id="run_002"
    )

    assert notebook.run_family_id == "legacy-family:run_001"
    assert notebook.active_head_run_id == "run_002"


def test_notebook_run_family_id_is_immutable_after_creation(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")

    with pytest.raises(NotebookOptionError) as excinfo:
        service.rebind_run_family(notebook.notebook_id, run_family_id="run-family:other")

    assert excinfo.value.code == "NOTEBOOK_RUN_FAMILY_IMMUTABLE"


# ----------------------------------------------------------------------
# §6 — generation limits
# ----------------------------------------------------------------------


def test_a_batch_of_three_options_records_ranks_one_two_three(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )

    revisions = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _draft(1, covariance="robust", proposal_id="p1"),
            _draft(2, covariance="clustered", proposal_id="p2"),
            _draft(3, covariance="unadjusted", proposal_id="p3"),
        ],
    )

    assert [r.rank for r in revisions] == [1, 2, 3]
    assert [r.option_revision for r in revisions] == [1, 1, 1]
    assert len({r.batch_id for r in revisions}) == 1
    assert len({r.option_id for r in revisions}) == 3
    assert all(r.notebook_id == notebook.notebook_id for r in revisions)
    assert all(r.run_family_id == notebook.run_family_id for r in revisions)
    assert all(r.lifecycle_status == "proposed" for r in revisions)
    assert all(r.freshness_status == "fresh" for r in revisions)
    assert all(r.validation_status == "valid" for r in revisions)
    # risk_level comes from the operation registry, not from the agent's text.
    assert all(r.risk_level == "medium" for r in revisions)


def test_four_options_are_refused_before_anything_is_written(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )

    with pytest.raises(OptionBatchInvalid) as excinfo:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                _draft(1, covariance="robust", proposal_id="p1"),
                _draft(2, covariance="clustered", proposal_id="p2"),
                _draft(3, covariance="unadjusted", proposal_id="p3"),
                _draft(3, covariance="hac", proposal_id="p4"),
            ],
        )

    assert excinfo.value.code == "OPTION_BATCH_LIMIT_EXCEEDED"
    assert service.list_options(notebook.notebook_id) == []


def test_two_rank_one_options_are_refused(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )

    with pytest.raises(OptionBatchInvalid) as excinfo:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                _draft(1, covariance="robust", proposal_id="p1"),
                _draft(1, covariance="clustered", proposal_id="p2"),
            ],
        )

    assert excinfo.value.code == "OPTION_BATCH_DUPLICATE_RANK"
    assert service.list_options(notebook.notebook_id) == []


def test_two_options_with_the_same_canonical_proposal_are_refused(tmp_path: Path) -> None:
    """Different proposal_id, identical content: that is one option, not two."""
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )

    with pytest.raises(OptionBatchInvalid) as excinfo:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                _draft(1, covariance="robust", proposal_id="p1"),
                _draft(2, covariance="robust", proposal_id="p2"),
            ],
        )

    assert excinfo.value.code == "OPTION_BATCH_DUPLICATE_PROPOSAL"
    assert service.list_options(notebook.notebook_id) == []


# ----------------------------------------------------------------------
# §7 — validation at creation time
# ----------------------------------------------------------------------


def test_an_option_failing_the_operation_validator_is_never_stored(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    broken = model_rerun_proposal("p1")
    broken["target"].pop("node_hash")

    with pytest.raises(OptionValidationFailed) as excinfo:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                OptionDraft(
                    rank=1,
                    rationale="r",
                    assumptions=(),
                    proposal=TypedProposal.from_dict(broken),
                    expected_artifacts=(),
                )
            ],
        )

    assert excinfo.value.code == "OPTION_VALIDATION_FAILED"
    assert "node_hash" in str(excinfo.value)
    assert service.list_options(notebook.notebook_id) == []


# ----------------------------------------------------------------------
# §3.4/§3.5/§3.6 — lifecycle and append-only revisions
# ----------------------------------------------------------------------


def test_lifecycle_transitions_are_appended_never_overwritten(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    (option,) = service.propose_batch(
        notebook.notebook_id, context=context, drafts=[_draft(1, covariance="robust")]
    )

    service.record_decision(
        notebook.notebook_id, option.option_id, decision="deferred", actor="user_1"
    )
    service.record_decision(
        notebook.notebook_id, option.option_id, decision="selected", actor="user_1"
    )

    view = service.option_view(notebook.notebook_id, option.option_id)
    assert view.lifecycle_status == "selected"
    assert [entry["to_status"] for entry in view.lifecycle_history] == [
        "proposed",
        "deferred",
        "selected",
    ]
    assert [entry["from_status"] for entry in view.lifecycle_history] == [
        None,
        "proposed",
        "deferred",
    ]


def test_rejected_is_terminal(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    (option,) = service.propose_batch(
        notebook.notebook_id, context=context, drafts=[_draft(1, covariance="robust")]
    )
    service.record_decision(
        notebook.notebook_id, option.option_id, decision="rejected", actor="user_1"
    )

    with pytest.raises(NotebookOptionError) as excinfo:
        service.record_decision(
            notebook.notebook_id, option.option_id, decision="selected", actor="user_1"
        )

    assert excinfo.value.code == "OPTION_LIFECYCLE_TRANSITION_INVALID"
    assert service.option_view(notebook.notebook_id, option.option_id).lifecycle_status == (
        "rejected"
    )


def test_revalidation_creates_a_new_revision_and_keeps_the_old_one_verbatim(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    (first,) = service.propose_batch(
        notebook.notebook_id, context=context, drafts=[_draft(1, covariance="robust")]
    )
    moved = make_context(
        project,
        notebook_id=notebook.notebook_id,
        run_family_id=notebook.run_family_id,
        contract_revision=2,
    )

    second = service.revalidate_option(
        notebook.notebook_id,
        first.option_id,
        context=moved,
        draft=_draft(1, covariance="clustered", proposal_id="p9", option_id=first.option_id),
    )

    assert second.option_id == first.option_id
    assert second.option_revision == 2
    assert second.supersedes_option_revision == 1
    assert second.freshness_status == "fresh"
    assert second.typed_proposal_id == "p9"
    view = service.option_view(notebook.notebook_id, first.option_id)
    assert [r.option_revision for r in view.revisions] == [1, 2]
    # The old snapshot is byte-for-byte what it was, including its proposal.
    assert view.revisions[0].to_dict() == first.to_dict()
    assert view.revisions[0].typed_proposal_id == "prop_1"
    assert view.current_revision.option_revision == 2


def test_explicit_agent_replan_revalidates_existing_option_ids_append_only(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    evidence = EvidenceRef(
        evidence_id="evidence:profile",
        result_hash="sha256:profile",
        source_refs=("dataset_profile:upload",),
    )
    first_decision = RecommendationDecision(
        recommendation_decision_id="rec_1",
        batch_id="batch_1",
        generation_context_hash="sha256:ctx_1",
        freshness_dependency_fingerprint="fresh1:ctx_1",
        evidence_pack_hashes=("sha256:pack_1",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_replan",),
        outcome="recommended",
        recommended_option_id="opt_replan",
        reason_refs=("evidence:profile",),
    )
    first_draft = OptionDraft(
        **{
            **_draft(1, covariance="robust", proposal_id="p1", option_id="opt_replan").__dict__,
            "evidence_refs": (evidence,),
            "comparative_claims": ("evidence:profile supports robust covariance",),
            "recommendation_decision_id": first_decision.recommendation_decision_id,
            "recommendation_status": first_decision.outcome,
        }
    )
    (first,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[first_draft],
        batch_id=first_decision.batch_id,
        recommendation_decision=first_decision,
    )

    second_decision = RecommendationDecision(
        recommendation_decision_id="rec_2",
        batch_id="batch_2",
        generation_context_hash="sha256:ctx_2",
        freshness_dependency_fingerprint="fresh1:ctx_2",
        evidence_pack_hashes=("sha256:pack_2",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_replan",),
        outcome="recommended",
        recommended_option_id="opt_replan",
        reason_refs=("evidence:profile",),
    )
    second_draft = OptionDraft(
        **{
            **_draft(1, covariance="clustered", proposal_id="p2", option_id="opt_replan").__dict__,
            "evidence_refs": (evidence,),
            "comparative_claims": ("evidence:profile supports clustered covariance",),
            "recommendation_decision_id": second_decision.recommendation_decision_id,
            "recommendation_status": second_decision.outcome,
        }
    )

    (second,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[second_draft],
        batch_id=second_decision.batch_id,
        recommendation_decision=second_decision,
        revalidate_existing=True,
    )

    assert second.option_id == first.option_id == "opt_replan"
    assert second.option_revision == 2
    assert second.supersedes_option_revision == 1
    assert second.batch_id == "batch_2"
    view = service.option_view(notebook.notebook_id, "opt_replan")
    assert [revision.option_revision for revision in view.revisions] == [1, 2]
    assert view.revisions[0].to_dict() == first.to_dict()
    assert view.current_revision.typed_proposal_id == "p2"


def test_explicit_agent_replan_preserves_materialized_terminal_option(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    first_decision = RecommendationDecision(
        recommendation_decision_id="rec_terminal_1",
        batch_id="batch_terminal_1",
        generation_context_hash="sha256:terminal_1",
        freshness_dependency_fingerprint="fresh1:terminal_1",
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_terminal",),
        outcome="recommended",
        recommended_option_id="opt_terminal",
        reason_refs=(),
    )
    first_draft = OptionDraft(
        **{
            **_draft(1, covariance="robust", proposal_id="terminal_p1", option_id="opt_terminal").__dict__,
            "recommendation_decision_id": first_decision.recommendation_decision_id,
            "recommendation_status": first_decision.outcome,
        }
    )
    (first,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[first_draft],
        batch_id=first_decision.batch_id,
        recommendation_decision=first_decision,
    )
    service._append_lifecycle(
        notebook.notebook_id,
        first.option_id,
        from_status="proposed",
        to_status="selected",
        revision=first.option_revision,
        actor="test",
        reason="select",
    )
    service._append_lifecycle(
        notebook.notebook_id,
        first.option_id,
        from_status="selected",
        to_status="materialized",
        revision=first.option_revision,
        actor="test",
        reason="draft_materialized",
    )

    second_decision = RecommendationDecision(
        recommendation_decision_id="rec_terminal_2",
        batch_id="batch_terminal_2",
        generation_context_hash="sha256:terminal_2",
        freshness_dependency_fingerprint="fresh1:terminal_2",
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_terminal",),
        outcome="recommended",
        recommended_option_id="opt_terminal",
        reason_refs=(),
    )
    second_draft = OptionDraft(
        **{
            **_draft(1, covariance="clustered", proposal_id="terminal_p2", option_id="opt_terminal").__dict__,
            "recommendation_decision_id": second_decision.recommendation_decision_id,
            "recommendation_status": second_decision.outcome,
        }
    )

    (result,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[second_draft],
        batch_id=second_decision.batch_id,
        recommendation_decision=second_decision,
        revalidate_existing=True,
    )

    assert result.option_id == first.option_id
    assert result.option_revision == first.option_revision
    view = service.option_view(notebook.notebook_id, first.option_id)
    assert view.lifecycle_status == "materialized"
    assert [revision.option_revision for revision in view.revisions] == [1]
    assert view.current_revision.typed_proposal_id == first.typed_proposal_id


def test_reading_the_same_context_twice_does_not_bump_the_revision(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = make_context(
        project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id
    )
    (option,) = service.propose_batch(
        notebook.notebook_id, context=context, drafts=[_draft(1, covariance="robust")]
    )

    for _ in range(3):
        service.option_view(notebook.notebook_id, option.option_id, context=context)

    assert service.option_view(notebook.notebook_id, option.option_id).current_revision.\
        option_revision == 1
