"""Append-only evidence, recommendation, and materialization state."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.errors import (
    NotebookOptionError,
    OptionLifecycleTransitionInvalid,
)
from workbench.contracts.agent.notebook_option import (
    ExpectedArtifact,
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


def test_materialization_records_cover_genesis_and_rerun_child_identities(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Materialization", created_by="ui")
    option = _option(service, notebook.notebook_id, option_id="opt_001")
    genesis = replace(
        _materialization("option_materialization_genesis_v1"),
        materialization_id="materialization_genesis",
        option_id=option.option_id,
        option_revision=1,
        run_family_id=notebook.run_family_id,
    )
    rerun_child = replace(
        _materialization("option_materialization_v1"),
        materialization_id="materialization_rerun_child",
        option_id=option.option_id,
        option_revision=2,
        run_family_id=notebook.run_family_id,
    )

    assert callable(getattr(service.store, "append_materialization", None))
    for record in (genesis, rerun_child):
        service.store.append_materialization(notebook.notebook_id, record)
        service.store.append_materialization(notebook.notebook_id, record)

    assert service.store.read_materialization(notebook.notebook_id, option.option_id, 1) == genesis
    assert service.store.read_materialization(notebook.notebook_id, option.option_id, 2) == rerun_child
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


def test_materialized_lifecycle_edges_are_allowed_and_terminal_states_refuse_exit(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Lifecycle", created_by="ui")
    option = _option(service, notebook.notebook_id, option_id="opt_lifecycle")
    service.record_decision(
        notebook.notebook_id, option.option_id, decision="selected", actor="user"
    )

    def transition(to_status: str) -> None:
        service._transition(
            notebook.notebook_id,
            service.option_view(notebook.notebook_id, option.option_id),
            to_status=to_status,
            actor="system",
            reason="test",
        )

    transition("materialized")
    transition("selected")
    transition("materialized")
    transition("executing")
    transition("materialized")
    transition("archived")

    with pytest.raises(OptionLifecycleTransitionInvalid):
        transition("selected")
