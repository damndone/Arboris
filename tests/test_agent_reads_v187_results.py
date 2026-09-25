"""v1.8.7 — can the Agent *read* what this version produces?

Reachability has two halves and the second is easy to forget. Every earlier
check in this version asked whether an Agent could ask for something; these ask
whether it can see the answer.

The gap matters most for the survey design. An Agent that declared one gets back
coefficients and standard errors like any other run, with nothing saying those
standard errors are design-based, what the design degrees of freedom are, or
that the effective sample size is well below the row count. It will speak about
the precision of the estimate, and it will have no way to know.
"""

from __future__ import annotations


def test_agent_and_notebook_forward_explicit_section_selection(monkeypatch, tmp_path):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    from workbench.agent.notebook.evidence import read_persisted_evidence_for_notebook
    from workbench.services import results_service
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        return {"status": "available"}
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", read)
    root = tmp_path / "runs" / "run-1"
    for fn in (read_persisted_evidence_for_agent, read_persisted_evidence_for_notebook):
        assert fn(root, requested_section_ids=("diagnostics",)) == {"status": "available"}
    assert [item["consumer_id"] for item in calls] == ["agent", "notebook"]
    assert all(item["requested_section_ids"] == ("diagnostics",) for item in calls)


def test_agent_summary_preserves_selected_sections_but_not_denied_content():
    from workbench.agent.context_tools import _agent_typed_evidence_projection
    section = {"section_id": "diagnostics", "status": "available", "content": {"kind": "object", "fields": {}}}
    evidence = {"status": "available", "facts": [], "sections": [section],
                "audit": {"selected_section_ids": ["diagnostics"]}, "projection_digest": "digest"}
    projected = _agent_typed_evidence_projection(evidence)
    assert projected["sections"] == [section]
    assert projected["audit"] == evidence["audit"]
    denied = _agent_typed_evidence_projection({**evidence, "status": "blocked"})
    assert denied["sections"] == [] and denied["facts"] == []


def test_agent_notebook_forward_semantic_selection_unchanged(monkeypatch, tmp_path):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    from workbench.agent.notebook.evidence import read_persisted_evidence_for_notebook
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    from workbench.services import results_service
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        return {"status": "available"}
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", read)
    selection = ModelCoefficientSelectionV1("model.two", terms=("C(x)[T.a:b]",))
    for fn in (read_persisted_evidence_for_agent, read_persisted_evidence_for_notebook):
        fn(tmp_path / "runs" / "r1", coefficient_selection=selection)
        fn(tmp_path / "runs" / "r1", requested_section_types=("diagnostics",))
    assert all(c["coefficient_selection"] is selection for c in calls[::2])
    assert all(c["requested_section_types"] == ("diagnostics",) for c in calls[1::2])


def test_agent_notebook_forward_provenance_selection_unchanged(monkeypatch, tmp_path):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    from workbench.agent.notebook.evidence import read_persisted_evidence_for_notebook
    from workbench.services import results_service
    selector = object()  # Adapter routing only; central admission validates its exact type.
    calls = []
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run",
        lambda **kwargs: calls.append(kwargs) or {"status": "available"})
    for reader in (read_persisted_evidence_for_agent, read_persisted_evidence_for_notebook):
        assert reader(tmp_path / "runs" / "r1", provenance_selection=selector) == {"status": "available"}
    assert [call["consumer_id"] for call in calls] == ["agent", "notebook"]
    assert all(call["provenance_selection"] is selector for call in calls)


def test_semantic_node_requires_agreeing_server_model_payload():
    from workbench.agent.context_tools import _coefficient_selection_for_node
    node = {"id": "model:a.b", "kind": "model", "payload_ref": "model_results/a.b.json"}
    selection = _coefficient_selection_for_node(node, terms=("C(x)[a:b]",))
    assert selection.model_id == "a.b" and selection.terms == ("C(x)[a:b]",)
    assert selection.roles == ("estimate",)
    assert _coefficient_selection_for_node({**node, "payload_ref": "model_results/foreign.json"}) is None
    assert _coefficient_selection_for_node({**node, "kind": "test"}) is None

import json
import hashlib
from contextlib import ExitStack
from pathlib import Path

import pytest

from workbench.agent.context_tools import (
    InspectDiagnosticsRequest,
    InspectProjectModelCoefficientsRequest,
    InspectResultSummaryRequest,
    NodeOperationContextProvider,
    _bounded_regression_table,
    _bounded_model_family_evidence,
    _public_requested_model_coefficients,
    _bounded_coefficient_row,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.results_service import read_model_results

FIXTURES = Path(__file__).parent / "fixtures"


def _section_tool_call(provider, arguments, *, chain=False, session="section-review"):
    import asyncio
    from workbench.agent.tools import ToolRegistry
    definitions = (provider.tool_definitions(chain_id="chain-review", session_id="section-review")
                   if chain else provider.global_tool_definitions(session_id="section-review"))
    name = "inspect_result_section" if chain else "inspect_project_result_section"
    definition = next((item for item in definitions if item.tool_id == name), None)
    assert definition is not None, f"{name} must be mounted"
    registry = ToolRegistry()
    registry.register(definition)
    result = asyncio.run(registry.execute({"tool_call_id": "section-review", "tool_id": name,
        "arguments": arguments}, session_id=session))
    return result, definition


def _provenance_tool_call(provider, arguments, *, chain=False, session="provenance-review"):
    import asyncio
    from workbench.agent.tools import ToolRegistry
    definitions = (provider.tool_definitions(chain_id="provenance-chain", session_id="provenance-review")
                   if chain else provider.global_tool_definitions(session_id="provenance-review"))
    name = "inspect_result_provenance" if chain else "inspect_project_result_provenance"
    definition = next((item for item in definitions if item.tool_id == name), None)
    assert definition is not None, f"{name} must be mounted"
    registry = ToolRegistry()
    registry.register(definition)
    return asyncio.run(registry.execute({"tool_call_id": "provenance-review", "tool_id": name,
        "arguments": arguments}, session_id=session)), definition


@pytest.mark.parametrize("chain", [False, True])
def test_provenance_tool_is_registered_as_bounded_read_only_query(tmp_path, chain):
    provider = NodeOperationContextProvider(tmp_path)
    definitions = (provider.tool_definitions(chain_id="provenance-chain", session_id="provenance-review")
                   if chain else provider.global_tool_definitions(session_id="provenance-review"))
    name = "inspect_result_provenance" if chain else "inspect_project_result_provenance"
    tool = next((item for item in definitions if item.tool_id == name), None)
    assert tool is not None, "Agent must discover the bounded provenance query"
    assert tool.side_effect == "none" and tool.max_output_budget == 8192
    assert tool.input_schema["additionalProperties"] is False
    assert {"owner_run_id", "model_id", "roles"} <= set(tool.input_schema["required"])
    assert not {"path", "owner", "destination", "fact_ids"} & set(tool.input_schema["properties"])


@pytest.mark.parametrize("attack", ["path", "authority", "role", "session", "foreign_node"])
def test_provenance_tool_rejects_unsafe_selectors_before_read(tmp_path, monkeypatch, attack):
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run",
        lambda **kwargs: pytest.fail("invalid query reached the owner reader"))
    args = {"owner_run_id": "r1", "model_id": "ols_1", "roles": ["coefficient_variance_source"], "terms": ["x"]}
    if attack == "path": args["owner_run_id"] = "../r1"
    if attack == "authority": args["owner"] = "forged"
    if attack == "role": args["roles"] = ["arbitrary.secret"]
    if attack == "foreign_node":
        args.update(op_node_id="model:other", active_head_run_id="r1")
        monkeypatch.setattr(provider, "_tool_active_head", lambda *a: "r1")
        monkeypatch.setattr(provider, "_read_node_snapshot", lambda **kw:
            ({"owner_run_id": "r1"}, {"id": "model:other", "kind": "model",
             "payload_ref": "model_results/other.json"}, {}))
    result, _ = _provenance_tool_call(provider, args, chain=attack == "foreign_node",
        session="wrong" if attack == "session" else "provenance-review")
    assert not result.ok


