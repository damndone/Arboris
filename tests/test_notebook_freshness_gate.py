"""Gate 4 — the two hashes, and the gate that is not the read-time evaluator.

Spec §4.0 (self-reference), §4.2 (evaluation timing), §9.1 criteria 6/7/7b.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from workbench.agent.notebook import (
    NotebookService,
    OptionDraft,
    OptionRevisionStale,
    TypedProposal,
    evaluate_option_freshness,
)
from workbench.contracts.agent.notebook_option import ExpectedArtifact
from workbench.lineage.run_family import RunFamilyMismatch, RunFamilyStore, bind_run_to_family

from tests.test_notebook_support import (
    make_context,
    make_project,
    make_run,
    model_rerun_proposal,
)

_EXPECTED = (
    ExpectedArtifact(
        artifact_id="ts.parameters", artifact_type="time_series_json", required=True, count=1
    ),
)


def _draft(rank: int, covariance: str, proposal_id: str) -> OptionDraft:
    return OptionDraft(
        rank=rank,
        rationale=covariance,
        proposal=TypedProposal.from_dict(
            model_rerun_proposal(proposal_id, covariance=covariance)
        ),
        expected_artifacts=_EXPECTED,
    )


def _notebook(project: Path) -> tuple[NotebookService, str]:
    service = NotebookService(project)
    notebook = service.create_notebook(
        title="n",
        created_by="u",
        analysis_contract={"revision": 1, "target": "y"},
        user_focus={"selected_text_hash": "sha256:aaa"},
        available_capabilities=["arma_garch_1"],
    )
    return service, notebook.notebook_id


# ----------------------------------------------------------------------
# §4.0 — the two hashes are different values answering different questions
# ----------------------------------------------------------------------


def test_a_batch_of_three_siblings_all_stay_fresh(tmp_path: Path) -> None:
    """§9.1 criterion 7b, the 命门: generating siblings must not stale anybody."""
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    before = service.compile_context(notebook_id)

    revisions = service.propose_batch(
        notebook_id,
        context=before,
        drafts=[
            _draft(1, "robust", "p1"),
            _draft(2, "clustered", "p2"),
            _draft(3, "unadjusted", "p3"),
        ],
    )

    # Recompiling now sees three options that did not exist before: the
    # generation hash MUST move and the freshness fingerprint MUST NOT.
    after = service.compile_context(notebook_id)
    assert generation_context_hash(after) != generation_context_hash(before)
    assert freshness_dependency_fingerprint(after) == freshness_dependency_fingerprint(before)
    assert [evaluate_option_freshness(r, after) for r in revisions] == [
        "fresh",
        "fresh",
        "fresh",
    ]
    assert len(after.existing_option_summaries) == 3


def test_confirm_ignores_a_changed_generation_context_hash(tmp_path: Path) -> None:
    """§9.1 criterion 7b, second half: evidence must not gate execution."""
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    context = service.compile_context(notebook_id)
    (option,) = service.propose_batch(
        notebook_id, context=context, drafts=[_draft(1, "robust", "p1")]
    )
    later = service.compile_context(notebook_id)
    assert generation_context_hash(later) != option.generation_context_hash

    execution = service.confirm(
        notebook_id,
        option.option_id,
        option_revision=1,
        proposal_id="p1",
        proposal_revision=1,
        context=later,
    )

    assert execution.option_revision == 1
    assert execution.generation_context_id == option.generation_context_id
    assert execution.freshness_dependency_fingerprint == (
        option.freshness_dependency_fingerprint
    )


def test_the_two_hashes_are_never_the_same_string(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    context = service.compile_context(notebook_id)

    (option,) = service.propose_batch(
        notebook_id, context=context, drafts=[_draft(1, "robust", "p1")]
    )

    assert option.generation_context_hash.startswith("sha256:")
    assert option.freshness_dependency_fingerprint.startswith("fresh1:")
    assert option.generation_context_hash != option.freshness_dependency_fingerprint


# ----------------------------------------------------------------------
# §4.2 — read-time freshness is not execution permission
# ----------------------------------------------------------------------


def test_read_time_fresh_then_upstream_change_still_refuses_at_confirm(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    context = service.compile_context(notebook_id)
    (option,) = service.propose_batch(
        notebook_id, context=context, drafts=[_draft(1, "robust", "p1")]
    )

    # 1. The user renders the notebook. The option is fresh, and the read says so.
    view = service.option_view(notebook_id, option.option_id, context=context)
    assert view.freshness_status == "fresh"
    assert view.freshness["grants_execution_permission"] is False

    # 2. Between the render and the click, the selected text changes upstream.
    service.set_focus(notebook_id, user_focus={"selected_text_hash": "sha256:bbb"})

    # 3. The click still carries the verdict from step 1. The gate recompiles.
    with pytest.raises(OptionRevisionStale) as excinfo:
        service.confirm(
            notebook_id,
            option.option_id,
            option_revision=1,
            proposal_id="p1",
            proposal_revision=1,
            context=service.compile_context(notebook_id),
        )

    assert excinfo.value.code == "OPTION_REVISION_STALE"
    assert excinfo.value.details["reason"] == "freshness_dependency_changed"
    assert excinfo.value.details["pinned_freshness_dependency_fingerprint"] == (
        option.freshness_dependency_fingerprint
    )
    assert service.option_view(notebook_id, option.option_id).lifecycle_status == "proposed"


def test_a_superseded_revision_cannot_be_confirmed(tmp_path: Path) -> None:
    """§3.3's race: the user clicked revision 2's button after revision 3 existed."""
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    context = service.compile_context(notebook_id)
    (option,) = service.propose_batch(
        notebook_id, context=context, drafts=[_draft(1, "robust", "p1")]
    )
    service.set_focus(notebook_id, user_focus={"selected_text_hash": "sha256:bbb"})
    moved = service.compile_context(notebook_id)
    service.revalidate_option(
        notebook_id,
        option.option_id,
        context=moved,
        draft=OptionDraft(
            rank=1,
            rationale="reconsidered",
            proposal=TypedProposal.from_dict(model_rerun_proposal("p2", covariance="hac")),
            expected_artifacts=_EXPECTED,
            option_id=option.option_id,
        ),
    )

    with pytest.raises(OptionRevisionStale) as excinfo:
        service.confirm(
            notebook_id,
            option.option_id,
            option_revision=1,
            proposal_id="p1",
            proposal_revision=1,
            context=service.compile_context(notebook_id),
        )

    assert excinfo.value.details["requested_revision"] == 1
    assert excinfo.value.details["current_revision"] == 2
    assert excinfo.value.details["reason"] == "superseded_revision"


def test_confirming_the_wrong_proposal_pin_is_refused(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    context = service.compile_context(notebook_id)
    (option,) = service.propose_batch(
        notebook_id, context=context, drafts=[_draft(1, "robust", "p1")]
    )

    with pytest.raises(OptionRevisionStale) as excinfo:
        service.confirm(
            notebook_id,
            option.option_id,
            option_revision=1,
            proposal_id="p1",
            proposal_revision=2,
            context=context,
        )

    assert excinfo.value.details["reason"] == "proposal_pin_mismatch"


# ----------------------------------------------------------------------
# §9.1 criterion 4 — cross-family runs
# ----------------------------------------------------------------------


def test_a_run_from_another_family_cannot_become_the_active_head(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    other = RunFamilyStore(project).create_family(
        project_id=project.name, created_by="u", origin="notebook"
    )
    foreign = make_run(project, "run_foreign")
    bind_run_to_family(foreign, run_family_id=other.run_family_id, bound_by="test")

    with pytest.raises(RunFamilyMismatch) as excinfo:
        service.set_active_head(notebook_id, "run_foreign", reason="manual")

    assert other.run_family_id in str(excinfo.value)
    assert service.get_notebook(notebook_id).active_head_run_id is None


def test_a_run_in_the_notebooks_family_becomes_the_head(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service, notebook_id = _notebook(project)
    notebook = service.get_notebook(notebook_id)
    mine = make_run(project, "run_mine")
    bind_run_to_family(mine, run_family_id=notebook.run_family_id, bound_by="test")

    updated = service.set_active_head(notebook_id, "run_mine", reason="option_executed")

    assert updated.active_head_run_id == "run_mine"
    assert updated.run_family_id == notebook.run_family_id
