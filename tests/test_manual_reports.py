"""Offline manual reporting uses persisted evidence, never provider output."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from response_contracts import violations
from workbench.api_errors import register_error_handlers
from workbench.artifacts import register_artifact, write_json
from workbench.graph_model import Edge, Graph, Node, NodeKind
from workbench.graph_store import GraphStore
from workbench.projects import create_project, create_run


@pytest.fixture
def report_case(tmp_path, monkeypatch):
    def no_provider(*args, **kwargs):
        raise AssertionError("manual reporting must never invoke a provider")
    monkeypatch.setattr("workbench.llm.client.chat_completion", no_provider)
    project = create_project(tmp_path, "manual")
    run = create_run(project.root, mode="auto")
    result = {"model_id": "ols_1", "model_type": "ols", "nobs": 24,
              "r_squared": .73, "covariance_estimator": "HC1", "coefficients": {"x": {"estimate": 1.25,
              "std_error": .2, "p_value": .004, "ci_lower": .85, "ci_upper": 1.65}}}
    write_json(run.root / "model_results/ols_1.json", result)
    nodes = {key: Node(key, kind, label, "2026-10-09T00:00:00Z", None, "main")
             for key, kind, label in [("stage:raw", NodeKind.DATASET_STAGE, "Source"),
                                     ("model:ols_1", NodeKind.MODEL, "OLS")]}
    GraphStore(run.root.parent).write(Graph(3, run.run_id, nodes,
        {"fit": Edge("fit", "stage:raw", "model:ols_1", "fit", {"y": "outcome", "x": ["x"]})}, {}))
    figure = run.root / "figures/coef.png"
    figure.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    register_artifact(run.root, "coef_plot", figure, "figure", "visualization", [])
    # Unknown/raw fields must not leak into the fact projection.
    result["raw_rows"] = [{"patient_secret": "NEVER_PROJECT_THIS"}]
    write_json(run.root / "model_results/ols_1.json", result)
    register_artifact(run.root, "ols_1", run.root / "model_results/ols_1.json", "model_result", "econometrics", [])
    app = FastAPI()
    register_error_handlers(app)
    if importlib.util.find_spec("workbench.http.manual_report_routes"):
        from workbench.http.manual_report_routes import router
        app.include_router(router)
    return TestClient(app), project, run, result


def draft(case):
    client, project, run, _ = case
    response = client.get(f"/runs/{run.run_id}/manual-reports/draft",
                          params={"project_root": str(project.root)})
    assert response.status_code == 200, response.text
    return response.json()


def request_for(snapshot, **changes):
    return {"id": "mrpt_first", "source_fingerprint": snapshot["source_fingerprint"],
            "title": "User findings", "text": "My interpretation of the computed results.",
            "fact_ids": [f["id"] for f in snapshot["facts"]],
            "figure_ids": [f["artifact_id"] for f in snapshot["figures"]], **changes}


def post(case, payload):
    client, project, run, _ = case
    return client.post(f"/runs/{run.run_id}/manual-reports",
                       params={"project_root": str(project.root)}, json=payload)


def test_offline_draft_edit_save_history_and_export(report_case):
    snapshot = draft(report_case)
    assert snapshot == draft(report_case)
    assert "NEVER_PROJECT_THIS" not in str(snapshot)
    values = {fact["field"]: fact["value"] for fact in snapshot["facts"]}
    for field, value in {"estimate": 1.25, "std_error": .2, "p_value": .004,
                         "ci_lower": .85, "ci_upper": 1.65}.items():
        assert any(key.endswith("/" + field) and got == value for key, got in values.items())
    assert any(value == "outcome" for value in values.values())
    estimate = next(f for f in snapshot["facts"] if f["field"].endswith("/estimate") and f["value"] == 1.25)
    payload = request_for(snapshot, text=f"My interpretation of the computed results. The slope is [[v:{estimate['id']}]].")
    saved = post(report_case, payload)
    assert saved.status_code == 200, saved.text
    record = saved.json()["record"]
    assert record["author"] == "user" and record["draft_origin"] == "deterministic"
    assert "model" not in record
    assert record["text"] == payload["text"]
    assert record["facts"] == snapshot["facts"]
    client, project, run, result = report_case
    history = client.get(f"/runs/{run.run_id}/manual-reports", params={"project_root": str(project.root)})
    assert history.json()["reports"] == [record]
    from workbench.http.responses.manual_reports import ManualReportDraft, ManualReportSaved, ManualReportHistory
    assert violations(ManualReportDraft, snapshot) == []
    assert violations(ManualReportSaved, saved.json()) == []
    assert violations(ManualReportHistory, history.json()) == []
    for format in ("html", "docx", "tex", "pdf-print"):
        exported = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                             params={"project_root": str(project.root), "format": format})
        assert exported.status_code == 200, exported.text
        if format in ("html", "pdf-print"):
            assert "My interpretation" in exported.text and "data:image/png;base64" in exported.text
            # The marker becomes the value; the appendix lists the fact it shows.
            assert "The slope is 1.25." in exported.text and "[[v:" not in exported.text
            assert "Evidence behind the numbers" in exported.text and estimate["id"] in exported.text
        else:
            assert zipfile.is_zipfile(io.BytesIO(exported.content))
    assert __import__('json').loads((run.root / "model_results/ols_1.json").read_text()) == result


def test_agent_report_requires_the_registered_sample_size_marker(tmp_path, monkeypatch):
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.tools import ToolRegistry
    from workbench.artifacts import read_json, sha256_file
    from workbench.http.manual_report_routes import router
    from workbench.orchestrator import run_workflow

    def no_provider(*args, **kwargs):
        raise AssertionError("report validation must never invoke a provider")

    monkeypatch.setattr("workbench.llm.client.chat_completion", no_provider)
    source = tmp_path / "source.csv"
    source.write_text("x,outcome\n" + "".join(f"{x},{23*x + 7*((x*17 % 19) - 9)}\n" for x in range(1, 38)))
    project = create_project(tmp_path, "registered_sample_size")
    run = run_workflow(project.root, [source], mode="auto", y="outcome", x=["x"], model_type="ols",
                       covariance="unadjusted")
    assert run["status"] == "completed", run
    run_id = run["run_id"]
    run_root = project.root / "runs" / run_id
    model = run_root / "model_results/ols_1.json"
    model_digest = sha256_file(model)
    kernel = read_json(run_root / "model_results/inference_kernels/ols_1.json")
    assert read_json(model)["nobs"] == 37 and kernel["df_resid"] == 35

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    client = TestClient(app)
    route = f"/runs/{run_id}/manual-reports"
    params = {"project_root": str(project.root)}
    snapshot = client.get(f"{route}/draft", params=params).json()
    count = next(fact for fact in snapshot["facts"] if fact["field"] == "model/nobs")
    wrong_field = next(fact for fact in snapshot["facts"] if fact["field"] == "coefficient/x/estimate")
    assert count["value"] == 37 and count["source"]["result_ref"] == "model_results:ols_1"

    repository = JsonlSessionRepository(project.root / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    # Conversation values, even the actual residual df, do not bind a report's sample size.
    repository.append("s", "message", {"role": "tool", "name": "inspect_operation_artifact",
                                         "content": {"df_resid": kernel["df_resid"], "some_other_count": 38}})
    tools = ToolRegistry()
    provider = NodeOperationContextProvider(project.root)
    for definition in provider.tool_definitions(chain_id="c", session_id="s"):
        tools.register(definition)

    def call(tool_id, call_id, **args):
        return asyncio.run(tools.execute({"tool_id": tool_id, "tool_call_id": call_id,
                                          "arguments": {"run_id": run_id, **args}}, session_id="s"))

    cases = {
        "cited_literal": ("OLS sample size", f"The OLS fit used 38 observations [[c:{count['id']}]]."),
        "other_field_literal": ("OLS sample size", "The OLS fit used 35 observations."),
        "explicit_nobs": ("OLS sample size", "The fit reported nobs = **35**."),
        "expanded_label": ("OLS sample size", "Number of observations (N): 35."),
        "sample_of": ("OLS sample size", "The model was fit on a sample of 35."),
        "wrong_marker": ("OLS sample size", f"The fit used [[v:{wrong_field['id']}]] observations."),
        "literal_title": ("OLS fit (N = 38)", "The reported fit is discussed below."),
    }
    receipts = {name: call("save_report_version", name, title=title, text=body) for name, (title, body) in cases.items()}
    assert not any(receipt.ok for receipt in receipts.values()), {name: receipt.ok for name, receipt in receipts.items()}
    assert all("REPORT_SAMPLE_SIZE_UNBOUND" in receipt.error_details[0]["message"] for receipt in receipts.values())
    assert client.get(route, params=params).json()["reports"] == []
    assert not any(entry["artifact_type"] == "manual_report"
                   for entry in read_json(run_root / "artifacts_index.json")["artifacts"])

    read = call("read_reports", "read")
    assert read.ok, read.error_details
    published_count = next(fact for fact in read.output["facts"] if fact["id"] == count["id"])
    assert published_count["field"] == "model/nobs" and published_count["source"]["run_id"] == run_id
    good = call("save_report_version", "bound", title="OLS sample size",
                text=f"The OLS fit used [[v:{count['id']}]] observations.")
    assert good.ok, good.error_details
    report_id = good.output["report_id"]
    exported = client.get(f"{route}/{report_id}/export", params={**params, "format": "html"})
    assert exported.status_code == 200, exported.text
    assert "The OLS fit used 37 observations." in exported.text
    assert f"model_results:ols_1; {count['id']}" in exported.text
    history = client.get(route, params=params).json()["reports"]
    assert len(history) == 1 and history[0]["id"] == report_id and history[0]["author"] == "agent"
    assert sha256_file(model) == model_digest
    entry = next(entry for entry in read_json(run_root / "artifacts_index.json")["artifacts"]
                 if entry["artifact_id"] == f"manual_report_{report_id}")
    assert sha256_file(run_root / entry["path"]) == entry["sha256"]


def test_human_report_prose_remains_editable_with_a_count_citation(report_case):
    snapshot = draft(report_case)
    count = next(fact for fact in snapshot["facts"] if fact["field"] == "model/nobs")
    text = f"I expected 25 observations, but the registered sample size is [[v:{count['id']}]]."
    saved = post(report_case, request_for(snapshot, text=text))
    assert saved.status_code == 200, saved.text
    assert saved.json()["record"]["text"] == text
    client, project, run, _ = report_case
    exported = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root), "format": "html"})
    assert exported.status_code == 200, exported.text
    assert "I expected 25 observations, but the registered sample size is 24." in exported.text


def test_agent_report_binds_each_count_to_its_model_in_a_multi_model_run(report_case):
    from workbench.api_errors import WorkbenchAPIError
    from workbench.services.manual_reports import ManualReportRequest, save_manual_report

    _, _, run, model = report_case
    other = run.root / "model_results/ols_2.json"
    write_json(other, {**model, "model_id": "ols_2", "nobs": 22})
    register_artifact(run.root, "ols_2", other, "model_result", "econometrics", [])
    snapshot = draft(report_case)
    facts = {(fact["source"]["node_key"], fact["field"]): fact["id"] for fact in snapshot["facts"]}
    primary = f"[[v:{facts['model:ols_1', 'model/id']}]]"
    wrong_count = f"[[v:{facts['model:ols_2', 'model/nobs']}]]"
    for bad in (f"{primary} used {wrong_count} observations.", f"The fit used {wrong_count} observations."):
        request = ManualReportRequest(**request_for(snapshot, text=bad))
        with pytest.raises(WorkbenchAPIError, match="model/id") as failure:
            save_manual_report(run.root, request, author="agent")
        assert failure.value.code == "REPORT_SAMPLE_SIZE_UNBOUND"

    request = ManualReportRequest(**request_for(snapshot, text=snapshot["text"]))
    saved = save_manual_report(run.root, request, author="agent")
    assert saved["record"]["id"] == "mrpt_first" and saved["record"]["author"] == "agent"
    client, project, _, _ = report_case
    exported = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root), "format": "html"})
    assert exported.status_code == 200, exported.text
    assert "ols_1 was estimated on 24 observations" in exported.text
    assert "ols_2 was estimated on 22 observations" in exported.text


def test_agent_report_checks_the_run_models_when_a_parent_selected_one_count(report_case):
    from workbench.api_errors import WorkbenchAPIError
    from workbench.artifacts import read_json
    from workbench.services.manual_reports import ManualReportRequest, save_manual_report

    _, _, run, model = report_case
    other = run.root / "model_results/ols_2.json"
    write_json(other, {**model, "model_id": "ols_2", "nobs": 22})
    register_artifact(run.root, "ols_2", other, "model_result", "econometrics", [])
    snapshot = draft(report_case)
    count = next(fact for fact in snapshot["facts"]
                 if fact["source"]["node_key"] == "model:ols_2" and fact["field"] == "model/nobs")
    selected = request_for(snapshot, fact_ids=[count["id"]])
    parent = post(report_case, selected)
    assert parent.status_code == 200, parent.text
    request = ManualReportRequest(**{**selected, "id": "mrpt_child", "parent_report_id": selected["id"],
                                    "text": f"ols_1 used [[v:{count['id']}]] observations."})
    with pytest.raises(WorkbenchAPIError, match="model/id") as failure:
        save_manual_report(run.root, request, author="agent")
    assert failure.value.code == "REPORT_SAMPLE_SIZE_UNBOUND"
    model_id = next(fact for fact in snapshot["facts"]
                    if fact["source"]["node_key"] == "model:ols_2" and fact["field"] == "model/id")
    new = ManualReportRequest(**request_for(snapshot, id="mrpt_scoped", fact_ids=[model_id["id"], count["id"]],
                                          text=f"[[v:{model_id['id']}]] used [[v:{count['id']}]] observations."))
    save_manual_report(run.root, new, author="agent")
    saved = read_json(run.root / "reports/manual_report_mrpt_scoped.json")
    assert saved["model_sample_size_scope"] == {"bases": {"model:ols_2": "rows"}, "require_model_id": True}


def test_unit_based_model_sample_size_uses_its_registered_basis(report_case):
    from workbench.api_errors import WorkbenchAPIError
    from workbench.engine.stages.report import _refresh_artifact_checksum
    from workbench.services.manual_reports import ManualReportRequest, save_manual_report
    from workbench.services.manual_report_text import render_values

    client, project, run, model = report_case
    model_path = run.root / "model_results/ols_1.json"
    write_json(model_path, {**model, "model_type": "cs_did", "nobs_basis": "units", "n_rows": 96})
    _refresh_artifact_checksum(run.root, "ols_1", model_path)
    snapshot = draft(report_case)
    facts = {fact["id"]: fact for fact in snapshot["facts"]}
    count = next(fact for fact in facts.values() if fact["field"] == "model/nobs")
    marker = f"[[v:{count['id']}]]"
    estimate = next(fact for fact in facts.values() if fact["field"] == "coefficient/x/estimate")
    bad = ManualReportRequest(**request_for(snapshot, fact_ids=[count["id"], estimate["id"]],
                                          text=f"The fit used {marker} observations."))
    with pytest.raises(WorkbenchAPIError, match="units") as failure:
        save_manual_report(run.root, bad, author="agent")
    assert failure.value.code == "REPORT_SAMPLE_SIZE_UNBOUND"
    assert "Estimated on 24 units" in render_values(snapshot["text"], facts)
    assert "Units 24" in render_values(snapshot["text"], facts)

    good = bad.model_copy(update={"text": f"The fit used {marker} units. The change was [[v:{estimate['id']}]] index units."})
    first = save_manual_report(run.root, good, author="agent")
    assert save_manual_report(run.root, good, author="agent") == first
    assert list(first) == ["schema_version", "record"]
    # A source update cannot reinterpret a saved version's count basis.
    write_json(model_path, {**model, "nobs": 96})
    _refresh_artifact_checksum(run.root, "ols_1", model_path)
    exported = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root), "format": "html"})
    assert exported.status_code == 200, exported.text
    assert "The fit used 24 units." in exported.text
    report_path = run.root / "reports/manual_report_mrpt_first.json"
    report_path.write_bytes(report_path.read_bytes() + b"\n")
    changed = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                         params={"project_root": str(project.root), "format": "html"})
    assert changed.status_code == 409 and "registered revision" in changed.text


def test_legacy_agent_report_history_preserves_text_and_rechecks_export(report_case):
    from workbench.engine.stages.report import _refresh_artifact_checksum

    snapshot = draft(report_case)
    count = next(fact for fact in snapshot["facts"] if fact["field"] == "model/nobs")
    client, project, run, _ = report_case
    route = f"/runs/{run.run_id}/manual-reports"
    params = {"project_root": str(project.root)}
    archived_requests = {}
    archived_bytes = {}
    for status, text in (("bound", f"The fit used [[v:{count['id']}]] observations."),
                         ("unbound", "Number of observations (N): 25.")):
        request = request_for(snapshot, id=f"mrpt_{status}", text=text)
        saved = post(report_case, request)
        assert saved.status_code == 200, saved.text
        # Reproduce a registered revision from before Agent sample-size validation.
        payload = saved.json()
        payload["record"]["author"] = "agent"
        path = run.root / "reports" / f"manual_report_{request['id']}.json"
        write_json(path, payload)
        _refresh_artifact_checksum(run.root, f"manual_report_{request['id']}", path)
        archived_requests[status] = request
        archived_bytes[path] = path.read_bytes()

    history = client.get(route, params=params).json()["reports"]
    assert {item["text"] for item in history} == {request["text"] for request in archived_requests.values()}
    assert all(any("older Agent revision" in line for line in item["limitations"]) for item in history)
    exported = client.get(f"{route}/mrpt_bound/export", params={**params, "format": "html"})
    refused = client.get(f"{route}/mrpt_unbound/export", params={**params, "format": "html"})
    assert exported.status_code == 200 and "The fit used 24 observations." in exported.text
    assert refused.status_code == 422 and "REPORT_SAMPLE_SIZE_UNBOUND" in refused.text

    previous = archived_requests["unbound"]
    successor = post(report_case, {**previous, "id": "mrpt_repaired", "parent_report_id": previous["id"],
                                  "text": f"Number of observations (N): [[v:{count['id']}]]."})
    assert successor.status_code == 200 and successor.json()["record"]["author"] == "user"
    assert all(path.read_bytes() == data for path, data in archived_bytes.items())


def test_draft_reads_as_prose_with_every_number_bound_to_a_fact(report_case):
    from workbench.services.manual_report_text import render_values, resolve, value_ids
    snapshot = draft(report_case)
    facts = {fact["id"]: fact for fact in snapshot["facts"]}
    assert "[[c:" not in snapshot["text"] and value_ids(snapshot["text"])
    # Every marker names exactly one fact of the snapshot.
    assert all(resolve(marker, facts) for marker in value_ids(snapshot["text"]))
    shown = render_values(snapshot["text"], facts)
    assert "### Estimates" in shown and "1.25" in shown and "p 0.004" in shown
    assert "coefficient · " not in shown and "metric · " not in shown, "lines are prose, not field paths"


def test_value_markers_name_one_fact_by_a_short_prefix():
    from workbench.services.manual_report_text import resolve, render_values
    facts = {"f_aaaaaaaaaa11": {"id": "f_aaaaaaaaaa11", "field": "x/estimate", "value": 2.5},
             "f_aaaaaaaaaa22": {"id": "f_aaaaaaaaaa22", "field": "x/p_value", "value": 0.0}}
    assert resolve("f_aaaaaaaaaa1", facts) == "f_aaaaaaaaaa11"
    assert resolve("f_aaaaaaaa", facts) is None, "a prefix shared by two facts names neither"
    assert resolve("f_aaa", facts) is None, "too short to be a reference"
    assert render_values("b = [[v:f_aaaaaaaaaa1]], p [[v:f_aaaaaaaaaa2]]", facts) == "b = 2.5, p < 0.001"


def test_text_may_show_only_selected_facts(report_case):
    snapshot = draft(report_case)
    first, second = snapshot["facts"][0], snapshot["facts"][1]
    payload = request_for(snapshot, fact_ids=[first["id"]], text=f"Value [[v:{second['id']}]].")
    response = post(report_case, payload)
    assert response.status_code == 422 and "not in the selected evidence" in response.text


@pytest.mark.parametrize("field,value", [("fact_ids", ["foreign_fact"]), ("figure_ids", ["foreign_figure"]),
                                          ("facts", [{"estimate": 999}]), ("path", "../../secret")])
def test_rejects_client_evidence_or_unknown_selection(report_case, field, value):
    response = post(report_case, request_for(draft(report_case), **{field: value}))
    assert response.status_code == 422


def test_stale_source_and_changed_figure_fail_closed(report_case):
    snapshot = draft(report_case)
    _, _, run, result = report_case
    result["coefficients"]["x"]["estimate"] = 9
    write_json(run.root / "model_results/ols_1.json", result)
    response = post(report_case, request_for(snapshot))
    assert response.status_code == 409
    from workbench.engine.stages.report import _refresh_artifact_checksum
    _refresh_artifact_checksum(run.root, "ols_1", run.root / "model_results/ols_1.json")
    snapshot = draft(report_case)
    (run.root / "figures/coef.png").write_bytes(b"changed")
    assert post(report_case, request_for(snapshot)).status_code == 409


def test_immutable_idempotent_revisions_and_parent_evidence(report_case):
    payload = request_for(draft(report_case))
    first = post(report_case, payload)
    assert first.status_code == 200
    assert post(report_case, payload).json() == first.json()
    assert post(report_case, {**payload, "text": "Overwrite"}).status_code == 409
    revision = {**payload, "id": "mrpt_second", "parent_report_id": "mrpt_first", "text": "Edited prose"}
    second = post(report_case, revision)
    assert second.status_code == 200, second.text
    assert second.json()["record"]["revision_number"] == 2
    assert first.json()["record"]["facts"] == second.json()["record"]["facts"]
    assert post(report_case, {**revision, "id": "mrpt_fork"}).status_code == 409
    assert post(report_case, {**revision, "id": "mrpt_third", "parent_report_id": "mrpt_second", "fact_ids": []}).status_code == 409


def test_simultaneous_different_content_same_id_has_one_winner(report_case):
    payload = request_for(draft(report_case))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda text: post(report_case, {**payload, "text": text}), ["Alpha", "Beta"]))
    assert sorted(item.status_code for item in results) == [200, 409]


def test_export_rejects_changed_assets_and_foreign_run(report_case):
    assert post(report_case, request_for(draft(report_case))).status_code == 200
    client, project, run, _ = report_case
    (run.root / "figures/coef.png").write_bytes(b"replacement")
    response = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root), "format": "html"})
    assert response.status_code == 409
    other = create_run(project.root, mode="auto")
    response = client.get(f"/runs/{other.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root), "format": "html"})
    assert response.status_code == 404


def test_registered_statistics_are_preserved_and_bad_citations_rejected(report_case):
    from workbench.statistical_tests import build_statistics_evidence_packet
    _, _, run, _ = report_case
    result = {"test_id": "welch_x", "test_version": 1, "test_type": "welch_t_test",
              "nobs": 24, "statistic": 2.9, "p_value": .008, "effect_size": .7,
              "assumptions": [], "warnings": []}
    packet = build_statistics_evidence_packet([result], dataset_sha256="a" * 64, lineage_parent="stage:raw")
    path = run.root / "statistical_tests/evidence.json"
    write_json(path, packet)
    register_artifact(run.root, "statistics_evidence", path, "statistical_test", "statistical_tests", [])
    snapshot = draft(report_case)
    test_facts = [fact for fact in snapshot["facts"] if fact["source"]["artifact_ids"] == ["statistics_evidence"]]
    assert any(fact["field"].endswith("/p_value") and fact["value"] == .008 for fact in test_facts)
    assert post(report_case, request_for(snapshot, text="Fake citation [[c:foreign]]")).status_code == 422
    assert post(report_case, request_for(snapshot, text="Foreign figure [[fig:foreign]]")).status_code == 422
    assert post(report_case, request_for(snapshot)).status_code == 200


def test_inference_change_invalidates_snapshot_and_draft_is_read_only(report_case):
    _, _, run, result = report_case
    before = {p.relative_to(run.root): p.read_bytes() for p in run.root.rglob("*") if p.is_file()}
    snapshot = draft(report_case)
    after = {p.relative_to(run.root): p.read_bytes() for p in run.root.rglob("*") if p.is_file()}
    assert before == after
    result["covariance_estimator"] = "HC3"
    write_json(run.root / "model_results/ols_1.json", result)
    assert post(report_case, request_for(snapshot)).status_code == 409


def test_manual_routes_declare_success_response_schemas(report_case):
    paths = report_case[0].app.openapi()["paths"]
    for path, verbs in paths.items():
        for operation in verbs.values():
            content = operation["responses"]["200"]["content"]
            if path.endswith("/export"):
                assert "application/octet-stream" in content
            else:
                assert "$ref" in content["application/json"]["schema"]


def test_fact_identities_do_not_alias_terms_with_path_separators(report_case):
    _, _, run, result = report_case
    result["coefficients"]["x"]["inference"] = {"std_error": .2}
    result["coefficients"]["x/inference"] = {"estimate": 3, "std_error": .4}
    write_json(run.root / "model_results/ols_1.json", result)
    from workbench.engine.stages.report import _refresh_artifact_checksum
    _refresh_artifact_checksum(run.root, "ols_1", run.root / "model_results/ols_1.json")
    snapshot = draft(report_case)
    identities = [fact["id"] for fact in snapshot["facts"]]
    assert len(identities) == len(set(identities))


def test_post_estimation_facts_keep_the_owning_run_and_reject_corruption(report_case):
    _, project, run, _ = report_case
    source_run = create_run(project.root, mode="auto")
    path = source_run.root / "workflow_joint_test.json"
    write_json(path, {"source": {"run_id": source_run.run_id, "model_run_id": run.run_id,
                                "workflow_id": "wf_saved", "workflow_step_id": "joint_test",
                                "operation_id": "model.joint_f_test"},
                      "result": {"f_statistic": 4.1, "p_value": .03}})
    register_artifact(source_run.root, "joint_test", path, "statistical_test", "model.joint_f_test", [])
    snapshot = draft(report_case)
    facts = [fact for fact in snapshot["facts"] if fact["source"]["artifact_ids"] == ["joint_test"]]
    assert facts and all(fact["source"]["run_id"] == source_run.run_id for fact in facts)
    assert any(fact["value"] == .03 for fact in facts)
    path.write_text("{}")
    client = report_case[0]
    response = client.get(f"/runs/{run.run_id}/manual-reports/draft", params={"project_root": str(project.root)})
    assert response.status_code == 422


def _draft_response(case):
    client, project, run, _ = case
    return client.get(f"/runs/{run.run_id}/manual-reports/draft", params={"project_root": str(project.root)})


@pytest.mark.parametrize("link", [False, True])
def test_unregistered_foreign_model_is_never_a_report_fact(report_case, link):
    import copy
    _, project, run, result = report_case
    other = create_run(project.root, mode="auto")
    foreign = copy.deepcopy(result)
    foreign["model_id"] = "foreign_model"
    foreign["coefficients"]["x"]["estimate"] = 654321
    path = other.root / "model_results/foreign_model.json"
    write_json(path, foreign)
    register_artifact(other.root, "foreign_model", path, "model_result", "econometrics", [])
    target = run.root / "model_results/foreign_model.json"
    if link:
        target.symlink_to(path)
    else:
        target.write_bytes(path.read_bytes())
    snapshot = draft(report_case)
    assert "foreign_model" not in str(snapshot)
    assert not any(fact["value"] == 654321 for fact in snapshot["facts"])
    assert any(fact["value"] == 1.25 for fact in snapshot["facts"])


@pytest.mark.parametrize("corruption", ["hash", "identity", "run_identity", "symlink"])
def test_registered_model_requires_hash_and_current_run_identity(report_case, corruption):
    _, project, run, result = report_case
    path = run.root / "model_results/ols_1.json"
    if corruption == "hash":
        result["coefficients"]["x"]["estimate"] = 1234
        write_json(path, result)
    elif corruption in {"identity", "run_identity"}:
        result["model_id" if corruption == "identity" else "run_id"] = "foreign"
        write_json(path, result)
        from workbench.artifacts import sha256_file
        import json
        index = json.loads((run.root / "artifacts_index.json").read_text())
        next(record for record in index["artifacts"] if record["artifact_id"] == "ols_1")["sha256"] = sha256_file(path)
        write_json(run.root / "artifacts_index.json", index)
    else:
        other = create_run(project.root, mode="auto")
        foreign = other.root / "model_results/ols_1.json"
        foreign.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(foreign)
    response = _draft_response(report_case)
    assert response.status_code == (409 if corruption == "hash" else 422), response.text


@pytest.mark.parametrize("corruption", ["unregistered", "hash", "run_identity", "symlink"])
def test_report_diagnostics_require_registration_integrity_and_run_identity(report_case, corruption):
    _, project, run, _ = report_case
    path = run.root / "diagnostic_summary.json"
    packet = {"run_id": run.run_id, "model_identity": {"n_observations": 24},
              "model_quality": {"metrics": {"r_squared": .73}}}
    if corruption == "run_identity":
        packet["run_id"] = "foreign"
    write_json(path, packet)
    if corruption != "unregistered":
        register_artifact(run.root, "diagnostic_summary", path, "metadata", "diagnostics", [])
    if corruption == "hash":
        packet["model_quality"]["metrics"]["r_squared"] = .999
        write_json(path, packet)
    if corruption == "symlink":
        other = create_run(project.root, mode="auto")
        foreign = other.root / "diagnostic_summary.json"
        foreign.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(foreign)
    response = _draft_response(report_case)
    if corruption == "unregistered":
        assert response.status_code == 200, response.text
        assert not any(fact["field"].startswith("metric/") for fact in response.json()["facts"])
    else:
        assert response.status_code == (409 if corruption == "hash" else 422), response.text


def test_registered_diagnostic_metrics_and_family_sidecars_keep_their_values(report_case):
    _, _, run, result = report_case
    summary = run.root / "diagnostic_summary.json"
    write_json(summary, {"run_id": run.run_id, "model_identity": {"n_observations": 24},
                         "model_quality": {"metrics": {"r_squared": .73}}})
    register_artifact(run.root, "diagnostic_summary", summary, "metadata", "diagnostics", [])
    snapshot = draft(report_case)
    assert any(fact["field"] == "metric/r_squared" and fact["value"] == .73 for fact in snapshot["facts"])
    # Use the actual ordinal sidecar declaration and writer's artifact identity.
    result["model_type"] = "ordinal_logit"
    result["model_id"] = "ordinal_logit_1"
    primary = run.root / "model_results/ordinal_logit_1.json"
    write_json(primary, result)
    from workbench.artifact_index import artifact_index_transaction
    with artifact_index_transaction(run.root) as index:
        index["artifacts"] = [record for record in index["artifacts"] if record["artifact_id"] != "ols_1"]
    register_artifact(run.root, "ordinal_logit_1", primary, "model_result", "econometrics", [])
    sidecar = run.root / "model_results/diagnostics_ordinal_logit_1.json"
    write_json(sidecar, {"contract": "workbench.ordinal_logit.diagnostics.v1", "model_type": "ordinal_logit",
                         "parallel_lines": {"status": "checked", "slope_ranges": {"x": 765432}}})
    assert 765432 not in [fact["value"] for fact in draft(report_case)["facts"]]
    register_artifact(run.root, "diagnostics_ordinal_logit_1", sidecar, "model_diagnostic", "model_families", ["cleaned_dataset"])
    assert 765432 in [fact["value"] for fact in draft(report_case)["facts"]]
    sidecar.write_text("{}")
    assert _draft_response(report_case).status_code == 409