def test_provenance_tool_never_truncates_source_warnings_to_fit(tmp_path, monkeypatch):
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    wire = {"status": "available", "facts": [], "semantic_selection": {
        "warnings": ["DO NOT DROP " + "w" * 8100]}, "receipt": {"proof": "kept"}}
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", lambda **kwargs: wire)
    result, _ = _provenance_tool_call(provider,
        {"owner_run_id": "r1", "model_id": "ols_1", "terms": ["x"], "roles": ["coefficient_warnings"]})
    assert result.ok
    assert result.output == {"status": "unavailable", "scope": "semantic_selection",
        "read_completeness": "PARTIAL", "reason_code": "tool_output_budget_exceeded"}
    assert "DO NOT DROP" not in json.dumps(result.output)


@pytest.mark.parametrize("wire_bytes,wrapped", [(8192, True), (8193, True), (8192, False), (8193, False)])
def test_provenance_tool_utf8_exact_budget_boundary(tmp_path, monkeypatch, wire_bytes, wrapped):
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    wire = {"status": "available", "facts": [], "semantic_selection": {"warnings": [""]},
            "receipt": {"proof": "must remain intact"}}
    payload = {"scope": "semantic_selection", "read_completeness": "PARTIAL",
               "owner_run_id": "r1", "persisted_evidence": wire}
    size = lambda value: len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    envelope = {"ok": True, "output": payload, "error": None}
    needed = wire_bytes - size(envelope if wrapped else payload)
    fragment = "统计🧪"
    width = len(fragment.encode("utf-8"))
    wire["semantic_selection"]["warnings"][0] = fragment * (needed // width) + "x" * (needed % width)
    assert size(envelope if wrapped else payload) == wire_bytes
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", lambda **kwargs: wire)
    result, _ = _provenance_tool_call(provider, {"owner_run_id": "r1", "model_id": "ols_1",
        "terms": ["x"], "roles": ["coefficient_warnings"]})
    if wrapped and wire_bytes == 8192:
        assert result.ok and result.output == payload
        assert size(result.to_payload()) == 8192
    elif not wrapped and wire_bytes == 8193:
        assert result.ok
        assert result.output == {"status": "unavailable", "scope": "semantic_selection",
            "read_completeness": "PARTIAL", "reason_code": "tool_output_budget_exceeded"}
    else:
        # A bare 8192-byte output needs 8231 bytes with ToolResult's envelope.
        # Preserve this old input as a rejection case; do not raise the limit.
        assert not result.ok and result.output is None
        assert result.error == "tool_output_budget_exceeded"
    assert size(result.to_payload()) <= 8192


def _provenance_values(evidence):
    """Test-only decode; every number must refer to an actually delivered fact."""
    facts = {fact["fact_id"]: fact["value"] for fact in evidence["facts"]}
    def value(node):
        if node["kind"] == "fact":
            return facts[node["fact_id"]]
        if node["kind"] == "list":
            return [value(child) for child in node["items"]]
        if node["kind"] == "object":
            return {key: value(child) for key, child in node["fields"].items()}
        assert node["kind"] == "text"
        return node["value"]
    semantic = evidence["semantic_selection"]
    assert semantic["scope"] == "selected_only" and semantic["whole_result_read"] is False
    return {(binding["term"], binding["role"]): value(binding["value"]) for binding in semantic["bindings"]}


def test_real_provenance_tool_and_notebook_keep_bound_qualifications(tmp_path):
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.services import results_service
    from workbench.agent.notebook.evidence import read_persisted_evidence_for_notebook
    from workbench.evidence.consumer_adapters import ModelProvenanceSelectionV1
    run = tmp_path / "project" / "runs" / "provenance-real"
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
        "coefficients": {"x": {"estimate": 1.25, "std_error": .2, "p_value": .125,
            "variance_source": "survey_design", "source_id": "model_results.ols_1.coefficients.x",
            "warnings": ["Design-based uncertainty; no causal interpretation."]}},
        "survey_design": {"variance_method": "jackknife", "degf": 12}}
    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary={}) as case:
        results_service.configure_report_evidence_persistence(case.owner)
        try:
            provider = NodeOperationContextProvider(run.parent.parent)
            roles = ("survey_variance_method", "survey_degf")
            result, definition = _provenance_tool_call(provider,
                {"owner_run_id": run.name, "model_id": "ols_1", "roles": list(roles)})
            assert result.ok and "persisted_evidence" in result.output, result
            evidence = result.output["persisted_evidence"]
            assert evidence["status"] == "available", evidence
            assert result.output["read_completeness"] == "PARTIAL"
            assert evidence["receipt"] and evidence["projection_digest"]
            assert evidence["identity"]["run_id"] == run.name
            assert _provenance_values(evidence) == {(None, "survey_variance_method"): "jackknife",
                (None, "survey_degf"): 12}
            notebook = read_persisted_evidence_for_notebook(run,
                provenance_selection=ModelProvenanceSelectionV1("ols_1", roles=roles))
            assert notebook["status"] == "available" and notebook["receipt"]
            assert _provenance_values(notebook) == _provenance_values(evidence)
            assert notebook["envelope_digest"] == evidence["envelope_digest"]
            assert len(json.dumps(result.output, ensure_ascii=False, sort_keys=True).encode()) <= definition.max_output_budget
            coefficient, _ = _provenance_tool_call(provider, {"owner_run_id": run.name,
                "model_id": "ols_1", "terms": ["x"], "roles": ["coefficient_variance_source",
                    "coefficient_source_id", "coefficient_warnings"]})
            assert coefficient.ok and "persisted_evidence" in coefficient.output, coefficient
            qualification = _provenance_values(coefficient.output["persisted_evidence"])
            assert qualification[("x", "coefficient_variance_source")] == "survey_design"
            assert qualification[("x", "coefficient_source_id")] == "model_results.ols_1.coefficients.x"
            assert qualification[("x", "coefficient_warnings")] == packet["coefficients"]["x"]["warnings"]
            (run / "model_results" / "ols_1.json").write_text("changed source")
            denied, _ = _provenance_tool_call(provider,
                {"owner_run_id": run.name, "model_id": "ols_1", "roles": list(roles)})
            assert denied.ok and denied.output["persisted_evidence"]["status"] == "unavailable"
            assert denied.output["persisted_evidence"]["facts"] == []
        finally:
            results_service.configure_report_evidence_persistence(None)


