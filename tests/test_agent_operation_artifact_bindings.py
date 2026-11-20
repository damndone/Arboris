"""Completed workflow references must round-trip without guessing artifact ids."""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.test_agent_context_tools import (
    _load_provider_type,
    _write_completed_workflow_result,
    _write_project_run,
)
from workbench.agent.context_tools_support.requests import InspectOperationArtifactRequest
from workbench.agent.operations import OperationRecordStore
from workbench.agent.operation_outcome import outcome_text
from workbench.agent.tools import ToolVisibleError


def _completed_branch(tmp_path):
    root = tmp_path / "project"
    _write_project_run(root)
    record_id, artifact_id = _write_completed_workflow_result(root)
    child = root / "runs" / "run-child"
    child.mkdir()
    payload = {"result": {"statistic": 3.25, "raw_rows": [{"private": 9}]}}
    content = json.dumps(payload)
    (child / "test.json").write_text(content)
    (child / "artifacts_index.json").write_text(json.dumps({"artifacts": [{
        "artifact_id": artifact_id, "artifact_type": "statistical_test", "path": "test.json",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }]}))
    store = OperationRecordStore(root / "workbench")
    original = store.get(record_id)
    outputs = original.outputs
    step = outputs["workflow_state"]["steps"]["summary"]
    step["artifact_ids"] = [f"run-child:{artifact_id}"]
    step["model_branches"] = [{"branch_id": "main", "run_id": "run-child",
                              "model_id": "ols_1", "artifact_ids": [artifact_id]}]
    record = store.append_status(record_id, "completed", outputs=outputs)
    return root, record, artifact_id


def _request(record, artifact_id):
    return InspectOperationArtifactRequest(
        request_id="read", owner_run_id="run-a", op_node_id="model:ols_1",
        active_head_run_id="run-a", operation_record_id=record.record_id, artifact_id=artifact_id,
    )


def _inspect(root, request, *, chain_id="chain-a"):
    return _load_provider_type()(root).inspect_operation_artifact(
        request, chain_id=chain_id, session_id="chain-session",
    )


