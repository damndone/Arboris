"""Append-only evidence, recommendation, and materialization state."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from workbench.agent.notebook.errors import (
    NotebookOptionError,
    OptionMaterializationFailed,
    OptionLifecycleTransitionInvalid,
    OptionValidationFailed,
)
from workbench.agent.notebook.materialization import NotebookOptionMaterializer
from workbench.agent.notebook.store import StoredRevision
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    NotebookOptionRevision,
    OptionMaterialization,
    RecommendationDecision,
)
from workbench.lineage.upload_store import store_upload_bytes
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)
from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.run_family import bind_run_to_family
from workbench.model_options import bind_new_model_options

from tests.test_notebook_support import make_project, make_run, model_rerun_proposal


_CONTRACT_FIXTURES = Path(__file__).parent / "fixtures" / "contracts" / "v181"


def _contract_fixture(name: str) -> dict[str, object]:
    return json.loads((_CONTRACT_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _decision() -> RecommendationDecision:
    return RecommendationDecision.from_dict(_contract_fixture("recommendation_decision_v1"))


def _materialization(name: str) -> OptionMaterialization:
    return OptionMaterialization.from_dict(_contract_fixture(name))


def _legacy_option(service: NotebookService, notebook_id: str):
    return service.propose_batch(
        notebook_id,
        context=service.compile_context(notebook_id),
        drafts=[
            OptionDraft(
                rank=1,
                rationale="legacy option",
                proposal=TypedProposal.from_dict(model_rerun_proposal("proposal_legacy")),
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ts.parameters",
                        artifact_type="time_series_json",
                        required=True,
                        count=1,
                    ),
                ),
                option_id="opt_legacy",
            )
        ],
    )[0]


def _option(service: NotebookService, notebook_id: str, *, option_id: str):
    return service.propose_batch(
        notebook_id,
        context=service.compile_context(notebook_id),
        drafts=[
            OptionDraft(
                rank=1,
                rationale="option for materialization state",
                proposal=TypedProposal.from_dict(model_rerun_proposal("proposal_001")),
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ts.parameters",
                        artifact_type="time_series_json",
                        required=True,
                        count=1,
                    ),
                ),
                option_id=option_id,
            )
        ],
    )[0]


def _v11_option(
    service: NotebookService,
    notebook_id: str,
    *,
    option_id: str,
    lifecycle_status: str = "selected",
) -> NotebookOptionRevision:
    """Persist one genuine v1.1 option packet for materialization-boundary tests."""

    notebook = service.get_notebook(notebook_id)
    context = service.compile_context(notebook_id)
    proposal = TypedProposal.from_dict(model_rerun_proposal(f"proposal_{option_id}"))
    payload = _contract_fixture("notebook_option_revision_v11")
    payload.update(
        {
            "option_id": option_id,
            "option_revision": 1,
            "notebook_id": notebook_id,
            "run_family_id": notebook.run_family_id,
            "generation_context_id": context.context_id,
            "generation_context_hash": generation_context_hash(context),
            "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
            "typed_proposal_id": proposal.proposal_id,
            "typed_proposal_revision": proposal.proposal_revision,
            "lifecycle_status": lifecycle_status,
            "batch_id": f"batch_{option_id}",
            "supersedes_option_revision": None,
        }
    )
    revision = NotebookOptionRevision.from_dict(payload)
    service.store.append_option_record(
        notebook_id,
        option_id,
        {
            "record_type": "option",
            "option_id": option_id,
            "notebook_id": notebook_id,
            "batch_id": revision.batch_id,
            "rank": revision.rank,
            "created_at": revision.created_at,
        },
    )
    service._append_revision(
        notebook_id,
        StoredRevision(
            revision=revision,
            proposal=proposal,
            canonical_proposal_hash=proposal.canonical_hash(),
        ),
    )
    service._append_lifecycle(
        notebook_id,
        option_id,
        from_status=None,
        to_status=lifecycle_status,
        revision=revision.option_revision,
        actor="test",
        reason="v11_fixture",
    )
    return revision


def _bound_materialization(
    service: NotebookService,
    notebook_id: str,
    revision: NotebookOptionRevision,
    *,
    materialization_id: str,
    name: str = "option_materialization_genesis_v1",
) -> OptionMaterialization:
    notebook = service.get_notebook(notebook_id)
    return replace(
        _materialization(name),
        materialization_id=materialization_id,
        option_id=revision.option_id,
        option_revision=revision.option_revision,
        proposal_id=revision.typed_proposal_id,
        proposal_revision=revision.typed_proposal_revision,
        freshness_dependency_fingerprint=revision.freshness_dependency_fingerprint,
        generation_context_id=revision.generation_context_id,
        run_family_id=notebook.run_family_id,
    )


def test_evidence_pack_is_append_only_idempotent_and_rejects_raw_paths(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="State", created_by="ui")
    store = service.store
    evidence = {
        "evidence_pack_hash": "sha256:evidence",
        "source_refs": ["dataset:upload"],
        "records": [{"inspection_id": "profile.v1", "result_hash": "sha256:result"}],
    }

    assert callable(getattr(store, "append_evidence_pack", None))
    store.append_evidence_pack(notebook.notebook_id, evidence)
    store.append_evidence_pack(notebook.notebook_id, dict(evidence))

    assert store.read_evidence_pack(notebook.notebook_id, "sha256:evidence") == evidence
    with pytest.raises(ValueError, match="conflicting"):
        store.append_evidence_pack(
            notebook.notebook_id, {**evidence, "records": [{"inspection_id": "changed"}]}
        )
    with pytest.raises(ValueError, match="raw path"):
        store.append_evidence_pack(
            notebook.notebook_id,
            {"evidence_pack_hash": "sha256:raw-path", "raw_path": "/tmp/evidence.json"},
        )
    with pytest.raises(ValueError, match="raw bytes"):
        store.append_evidence_pack(
            notebook.notebook_id,
            {"evidence_pack_hash": "sha256:raw-bytes", "payload": b"not-json"},
        )


def test_decision_is_append_only_idempotent_and_rejects_conflicts(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Decision", created_by="ui")
    decision = _decision()

    assert callable(getattr(service.store, "append_decision", None))
    service.store.append_decision(notebook.notebook_id, decision)
    service.store.append_decision(notebook.notebook_id, decision)

    assert service.store.read_decision(notebook.notebook_id, decision.batch_id) == decision
    with pytest.raises(ValueError, match="conflicting"):
        service.store.append_decision(
            notebook.notebook_id, replace(decision, reason_refs=("reason:changed",))
        )


def test_repeating_identical_v11_batch_is_idempotent(tmp_path: Path) -> None:
    """A remount/retry must not write the same option revision twice."""

    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Retry", created_by="ui")
    context = service.compile_context(notebook.notebook_id)
    option_id = "opt_retry"
    decision = RecommendationDecision(
        recommendation_decision_id="rec_retry",
        batch_id="batch_retry",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=(option_id,),
        outcome="recommended",
        recommended_option_id=option_id,
        reason_refs=(),
    )
    draft = OptionDraft(
        rank=1,
        rationale="verified retry option",
        proposal=TypedProposal.from_dict(model_rerun_proposal("proposal_retry")),
        expected_artifacts=(
            ExpectedArtifact(
                artifact_id="ts.parameters",
                artifact_type="time_series_json",
                required=True,
                count=1,
            ),
        ),
        option_id=option_id,
        recommendation_decision_id=decision.recommendation_decision_id,
        recommendation_status=decision.outcome,
    )

    first = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[draft],
        recommendation_decision=decision,
    )
    second = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[draft],
        recommendation_decision=decision,
    )

    assert second == first
    assert service.store.read_option(notebook.notebook_id, option_id).revisions == (
        first[0],
    )


def test_selected_v11_materialization_records_cover_genesis_and_rerun_child_identities(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Materialization", created_by="ui")
    genesis_option = _v11_option(
        service, notebook.notebook_id, option_id="opt_genesis"
    )
    rerun_option = _v11_option(
        service, notebook.notebook_id, option_id="opt_rerun"
    )
    genesis = _bound_materialization(
        service,
        notebook.notebook_id,
        genesis_option,
        materialization_id="materialization_genesis",
    )
    rerun_child = _bound_materialization(
        service,
        notebook.notebook_id,
        rerun_option,
        materialization_id="materialization_rerun_child",
        name="option_materialization_v1",
    )

    assert callable(getattr(service.store, "append_materialization", None))
    for record in (genesis, rerun_child):
        service.store.append_materialization(notebook.notebook_id, record)
        service.store.append_materialization(notebook.notebook_id, record)

    assert service.store.read_materialization(
        notebook.notebook_id, genesis_option.option_id, genesis_option.option_revision
    ) == genesis
    assert service.store.read_materialization(
        notebook.notebook_id, rerun_option.option_id, rerun_option.option_revision
    ) == rerun_child
    with pytest.raises(ValueError, match="conflicting"):
        service.store.append_materialization(
            notebook.notebook_id,
            replace(genesis, draft_id="draft_002", draft_hash="sha256:draft-2"),
        )


def test_read_rejects_malformed_or_conflicting_persisted_state(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Malformed", created_by="ui")
    decision = _decision()
    service.store.append_decision(notebook.notebook_id, decision)
    notebook_log = project / "notebooks" / notebook.notebook_id / "notebook.jsonl"
    notebook_log.write_text(
        notebook_log.read_text(encoding="utf-8")
        + json.dumps({"record_type": "recommendation_decision", "decision": {"batch_id": "bad"}})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        service.store.read_decision(notebook.notebook_id, decision.batch_id)


def test_legacy_option_is_rejected_before_any_materialization_record(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Legacy", created_by="ui")
    legacy = _legacy_option(service, notebook.notebook_id)

    assert callable(getattr(service, "assert_materializable", None))
    with pytest.raises(NotebookOptionError) as excinfo:
        service.assert_materializable(notebook.notebook_id, legacy.option_id)

    assert getattr(excinfo.value, "code", None) == "OPTION_LEGACY_UNVERIFIED"
    assert service.store.read_materialization(
        notebook.notebook_id, legacy.option_id, legacy.option_revision
    ) is None


def test_direct_storage_append_rejects_a_legacy_option(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Legacy", created_by="ui")
    legacy = _legacy_option(service, notebook.notebook_id)
    materialization = _bound_materialization(
        service,
        notebook.notebook_id,
        legacy,
        materialization_id="materialization_legacy",
    )

    with pytest.raises(NotebookOptionError) as excinfo:
        service.store.append_materialization(notebook.notebook_id, materialization)

    assert excinfo.value.code == "OPTION_LEGACY_UNVERIFIED"
    assert service.store.read_materialization(
        notebook.notebook_id, legacy.option_id, legacy.option_revision
    ) is None


def test_v11_option_cannot_confirm_without_a_bound_materialization_record(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Direct confirm", created_by="ui")
    revision = _v11_option(service, notebook.notebook_id, option_id="opt_direct")

    with pytest.raises(NotebookOptionError) as excinfo:
        service.confirm(
            notebook.notebook_id,
            revision.option_id,
            option_revision=revision.option_revision,
            proposal_id=revision.typed_proposal_id,
            proposal_revision=revision.typed_proposal_revision,
            context=service.compile_context(notebook.notebook_id),
        )

    assert excinfo.value.code == "OPTION_MATERIALIZATION_REQUIRED"
    view = service.option_view(notebook.notebook_id, revision.option_id)
    assert view.lifecycle_status == "selected"
    assert view.last_execution is None
    assert service.store.read_materialization(
        notebook.notebook_id, revision.option_id, revision.option_revision
    ) is None


def test_v11_completion_requires_bound_materialization_record_and_execution_state(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Direct completion", created_by="ui")
    revision = _v11_option(service, notebook.notebook_id, option_id="opt_complete")

    with pytest.raises(NotebookOptionError) as excinfo:
        service.complete_execution(
            notebook.notebook_id,
            revision.option_id,
            execution_status="failed",
        )

    assert excinfo.value.code == "OPTION_MATERIALIZATION_REQUIRED"
    assert service.option_view(notebook.notebook_id, revision.option_id).lifecycle_status == (
        "selected"
    )


def test_materialized_option_can_reconcile_a_successful_draft_run(
    tmp_path: Path,
) -> None:
    """Graph execution starts after materialization, then commits the same option."""

    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Draft reconciliation", created_by="ui")
    revision = _v11_option(service, notebook.notebook_id, option_id="opt_draft_run")
    materialization = _bound_materialization(
        service,
        notebook.notebook_id,
        revision,
        materialization_id="mat_draft_run",
    )
    service.store.append_materialization(notebook.notebook_id, materialization)
    service._transition(
        notebook.notebook_id,
        service.option_view(notebook.notebook_id, revision.option_id),
        to_status="materialized",
        actor="agent",
        reason="draft_materialized",
    )

    run = make_run(project, "run_draft_reconciled")
    bind_run_to_family(run, run_family_id=notebook.run_family_id, bound_by="test")

    outcome = service.complete_execution(
        notebook.notebook_id,
        revision.option_id,
        execution_status="succeeded",
        run_id="run_draft_reconciled",
        produced_artifacts=[
            {
                "artifact_id": "ets_1",
                "artifact_type": "model_result",
                "count": 1,
                "step": "estimation",
            }
        ],
    )

    assert outcome.lifecycle_status == "executed"
    assert outcome.active_head_advanced is True
    assert service.get_notebook(notebook.notebook_id).active_head_run_id == (
        "run_draft_reconciled"
    )
    assert [entry["to_status"] for entry in service.option_view(
        notebook.notebook_id, revision.option_id
    ).lifecycle_history] == ["selected", "materialized", "executing", "executed"]


def test_legacy_confirmation_remains_legacy_without_a_materialized_lie(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Legacy confirm", created_by="ui")
    legacy = _legacy_option(service, notebook.notebook_id)

    execution = service.confirm(
        notebook.notebook_id,
        legacy.option_id,
        option_revision=legacy.option_revision,
        proposal_id=legacy.typed_proposal_id,
        proposal_revision=legacy.typed_proposal_revision,
        context=service.compile_context(notebook.notebook_id),
    )

    view = service.option_view(notebook.notebook_id, legacy.option_id)
    assert execution.contract_version == "1.0"
    assert view.lifecycle_status == "executing"
    assert {entry["to_status"] for entry in view.lifecycle_history} == {
        "proposed",
        "selected",
        "executing",
    }
    assert service.store.read_materialization(
        notebook.notebook_id, legacy.option_id, legacy.option_revision
    ) is None


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("option", lambda record: replace(record, option_id="opt_missing")),
        ("revision", lambda record: replace(record, option_revision=2)),
        ("family", lambda record: replace(record, run_family_id="run-family:other")),
        ("proposal", lambda record: replace(record, proposal_id="proposal_other")),
        ("proposal revision", lambda record: replace(record, proposal_revision=2)),
        (
            "freshness",
            lambda record: replace(record, freshness_dependency_fingerprint="fresh1:other"),
        ),
        ("generation context", lambda record: replace(record, generation_context_id="ctx_other")),
    ],
)
def test_materialization_rejects_mismatched_current_option_pins(
    tmp_path: Path, label: str, change
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Pins", created_by="ui")
    revision = _v11_option(service, notebook.notebook_id, option_id="opt_pins")
    materialization = _bound_materialization(
        service,
        notebook.notebook_id,
        revision,
        materialization_id=f"materialization_{label.replace(' ', '_')}",
    )

    with pytest.raises((NotebookOptionError, ValueError)):
        service.store.append_materialization(
            notebook.notebook_id, change(materialization)
        )


def test_materialization_rejects_a_v11_option_that_is_not_selected(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="State", created_by="ui")
    revision = _v11_option(
        service, notebook.notebook_id, option_id="opt_proposed", lifecycle_status="proposed"
    )
    materialization = _bound_materialization(
        service,
        notebook.notebook_id,
        revision,
        materialization_id="materialization_proposed",
    )

    with pytest.raises(ValueError, match="selected"):
        service.store.append_materialization(notebook.notebook_id, materialization)


def test_materialized_lifecycle_edges_are_allowed_and_terminal_states_refuse_exit(
    tmp_path: Path,
) -> None:
    """Task 2 gates on a bound record only; Task 7 verifies PipelineDraft provenance."""
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Lifecycle", created_by="ui")
    option = _v11_option(service, notebook.notebook_id, option_id="opt_lifecycle")

    def transition(to_status: str) -> None:
        service._transition(
            notebook.notebook_id,
            service.option_view(notebook.notebook_id, option.option_id),
            to_status=to_status,
            actor="system",
            reason="test",
        )

    with pytest.raises(OptionLifecycleTransitionInvalid):
        transition("executing")
    with pytest.raises(NotebookOptionError) as excinfo:
        transition("materialized")
    assert excinfo.value.code == "OPTION_MATERIALIZATION_REQUIRED"

    service.store.append_materialization(
        notebook.notebook_id,
        _bound_materialization(
            service,
            notebook.notebook_id,
            option,
            materialization_id="materialization_lifecycle",
        ),
    )
    transition("materialized")
    transition("selected")
    transition("materialized")
    transition("executing")
    with pytest.raises(OptionLifecycleTransitionInvalid):
        transition("selected")
    transition("materialized")
    transition("archived")

    with pytest.raises(OptionLifecycleTransitionInvalid):
        transition("selected")


def test_selected_dataset_option_materializes_one_genesis_draft_idempotently(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    upload_sha = store_upload_bytes(
        project,
        b"outcome,predictor\n1,2\n2,3\n",
        filename="data.csv",
    )
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "data.csv",
            "sheet_names": [],
        },
        created_by="ui",
    )
    context = service.compile_context(notebook.notebook_id)
    pack = {
        "schema_version": "data-evidence-pack/v1",
        "source_id": f"dataset:{upload_sha}",
        "records": [
            {
                "evidence_id": "evidence:profile",
                "inspection_id": "profile.v1",
                "source_refs": [f"dataset_profile:{upload_sha}"],
                "protocol_version": "profile/v1",
                "status": "completed",
                "observations": {"columns": [{"name": "outcome"}, {"name": "predictor"}]},
                "metrics": {},
                "warnings": [],
                "omissions": [],
                "failure_code": None,
                "result_hash": "sha256:profile-result",
            }
        ],
        "pack_omissions": [],
        "content_hash": "sha256:profile-pack",
        "evidence_pack_hash": "sha256:profile-pack",
    }
    service.store.append_evidence_pack(notebook.notebook_id, pack)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id="prop_genesis",
        operation_id="model.genesis",
        target={"dataset_source_id": upload_sha},
        preconditions={
            "context_version": "notebook-planning-context/v1",
            "context_fingerprint": context.context_id,
            "owner_resolution": "dataset_projection",
        },
        changes={
            "model_params": {
                "model_type": "ols",
                "y": "outcome",
                "x": ["predictor"],
                "covariance": "robust",
            }
        },
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_genesis",
        batch_id="batch_genesis",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=("sha256:profile-pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_genesis_real",),
        outcome="recommended",
        recommended_option_id="opt_genesis_real",
        reason_refs=("evidence:profile",),
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="The verified dataset columns support the selected model path.",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ols_1",
                        artifact_type="model_result",
                        required=True,
                        count=1,
                    ),
                ),
                capability_id="ols",
                option_id="opt_genesis_real",
                evidence_refs=(
                    EvidenceRef(
                        evidence_id="evidence:profile",
                        result_hash="sha256:profile-result",
                        source_refs=(f"dataset_profile:{upload_sha}",),
                    ),
                ),
                comparative_claims=("evidence:profile supports the model path",),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="ui",
    )

    first = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    second = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )

    assert first.materialization.materialization_id == second.materialization.materialization_id
    assert first.materialization.draft_execution_mode == "genesis"
    assert first.draft.draft["created_from"]["source_type"] == "genesis"
    assert first.draft.draft["created_from"]["source_input_fingerprint"] == upload_sha
    assert first.draft.draft["notebook_provenance"]["option_id"] == revision.option_id
    assert first.draft.draft["graph"]["nodes"][2]["params"]["model_type"] == "ols"
    assert first.draft.draft["graph"]["nodes"][2]["params"]["covariance"] == "robust"
    assert service.option_view(notebook.notebook_id, revision.option_id).lifecycle_status == "materialized"


def test_univariate_genesis_option_materializes_without_x_regressors(
    tmp_path: Path,
) -> None:
    """A univariate model (ETS) declares no x regressors and must materialize
    a genesis draft without one; the mandatory-x rule is keyed to the target
    capability, not to a hardcoded model_type. Notebook is model-agnostic."""
    project = make_project(tmp_path)
    service = NotebookService(project)
    upload_sha = store_upload_bytes(
        project,
        b"when,value\n2020-01-01,1\n2020-01-02,2\n",
        filename="series.csv",
    )
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "series.csv",
            "sheet_names": [],
        },
        created_by="ui",
    )
    context = service.compile_context(notebook.notebook_id)
    pack = {
        "schema_version": "data-evidence-pack/v1",
        "source_id": f"dataset:{upload_sha}",
        "records": [
            {
                "evidence_id": "evidence:profile",
                "inspection_id": "profile.v1",
                "source_refs": [f"dataset_profile:{upload_sha}"],
                "protocol_version": "profile/v1",
                "status": "completed",
                "observations": {"columns": [{"name": "when"}, {"name": "value"}]},
                "metrics": {},
                "warnings": [],
                "omissions": [],
                "failure_code": None,
                "result_hash": "sha256:profile-result",
            }
        ],
        "pack_omissions": [],
        "content_hash": "sha256:profile-pack",
        "evidence_pack_hash": "sha256:profile-pack",
    }
    service.store.append_evidence_pack(notebook.notebook_id, pack)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id="prop_ets_genesis",
        operation_id="model.genesis",
        target={"dataset_source_id": upload_sha},
        preconditions={
            "context_version": "notebook-planning-context/v1",
            "context_fingerprint": context.context_id,
            "owner_resolution": "dataset_projection",
        },
        changes={
            "model_params": {
                "model_type": "time_series.ets",
                "y": "value",
                "model_options": {
                    "time_column": "when",
                    "value_column": "value",
                    "error": "add",
                    "trend": None,
                    "seasonal": None,
                    "damped_trend": False,
                },
            }
        },
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_ets_genesis",
        batch_id="batch_ets_genesis",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=("sha256:profile-pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_ets_genesis",),
        outcome="recommended",
        recommended_option_id="opt_ets_genesis",
        reason_refs=("evidence:profile",),
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="The verified evenly spaced series supports a univariate ETS fit.",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ets_1",
                        artifact_type="model_result",
                        required=True,
                        count=1,
                    ),
                ),
                capability_id="time_series.ets",
                option_id="opt_ets_genesis",
                evidence_refs=(
                    EvidenceRef(
                        evidence_id="evidence:profile",
                        result_hash="sha256:profile-result",
                        source_refs=(f"dataset_profile:{upload_sha}",),
                    ),
                ),
                comparative_claims=("evidence:profile supports the univariate fit",),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="ui",
    )

    result = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )

    assert result.materialization.draft_execution_mode == "genesis"
    assert result.draft.draft["created_from"]["source_type"] == "genesis"
    model_node = result.draft.draft["graph"]["nodes"][2]
    assert model_node["params"]["model_type"] == "time_series.ets"
    assert "x" not in model_node["params"]
    assert (
        service.option_view(notebook.notebook_id, revision.option_id).lifecycle_status
        == "materialized"
    )


@pytest.mark.parametrize(
    "model_options",
    [
        pytest.param(
            {
                "time_column": "when",
                "value_column": "value",
                "error": "add",
                "trend": None,
                "seasonal": None,
                "damped_trend": False,
            },
            id="non-empty-options",
        ),
        pytest.param({}, id="retain-current-path"),
    ],
)
def test_selected_run_option_materializes_one_pinned_rerun_child_draft(
    tmp_path: Path, model_options: dict[str, object]
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    run_root = make_run(project, "run_active")
    upload_sha = store_upload_bytes(project, b"when,value\n2020-01-01,1\n", filename="data.csv")
    (run_root / "run_inputs.json").write_text(
        json.dumps(
            {
                "run_input_schema_version": 1,
                "upload": {"sha256": upload_sha},
                "form": {
                    "model_type": "time_series.ets",
                    "model_options": {
                        "time_column": "when",
                        "value_column": "value",
                        "error": "add",
                        "trend": "add",
                        "seasonal": None,
                        "damped_trend": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_active",
                "mode": "manual",
                "status": "completed",
                "model_routing": {
                    "requested_model_type": "time_series.ets",
                    "effective_model_type": "time_series.ets",
                },
            }
        ),
        encoding="utf-8",
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id="run_active",
            nodes={
                "model:ets_1": Node(
                    id="model:ets_1",
                    kind=NodeKind.MODEL,
                    display_label="ETS",
                    created_at="2026-07-23T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    node_hash = "a" * 64
    (run_root / "node_index.json").write_text(
        json.dumps({"model:ets_1": {"node_hash": node_hash, "cas_ref": {}}}),
        encoding="utf-8",
    )
    notebook = service.ensure_default_projection(from_run_id="run_active", created_by="ui")
    request = NodeWriteOperationRequestV1(
        request_id="materialization-test",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id="run_active",
        op_node_id="model:ets_1",
        node_hash=node_hash,
        forest_node_key=f"{node_hash}::model:ets_1",
        owner_resolution="single_candidate",
        active_head_run_id="run_active",
    )
    source_context_fingerprint = compute_context_fingerprint(project / "runs", request)
    context = service.compile_context(notebook.notebook_id)
    pack = {
        "schema_version": "data-evidence-pack/v1",
        "source_id": "run:run_active",
        "records": [
            {
                "evidence_id": "evidence:time",
                "inspection_id": "time_index.v1",
                "source_refs": ["time_index:run_active"],
                "protocol_version": "time-index/v1",
                "status": "completed",
                "observations": {"candidate_column": "when"},
                "metrics": {},
                "warnings": [],
                "omissions": [],
                "failure_code": None,
                "result_hash": "sha256:time-result",
            }
        ],
        "pack_omissions": [],
        "content_hash": "sha256:time-pack",
        "evidence_pack_hash": "sha256:time-pack",
    }
    service.store.append_evidence_pack(notebook.notebook_id, pack)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id="prop_rerun",
        operation_id="model.rerun",
        target={
            "run_id": "run_active",
            "node_ref": "model:ets_1",
            "node_hash": node_hash,
            "forest_node_key": f"{node_hash}::model:ets_1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_context_fingerprint,
            "active_head_run_id": "run_active",
            "owner_resolution": "single_candidate",
        },
        changes={
            "model_options": model_options,
        },
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_rerun",
        batch_id="batch_rerun",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=("sha256:time-pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_rerun_real",),
        outcome="recommended",
        recommended_option_id="opt_rerun_real",
        reason_refs=("evidence:time",),
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="The active run has a valid time index.",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ets_1",
                        artifact_type="model_result",
                        required=True,
                        count=1,
                    ),
                ),
                capability_id="time_series.ets",
                option_id="opt_rerun_real",
                evidence_refs=(
                    EvidenceRef(
                        evidence_id="evidence:time",
                        result_hash="sha256:time-result",
                        source_refs=("time_index:run_active",),
                    ),
                ),
                comparative_claims=("evidence:time supports the rerun path",),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        recommendation_decision=decision,
    )
    service.record_decision(notebook.notebook_id, revision.option_id, decision="selected", actor="ui")

    result = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )

    assert result.materialization.draft_execution_mode == "rerun_child"
    assert result.draft.draft["created_from"]["source_run_id"] == "run_active"
    assert result.draft.draft["created_from"]["source_model_node_id"] == "model:ets_1"
    assert result.draft.draft["notebook_provenance"]["option_id"] == revision.option_id
    if model_options:
        assert result.draft.draft["graph"]["nodes"][1]["params"]["model_options"]["trend"] is None


def test_invalid_model_options_are_rejected_before_option_persistence(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    run_root = make_run(project, "run_arma")
    source_options = {
        "dataset_ref": "upload:vix.csv",
        "time_column": "date",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "log_return_pct",
        "transform_confirmed": True,
        "analysis_goal": "balanced",
        "selection_mode": "auto",
        "arma": {
            "p": None,
            "q": None,
            "constant_mode": "auto",
            "auto_max_p": 3,
            "auto_max_q": 3,
            "auto_max_total_order": 4,
        },
        "variance": {
            "model": "auto",
            "arch_p": None,
            "garch_p": None,
            "garch_q": None,
            "auto_arch_max_p": 10,
            "include_garch_1_1": True,
        },
        "estimation_strategy": "auto",
        "innovation_distribution": "normal",
        "missing_value_policy": "drop_missing_confirmed",
        "validation": {"validation_n": 20, "refit_every": 1},
        "random_seed": 1,
    }
    bound = bind_new_model_options("time_series.arma_garch", source_options)
    (run_root / "run_inputs.json").write_text(
        json.dumps(
            {
                "run_input_schema_version": 1,
                "form": {
                    "model_type": "time_series.arma_garch",
                    "model_options": bound.payload,
                    "model_options_binding": bound.binding.to_dict(),
                },
            }
        ),
        encoding="utf-8",
    )
    notebook = service.create_notebook(title="Contract", created_by="test")
    proposal = TypedProposal.from_dict(
        {
            "proposal_id": "prop_bad_arma_aliases",
            "proposal_revision": 1,
            "operation_id": "model.rerun",
            "operation_version": "v1",
            "target": {
                "run_id": "run_arma",
                "node_ref": "model:arma",
                "node_hash": "a" * 64,
                "forest_node_key": "a" * 64 + "::model:arma",
            },
            "preconditions": {
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "nocv1:test",
                "active_head_run_id": "run_arma",
                "owner_resolution": "single_candidate",
            },
            "changes": {
                "model_options": {
                    "ar": 2,
                    "ma": 1,
                    "dist": "normal",
                    "volatility_model": "EGARCH",
                }
            },
        }
    )

    with pytest.raises(OptionValidationFailed, match="MODEL_OPTIONS_INVALID_VALUE"):
        service.propose_batch(
            notebook.notebook_id,
            context=service.compile_context(notebook.notebook_id),
            drafts=[
                OptionDraft(
                    rank=1,
                    rationale="invalid target contract",
                    proposal=proposal,
                    expected_artifacts=(
                        ExpectedArtifact(
                            artifact_id="ts.artifact_manifest",
                            artifact_type="time_series_manifest",
                            required=True,
                        ),
                    ),
                    capability_id="time_series.arma_garch",
                    option_id="opt_bad_arma_aliases",
                )
            ],
        )

    assert service.store.option_ids(notebook.notebook_id) == []


def test_ols_run_model_options_are_editable_before_draft_creation(
    tmp_path: Path,
) -> None:
    """OLS now owns the generic envelope and materializes a bound Draft patch."""

    project = make_project(tmp_path)
    service = NotebookService(project)
    run_root = make_run(project, "run_ols")
    upload_sha = store_upload_bytes(project, b"y,x\n1,2\n3,4\n", filename="data.csv")
    (run_root / "run_inputs.json").write_text(
        json.dumps(
            {
                "run_input_schema_version": 1,
                "upload": {"sha256": upload_sha},
                "form": {
                    "model_type": "ols",
                    "y": "y",
                    "x": "x",
                    "covariance": "robust",
                    "model_options": {},
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_ols",
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
            run_id="run_ols",
            nodes={
                "model:ols_1": Node(
                    id="model:ols_1",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-07-23T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    node_hash = "b" * 64
    (run_root / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": node_hash, "cas_ref": {}}}),
        encoding="utf-8",
    )
    notebook = service.ensure_default_projection(from_run_id="run_ols", created_by="ui")
    request = NodeWriteOperationRequestV1(
        request_id="materialization-non-editable-options",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id="run_ols",
        op_node_id="model:ols_1",
        node_hash=node_hash,
        forest_node_key=f"{node_hash}::model:ols_1",
        owner_resolution="single_candidate",
        active_head_run_id="run_ols",
    )
    source_context_fingerprint = compute_context_fingerprint(project / "runs", request)
    proposal = TypedProposal(
        proposal_id="prop_ols_unsupported_options",
        operation_id="model.rerun",
        target={
            "run_id": "run_ols",
            "node_ref": "model:ols_1",
            "node_hash": node_hash,
            "forest_node_key": f"{node_hash}::model:ols_1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_context_fingerprint,
            "active_head_run_id": "run_ols",
            "owner_resolution": "single_candidate",
        },
        changes={"model_options": {"covariance": "clustered"}},
    )

    result = NotebookOptionMaterializer(service)._materialize_run(
        notebook,
        proposal.to_dict(),
        {
            "notebook_id": notebook.notebook_id,
            "option_id": "opt_ols_options",
            "option_revision": "1",
        },
    )

    model = next(node for node in result.draft["graph"]["nodes"] if node["node_type"] == "model")
    assert model["params"]["model_options"] == {"covariance": "clustered"}
    assert service.project_root.joinpath("data", "pipeline_drafts").exists()


def test_ols_genesis_covariance_model_options_are_materialized_as_covariance(
    tmp_path: Path,
) -> None:
    """Provider-era nested covariance is normalized before an OLS Draft is persisted."""
    project = make_project(tmp_path)
    service = NotebookService(project)
    upload_sha = store_upload_bytes(project, b"outcome,age\n1,20\n2,30\n", filename="data.csv")
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "data.csv",
            "sheet_names": [],
        },
        created_by="ui",
    )
    context = service.compile_context(notebook.notebook_id)
    pack = {
        "schema_version": "data-evidence-pack/v1",
        "source_id": f"dataset:{upload_sha}",
        "records": [
            {
                "evidence_id": "evidence:profile",
                "inspection_id": "profile.v1",
                "source_refs": [f"dataset_profile:{upload_sha}"],
                "protocol_version": "profile/v1",
                "status": "completed",
                "observations": {"columns": [{"name": "outcome"}, {"name": "age"}]},
                "metrics": {},
                "warnings": [],
                "omissions": [],
                "failure_code": None,
                "result_hash": "sha256:profile-result",
            }
        ],
        "pack_omissions": [],
        "content_hash": "sha256:profile-pack",
        "evidence_pack_hash": "sha256:profile-pack",
    }
    service.store.append_evidence_pack(notebook.notebook_id, pack)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id="prop_ols_nested_covariance",
        operation_id="model.genesis",
        target={"dataset_source_id": upload_sha},
        preconditions={
            "context_version": "notebook-planning-context/v1",
            "context_fingerprint": context.context_id,
            "owner_resolution": "dataset_projection",
        },
        changes={
            "model_params": {
                "model_type": "ols",
                "y": "outcome",
                "x": ["age"],
            },
            "model_options": {"covariance": "robust"},
        },
    )
    decision = RecommendationDecision(
        recommendation_decision_id="rec_ols_nested_covariance",
        batch_id="batch_ols_nested_covariance",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=("sha256:profile-pack",),
        comparison_protocol_refs=(),
        candidate_option_ids=("opt_ols_nested_covariance",),
        outcome="recommended",
        recommended_option_id="opt_ols_nested_covariance",
        reason_refs=("evidence:profile",),
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="The verified columns support OLS.",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="ols_1",
                        artifact_type="model_result",
                        required=True,
                        count=1,
                    ),
                ),
                capability_id="ols",
                option_id="opt_ols_nested_covariance",
                evidence_refs=(
                    EvidenceRef(
                        evidence_id="evidence:profile",
                        result_hash="sha256:profile-result",
                        source_refs=(f"dataset_profile:{upload_sha}",),
                    ),
                ),
                comparative_claims=("evidence:profile supports OLS",),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        recommendation_decision=decision,
    )
    service.record_decision(notebook.notebook_id, revision.option_id, decision="selected", actor="ui")
    result = NotebookOptionMaterializer(service).materialize(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    model = next(node for node in result.draft.draft["graph"]["nodes"] if node["node_id"] == "model_1")
    assert model["params"]["covariance"] == "robust"
    assert model["params"]["model_options"] == {"covariance": "robust"}
