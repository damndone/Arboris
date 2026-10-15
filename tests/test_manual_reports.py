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