def test_exact_emitted_child_artifact_round_trips_through_parent_scope(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    qualified = f"run-child:{artifact_id}"
    evidence = _inspect(root, _request(record, qualified))["artifact_evidence"]
    assert evidence["available"] is True
    assert evidence["result"] == {"statistic": 3.25}
    assert evidence["evidence_ref"]["artifact_id"] == qualified
    assert evidence["evidence_ref"]["source_run_id"] == "run-child"
    assert evidence["evidence_ref"]["registered_artifact_id"] == artifact_id


def test_execution_receipt_supplies_exact_read_arguments_and_model_run(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    provider = _load_provider_type()(root)
    entry = provider.executed_workflow_results(record)[0]
    item = entry["artifacts"][0]
    assert item["result"] == {"statistic": 3.25}
    assert entry["model_branches"] == [{"branch_id": "main", "run_id": "run-child", "model_id": "ols_1"}]
    assert entry["read_with"] == {
        "owner_run_id": "run-a", "op_node_id": "model:ols_1", "active_head_run_id": "run-a",
        "operation_record_id": record.record_id,
    }
    # A reader can use the receipt verbatim, including the run-qualified id.
    request = InspectOperationArtifactRequest(request_id="read", **entry["read_with"], artifact_id=item["artifact_id"])
    assert _inspect(root, request)["artifact_evidence"]["result"] == item["result"]


def test_a_bare_id_naming_one_declaration_reads_it_and_any_other_is_refused_with_declarations(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    evidence = _inspect(root, _request(record, artifact_id))["artifact_evidence"]
    assert evidence["evidence_ref"]["artifact_id"] == f"run-child:{artifact_id}"
    with pytest.raises(ToolVisibleError, match="OPERATION_ARTIFACT_NOT_DECLARED") as error:
        _inspect(root, _request(record, "no_such_artifact"))
    message = str(error.value)
    assert f"run-child:{artifact_id}" in message
    assert "inspect_completed_operations" in message
    assert "Do not remove" in message
    assert len(message) < 4000


@pytest.mark.parametrize("change", ["branch_run", "branch_artifact", "step_status", "digest"])
def test_qualified_reference_requires_completed_branch_binding_and_registered_digest(tmp_path, change):
    root, record, artifact_id = _completed_branch(tmp_path)
    step = record.outputs["workflow_state"]["steps"]["summary"]
    if change == "branch_run":
        step["model_branches"][0]["run_id"] = "other-run"
    elif change == "branch_artifact":
        step["model_branches"][0]["artifact_ids"] = []
    elif change == "step_status":
        step["status"] = "failed"
    else:
        (root / "runs" / "run-child" / "test.json").write_text('{"result":{"statistic":99}}')
    OperationRecordStore(root / "workbench").append_status(record.record_id, "completed", outputs=record.outputs)
    with pytest.raises(ToolVisibleError, match="OPERATION_ARTIFACT_UNAVAILABLE"):
        _inspect(root, _request(record, f"run-child:{artifact_id}"))


def test_qualified_reference_does_not_disclose_foreign_chain_declarations(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    with pytest.raises(ToolVisibleError, match="OPERATION_RESULT_NOT_IN_SCOPE") as error:
        _inspect(root, _request(record, artifact_id), chain_id="foreign-chain")
    assert "run-child" not in str(error.value)


def test_receipt_does_not_offer_an_unbound_child_as_available(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    record.outputs["workflow_state"]["steps"]["summary"]["model_branches"] = []
    entry = _load_provider_type()(root).executed_workflow_results(record)[0]
    assert entry["artifacts"] == []
    assert entry["artifacts_without_result_view"] == [f"run-child:{artifact_id}"]


def test_outcome_names_model_reader_and_keeps_operation_read_scope(tmp_path):
    root, record, _artifact_id = _completed_branch(tmp_path)
    results = _load_provider_type()(root).executed_workflow_results(record)
    text = outcome_text({"operation_id": record.operation_id, "status": "completed", "results": results})
    assert 'model branches ["run-child"]' in text
    assert "call it only for runs_not_shown or terms_not_shown" in text
    assert '"runs_not_shown": ["run-child"]' in text
    assert "Do not remove run prefixes" in text
    assert "unavailable artifacts are not numerical evidence" in text
    assert '"owner_run_id": "run-a"' in text


def test_model_artifact_keeps_public_projection_closed_and_names_existing_reader(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    index = root / "runs" / "run-child" / "artifacts_index.json"
    registry = json.loads(index.read_text())
    registry["artifacts"][0]["artifact_type"] = "model_result"
    index.write_text(json.dumps(registry))
    evidence = _inspect(root, _request(record, f"run-child:{artifact_id}"))["artifact_evidence"]
    assert evidence["available"] is False
    assert evidence["result"] is None
    assert 'inspect_project_model_coefficients using run_ids ["run-child"]' in evidence["reason"]


def test_child_non_json_artifacts_are_not_parsed_as_public_results(tmp_path):
    root, record, artifact_id = _completed_branch(tmp_path)
    child = root / "runs" / "run-child"
    # Even parseable content does not authorize reading a dataset/media file.
    (child / "test.json").rename(child / "source.parquet")
    index = child / "artifacts_index.json"
    registry = json.loads(index.read_text())
    registry["artifacts"][0]["path"] = "source.parquet"
    index.write_text(json.dumps(registry))
    entry = _load_provider_type()(root).executed_workflow_results(record)[0]
    assert entry["artifacts"] == [] and entry["artifacts_without_result_view"] == [f"run-child:{artifact_id}"]
    with pytest.raises(ToolVisibleError, match="a .parquet file"):
        _inspect(root, _request(record, f"run-child:{artifact_id}"))


def _fitted_branch(tmp_path, coefficients):
    root, record, artifact_id = _completed_branch(tmp_path)
    results = root / "runs" / "run-child" / "model_results"
    results.mkdir()
    results.joinpath("ols_1.json").write_text(json.dumps({
        "model_id": "ols_1", "model_type": "ols", "nobs": 100, "y_column": "y", "x_columns": list(coefficients),
        "coefficients": {term: {"estimate": value, "std_error": 0.5, "p_value": 0.01} for term, value in coefficients.items()},
    }))
    return root, record


def test_executed_fit_carries_the_coefficient_view_so_no_separate_read_is_needed(tmp_path):
    root, record = _fitted_branch(tmp_path, {"Intercept": 0.25, "x1": 1.2})
    provider = _load_provider_type()(root)
    [entry] = provider.executed_workflow_results(record)
    estimates = entry["model_estimates"]
    from workbench.agent.context_tools_support.requests import InspectProjectModelCoefficientsRequest
    direct = provider.inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=("run-child",), terms=("Intercept", "x1")))
    assert estimates["models"] == direct["models"]
    assert estimates["runs_not_shown"] == []
    text = outcome_text({"operation_id": record.operation_id, "status": "completed", "results": [entry]})
    assert '"estimate": 1.2' in text and '"term": "x1"' in text


def test_estimates_name_the_terms_they_leave_out(tmp_path):
    from workbench.agent.context_tools_support.workflow_results import ESTIMATED_TERMS
    terms = {f"x{index}": float(index) for index in range(ESTIMATED_TERMS + 3)}
    root, record = _fitted_branch(tmp_path, terms)
    [model] = _load_provider_type()(root).executed_workflow_results(record)[0]["model_estimates"]["models"]
    assert len(model["coefficients"]) == ESTIMATED_TERMS
    assert model["terms_not_shown"] == list(terms)[ESTIMATED_TERMS:]
