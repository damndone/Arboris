"""Analysis-loop admission and Notebook validation share typed requests."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from workbench.agent import operation_requests
from workbench.agent.notebook import NotebookService
from workbench.agent.notebook.errors import OptionValidationFailed
from workbench.agent.operations import OperationRegistry
from workbench.analysis_loop.lifecycle import build_analysis_loop_proposal, create_analysis_loop_proposal
from tests.test_agent_analysis_loop_lifecycle import _adapter_kwargs, _orchestrator
from tests.test_notebook_option_lifecycle import _draft
from tests.test_notebook_support import make_context, make_project


def test_pure_declaration_validation_never_consumes_narrative_iterables() -> None:
    assert hasattr(operation_requests, "validate"), "pure shared declaration validation is missing"
    definition = OperationRegistry().require("graph.fork", "v1")

    def narrative():
        raise AssertionError("declaration validation must not consume narrative fields")
        yield "unreachable"

    request = operation_requests.OperationRequest(
        operation_id="graph.fork", target={"run_id": "run-a", "node_ref": "model:ols", "node_hash": "h", "forest_node_key": "h", "source_session_entry_id": "entry-source"},
        preconditions={"context_version": "v1", "context_fingerprint": "ctx", "active_head_run_id": "run-a", "owner_resolution": "active_head"},
        changes={"reason": "read-only declaration check"},
        evidence_refs=narrative(), expected_effect=narrative(), risks=narrative(),
    )
    operation_requests.validate(request, definition)


def test_analysis_loop_direct_admission_preserves_spec_and_retry_identity(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)
    spec = build_analysis_loop_proposal(**kwargs)
    assert hasattr(spec, "to_operation_request"), "analysis-loop must expose a typed request"
    request = spec.to_operation_request()
    legacy = spec.to_proposal_kwargs(chain_id="chain-a", command_id="cmd-loop")
    assert request.operation_id == legacy["operation_id"]
    assert request.target == legacy["target"]
    assert request.preconditions == legacy["preconditions"]
    assert request.changes == legacy["changes"]
    assert list(request.evidence_refs) == legacy["evidence_refs"]
    admitted = []
    original = operation_requests.admit

    def observe(request, **scope):
        receipt = original(request, **scope)
        admitted.append((request, scope))
        return receipt

    monkeypatch.setattr(operation_requests, "admit", observe)
    assert not hasattr(orchestrator, "create_proposal")
    first = create_analysis_loop_proposal(orchestrator=orchestrator, chain_id="chain-a", command_id="cmd-loop", **kwargs)
    second = create_analysis_loop_proposal(orchestrator=orchestrator, chain_id="chain-a", command_id="cmd-loop", **kwargs)
    assert first.to_dict() == second.to_dict()
    assert first.target == legacy["target"]
    assert first.preconditions == legacy["preconditions"]
    assert first.changes == legacy["changes"]
    assert len(admitted) == 1
    assert isinstance(admitted[0][0], operation_requests.OperationRequest)
    assert admitted[0][1]["proposal_id"] == spec.proposal_id
    assert first.command_id == "cmd-loop"
    assert orchestrator.operation_store.list_records() == []


def test_notebook_batch_uses_shared_validation_without_creating_chain_records(tmp_path: Path, monkeypatch) -> None:
    assert hasattr(operation_requests, "validate"), "pure shared declaration validation is missing"
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="shared validation", created_by="u")
    context = make_context(project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id)
    drafts = [_draft(1, covariance="robust", proposal_id="p1"), _draft(2, covariance="clustered", proposal_id="p2")]
    broken = replace(drafts[1].proposal, target={key: value for key, value in drafts[1].proposal.target.items() if key != "node_hash"})
    drafts[1] = replace(drafts[1], proposal=broken)
    seen = []
    original = operation_requests.validate

    def observe(request, definition):
        seen.append((request, definition))
        return original(request, definition)

    monkeypatch.setattr(operation_requests, "validate", observe)
    with pytest.raises(OptionValidationFailed, match="node_hash"):
        service.propose_batch(notebook.notebook_id, context=context, drafts=drafts, batch_id="batch-shared")
    assert len(seen) == 2
    assert all(isinstance(request, operation_requests.OperationRequest) for request, _definition in seen)
    assert [request.changes for request, _definition in seen] == [draft.proposal.changes for draft in drafts]
    assert service.list_options(notebook.notebook_id) == []
    for directory in ("agent-sessions", "proposals", "operation-records"):
        assert not (project / "workbench" / directory).exists()


@pytest.mark.parametrize("stage", ("lookup", "validation"))
def test_notebook_keeps_lookup_and_validator_exception_boundaries(tmp_path: Path, monkeypatch, stage: str) -> None:
    assert hasattr(operation_requests, "validate"), "pure shared declaration validation is missing"
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="error boundaries", created_by="u")
    context = make_context(project, notebook_id=notebook.notebook_id, run_family_id=notebook.run_family_id)
    definition = service.registry.require("model.rerun", "v1")

    def fail(*args, **kwargs):
        raise ValueError(f"{stage} sentinel")

    monkeypatch.setattr(service.registry, "require", fail if stage == "lookup" else lambda *_args: replace(definition, validator=fail))
    expected = OptionValidationFailed if stage == "lookup" else ValueError
    with pytest.raises(expected, match="unknown operation" if stage == "lookup" else "validation sentinel"):
        service.propose_batch(notebook.notebook_id, context=context, drafts=[_draft(1, covariance="robust")])
    assert service.list_options(notebook.notebook_id) == []