@pytest.mark.parametrize("chain", [False, True])
def test_generic_section_tool_live_enum_metadata_and_single_payload(tmp_path, monkeypatch, chain):
    from workbench.contracts.evidence.result_sections import SECTION_FIELDS
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    calls = []
    wire = {"status": "available", "facts": [], "sections": [{"section_type": "survey_design",
        "content": {"method": "jackknife"}}], "projection_digest": "canonical", "audit": {}}
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run",
        lambda **kwargs: calls.append(kwargs) or wire)
    identities = []
    monkeypatch.setattr(provider, "_tool_active_head", lambda chain_id, requested: "server-head")
    monkeypatch.setattr(provider, "_read_node_snapshot", lambda **kwargs:
        (identities.append(kwargs) or {"owner_run_id": "r1"}, {"id": "model:a"}, {}))
    args = {"owner_run_id": "r1", "section_type": "survey_design"}
    if chain:
        args.update(op_node_id="model:a", active_head_run_id="requested-head")
    result, definition = _section_tool_call(provider, args, chain=chain)
    assert result.ok, result
    assert definition.input_schema["properties"]["section_type"]["enum"] == sorted(SECTION_FIELDS)
    assert result.output["scope"] == "owner_run"
    assert result.output["persisted_evidence"] == wire
    assert "facts" not in result.output and "sections" not in result.output
    assert calls[0]["consumer_id"] == "agent"
    assert calls[0]["requested_section_types"] == ("survey_design",)
    assert calls[0]["run_id"] == "r1"
    if chain:
        assert identities[0]["active_head_run_id"] == "server-head"
        assert identities[0]["op_node_id"] == "model:a"


@pytest.mark.parametrize("attack", ["unknown", "path", "authority", "session", "stale"])
def test_generic_section_tool_rejects_before_evidence_read(tmp_path, monkeypatch, attack):
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run",
        lambda **kwargs: pytest.fail("rejected request reached evidence reader"))
    args = {"owner_run_id": "r1", "section_type": "survey_design"}
    if attack == "unknown": args["section_type"] = "unknown"
    if attack == "path": args["owner_run_id"] = "../r1"
    if attack == "authority": args["owner"] = "forged"
    if attack == "stale":
        args.update(op_node_id="model:a", active_head_run_id="old")
        def stale(*args, **kwargs):
            raise ValueError("context_stale")
        monkeypatch.setattr(provider, "_tool_active_head", stale)
    result, _ = _section_tool_call(provider, args, chain=attack == "stale",
        session="wrong" if attack == "session" else "section-review")
    assert not result.ok


def test_generic_section_tool_whole_payload_budget_is_atomic(tmp_path, monkeypatch):
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    wire = {"status": "available", "facts": [{"value": 1.25}], "sections": [], "padding": "x" * 8050}
    assert len(json.dumps(wire, ensure_ascii=False, sort_keys=True).encode()) < 8192
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", lambda **kwargs: wire)
    result, _ = _section_tool_call(provider, {"owner_run_id": "r1", "section_type": "survey_design"})
    assert result.ok
    assert result.output["status"] == "unavailable"
    assert result.output["reason_code"] == "tool_output_budget_exceeded"
    assert "persisted_evidence" not in result.output and "facts" not in result.output
    assert len(json.dumps(result.output).encode()) <= 8192


def test_generic_section_tool_real_central_projection_and_tamper(quality2_bound_agent):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    provider, run = quality2_bound_agent
    expected = read_persisted_evidence_for_agent(run, requested_section_types=("regression_table",))
    result, _ = _section_tool_call(provider, {"owner_run_id": "r1", "section_type": "regression_table"})
    assert result.ok and expected["status"] == "available"
    assert result.output["persisted_evidence"] == expected
    (run / "model_results" / "b.json").write_bytes(b"tampered")
    result, _ = _section_tool_call(provider, {"owner_run_id": "r1", "section_type": "regression_table"})
    denied = result.output["persisted_evidence"]
    assert denied["status"] == "unavailable" and not denied["facts"]


def test_generic_section_marginal_tool_preserves_central_fields(tmp_path, monkeypatch):
    from workbench.agent.context_tools import InspectProjectLinearInteractionEffectsRequest
    from workbench.services import results_service
    provider = NodeOperationContextProvider(tmp_path)
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    wire = {"status": "available", "facts": [{"statistic_id": "estimate", "value": 0.3}],
        "sections": [{"section_type": "marginal_effects"}], "audit": {"selected_section_ids": ["marginal_effects"]}}
    calls = []
    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", lambda **kwargs: calls.append(kwargs) or wire)
    result = provider.inspect_project_linear_interaction_effects(InspectProjectLinearInteractionEffectsRequest(
        effects=({"run_id": "r1", "focal_term": "x", "interaction_term": "x:z", "moderator_column": "z"},)))
    assert result["effects"][0]["persisted_evidence"] == wire
    assert result["effects"][0]["scope"] == "owner_run"
    assert "marginal_effect" not in result["effects"][0]
    assert calls[0]["requested_section_types"] == ("marginal_effects",)


