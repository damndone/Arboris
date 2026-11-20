"""Actual-engine receipts are bounded evidence, not numerical certification."""
from __future__ import annotations

import copy
import json

import pytest

from workbench import estimation_engine
from workbench.agent.context_tools import InspectResultSummaryRequest
from workbench.agent.tools import _bounded_tool_output
from workbench.services.results_service import _model_results, read_model_results
from tests.test_agent_context_tools import _load_provider_type, _write_project_run


BUILD_SHA = "a" * 64


def selection():
    return {
        "requested": "fast", "used": "arboris-engine", "bit_identical_to_reference": False,
        "build": {"build_identity_sha256": BUILD_SHA, "compiler": {"path": "/private/compiler"},
                  "binary": "/private/build/libengine.dylib", "source_files": ["/private/source"]},
        "agreement_with_reference": {"basis": "not a universal error bound"},
    }


def expected_fast():
    return {"requested": "fast", "used": "arboris-engine", "bit_identical_to_reference": False,
            "build_identity_sha256": BUILD_SHA}


def test_public_provenance_whitelists_recorded_facts_without_mutating_selection():
    raw = selection()
    original = copy.deepcopy(raw)
    assert estimation_engine.engine_provenance({"engine_selection": raw}) == expected_fast()
    assert raw == original


def test_public_provenance_keeps_reference_fallback_reason_without_inferred_bit_or_build():
    fallback = {"requested": "fast", "used": "reference", "reason": "native engine is not built"}
    assert estimation_engine.engine_provenance({"engine_selection": fallback}) == fallback
    assert estimation_engine.engine_provenance({"engine": "linearmodels"}) is None


def test_public_provenance_bounds_reason_and_discards_invalid_digest():
    raw = {"requested": "fast", "used": "reference", "reason": "r" * 900,
           "bit_identical_to_reference": "false", "build": {"build_identity_sha256": "invalid"}}
    public = estimation_engine.engine_provenance({"engine_selection": raw})
    assert public == {"requested": "fast", "used": "reference", "reason": "r" * 500 + "…"}


def test_http_projection_adds_receipt_but_preserves_existing_full_selection(tmp_path):
    model_dir = tmp_path / "model_results"
    model_dir.mkdir()
    raw = {"model_id": "iv_1", "model_type": "iv_2sls", "coefficients": {}, "engine_selection": selection()}
    path = model_dir / "iv_1.json"
    path.write_text(json.dumps(raw))
    assert _model_results(tmp_path) == [{**raw, "engine_provenance": expected_fast()}]
    assert read_model_results(tmp_path) == [raw]
    assert json.loads(path.read_text()) == raw


def test_http_projection_leaves_default_result_exactly_unchanged(tmp_path):
    model_dir = tmp_path / "model_results"
    model_dir.mkdir()
    raw = {"model_id": "iv_1", "model_type": "iv_2sls", "coefficients": {}}
    (model_dir / "iv_1.json").write_text(json.dumps(raw))
    assert _model_results(tmp_path) == [raw]


@pytest.mark.parametrize("actual", [selection(), {"requested": "fast", "used": "reference", "reason": "missing binary"}])
def test_agent_selected_third_model_uses_owner_receipt_without_raw_build(tmp_path, actual):
    project = tmp_path / "project"
    _write_project_run(project, run_id="run-a")
    _write_project_run(project, run_id="run-b")
    root = project / "runs" / "run-a"
    path = root / "model_results" / "ols_1.json"
    raw = json.loads(path.read_text())
    raw["engine_selection"] = actual
    path.unlink()
    (root / "model_results" / "z_selected.json").write_text(json.dumps(raw))
    for index in range(2):
        (root / "model_results" / f"a_{index}.json").write_text(json.dumps({
            "model_id": f"sibling_{index}", "coefficients": {}, "engine_selection": {
                "requested": "fast", "used": "reference", "reason": "sibling must not substitute"}}))
    other = project / "runs" / "run-b" / "model_results" / "ols_1.json"
    other.write_text(json.dumps({**raw, "engine_selection": {"requested": "fast", "used": "reference", "reason": "wrong owner"}}))
    provider = _load_provider_type()(project)
    output = provider.inspect_result_summary(InspectResultSummaryRequest(
        request_id="receipt", owner_run_id="run-a", op_node_id="model:ols_1", active_head_run_id="run-a"))
    expected = expected_fast() if actual["used"] == "arboris-engine" else actual
    assert output["result_summary"]["engine_provenance"] == {"model_id": "ols_1", **expected}
    encoded = json.dumps(output)
    assert "/private/" not in encoded
    assert "wrong owner" not in encoded
    assert "compiler" not in encoded
    # Existing tool budgeting must keep facts or explicitly report the cut.
    for budget in (16384, 2048, 600):
        bounded = _bounded_tool_output(output, budget)
        assert len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))) <= budget
        summary = bounded.get("result_summary")
        if isinstance(summary, dict) and "engine_provenance" in summary:
            assert summary["engine_provenance"] == {"model_id": "ols_1", **expected}
        else:
            assert ("result_summary" in bounded.get("omitted_sections", [])
                    or isinstance(summary, dict) and "engine_provenance" in summary.get("_omitted_keys", []))


def test_agent_default_summary_adds_no_provenance(tmp_path):
    project = tmp_path / "project"
    _write_project_run(project)
    output = _load_provider_type()(project).inspect_result_summary(InspectResultSummaryRequest(
        request_id="default", owner_run_id="run-a", op_node_id="model:ols_1", active_head_run_id="run-a"))
    assert "engine_provenance" not in output["result_summary"]
