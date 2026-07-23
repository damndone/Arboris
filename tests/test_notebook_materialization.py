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
    OptionLifecycleTransitionInvalid,
)
from workbench.agent.notebook.store import StoredRevision
from workbench.contracts.agent.notebook_option import (
    ExpectedArtifact,
    NotebookOptionRevision,
    OptionMaterialization,
    RecommendationDecision,
)

from tests.test_notebook_support import make_project, model_rerun_proposal


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


def test_v11_option_cannot_confirm_without_a_real_materialization(tmp_path: Path) -> None:
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


def test_v11_completion_requires_real_materialization_and_execution_state(
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