@pytest.mark.parametrize("section_type", ["survey_design", "marginal_effects", "interpretation_constraints"])
def test_generic_section_tool_real_producer_survey_marginal_and_metadata(tmp_path, section_type):
    from tests.test_v189_evidence_report_boundary import _produced_report
    from workbench.services import results_service
    from workbench.agent.context_tools import read_persisted_evidence_for_agent

    run = tmp_path / "project" / "runs" / "section-real"
    packet = {"model_id": "ols_1", "model_type": "ols", "nobs": 20,
        "coefficients": {"x": {"estimate": 1.25, "std_error": 0.2, "p_value": 0.125}},
        "survey_design": {"variance_method": "jackknife", "degf": 12},
        "marginal_effects": [{"term": "x", "estimate": 0.3, "p_value": 0.02}],
        "marginal_effects_method": "average"}
    summary = {"narrative_contract": {"constraints": {"causal_language_allowed": False},
        "required_mentions": ["Do not infer causality"], "forbidden_claims": []}}
    with _produced_report(run, model_results={"ols_1": packet}, diagnostic_summary=summary) as case:
        results_service.configure_report_evidence_persistence(case.owner)
        try:
            provider = NodeOperationContextProvider(run.parent.parent)
            expected = read_persisted_evidence_for_agent(run, requested_section_types=(section_type,))
            assert expected["status"] == "available", expected
            result, definition = _section_tool_call(provider, {"owner_run_id": run.name, "section_type": section_type})
            assert result.ok and "persisted_evidence" in result.output, (section_type, result)
            wire = result.output["persisted_evidence"]
            assert wire == expected and wire["status"] == "available"
            assert len(json.dumps(result.output, ensure_ascii=False, sort_keys=True).encode("utf-8")) <= definition.max_output_budget
            assert [section["section_type"] for section in wire["sections"]] == [section_type]
            if section_type == "interpretation_constraints":
                assert wire["facts"] == []
                assert "Do not infer causality" in json.dumps(wire["sections"])
            if section_type == "marginal_effects":
                assert any(fact["value"] == 0.3 for fact in wire["facts"])
            if section_type == "survey_design":
                assert "jackknife" in json.dumps(wire["sections"])
        finally:
            results_service.configure_report_evidence_persistence(None)


@pytest.fixture
def quality2_bound_agent(tmp_path):
    from tests.test_v189_structured_consumer_projection import committed, owner_for
    from workbench.graph_model import Graph, Node, NodeKind, SCHEMA_VERSION
    from workbench.graph_store import GraphStore
    from workbench.services import results_service as service
    with committed(tmp_path, regression=True, term="C(café)[T.a:b]",
                   artifact_paths=("model_results/a.json", "model_results/b.json")) as (_, run, _, _, kwargs, args):
        node = Node(id="model:a", kind=NodeKind.MODEL, display_label="model a",
            created_at="2026-09-14T00:00:00Z", parent_stage_id=None, branch_id="main",
            payload_ref="model_results/a.json")
        GraphStore(run.parent).write(Graph(schema_version=SCHEMA_VERSION, run_id="r1",
            nodes={node.id: node}, edges={}, branches={}))
        service.configure_report_evidence_persistence(owner_for(kwargs, args))
        try:
            yield NodeOperationContextProvider(run.parent.parent), run
        finally:
            service.configure_report_evidence_persistence(None)


def test_quality2_real_service_nfc_term_reaches_project_agent(quality2_bound_agent):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    provider, run = quality2_bound_agent
    term = "C(cafe\u0301)[T.a:b]"
    wire = read_persisted_evidence_for_agent(run, coefficient_selection=ModelCoefficientSelectionV1("a", terms=(term,)))
    assert wire["status"] == "available" and wire["semantic_selection"]["terms"] == ["C(café)[T.a:b]"]
    result = provider.inspect_project_model_coefficients(InspectProjectModelCoefficientsRequest(run_ids=("r1",), terms=(term,)))
    model = result["models"][0]
    assert model["projection_status"] == "available", model
    assert "missing_terms" not in model
    assert model["coefficients"][0]["term"] == "C(café)[T.a:b]"
    assert model["coefficients"][0]["estimate"] == wire["facts"][0]["value"]
    assert model["coefficients"][0]["fact_id"] == wire["facts"][0]["fact_id"]


@pytest.mark.parametrize("path", ["summary", "project"])
@pytest.mark.parametrize("failure,reason", [("source_tamper", "EVIDENCE_DEPENDENCY_MISMATCH"),
                                           ("section_policy", "section_type_unavailable")])
def test_quality2_real_service_denial_cause_and_safe_audit(quality2_bound_agent, path, failure, reason):
    from workbench.agent.context_tools import read_persisted_evidence_for_agent, _agent_typed_evidence_projection
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    provider, run = quality2_bound_agent
    selection = ModelCoefficientSelectionV1("a")
    assert read_persisted_evidence_for_agent(run, coefficient_selection=selection)["status"] == "available"
    if failure == "source_tamper":
        target = run / "model_results" / "b.json"
        assert target.read_bytes() == b"b"
        target.write_bytes(b"changed parent dependency")
    query = {"coefficient_selection": selection} if failure == "source_tamper" else {"requested_section_types": ("statistical_tests",)}
    wire = read_persisted_evidence_for_agent(run, **query)
    assert wire["status"] == "unavailable" and wire["audit"]["restriction_reason"] == reason
    if path == "summary":
        result = _agent_typed_evidence_projection(wire)
    else:
        evidence, facts, result = provider._central_agent_section("r1",
            statistic_ids=("model_coefficient",) if failure == "source_tamper" else ("statistical_test",))
        assert not evidence and not facts
    assert result["unavailable_reason"] == reason
    assert result["audit"]["restriction_reason"] == reason
    assert result["audit"]["destination"] == wire["audit"]["destination"]
    assert result["audit"]["policy_ref"] == wire["audit"]["policy_ref"]
    assert result["audit"]["token_budget"] == wire["audit"]["token_budget"]
    assert not result.get("facts") and not result.get("sections") and not result.get("semantic_selection")
    assert not result.get("receipt") and not result.get("projection_digest")


@pytest.mark.parametrize("path", ["summary", "project"])
def test_quality2_denied_audit_drops_contents_selectors_and_unsafe_extras(quality2_bound_agent, path):
    from workbench.agent.context_tools import (
        read_persisted_evidence_for_agent, _agent_typed_evidence_projection, _agent_section_unavailable,
    )
    from workbench.evidence.consumer_adapters import ModelCoefficientSelectionV1
    _, run = quality2_bound_agent
    (run / "model_results" / "b.json").write_bytes(b"changed")
    wire = read_persisted_evidence_for_agent(run, coefficient_selection=ModelCoefficientSelectionV1("a"))
    assert wire["status"] == "unavailable"
    secret = "DENIED_CONTENT_MUST_NOT_SURVIVE"
    wire["audit"].update({"sections": [secret], "facts": [secret], "raw_path": secret,
        "requested_fact_ids": [secret], "selected_section_ids": [secret], "semantic_selection": secret,
        "egress_receipt_id": secret, "extra": {"payload": secret}})
    wire.update({"facts": [secret], "sections": [secret], "semantic_selection": secret,
                 "completeness_status": {"unsafe": secret}, "receipt": secret, "projection_digest": secret})
    if path == "summary":
        result = _agent_typed_evidence_projection(wire)
    else:
        result = _agent_section_unavailable("r1", wire["audit"]["restriction_reason"], audit=wire["audit"])
    assert result["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert set(result["audit"]) == {"restriction_reason", "destination", "policy_ref",
                                    "token_budget", "row_budget", "raw_rows_rejected"}
    assert secret not in json.dumps(result)
    result["audit"]["policy_ref"]["logical_id"] = "changed"
    assert wire["audit"]["policy_ref"]["logical_id"] != "changed"


