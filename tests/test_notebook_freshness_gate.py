"""Gate 4 — the two hashes, and the gate that is not the read-time evaluator.

Spec §4.0 (self-reference), §4.2 (evaluation timing), §9.1 criteria 6/7/7b.
"""
from __future__ import annotations

import json
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
from workbench.contracts.agent.notebook_option import RecommendationDecision
from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)
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


def _materializable_rerun_option(
    project: Path,
    *,
    option_id: str = "opt_materializable",
    proposal_id: str = "proposal_materializable",
    trace_factory=None,
) -> tuple[NotebookService, str, object, object]:
    """Build a source-bound V1.1 option through the server materializer seam."""

    service = NotebookService(project)
    source_run = make_run(project, "run_source")
    source_node_hash = "a" * 64
    source_upload_sha = "upload-source"
    (source_run / "run_inputs.json").write_text(
        json.dumps(
            {
                "run_input_schema_version": 1,
                "upload": {"sha256": source_upload_sha},
                "form": {
                    "model_type": "ols",
                    "y": "outcome",
                    "x": "predictor",
                    "model_options": {},
                },
            }
        ),
        encoding="utf-8",
    )
    (source_run / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_source",
                "mode": "manual",
                "status": "completed",
                "model_routing": {
                    "requested_model_type": "ols",
                    "effective_model_type": "ols",
                },
            }
        ),
        encoding="utf-8",
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id="run_source",
            nodes={
                "model:ols_1": Node(
                    id="model:ols_1",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-08-21T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    (source_run / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": source_node_hash, "cas_ref": {}}}),
        encoding="utf-8",
    )

    notebook = service.ensure_default_projection(from_run_id="run_source", created_by="test")
    trace = trace_factory(notebook) if trace_factory is not None else None
    request = NodeWriteOperationRequestV1(
        request_id="freshness-test",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id="run_source",
        op_node_id="model:ols_1",
        node_hash=source_node_hash,
        forest_node_key=f"{source_node_hash}::model:ols_1",
        owner_resolution="single_candidate",
        active_head_run_id="run_source",
    )
    source_context_fingerprint = compute_context_fingerprint(project / "runs", request)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id=proposal_id,
        proposal_revision=1,
        operation_id="model.rerun",
        operation_version="v1",
        target={
            "run_id": "run_source",
            "node_ref": "model:ols_1",
            "node_hash": source_node_hash,
            "forest_node_key": f"{source_node_hash}::model:ols_1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_context_fingerprint,
            "active_head_run_id": "run_source",
            "owner_resolution": "single_candidate",
        },
        changes={"model_options": {}},
    )
    decision = RecommendationDecision(
        recommendation_decision_id=f"decision_{option_id}",
        batch_id=f"batch_{option_id}",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=(option_id,),
        outcome="recommended",
        recommended_option_id=option_id,
        reason_refs=(),
    )
    (option,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="server-owned freshness option",
                proposal=proposal,
                expected_artifacts=_EXPECTED,
                option_id=option_id,
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
        trace=trace,
    )
    assert option.materializable is True
    service.record_decision(
        notebook.notebook_id,
        option.option_id,
        decision="selected",
        actor="test",
        trace=trace,
    )
    return service, notebook.notebook_id, notebook, option


def _materializable_rerun_draft(proposal_id: str) -> OptionDraft:
    proposal = model_rerun_proposal(proposal_id, covariance="unadjusted")
    proposal["target"] = {
        "run_id": "run_source",
        "node_ref": "model:ols_1",
        "node_hash": "a" * 64,
        "forest_node_key": f"{'a' * 64}::model:ols_1",
    }
    proposal["preconditions"] = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "freshness-revalidation",
        "active_head_run_id": "run_source",
        "owner_resolution": "single_candidate",
    }
    proposal["changes"] = {"model_options": {}}
    return OptionDraft(
        rank=1,
        rationale="server-owned revalidation",
        proposal=TypedProposal.from_dict(proposal),
        expected_artifacts=_EXPECTED,
        option_id="opt_materializable",
    )


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


def test_materialize_ignores_a_changed_generation_context_hash(tmp_path: Path) -> None:
    """§9.1 criterion 7b, second half: evidence must not gate execution."""
    project = make_project(tmp_path)
    service, notebook_id, _notebook_record, option = _materializable_rerun_option(project)
    later = service.compile_context(notebook_id)
    assert generation_context_hash(later) != option.generation_context_hash

    materialized = service.materialize_option(
        notebook_id,
        option.option_id,
        context=later,
    )

    assert materialized.materialization.option_revision == 1
    assert materialized.materialization.generation_context_id == option.generation_context_id
    assert materialized.materialization.freshness_dependency_fingerprint == (
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


def test_read_time_fresh_then_upstream_change_still_refuses_at_materialize(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service, notebook_id, _notebook_record, option = _materializable_rerun_option(project)
    context = service.compile_context(notebook_id)

    # 1. The user renders the notebook. The option is fresh, and the read says so.
    view = service.option_view(notebook_id, option.option_id, context=context)
    assert view.freshness_status == "fresh"
    assert view.freshness["grants_execution_permission"] is False

    # 2. Between the render and the click, the selected text changes upstream.
    service.set_focus(notebook_id, user_focus={"selected_text_hash": "sha256:bbb"})

    # 3. The click still carries the verdict from step 1. The gate recompiles.
    with pytest.raises(OptionRevisionStale) as excinfo:
        service.materialize_option(
            notebook_id,
            option.option_id,
            context=service.compile_context(notebook_id),
        )

    assert excinfo.value.code == "OPTION_REVISION_STALE"
    assert excinfo.value.details["reason"] == "freshness_dependency_changed"
    assert excinfo.value.details["pinned_freshness_dependency_fingerprint"] == (
        option.freshness_dependency_fingerprint
    )
    assert service.option_view(notebook_id, option.option_id).lifecycle_status == "selected"


def test_a_superseded_revision_cannot_be_confirmed(tmp_path: Path) -> None:
    """§3.3's race: the user clicked revision 2's button after revision 3 existed."""
    project = make_project(tmp_path)
    service, notebook_id, _notebook_record, option = _materializable_rerun_option(project)
    service.set_focus(notebook_id, user_focus={"selected_text_hash": "sha256:bbb"})
    moved = service.compile_context(notebook_id)
    service.revalidate_option(
        notebook_id,
        option.option_id,
        context=moved,
        draft=OptionDraft(
            rank=1,
            rationale="reconsidered",
            proposal=_materializable_rerun_draft("p2").proposal,
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
    service, notebook_id, _notebook_record, option = _materializable_rerun_option(project)
    context = service.compile_context(notebook_id)

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
