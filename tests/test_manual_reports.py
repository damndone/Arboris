"""Offline manual reporting uses persisted evidence, never provider output."""
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
    payload = request_for(snapshot)
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
            assert "Computed evidence" in exported.text and "1.25" in exported.text
        else:
            assert zipfile.is_zipfile(io.BytesIO(exported.content))
    assert __import__('json').loads((run.root / "model_results/ols_1.json").read_text()) == result


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