@pytest.mark.parametrize("top_reason,expected", [
    ("EVIDENCE_OWNER_CONTEXT_MISMATCH", "EVIDENCE_OWNER_CONTEXT_MISMATCH"),
    (None, "EVIDENCE_DEPENDENCY_MISMATCH"),
    ({"unsafe": "not a cause"}, "EVIDENCE_DEPENDENCY_MISMATCH"),
])
def test_quality2_top_level_cause_precedence_does_not_erase_audit(top_reason, expected):
    from workbench.agent.context_tools import _agent_typed_evidence_projection
    result = _agent_typed_evidence_projection({"status": "unavailable", "reason_code": top_reason,
        "audit": {"restriction_reason": "EVIDENCE_DEPENDENCY_MISMATCH"}})
    assert result["unavailable_reason"] == expected
    assert result["audit"] == {"restriction_reason": "EVIDENCE_DEPENDENCY_MISMATCH"}


def test_quality2_invalid_audit_values_are_not_copied():
    from workbench.agent.context_tools import _agent_typed_evidence_projection
    result = _agent_typed_evidence_projection({"status": "blocked", "reason_code": "/private/secret",
        "audit": {"restriction_reason": "\nunsafe", "destination": "secret", "row_budget": True,
                  "token_budget": 65537, "raw_rows_rejected": "true", "policy_ref": {"extra": "secret"}}})
    assert result["unavailable_reason"] == "AGENT_TYPED_EVIDENCE_UNAVAILABLE"
    assert result["audit"] == {}
    assert "secret" not in json.dumps(result)


@pytest.fixture(autouse=True)
def admitted_workflow_evidence(monkeypatch):
    """Keep real host/store authority live through each Agent consumer read."""
    from fastapi import FastAPI
    from tests.test_v189_evidence_envelope import _admit_store, _authorized_registry
    from tests.test_v189_report_owner_factory import _factory_type
    from workbench.app import configure_report_evidence_owner_factory

    workflow = run_workflow
    with ExitStack() as contexts:
        def admitted_run(project_root, sources, **kwargs):
            scope = f"scope:agent-test:{Path(project_root).name}"
            registry, host = _authorized_registry(scope)
            evidence_root = Path(project_root) / "workbench" / "evidence"
            evidence_root.mkdir(parents=True, exist_ok=True)
            store = contexts.enter_context(_admit_store(evidence_root, registry))
            factory = _factory_type().from_host(
                store, registry,
                actor_ref="actor:agent-test",
                project_ref=f"project:{Path(project_root).name}",
                session_ref="session:agent-test",
                scope_ref=scope,
                canonical_project_root=project_root,
                authority_handle=host.channel,
            )
            execution_app = FastAPI()
            configure_report_evidence_owner_factory(factory, app_instance=execution_app)
            return workflow(project_root, sources, app_instance=execution_app, **kwargs)

        monkeypatch.setattr(__name__ + ".run_workflow", admitted_run)
        yield


def _run(tmp_path: Path, name: str, fixture: str, **kwargs):
    source = tmp_path / f"{name}.csv"
    source.write_text((FIXTURES / fixture).read_text())
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    return project, outcome["run_id"]


def _summary(project, run_id: str, node: str) -> dict:
    provider = NodeOperationContextProvider(project.root)
    return provider.inspect_result_summary(
        InspectResultSummaryRequest(
            request_id="read-test", owner_run_id=run_id,
            op_node_id=node, active_head_run_id=run_id,
        )
    )


def _diagnostics(project, run_id: str, node: str) -> dict:
    provider = NodeOperationContextProvider(project.root)
    return provider.inspect_diagnostics(
        InspectDiagnosticsRequest(
            request_id="diagnostics-test", owner_run_id=run_id,
            op_node_id=node, active_head_run_id=run_id,
        )
    )


def test_agent_admitted_coefficients_are_available_and_match_persisted_numbers(tmp_path):
    project, run_id = _run(
        tmp_path, "typed-positive", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
    )
    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is True, summary
    assert summary["authority"] == "server-owned"
    assert summary["source"] == "persisted-typed-evidence"
    assert summary["receipt"]
    assert summary["projection_digest"]
    assert summary["facts"]
    persisted = read_model_results(project.root / "runs" / run_id)[0]
    assert {fact["estimand_id"] for fact in summary["facts"]} == set(persisted["coefficients"])
    for fact in summary["facts"]:
        assert fact["statistic_id"] == "model_coefficient"
        coefficient = persisted["coefficients"][fact["estimand_id"]]
        assert fact["value"] == coefficient["estimate"]
        assert fact["standard_error"] == coefficient["std_error"]
    requested = NodeOperationContextProvider(project.root).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=(run_id,), terms=("x1",)))
    assert requested["models"][0]["model_id"] == "ols_1"
    assert [c["term"] for c in requested["models"][0]["coefficients"]] == ["x1"]
    assert requested["models"][0]["coefficients"][0]["estimate"] == persisted["coefficients"]["x1"]["estimate"]


