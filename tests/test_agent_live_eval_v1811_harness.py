"""Offline harness control tests; these never call an LLM provider."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("live_eval_v1811", ROOT / "scripts/agent_live_eval.py")
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)

@pytest.fixture
def cases_path(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{"id": "one", "request": "hello"}, {"id": "two", "request": "hello"}]))
    return path

def invoke(monkeypatch, out, cases, *extra):
    monkeypatch.setattr(sys, "argv", ["eval", "--out", str(out), "--cases", str(cases), *extra])
    return harness.main()

@pytest.mark.parametrize("extra", [("--only", ""), ("--only", "missing"), ("--only", "one,one"), ("--only", "one,,two"), ("--repeat", "0"), ("--repeat", "-2")])
def test_invalid_selection_precedes_provider(monkeypatch, tmp_path, cases_path, extra):
    def forbidden():
        pytest.fail("provider config read before CLI validation")
    monkeypatch.setattr(harness, "load_llm_config", forbidden)
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, tmp_path / "fresh", cases_path, *extra)
    assert exc.value.code == 2
    assert not (tmp_path / "fresh").exists()

def stub_run(monkeypatch, fail=False, exception=False):
    config = SimpleNamespace(is_configured=lambda: True, base_url="offline", model="stub")
    monkeypatch.setattr(harness, "load_llm_config", lambda: config)
    monkeypatch.setattr(harness, "TestClient", lambda app: object())
    monkeypatch.setattr(harness, "_dataset", lambda path: path)
    monkeypatch.setattr(harness, "create_project", lambda parent, name: (parent / name).mkdir())
    monkeypatch.setattr(harness, "_seed_source_run", lambda *a, **k: "seed")
    def run(*a, **k):
        if exception and a[3]["id"] == "one":
            raise RuntimeError("offline injected failure")
        return {"id": a[3]["id"], "elapsed_s": 0, "tool_calls": [], "fabricated_numbers": []}
    monkeypatch.setattr(harness, "_run_case", run)
    monkeypatch.setattr(harness, "_score", lambda *a: [{"check": "offline", "passed": not fail}])

def test_existing_output_never_overwritten(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch)
    out = tmp_path / "existing"
    out.mkdir()
    marker = out / "results.json"
    marker.write_text("keep original")
    with pytest.raises(SystemExit):
        invoke(monkeypatch, out, cases_path)
    assert marker.read_text() == "keep original"

def test_fail_has_nonzero_exit_and_each_case_persisted(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch, fail=True)
    out = tmp_path / "fresh"
    assert invoke(monkeypatch, out, cases_path, "--repeat", "2") == 1
    records = list((out / "cases").glob("*.json"))
    assert len(records) == 4
    assert all(not json.loads(p.read_text())["passed"] for p in records)

def test_case_exception_is_persisted_and_remaining_cases_run(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch, exception=True)
    out = tmp_path / "fresh"
    assert invoke(monkeypatch, out, cases_path) == 1
    report = json.loads((out / "results.json").read_text())
    assert len(report["results"]) == 2
    assert report["results"][0]["passed"] is False
    assert "offline injected failure" in report["results"][0]["error"]
    assert report["results"][1]["passed"] is True

def test_exact_selected_repeats_pass_and_persist(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch)
    out = tmp_path / "fresh"
    assert invoke(monkeypatch, out, cases_path, "--only", "two", "--repeat", "2") == 0
    report = json.loads((out / "results.json").read_text())
    assert [(r["id"], r["attempt"]) for r in report["results"]] == [("two", 1), ("two", 2)]
    assert len(list((out / "cases").glob("*.json"))) == 2


def test_tool_text_is_not_execution(monkeypatch, tmp_path):
    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}
        def __init__(self, body): self.body = body
        def json(self): return self.body
        def raise_for_status(self): pass
    class Client:
        def post(self, url, **kwargs):
            if url == "/agent/sessions":
                assert kwargs["json"]["context_packet"] == {"operation_target": {"owner_run_id": "seed", "op_node_id": "model:m"}, "ownership": {"owner_run_id": "seed"}}
            return Response({"session_id": "s"} if url == "/agent/sessions" else {"assistant": "hello"})
        def get(self, url, **kwargs): return Response({"proposals": []})
    monkeypatch.setattr(harness, "_session_messages", lambda *a: [{"payload": {"role": "tool", "content": '{"executed": true}'}}])
    record = harness._run_case(Client(), tmp_path, "seed", {"id": "one", "request": "hello", "context_packet": {"operation_target": {"owner_run_id": "seed", "op_node_id": "model:m"}, "ownership": {"owner_run_id": "seed"}}}, confirm=False)
    assert record["executed"] is False

@pytest.mark.parametrize("mutant", ["wrong_family", "wrong_alpha", "wrong_target", "missing_parameters"])
def test_proposal_full_binding_rejects_mutants(mutant):
    packet = {"params": {"model_type": "glm:negative_binomial", "y": "y", "x": ["x1"], "model_options": {"alpha": 1.0}}}
    proposal = {"operation_id": "model.rerun", "target": {"run_id": "source"}, "changes": {"model_type": "glm:negative_binomial", "y": "y", "x": ["x1"], "model_options": {"alpha": 1.0}}}
    if mutant == "wrong_family": proposal["changes"]["model_type"] = "poisson"
    if mutant == "wrong_alpha": proposal["changes"]["model_options"]["alpha"] = 2.0
    if mutant == "wrong_target": proposal["target"]["run_id"] = "other"
    if mutant == "missing_parameters": proposal["changes"].pop("x")
    with pytest.raises(ValueError):
        harness._validate_family_proposal(proposal, packet, "source", {})

def test_proposal_partial_rerun_resolves_from_source_not_expected():
    params = {"model_type": "glm:negative_binomial", "y": "y", "x": ["x1"], "model_options": {"alpha": 1.0}}
    proposal = {"operation_id": "model.rerun", "target": {"run_id": "source"}, "changes": {}}
    assert harness._validate_family_proposal(proposal, {"params": params}, "source", params) == params
    bad_source = {**params, "x": ["x2"]}
    with pytest.raises(ValueError):
        harness._validate_family_proposal(proposal, {"params": params}, "source", bad_source)

def test_completed_result_requires_real_binding_and_terminal():
    with pytest.raises(ValueError): harness._result_binding({"status": "completed", "outputs": {"executed": True}})
    with pytest.raises(ValueError): harness._result_binding({"status": "running", "outputs": {"target_run_id": "r"}})
    with pytest.raises(ValueError): harness._result_binding({"status": "completed", "execution": {"bindings": {"child_run_id": "r1"}}, "outputs": {"target_run_id": "r2"}})
    assert harness._result_binding({"status": "completed", "execution": {"bindings": {"child_run_id": "r1", "child_session_id": "s1"}}, "outputs": {"target_run_id": "r1"}}) == ("r1", "s1")


FAMILIES = ["iv_2sls", "glm:binomial", "glm:poisson", "glm:negative_binomial", "panel_ols", "did", "linear_mixed_effects", "probit", "poisson", "negative_binomial", "ordinal_logit", "multinomial_logit", "quantile_regression", "survival_cox", "cs_did", "sa_did", "dcdh"]

def load_packets():
    return json.loads((ROOT / "scripts/agent_live_eval_fixtures_v1811.json").read_text())["families"]

def test_legacy_37_unchanged_and_17_exact_bound_packets():
    import subprocess
    import hashlib
    before = json.loads(subprocess.check_output(["git", "show", "485ce4fc:scripts/agent_live_eval_cases.json"], cwd=ROOT))
    current = json.loads((ROOT / "scripts/agent_live_eval_cases.json").read_text())
    assert current[:37] == before and len(before) == 37
    new = current[37:]
    packets = load_packets()
    assert len(new) == 17 and set(packets) == set(FAMILIES)
    assert {case["fixture"] for case in new} == set(FAMILIES)
    for packet in packets.values():
        for prefix in ("source", "oracle"):
            path = ROOT / packet[f"{prefix}_path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == packet[f"{prefix}_sha256"]
        assert packet["comparisons"]
        oracle = json.loads((ROOT / packet["oracle_path"]).read_text())
        for field in packet["comparisons"]:
            assert isinstance(harness._pointer(oracle, field["oracle"]), (int, float))
            assert field["tolerance_source"].startswith("tests/")
    assert packets["glm:negative_binomial"]["params"]["model_options"]["alpha"] == 1.0
    assert packets["survival_cox"]["params"]["model_options"]["ties"] == "efron"
    assert packets["negative_binomial"]["params"]["model_options"] == {"dispersion": "mean"}
    assert packets["cs_did"]["params"]["x"] == ["x1"]
    assert packets["linear_mixed_effects"]["host_canary_required"] is True
    assert "different estimand" in " ".join(packets["dcdh"]["not_native_verified_fields"])
    assert "Av_tot_eff" in packets["dcdh"]["known_limitations"][0]

@pytest.mark.parametrize("family", FAMILIES)
def test_public_family_fixture_owner_and_native_fields(tmp_path, family):
    packet = load_packets()[family]
    root = harness.create_project(tmp_path, "public").root
    with harness.TestClient(harness.app) as client:
        if family == "linear_mixed_effects":
            # Actual public canary may be blocked under nested containment. A
            # blocker is evidence of truthful refusal, never a live-family PASS.
            try:
                run = harness._seed_family(client, root, packet)
            except ValueError as exc:
                assert "LMM_FROZEN_CONTAINMENT_REQUIRED" in str(exc) or "CONTAINMENT" in str(exc)
                (tmp_path / "lmm-blocker.json").write_text(json.dumps({"status": "BLOCKED_NOT_LIVE_PASS", "error": str(exc)}))
                return
        else:
            run = harness._seed_family(client, root, packet)
        evidence = harness._read_verified_run(root, run, packet)
        rows = harness._native_diffs(evidence, packet)
        (tmp_path / "public-fixture-evidence.json").write_text(json.dumps({"family": family, "evidence": evidence, "native_diffs": rows, "scope": packet["native_verified_fields"], "known_limitations": packet.get("known_limitations", [])}, ensure_ascii=False, indent=2, allow_nan=False))
        assert all(row["passed"] for row in rows), rows


def test_family_followup_occurs_after_completed_bound_run(monkeypatch, tmp_path):
    directory = tmp_path / "stages"; directory.mkdir()
    chronology = []
    packet = {"params": {"model_type": "poisson", "y": "y", "x": ["x1"], "model_options": {}}, "model_id": "poisson_1", "comparisons": [{"actual": ["coefficients", "x1", "estimate"]}]}
    proposal = {"proposal_id": "p", "revision": 4, "fingerprint": "real-current-fingerprint", "status": "pending", "operation_id": "model.rerun", "target": {"run_id": "source"}, "changes": {}}
    def read(root, run, packet):
        chronology.append("verify:"+run)
        return {"executed_params": packet["params"], "model": {}, "run_id": run,
                "rerun_of": "source" if run == "result" else None, "execution_context": {"proposal_id": "p"}}
    monkeypatch.setattr(harness, "_read_verified_run", read)
    def turn(client, root, run, case, **kwargs):
        chronology.append("turn:"+run)
        if run == "source": return {"proposals": {"proposals": [proposal]}, "session_id": "planning", "assistant": "pre-confirm answer"}
        assert chronology.index("confirm") < chronology.index("verify:result")
        return {"session_id": "answer", "assistant": json.dumps({"schema": "workbench-live-answer-v1", "run_id": "result", "model_id": "poisson_1", "fields": [{"path": ["coefficients", "x1", "estimate"], "artifact": None, "value": .6}]}), "tool_calls": [{"name": "inspect_project_model_coefficients"}]}
    monkeypatch.setattr(harness, "_run_case", turn)
    def confirm(*args):
        chronology.append("confirm")
        assert args[-1]["revision"] == 4
        return {"operation": {"status": "completed", "agent_session_id": "planning", "proposal_id": "p", "proposal_revision": 4, "proposal_fingerprint": "real-current-fingerprint", "operation_id": "model.rerun", "target": {"run_id": "source"}, "confirmation": {"session_id": "planning", "proposal_id": "p", "revision": 4, "fingerprint": "real-current-fingerprint", "operation_id": "model.rerun", "target": {"run_id": "source"}}, "execution": {"bindings": {"child_run_id": "result"}}}}
    monkeypatch.setattr(harness, "_confirm_and_wait", confirm)
    monkeypatch.setattr(harness, "_wait_run", lambda *a: chronology.append("wait:result"))
    monkeypatch.setattr(harness, "_native_diffs", lambda *a: [{"actual": .6, "field": ["coefficients", "x1", "estimate"], "tolerance": 1e-6, "passed": True}])
    monkeypatch.setattr(harness, "_session_messages", lambda *a: [{"payload": {"role": "tool", "name": "inspect_project_model_coefficients", "content": '{"run_id":"result","model_id":"poisson_1","coefficients":{"x1":{"estimate":0.6}}}'}}])
    monkeypatch.setattr(harness, "_sha", lambda *a: "sha")
    record = harness._run_family_case(object(), tmp_path, "source", {"id": "one", "followup": "current coefficient"}, packet, directory, confirm=True)
    assert record["result_run_id"] == "result" and record["assistant"] != record["planning_answer"]
    assert chronology == ["verify:source", "turn:source", "confirm", "wait:result", "verify:result", "turn:result"]
    assert len(list(directory.glob("*.json"))) == 7
    assert all(row["passed"] for row in record["family_checks"])


def test_artifact_hash_drift_fails_before_native_comparison(tmp_path):
    import hashlib
    path = tmp_path / "model_results"; path.mkdir()
    asset = path / "poisson_1.json"; asset.write_text('{"estimate": 1}')
    index = {"artifacts": [{"path": "model_results/poisson_1.json", "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()}]}
    asset.write_text('{"estimate": 2}')
    with pytest.raises(ValueError, match="SHA mismatch"):
        harness._verified_artifact(tmp_path, index, "model_results/poisson_1.json")


@pytest.mark.parametrize("change", [{"row_filter": "x1>0"}, {"model_options": {"alpha": 1.0, "unrequested": True}}])
def test_family_extra_transform_or_option_cannot_be_confirmed(change):
    params = {"model_type": "glm:negative_binomial", "y": "y", "x": ["x1"], "model_options": {"alpha": 1.0}}
    proposal = {"operation_id": "model.rerun", "target": {"run_id": "r"}, "changes": change}
    with pytest.raises(ValueError): harness._validate_family_proposal(proposal, {"params": params}, "r", params)


def test_seed_failure_persists_all_case_failures(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch)
    def seed(*a, **k): raise RuntimeError("seed deliberately unavailable")
    monkeypatch.setattr(harness, "_seed_source_run", seed)
    out = tmp_path / "fresh"
    assert invoke(monkeypatch, out, cases_path) == 1
    report = json.loads((out / "results.json").read_text())
    assert len(report["results"]) == 2
    assert all(not row["passed"] and "source seed failed" in row["error"] for row in report["results"])


def test_real_public_confirmation_terminal_result_binding_without_llm(tmp_path):
    from workbench.dev_fixtures.agent_navigation import seed_agent_rerun_smoke_fixture
    source = harness._dataset(tmp_path / "wages.csv")
    fixture = seed_agent_rerun_smoke_fixture(tmp_path / "public-confirm", input_file=source, timeout_s=40)
    client = harness.TestClient(harness.app)
    # The legacy seeder registers an in-memory chain. Real /sessions establishes
    # its durable active head, exactly as _run_case does before planning.
    initialized = client.post("/agent/sessions", params={"project_root": str(fixture.project_root)},
        json={"role": "chain", "chain_id": fixture.chain_id, "run_id": fixture.source_run_id, "context_packet": {}})
    assert initialized.status_code == 200, initialized.text
    response = client.get(f"/agent/sessions/{fixture.session_id}/proposals", params={"project_root": str(fixture.project_root)})
    assert response.status_code == 200
    proposal = response.json()["proposals"][0]
    result = harness._confirm_and_wait(client, fixture.project_root, fixture.session_id, fixture.source_run_id, proposal)
    (tmp_path / "public-confirmation-attempt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["confirmed_revision"] == proposal["revision"]
    assert result["confirmed_fingerprint"] == proposal["fingerprint"]
    assert result["status"] == "completed", result
    harness._verify_confirmation_identity(result["operation"], fixture.session_id, proposal)
    run, session = harness._result_binding(result["operation"])
    assert run != fixture.source_run_id and session
    assert client.get(f"/runs/{run}", params={"project_root": str(fixture.project_root)}).json()["status"] == "completed"
    inputs = json.loads((fixture.project_root / "runs" / run / "run_inputs.json").read_text())
    assert inputs["rerun_of"] == fixture.source_run_id
    assert inputs["workbench_context"]["proposal_id"] == proposal["proposal_id"]
    (tmp_path / "public-confirmation-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


def test_existing_dangling_output_link_is_not_followed(monkeypatch, tmp_path, cases_path):
    stub_run(monkeypatch)
    out = tmp_path / "existing-link"
    target = tmp_path / "must-remain-absent"
    out.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit): invoke(monkeypatch, out, cases_path)
    assert not target.exists()


def test_empty_catalog_is_failure_before_provider(monkeypatch, tmp_path):
    cases = tmp_path / "empty.json"; cases.write_text("[]")
    monkeypatch.setattr(harness, "load_llm_config", lambda: pytest.fail("config must not be read"))
    with pytest.raises(SystemExit) as exc: invoke(monkeypatch, tmp_path / "fresh", cases)
    assert exc.value.code == 1


@pytest.mark.parametrize("mutation", [{"rerun_of": "other"}, {"execution_context": {"proposal_id": "other"}}, {"execution_context": {}}])
def test_result_lineage_cannot_use_unrelated_completed_run(mutation):
    actual = {"run_id": "result", "rerun_of": "source", "execution_context": {"proposal_id": "p"}}
    actual.update(mutation)
    with pytest.raises(ValueError): harness._verify_result_lineage(actual, "source", "p")

# Review repair contract: explicit field declarations and exact current owners.
def repair_proposal_operation():
    proposal = {"proposal_id": "p", "revision": 4, "fingerprint": "fp", "operation_id": "model.rerun", "target": {"run_id": "source", "node_ref": "model:poisson_1"}, "changes": {}}
    op = {"status": "completed", "agent_session_id": "planning", "proposal_id": "p", "proposal_revision": 4, "proposal_fingerprint": "fp", "operation_id": "model.rerun", "target": proposal["target"].copy(), "confirmation": {"session_id": "planning", "proposal_id": "p", "revision": 4, "fingerprint": "fp", "operation_id": "model.rerun", "target": proposal["target"].copy()}}
    return proposal, op

@pytest.mark.parametrize("where,key,bad", [("operation", "agent_session_id", "other"), ("operation", "proposal_id", "other"), ("operation", "proposal_revision", 3), ("operation", "proposal_fingerprint", "old"), ("operation", "operation_id", "model.genesis"), ("operation", "target", {"run_id": "source", "node_ref": "other"}), ("confirmation", "session_id", "other"), ("confirmation", "revision", 3), ("confirmation", "fingerprint", "old"), ("confirmation", "proposal_id", "other"), ("confirmation", "operation_id", "model.genesis"), ("confirmation", "target", {"run_id": "other"})])
def test_repair_completed_identity_mutants(where, key, bad):
    proposal, op = repair_proposal_operation()
    if where == "operation": op[key] = bad
    else: op["confirmation"][key] = bad
    with pytest.raises(ValueError): harness._verify_confirmation_identity(op, "planning", proposal)

def test_repair_completed_identity_requires_durable_confirmation():
    proposal, op = repair_proposal_operation()
    harness._verify_confirmation_identity(op, "planning", proposal)
    del op["confirmation"]
    with pytest.raises(ValueError): harness._verify_confirmation_identity(op, "planning", proposal)

@pytest.mark.parametrize("objects", [[{"run_id": "result_unrelated", "model_id": "poisson_10"}], [{"run_id": "result"}, {"model_id": "poisson_1"}], [{"run_id": "result", "model_id": "poisson_1", "evidence_ref": {"run_id": "wrong", "model_id": "poisson_1"}}]])
def test_repair_tool_owner_cannot_use_substrings_or_merge_objects(objects):
    entries = [{"payload": {"role": "tool", "name": "inspect_project_model_coefficients", "content": json.dumps({"models": objects})}}]
    assert not harness._answer_owner_evidence(entries, "result", "poisson_1", [])

def test_repair_tool_owner_positive_and_role_boundary():
    payload = {"models": [{"run_id": "result", "model_id": "poisson_1", "evidence_ref": {"run_id": "result", "model_id": "poisson_1"}}]}
    entry = {"payload": {"role": "tool", "name": "inspect_project_model_coefficients", "content": json.dumps(payload)}}
    assert harness._answer_owner_evidence([entry], "result", "poisson_1", [])
    entry["payload"]["role"] = "assistant"
    assert not harness._answer_owner_evidence([entry], "result", "poisson_1", [])

def test_result_summary_owned_coefficient_projection_is_valid_field_evidence():
    model = {"model_id": "m", "evidence_ref": {"run_id": "r", "model_id": "m", "result_ref": "model_results:m"},
             "coefficients": [{"term": "x", "estimate": -.6}]}
    entry = {"payload": {"role": "tool", "name": "inspect_result_summary",
                         "content": json.dumps({"ok": True, "output": {"result_summary": {"persisted_models": [model]}}})}}
    field = {"path": ["coefficients", "x", "estimate"], "artifact": None}
    rows = [{"actual": -.6, "tolerance": 1e-6}]
    assert harness._answer_field_evidence([entry], "r", "m", [field], rows, {})["passed"]
    model["evidence_ref"]["run_id"] = "old"
    entry["payload"]["content"] = json.dumps({"ok": True, "output": {"result_summary": {"persisted_models": [model]}}})
    assert not harness._answer_field_evidence([entry], "r", "m", [field], rows, {})["passed"]

@pytest.mark.parametrize("mutation", ["field", "sign", "term", "missing", "duplicate", "rounded", "bool", "owner", "nan"])
def test_repair_answer_exact_signed_fields(mutation):
    fields = [{"path": ["coefficients", "x1", "estimate"], "artifact": None}]
    rows = [{"field": fields[0]["path"], "actual": .40536541665861775, "tolerance": 1e-6}]
    answer = {"schema": "workbench-live-answer-v1", "run_id": "result", "model_id": "poisson_1", "fields": [{"path": fields[0]["path"].copy(), "artifact": None, "value": .405365416659}]}
    if mutation == "field": answer["fields"][0]["path"][-1] = "std_error"
    if mutation == "sign": answer["fields"][0]["value"] *= -1
    if mutation == "term": answer["fields"][0]["path"][1] = "x10"
    if mutation == "missing": answer["fields"] = []
    if mutation == "duplicate": answer["fields"] *= 2
    if mutation == "rounded": answer["fields"][0]["value"] = .40536542
    if mutation == "bool": answer["fields"][0]["value"] = True
    if mutation == "owner": answer["run_id"] = "result_unrelated"
    if mutation == "nan": answer["fields"][0]["value"] = float("nan")
    assert not harness._verify_answer_fields(json.dumps(answer), "result", "poisson_1", fields, rows)["passed"]

def test_repair_answer_multiple_fields_positive_and_unverifiable_prose():
    fields = [{"path": ["fits", tau, "coefficients", "x1", "estimate"], "artifact": None} for tau in ["0.25", "0.5", "0.75"]]
    rows = [{"field": f["path"], "actual": v, "tolerance": 1e-5} for f,v in zip(fields, [-.6,.4,.7])]
    answer = {"schema": "workbench-live-answer-v1", "run_id": "result", "model_id": "quantile_regression_1", "fields": [{**f, "value": row["actual"]} for f,row in zip(fields,rows)]}
    assert harness._verify_answer_fields('```json\n'+json.dumps(answer)+'\n```', "result", "quantile_regression_1", fields, rows)["passed"]
    assert not harness._verify_answer_fields("x1 coefficient = -.60", "result", "quantile_regression_1", fields, rows)["passed"]

@pytest.fixture(scope="module")
def repair_completed_public_owner_fixture(tmp_path_factory):
    """Fresh public rerun; no historical temp-directory dependency or provider."""
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.dev_fixtures.agent_navigation import _NoopModelAdapter, _model_node_ref
    from workbench.lineage.node_write_validation import build_rerun_operation_context
    directory = tmp_path_factory.mktemp("repair-fresh-public-owner")
    root = harness.create_project(directory, "confirmed-public").root
    packet = load_packets()["poisson"]
    with harness.TestClient(harness.app) as client:
        source = harness._seed_family(client, root, packet)
        node = _model_node_ref(root, source)
        context = build_rerun_operation_context(root / "runs", request_id="repair-context", owner_run_id=source, op_node_id=node, active_head_run_id=source)
        repo = JsonlSessionRepository(root / "workbench")
        repo.create_session("main-repair", chain_id="project", role="main")
        repo.create_session("planning-review", chain_id="planning-chain-repair", role="chain")
        events = AgentEventStream(root / "workbench")
        agent = AgentCore(repo, events, _NoopModelAdapter(), session_id="planning-review")
        orchestrator = WorkbenchOrchestrator(repo, events, main_session_id="main-repair", context_provider=NodeOperationContextProvider(root))
        orchestrator.register_chain("planning-chain-repair", "planning-review", agent)
        proposal = orchestrator.create_proposal(chain_id="planning-chain-repair", operation_id="model.rerun", target={"run_id": source, "node_ref": node, "node_hash": context.node_hash, "forest_node_key": context.forest_node_key}, preconditions={"context_version": context.context_version, "context_fingerprint": context.context_fingerprint, "active_head_run_id": source, "owner_resolution": context.owner_resolution, "run_family_id": f"legacy-family:{source}"}, changes={"x": {"old": packet["params"]["x"], "new": packet["params"]["x"]}}, evidence_refs=["repair:public-native-fixture"], expected_effect=["one real child"], risks=[], proposal_id="repair-poisson-proposal")
        initialized = client.post("/agent/sessions", params={"project_root": str(root)}, json={"role": "chain", "chain_id": "planning-chain-repair", "run_id": source, "context_packet": {}})
        assert initialized.status_code == 200, initialized.text
        proposals = client.get("/agent/sessions/planning-review/proposals", params={"project_root": str(root)}).json()["proposals"]
        current = next(p for p in proposals if p["proposal_id"] == proposal.proposal_id)
        result = harness._confirm_and_wait(client, root, "planning-review", source, current)
        assert result["status"] == "completed", result
        harness._verify_confirmation_identity(result["operation"], "planning-review", current)
        run, _ = harness._result_binding(result["operation"])
        harness._wait_run(client, root, run)
        evidence = harness._read_verified_run(root, run, packet)
        harness._verify_result_lineage(evidence, source, current["proposal_id"])
        assert all(row["passed"] for row in harness._native_diffs(evidence, packet))
    fixture = {"scope": "FRESH_PUBLIC_COMPLETED_OWNER_NO_PROVIDER", "root": str(root), "source": source, "result": result, "evidence": evidence}
    (directory / "repair-fresh-confirm-evidence.json").write_text(json.dumps(fixture, indent=2, allow_nan=False))
    return fixture

@pytest.mark.parametrize("attack", [None, "wrong_field", "wrong_sign", "wrong_tool_owner", "wrong_confirmation"])
def test_repair_real_completed_public_owner_end_to_end(monkeypatch, tmp_path, repair_completed_public_owner_fixture, attack):
    import copy
    import uuid
    fixture = repair_completed_public_owner_fixture
    root = Path(fixture["root"])
    source, run = fixture["source"], fixture["evidence"]["run_id"]
    operation = copy.deepcopy(fixture["result"]["operation"])
    proposal = {"proposal_id": operation["proposal_id"], "revision": operation["proposal_revision"], "fingerprint": operation["proposal_fingerprint"], "operation_id": operation["operation_id"], "target": operation["target"], "changes": operation["changes"], "status": "pending"}
    packet = load_packets()["poisson"]
    case = next(c for c in json.loads((ROOT / "scripts/agent_live_eval_cases.json").read_text()) if c.get("fixture") == "poisson")
    actual = harness._read_verified_run(root, run, packet)
    rows = harness._native_diffs(actual, packet)
    answer = {"schema": "workbench-live-answer-v1", "run_id": run, "model_id": packet["model_id"], "fields": [{"path": f["actual"].copy(), "artifact": f.get("artifact"), "value": float(format(row["actual"], ".12g"))} for f,row in zip(packet["comparisons"], rows)]}
    if attack == "wrong_field": answer["fields"][0]["path"][-1] = "std_error"
    if attack == "wrong_sign": answer["fields"][0]["value"] *= -1
    tool = {"run_id": run, "model_id": packet["model_id"], "coefficients": actual["model"]["coefficients"]}
    if attack == "wrong_tool_owner": tool.update(run_id=run+"_unrelated", model_id=packet["model_id"]+"0")
    if attack == "wrong_confirmation": operation["confirmation"]["proposal_id"] = "different"
    session = "repair-offline-answer-"+uuid.uuid4().hex
    entries = [{"payload": {"role": "tool", "name": "inspect_project_model_coefficients", "content": json.dumps(tool)}}]
    with (root / "workbench/agent-sessions" / (session+".jsonl")).open("x") as handle:
        handle.write(json.dumps(entries[0])+"\n")
    text = "以下是当前真实结果，字段及有符号数值均来自已完成模型的工具证据。\n```json\n"+json.dumps(answer)+"\n```"
    def turn(client, r, run_id, request, **kwargs):
        if run_id == source:
            return {"session_id": "planning-review", "assistant": "待确认方案", "proposals": {"proposals": [proposal]}}
        assert run_id == run and "workbench-live-answer-v1" in request["request"]
        return {"id": case["id"], "elapsed_s": 0, "session_id": session, "assistant": text, "tool_calls": [{"name": "inspect_project_model_coefficients"}], "proposals": {"proposals": []}, "empty_reply": False, "http_status": 200, "final_stop_reason": "stop", "reply_language": "zh", "fabricated_numbers": harness._fabricated_numbers(text, entries)}
    monkeypatch.setattr(harness, "_run_case", turn)
    monkeypatch.setattr(harness, "_confirm_and_wait", lambda *a: {**fixture["result"], "operation": operation})
    directory = tmp_path / "stages"; directory.mkdir()
    with harness.TestClient(harness.app) as client:
        record = harness._run_family_case(client, root, source, case, packet, directory, confirm=True)
    checks = harness._score(record, case["checks"], root, run)+record["family_checks"]
    (tmp_path / "repair-real-owner-record.json").write_text(json.dumps({"scope": "OFFLINE_ANSWER_SEAM_REAL_PUBLIC_COMPLETED_OWNER_NOT_LIVE_PROVIDER", "attack": attack, "record": record, "checks": checks}, ensure_ascii=False, indent=2, allow_nan=False))
    assert all(c["passed"] for c in checks) is (attack is None), checks
    if attack == "wrong_confirmation":
        assert not (directory / "05-result.json").exists()

def test_repair_preserves_native_contracts_and_declares_real_followup_fields():
    import subprocess
    before = json.loads(subprocess.check_output(["git", "show", "a41e2165:scripts/agent_live_eval_fixtures_v1811.json"], cwd=ROOT))
    after = json.loads((ROOT / "scripts/agent_live_eval_fixtures_v1811.json").read_text())
    cases = json.loads((ROOT / "scripts/agent_live_eval_cases.json").read_text())[37:]
    # v1.8.11 correction: the LMM packet compared coefficients.x, which the
    # locked LMM recipe never publishes (only its group x time estimand), so
    # it could not run. Same source, oracle, params and owner; the native
    # comparison now reads the published estimand, SE tightened to rel 1e-6.
    corrected = {"linear_mixed_effects": {"comparisons", "native_verified_fields", "not_native_verified_fields"}}
    for family, packet in after["families"].items():
        kept = lambda value: {k:v for k,v in value.items() if k != "answer_comparison_indices" and k not in corrected.get(family, ())}
        assert kept(packet) == kept(before["families"][family])
        assert packet["answer_comparison_indices"] == list(range(len(packet["comparisons"])))
        case = next(c for c in cases if c["fixture"] == family)
        fields = [{"path": field["actual"], "artifact": field.get("artifact")} for field in packet["comparisons"]]
        prompt = harness._answer_request(case["followup"], "current-run", packet["model_id"], fields)
        assert "workbench-live-answer-v1" in prompt and "12位有效数字" in prompt
        declaration = json.loads(prompt.split("JSON结构（占位字符串不是数值来源）：", 1)[1])
        assert [{"path": field["path"], "artifact": field.get("artifact")} for field in declaration["fields"]] == fields

def test_lmm_live_comparison_reads_the_published_recipe_estimand():
    packet = json.loads((ROOT / "scripts/agent_live_eval_fixtures_v1811.json").read_text())["families"]["linear_mixed_effects"]
    oracle = json.loads((ROOT / packet["oracle_path"]).read_text())
    assert [field["actual"] for field in packet["comparisons"]] == [
        ["coefficients", "group_time_interaction", "estimate"], ["coefficients", "group_time_interaction", "std_error"]]
    assert [field["oracle"] for field in packet["comparisons"]] == [["coefficients", "armb:time"], ["std_error", "armb:time"]]
    assert all(isinstance(harness._pointer(oracle, field["oracle"]), float) for field in packet["comparisons"])
    assert packet["comparisons"][0]["abs"] == 1e-08 and packet["comparisons"][1]["rel"] == 1e-06

@pytest.mark.parametrize("body", ['{"schema":"wrong","schema":"workbench-live-answer-v1","run_id":"r","model_id":"m","fields":[]}', '{"schema":"workbench-live-answer-v1","run_id":"r","model_id":"m","fields":[{"path":["coefficients","x1","estimate"],"artifact":null,"value":Infinity}]}'])
def test_repair_answer_duplicate_keys_nonfinite_reject(body):
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    row = {"actual": .6, "tolerance": 1e-6}
    assert not harness._verify_answer_fields(body, "r", "m", [field], [row])["passed"]

@pytest.mark.parametrize("prose", ["x1 coefficient = -.60", "x1：系数为−0.60", "x1 的估计值为−0.60"])
def test_repair_prose_cannot_contradict_structured_signed_value(prose):
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    row = {"actual": .6, "tolerance": 1e-6}
    answer = {"schema": "workbench-live-answer-v1", "run_id": "r", "model_id": "m", "fields": [{**field, "value": .6}]}
    text = prose + "\n```json\n"+json.dumps(answer)+"\n```"
    assert not harness._verify_answer_fields(text, "r", "m", [field], [row])["passed"]

def test_answer_metadata_and_diagnostics_are_not_additional_coefficient_claims():
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    row = {"actual": .3789844117869672, "tolerance": 1e-6}
    answer = {"schema": "workbench-live-answer-v1", "run_id": "r", "model_id": "m", "fields": [{**field, "value": row["actual"]}]}
    prose = "模型有3个系数行，未截断0行。警告：事件时间−4.0与2.0仅由单一cohort支持。x1的estimate显示为0.379。"
    assert harness._verify_answer_fields(prose + "\n```json\n" + json.dumps(answer) + "\n```", "r", "m", [field], [row])["passed"]

@pytest.mark.parametrize("index", [False, 0.0])
def test_repair_answer_path_tokens_require_exact_types(index):
    field = {"path": ["event_study", "estimate", 0], "artifact": "dcdh.json"}
    row = {"actual": .6, "tolerance": 1e-6}
    item = {**field, "path": ["event_study", "estimate", index], "value": .6}
    answer = {"schema": "workbench-live-answer-v1", "run_id": "r", "model_id": "m", "fields": [item]}
    assert not harness._verify_answer_fields(json.dumps(answer), "r", "m", [field], [row])["passed"]

# Remaining owner P2: each value must come from its matching owner object.
def owner_field_entries(objects):
    return [{"payload": {"role": "tool", "name": "inspect_project_model_coefficients", "content": json.dumps(objects)}}]

@pytest.mark.parametrize("attack", ["metadata_only", "wrong_term", "wrong_field", "wrong_sign", "foreign_nested", "conflicting_ref", "duplicate_terms", "short_round"])
def test_remaining_owner_field_binding_mutants(attack):
    current = {"run_id": "r", "model_id": "m", "coefficients": {"x1": {"estimate": .40536541665861775}}}
    foreign = {"run_id": "r_other", "model_id": "m0", "coefficients": current["coefficients"]}
    objects = [current]
    if attack == "metadata_only": objects = [{"run_id": "r", "model_id": "m"}, foreign]
    if attack == "wrong_term": current["coefficients"] = {"x10": {"estimate": .40536541665861775}}
    if attack == "wrong_field": current["coefficients"] = {"x1": {"std_error": .40536541665861775}}
    if attack == "wrong_sign": current["coefficients"]["x1"]["estimate"] *= -1
    if attack == "foreign_nested": current["coefficients"]["x1"].update(run_id="r_other", model_id="m0")
    if attack == "conflicting_ref": current["evidence_ref"] = {"run_id": "r_other", "model_id": "m0"}
    if attack == "duplicate_terms": current["coefficients"] = [{"term": "x1", "estimate": .40536541665861775}]*2
    if attack == "short_round": current["coefficients"]["x1"]["estimate"] = .40536542
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    row = {"actual": .40536541665861775, "tolerance": 1e-6}
    verdict = harness._answer_field_evidence(owner_field_entries(objects), "r", "m", [field], [row], {})
    assert not verdict["passed"], verdict

@pytest.mark.parametrize("shape", ["raw", "bounded", "projection"])
def test_remaining_owner_field_binding_valid_projections(shape):
    coeffs = {"x1": {"estimate": -.6}, "x2": {"estimate": .7}}
    if shape == "bounded": coeffs = [{"term": term, **values} for term,values in coeffs.items()]
    current = {"run_id": "r", "model_id": "m", "coefficients": coeffs, "evidence_ref": {"run_id": "r", "model_id": "m"}}
    if shape == "projection": current = {"run_id": "r", "model_id": "m", "result": {"coefficients": coeffs}}
    fields = [{"path": ["coefficients", term, "estimate"], "artifact": None} for term in ["x1", "x2"]]
    rows = [{"actual": value, "tolerance": 1e-6} for value in [-.6,.7]]
    verdict = harness._answer_field_evidence(owner_field_entries([current]), "r", "m", fields, rows, {})
    assert verdict["passed"] and len(verdict["fields"]) == 2

@pytest.mark.parametrize("artifact", ["registered", "foreign", "missing"])
def test_remaining_owner_artifact_fields_require_exact_registered_owner(artifact):
    current = {"run_id": "r", "artifact_id": "dcdh_1", "result": {"event_study": {"estimate": [.1,.2,.6]}}}
    if artifact == "foreign": current["artifact_id"] = "dcdh_10"
    if artifact == "missing": del current["artifact_id"]
    entry = {"payload": {"role": "tool", "name": "inspect_operation_artifact", "content": json.dumps(current)}}
    field = {"path": ["event_study", "estimate", 2], "artifact": "dcdh.json"}
    verdict = harness._answer_field_evidence([entry], "r", "dcdh_1", [field], [{"actual": .6, "tolerance": 1e-6}], {"dcdh.json": "dcdh_1"})
    assert verdict["passed"] is (artifact == "registered")

def test_remaining_owner_chinese_adjacent_wrong_field_prose_rejected():
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    answer = {"schema": "workbench-live-answer-v1", "run_id": "r", "model_id": "m", "fields": [{**field, "value": .6}]}
    text = "x1的标准误为0.60且已核实。\n```json\n"+json.dumps(answer)+"\n```"
    assert not harness._verify_answer_fields(text, "r", "m", [field], [{"actual": .6, "tolerance": 1e-6}])["passed"]

def test_remaining_owner_split_current_objects_accepted():
    objects = [{"run_id": "r", "model_id": "m", "coefficients": {term: {"estimate": value}}} for term,value in [("x1",.6),("x2",.7)]]
    fields = [{"path": ["coefficients", term, "estimate"], "artifact": None} for term in ["x1","x2"]]
    assert harness._answer_field_evidence(owner_field_entries(objects), "r", "m", fields, [{"actual": v, "tolerance": 1e-6} for v in [.6,.7]], {})["passed"]

def test_remaining_owner_conflicting_current_field_sources_rejected():
    objects = [{"run_id": "r", "model_id": "m", "coefficients": {"x1": {"estimate": value}}} for value in [.6,.7]]
    field = {"path": ["coefficients", "x1", "estimate"], "artifact": None}
    assert not harness._answer_field_evidence(owner_field_entries(objects), "r", "m", [field], [{"actual": .6,"tolerance": 1e-6}], {})["passed"]

def test_remaining_owner_qr_and_ancillary_declared_projection_fields():
    fields = [{"path": ["fits", tau, "coefficients", "x1", "estimate"], "artifact": None} for tau in ["0.25","0.5","0.75"]]
    values = [-.6,.4,.7]
    model = {"run_id": "r", "model_id": "m", "model_family_evidence": {"fits": {tau: {"coefficients": {"x1": {"estimate": value}}} for tau,value in zip(["0.25","0.5","0.75"], values)}, "ancillary_parameters": [{"parameter":"lnalpha","estimate": -.2}, {"parameter":"alpha","estimate":.8}]}}
    fields.append({"path": ["ancillary_parameters", 1, "estimate"], "artifact": None})
    verdict = harness._answer_field_evidence(owner_field_entries([model]), "r", "m", fields, [{"actual": v,"tolerance": 1e-6} for v in [*values,.8]], {})
    assert verdict["passed"] and len(verdict["fields"]) == 4

def test_real_declared_ancillary_projection_carries_its_completed_owner(tmp_path):
    from workbench.agent.family_evidence import bounded_model_family_evidence
    packet = load_packets()["negative_binomial"]
    source = ROOT / packet["oracle_path"]
    assert source.is_file()
    primary = {"model_type": "negative_binomial", "model_id": packet["model_id"],
               "ancillary_parameters": [{"name": "lnalpha", "estimate": -.2}, {"name": "alpha", "estimate": .8}]}
    root = tmp_path / "actual-owner"; root.mkdir()
    projected = bounded_model_family_evidence(root, [primary])
    field = {"path": ["ancillary_parameters", 1, "estimate"], "artifact": None}
    verdict = harness._answer_field_evidence(owner_field_entries([projected]), root.name, packet["model_id"],
                                              [field], [{"actual": .8, "tolerance": 1e-6}], {})
    assert verdict["passed"], verdict

def test_declared_document_series_preserves_artifact_and_source_index(tmp_path):
    from workbench.agent.family_evidence import bounded_model_family_evidence
    from workbench.artifacts import sha256_file
    root = tmp_path / "actual-owner"; root.mkdir()
    source = root / "dcdh.json"
    source.write_text(json.dumps({"event_study": {"event_time": [-1, 0, 1], "estimate": [None, .3, -.6], "se": [None, .1, .2]}}))
    (root / "artifacts_index.json").write_text(json.dumps({"artifacts": [{"artifact_id": "dcdh", "path": "dcdh.json", "sha256": sha256_file(source)}]}))
    projected = bounded_model_family_evidence(root, [{"model_type": "dcdh", "model_id": "dcdh_1"}])
    field = {"path": ["event_study", "estimate", 2], "artifact": "dcdh.json"}
    verdict = harness._answer_field_evidence(owner_field_entries([projected]), root.name, "dcdh_1", [field], [{"actual": -.6, "tolerance": 1e-6}], {"dcdh.json": "dcdh"})
    assert verdict["passed"], verdict
    assert projected["event_study"]["rows"][0]["source_index"] == 1
    source.write_text("{}")
    assert bounded_model_family_evidence(root, [{"model_type": "dcdh", "model_id": "dcdh_1"}]) is None

def test_remaining_owner_artifact_requires_registered_id_mapping():
    current = {"run_id": "r", "model_id": "m", "event_study": {"estimate": [.6]}}
    field = {"path": ["event_study", "estimate", 0], "artifact": "dcdh.json"}
    verdict = harness._answer_field_evidence(owner_field_entries([current]), "r", "m", [field], [{"actual": .6, "tolerance": 1e-6}], {})
    assert not verdict["passed"]

def test_remaining_owner_actual_public_bounded_tool_positive(repair_completed_public_owner_fixture, tmp_path):
    from workbench.agent.context_tools import NodeOperationContextProvider, InspectProjectModelCoefficientsRequest
    fixture = repair_completed_public_owner_fixture
    run, root = fixture["evidence"]["run_id"], Path(fixture["root"])
    packet = load_packets()["poisson"]
    actual = harness._read_verified_run(root, run, packet)
    body = NodeOperationContextProvider(root).inspect_project_model_coefficients(InspectProjectModelCoefficientsRequest(run_ids=(run,), terms=("x1","x2","x3")))
    fields = [{"path": f["actual"], "artifact": f.get("artifact")} for f in packet["comparisons"]]
    entries = owner_field_entries(body)
    verdict = harness._answer_field_evidence(entries, run, packet["model_id"], fields, harness._native_diffs(actual, packet), {})
    (tmp_path / "remaining-owner-real-bounded-tool.json").write_text(json.dumps({"scope": "REAL_PUBLIC_BOUND_TOOL_COMPLETED_OWNER_NO_PROVIDER", "tool_result": body, "verdict": verdict}, indent=2, allow_nan=False))
    assert verdict["passed"] and len(verdict["fields"]) == 3