def test_the_agent_can_see_that_standard_errors_are_design_based(tmp_path):
    """Otherwise it will describe the precision of an interval it cannot read."""
    project, run_id = _run(
        tmp_path, "svy", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    provider = NodeOperationContextProvider(project.root)
    for field in ("degf", "variance_method", "design_effect", "effective_sample_size"):
        role = f"survey_{field}"
        result, _ = _provenance_tool_call(provider,
            {"owner_run_id": run_id, "model_id": "ols_1", "roles": [role]})
        assert result.ok and "persisted_evidence" in result.output, result
        evidence = result.output["persisted_evidence"]
        assert evidence["status"] == "available" and evidence["receipt"], evidence
        values = _provenance_values(evidence)
        assert (None, role) in values, f"the Agent cannot read {field}"
        assert any(binding["section_id"] == "survey_design" for binding in evidence["semantic_selection"]["bindings"])


def test_agent_projection_preserves_survey_provenance_and_replicate_metadata(tmp_path):
    """A bounded Agent read must retain the survey qualification per coefficient."""
    replicate_columns = [f"repw{i:02d}" for i in range(1, 13)]
    project, run_id = _run(
        tmp_path, "svy-replicate", "survey/design_with_replicate_weights.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
        survey_replicate_type="provided", survey_replicate_weights=replicate_columns,
    )
    provider = NodeOperationContextProvider(project.root)
    design = {}
    # Explicit bounded queries replace the removed raw summary shape; retain
    # every original positive assertion and do not reinterpret unavailable.
    for field in ("replicates_attempted", "replicates_succeeded", "replicates_failed", "replicate_failure_reasons"):
        role = f"survey_{field}"
        result, _ = _provenance_tool_call(provider,
            {"owner_run_id": run_id, "model_id": "ols_1", "roles": [role]})
        assert result.ok and "persisted_evidence" in result.output, result
        evidence = result.output["persisted_evidence"]
        assert evidence["status"] == "available" and evidence["receipt"], evidence
        assert result.output["read_completeness"] == "PARTIAL"
        design[field] = _provenance_values(evidence)[(None, role)]
    assert design["replicates_attempted"] == 12
    assert design["replicates_succeeded"] + design["replicates_failed"] == 12
    assert isinstance(design["replicate_failure_reasons"], dict)

    coefficient_roles = ["coefficient_variance_source", "coefficient_source_id", "coefficient_warnings"]
    request = {"owner_run_id": run_id, "model_id": "ols_1", "terms": ["x1"], "roles": coefficient_roles}
    scoped, _ = _provenance_tool_call(provider, {**request,
        "op_node_id": "model:ols_1", "active_head_run_id": run_id}, chain=True)
    assert scoped.ok and "persisted_evidence" in scoped.output, scoped
    scoped_evidence = scoped.output["persisted_evidence"]
    assert scoped_evidence["status"] == "available" and scoped_evidence["receipt"], scoped_evidence
    values = _provenance_values(scoped_evidence)
    coefficient = {field: values[("x1", f"coefficient_{field}")] for field in ("variance_source", "source_id", "warnings")}
    assert coefficient["variance_source"] == "survey_design"
    assert coefficient["source_id"] == "model_results.ols_1.coefficients.x1"
    assert isinstance(coefficient["warnings"], list)

    requested, _ = _provenance_tool_call(provider, request)
    assert requested.ok and "persisted_evidence" in requested.output, requested
    requested_evidence = requested.output["persisted_evidence"]
    assert requested_evidence["status"] == "available" and requested_evidence["receipt"]
    values = _provenance_values(requested_evidence)
    projected = {field: values[("x1", f"coefficient_{field}")] for field in ("variance_source", "source_id", "warnings")}
    assert projected["variance_source"] == "survey_design"
    assert projected["source_id"] == "model_results.ols_1.coefficients.x1"
    assert isinstance(projected["warnings"], list)


def test_agent_rejects_tampered_model_result_before_projection(tmp_path):
    """A valid JSON file is not valid evidence once its indexed hash changes."""
    project, run_id = _run(
        tmp_path, "tampered", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    result_path = project.root / "runs" / run_id / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["coefficients"]["x1"]["estimate"] = 999.0
    result_path.write_text(json.dumps(payload))

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["status"] == "unavailable"
    assert summary["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert summary["facts"] == [] and summary["sections"] == []


def test_invalid_server_owned_model_artifact_omits_optional_result_and_diagnostic_fields(
    tmp_path,
):
    """Invalid real-run evidence keeps typed reason without invented sections."""
    project, run_id = _run(
        tmp_path,
        "invalid-agent-result",
        "survey/design.csv",
        model_type="ols",
        y="y",
        x=["x1", "x2"],
    )
    result_path = project.root / "runs" / run_id / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["coefficients"]["x1"]["estimate"] = 999.0
    result_path.write_text(json.dumps(payload))

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    diagnostics = _diagnostics(project, run_id, "model:ols_1")["diagnostics"]
    for projection in (summary, diagnostics):
        assert projection["available"] is False
        assert projection["status"] == "unavailable"
        assert projection["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
        assert projection["facts"] == [] and projection["sections"] == []
        assert "survey_design" not in projection
        assert "regression_table" not in projection
        assert "marginal_effects" not in projection


def test_agent_rejects_foreign_binding_even_when_index_hash_is_rewritten(tmp_path):
    from workbench.artifacts import sha256_file, write_json

    project, run_id = _run(
        tmp_path, "foreign-binding", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    result_path = run_root / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["result_binding"]["project_root"] = "/foreign/project"
    write_json(result_path, payload)

    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    for record in index["artifacts"]:
        if record.get("artifact_id") == "ols_1":
            record["sha256"] = sha256_file(result_path)
    write_json(index_path, index)

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert summary["facts"] == [] and summary["sections"] == []


def test_agent_requires_server_index_and_rejects_synchronized_digest_forgery(tmp_path):
    project, run_id = _run(
        tmp_path, "tamper", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    result_path = run_root / "model_results" / "ols_1.json"
    payload = json.loads(result_path.read_text())
    payload["coefficients"]["x1"]["estimate"] = 123.0
    result_path.write_text(json.dumps(payload))
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text())
    for record in index["artifacts"]:
        if record.get("artifact_id") == "ols_1":
            record["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert summary["facts"] == [] and summary["sections"] == []


def test_agent_rejects_legacy_model_results_without_index(tmp_path):
    project, run_id = _run(
        tmp_path, "missing-index", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
    )
    run_root = project.root / "runs" / run_id
    (run_root / "artifacts_index.json").unlink()

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is False
    assert summary["unavailable_reason"] == "EVIDENCE_DEPENDENCY_UNAVAILABLE"
    assert summary["facts"] == [] and summary["sections"] == []


def test_agent_coefficient_projection_bounds_huge_values_and_provenance():
    """Agent output must be typed unavailable rather than serializing huge values."""
    result = {
        "model_id": "ols_1",
        "model_label": "Survey OLS",
        "coefficients": {
            "x": {
                "estimate": 10**400,
                "std_error": 10**400,
                "p_value": 10**400,
                "ci_lower": 10**400,
                "ci_upper": 10**400,
                "variance_source": "v" * 2000,
                "source_id": "s" * 2000,
                "warnings": ["w" * 2000] * 100,
            }
        },
        "nobs": 10**400,
        "df_model": -1,
        "df_resid": 10**400,
        "exposure_col": 10**400,
        "sampling_weight": 10**400,
    }

    projected_model = _public_requested_model_coefficients(
        run_id="run-1", result=result, requested_terms=("x",)
    )
    projected = projected_model["coefficients"][0]
    assert projected["projection_status"] == "unavailable"
    assert projected["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"
    assert "estimate" not in projected
    assert projected["projection_status"] == "unavailable"
    assert projected["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"
    assert "nobs" not in projected_model
    assert "df_model" not in projected_model
    assert "df_resid" not in projected_model
    assert projected_model["model_metadata_status"] == "unavailable"
    assert "exposure_col" not in projected_model
    assert "sampling_weight" not in projected_model
    assert len(projected["source_id"]) <= 128
    assert len(projected["variance_source"]) <= 128
    assert len(projected["warnings"]) <= 16
    assert all(len(item) <= 128 for item in projected["warnings"])

    table_cell = _bounded_regression_table([result])["rows"][0]["models"]["ols_1"]
    assert table_cell["projection_status"] == "unavailable"
    assert table_cell["unavailable_reason"] == "AGENT_COEFFICIENT_VALUE_INVALID"


@pytest.mark.parametrize("bad_p", [-1, 2, 10**400, float("nan"), float("inf")])
def test_agent_regression_and_diagnostic_projections_do_not_copy_invalid_survey_scalars(bad_p):
    result = {
        "model_id": "ols_1",
        "model_type": "ols",
        "nobs": 10**400,
        "survey_design": {
            "n_obs": -1,
            "n_psu": 2.5,
            "degf": -2,
            "residual_degf": 10**400,
            "variance_method": "linearization",
            "source_id": "run-1:model_results.ols_1",
        },
        "coefficients": {
            "x": {
                "estimate": 1.0,
                "std_error": -1,
                "p_value": bad_p,
                "ci_lower": 2.0,
                "ci_upper": 1.0,
                "variance_source": "survey_design",
                "source_id": "run-1:model_results.ols_1.coefficients.x",
                "warnings": ["SURVEY_INVALID"],
            }
        },
    }

    table = _bounded_regression_table([result])
    model = table["models"][0]
    cell = table["rows"][0]["models"]["ols_1"]
    assert "nobs" not in model
    assert model["projection_status"] == "unavailable"
    assert model["survey_design"]["projection_status"] == "unavailable"
    assert "n_obs" not in model["survey_design"]
    assert "degf" not in model["survey_design"]
    assert cell["projection_status"] == "unavailable"
    assert "p_value" not in cell
    assert "std_error" not in cell
    assert "ci_lower" not in cell
    assert "ci_upper" not in cell
    assert cell["source_id"] == "run-1:model_results.ols_1.coefficients.x"

    diagnostic = _bounded_coefficient_row({"variable": "x", **result["coefficients"]["x"]})
    assert diagnostic["projection_status"] == "unavailable"
    assert "p_value" not in diagnostic
    assert "std_error" not in diagnostic


def test_agent_result_summary_bounds_raw_identity_and_metrics(tmp_path):
    """Summary metadata must cross the same finite/bounds/status contract."""
    from workbench.agent.context_tools import _bounded_result_summary

    summary = {
        "model_identity": {
            "model_family": "ols",
            "model_label": "Survey OLS",
            "y_variable": "y",
            "n_observations": 10**400,
            "x_variable_count": -1,
        },
        "model_quality": {
            "metrics": {
                "aic": 10**400,
                "p_value": 2,
                "ok": 1.25,
            },
            "primary_metric_keys": ["aic", "p_value", "ok"],
        },
    }

    projected = _bounded_result_summary(
        summary,
        summary_status="complete",
        preview={"available": True},
        model_results=[],
        run_root=tmp_path,
    )

    assert projected["available"] is False
    assert projected["summary_projection_status"] == "unavailable"
    assert projected["model_identity"].get("n_observations") is None
    assert projected["metrics"].get("aic") is None
    assert projected["metrics"].get("p_value") is None
    assert projected["metrics"]["ok"] == 1.25
    assert projected["unavailable_reason"] == "AGENT_RESULT_SUMMARY_INVALID"


def test_agent_rejects_diagnostic_summary_when_file_and_index_are_tampered_together(tmp_path):
    """An index rewrite must not make a changed diagnostic payload authoritative."""
    from workbench.agent.context_tools import _read_diagnostic_summary
    from workbench.artifacts import sha256_file

    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    payload = {
        "run_id": "run-1",
        "model_identity": {"model_family": "ols", "n_observations": 10},
        "run_status": {"report_render_status": "complete"},
    }
    unsigned = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["summary_binding"] = {
        "artifact_id": "diagnostic_summary",
        "run_id": "run-1",
        "status": "complete",
        "provenance": "server",
        "payload_sha256": hashlib.sha256(unsigned.encode()).hexdigest(),
    }
    summary_path = run_root / "diagnostic_summary.json"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "artifact_id": "diagnostic_summary",
                        "artifact_type": "metadata",
                        "path": "diagnostic_summary.json",
                        "sha256": sha256_file(summary_path),
                        "step": "diagnostics",
                        "inputs": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    tampered = dict(payload)
    tampered["model_identity"] = {"model_family": "ols", "n_observations": 999}
    summary_path.write_text(json.dumps(tampered), encoding="utf-8")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["artifacts"][0]["sha256"] = sha256_file(summary_path)
    index_path.write_text(json.dumps(index), encoding="utf-8")

    summary, status = _read_diagnostic_summary(run_root)
    assert summary is None
    assert status == "artifact_invalid"


def test_agent_diagnostics_rejects_synchronized_committed_input_tamper(tmp_path):
    project, run_id = _run(
        tmp_path, "diagnostic-tamper", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    # Diagnostics consume the sealed result input, not the mutable legacy summary.
    summary_path = run_root / "result_input.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["sections"]["model_identity"]["models"][0]["nobs"] > 0
    summary["sections"]["model_identity"]["models"][0]["nobs"] = 999
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    records = [record for record in index["artifacts"] if record.get("artifact_id") == f"result-input:{run_id}"]
    assert len(records) == 1 and records[0]["path"] == "result_input.json"
    records[0]["sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index), encoding="utf-8")

    diagnostics = _diagnostics(project, run_id, "model:ols_1")["diagnostics"]
    assert diagnostics["available"] is False
    assert diagnostics["status"] == "unavailable"
    assert diagnostics["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert diagnostics["facts"] == [] and diagnostics["sections"] == []


def test_agent_diagnostics_rejects_invalid_scalars_even_with_rebound_input_digest(tmp_path):
    """A rewritten committed input and index cannot authorize raw scalars."""
    from workbench.artifacts import sha256_file

    project, run_id = _run(
        tmp_path, "diagnostic-invalid-scalar", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    run_root = project.root / "runs" / run_id
    summary_path = run_root / "result_input.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["sections"]["model_identity"]["models"][0]["nobs"] > 0
    summary["sections"]["model_identity"]["models"][0]["nobs"] = 10**400
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    records = [record for record in index["artifacts"] if record.get("artifact_id") == f"result-input:{run_id}"]
    assert len(records) == 1 and records[0]["path"] == "result_input.json"
    records[0]["sha256"] = sha256_file(summary_path)
    index_path.write_text(json.dumps(index), encoding="utf-8")

    diagnostics = _diagnostics(project, run_id, "model:ols_1")["diagnostics"]
    assert diagnostics["available"] is False
    assert diagnostics["status"] == "unavailable"
    assert diagnostics["unavailable_reason"] == "EVIDENCE_DEPENDENCY_MISMATCH"
    assert diagnostics["facts"] == [] and diagnostics["sections"] == []


def test_a_run_without_a_design_omits_the_optional_field(tmp_path):
    """Absent persisted design metadata must not be synthesized as ``None``."""
    project, run_id = _run(
        tmp_path, "plain", "survey/design.csv",
        model_type="ols", y="y", x=["x1", "x2"],
    )
    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert "survey_design" not in summary


def test_ordinary_non_survey_agent_diagnostics_omit_optional_survey_fields(tmp_path):
    """A normal run must not advertise absent Survey result sections."""
    project, run_id = _run(
        tmp_path,
        "ordinary-agent-read",
        "survey/design.csv",
        model_type="ols",
        y="y",
        x=["x1", "x2"],
    )

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    diagnostics = _diagnostics(project, run_id, "model:ols_1")["diagnostics"]
    assert "survey_design" not in summary
    assert "marginal_effects" not in summary
    assert "survey_design" not in diagnostics
    assert "marginal_effects" not in diagnostics


def test_real_agent_projection_has_no_nullable_sparse_model_facts(tmp_path):
    """A real completed Agent read must omit absent low-level placeholders."""
    project, run_id = _run(
        tmp_path,
        "ordinary-sparse-projection",
        "survey/design.csv",
        model_type="ols",
        y="y",
        x=["x1", "x2"],
    )

    summary = _summary(project, run_id, "model:ols_1")["result_summary"]
    assert summary["available"] is True, summary
    assert summary["facts"]
    for fact in summary["facts"]:
        assert all(value is not None for value in fact.values())
    assert "persisted_models" not in summary
    assert "survey_design" not in summary
    assert "marginal_effects" not in summary


def test_report_projection_keeps_sparse_survey_boundary():
    """Report remains a separate bounded consumer for sparse model packets."""
    from workbench.report_view_model import build_regression_table

    packet = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_id": "ols_1",
                    "model_type": "ols",
                    "coefficients": {"x": {"estimate": 1.25}},
                },
            )
        ]
    )

    assert packet["models"][0]["id"] == "ols_1"
    assert "survey_design" not in packet["models"][0]
    assert "survey_provenance" not in packet["models"][0]


def test_agent_result_summary_omits_unpersisted_survey_sections(tmp_path):
    """No persisted survey sections means no invented ``None`` or empty list."""
    from workbench.agent.context_tools import _bounded_result_summary

    projected = _bounded_result_summary(
        None,
        summary_status="missing",
        preview={"available": False},
        model_results=[],
        run_root=tmp_path / "run-1",
    )

    for field in (
        "survey_design",
        "regression_table",
        "marginal_effects",
        "full_table_ref",
        "interpretation_mode",
        "run_status",
        "persisted_models",
        "statistical_evidence",
        "model_family_evidence",
        "coefficient_rows",
    ):
        assert field not in projected


def test_the_agent_can_read_an_anova_table(tmp_path):
    """It can already propose ANOVA; without this it cannot read the result."""
    project, run_id = _run(
        tmp_path, "an", "anova/anova.csv",
        model_type="anova", y="score", x=["factor_a", "factor_b", "covariate"],
        model_options={"sums_of_squares": 3, "categorical": ["factor_a", "factor_b"]},
    )
    run_root = project.root / "runs" / run_id
    evidence = _bounded_model_family_evidence(run_root, read_model_results(run_root))

    assert evidence is not None, "no ANOVA evidence is projected to the Agent at all"
    payload = json.dumps(evidence)
    # The type is not decoration: Type I and Type III disagree on this fixture
    # (166.74 against 104.05), so a table quoted without it is ambiguous.
    assert "sums_of_squares_type" in payload
    assert "anova_table" in payload
    assert "partial_eta_squared" in payload


def test_the_agent_can_read_average_marginal_effects(tmp_path):
    """A logit coefficient is a log-odds; the AME is the number people quote."""
    project, run_id = _run(
        tmp_path, "glm", "marginal_effects/glm.csv",
        model_type="logit", y="binary", x=["x1", "x2"],
    )
    payload = json.dumps(_summary(project, run_id, "model:logit_1"))
    assert "marginal_effect" in payload, (
        "the result carries average marginal effects and the Agent cannot see them"
    )


def test_the_agent_can_read_how_strongly_a_family_was_validated(tmp_path):
    """v1.8.7 made this a per-family claim; an Agent quoting a result should
    be able to say what backs it rather than implying more than is known."""
    project, run_id = _run(
        tmp_path, "ord", "v186_families/families.csv",
        model_type="ordinal_logit", y="rating", x=["x1", "x2", "grp"],
        model_options={"outcome_order": ["low", "mid", "high"]},
    )
    run_root = project.root / "runs" / run_id
    evidence = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    payload = json.dumps(evidence)
    assert "validation" in payload, "the Agent cannot read the verification level"
    assert "polr" in payload, "the reference implementation is not readable"


def test_every_family_with_its_own_result_shape_is_readable_by_the_agent():
    """The gap this file closed, stated so a new family cannot reopen it.

    `anova` shipped able to be proposed and impossible to read: the run
    succeeded, the Agent had asked for it, and the result projection returned
    None. Reachability has two halves, and the second is the easy one to forget
    because nothing fails when it is missing.

    Families whose result is the ordinary coefficient table are covered by the
    result summary; the ones listed here carry a shape of their own, and each
    needs a declared projection.
    """
    from workbench.agent.context_tools import FAMILY_EVIDENCE_PROJECTIONS
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    # `coefficient_intervals` is the ordinary coefficient table, which the
    # result summary already projects with its own bounds. Everything else has
    # a shape of its own that the summary cannot represent.
    summary_covered = {"coefficient_intervals"}
    shaped = {
        key
        for key, contract in MODEL_FAMILY_CONTRACTS.items()
        if contract.result_shape and contract.result_shape not in summary_covered
    }
    assert shaped, "no family declares a non-standard result shape; the scan is vacuous"
    assert "anova" in shaped, "the family this guard was written for left the scan"

    # The DID families predate this projection and read through their own
    # diagnostics cards; recorded as a known gap rather than silently excluded.
    known_gaps = {"cs_did", "sa_did", "dcdh"}
    missing = sorted(shaped - set(FAMILY_EVIDENCE_PROJECTIONS) - known_gaps)
    assert not missing, (
        f"{missing} declare their own result shape but project nothing to the "
        "Agent, so it can ask for them and cannot read the answer"
    )
