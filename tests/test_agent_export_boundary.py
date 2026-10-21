"""One admitted export rule applies to manual, Agent and renderer entry points."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_agent_extensions import install, manifest
from tests.test_data_column_cast import _source_project
from tests.test_manual_reports import report_case, draft, request_for, post


def dataset_case(tmp_path):
    from workbench.artifacts import write_json
    root, run_id, artifact = _source_project(tmp_path, pd.DataFrame({"x": [1, 2, 3]}))
    write_json(root / "runs" / run_id / "run_inputs.json", {"form": {}})
    return root, run_id, artifact


def deny_exports(root):
    doc = manifest()
    doc["hooks"][0]["operation_ids"] = ["export"]
    install(root, doc)


@pytest.mark.parametrize("actor", ["agent", "manual", "service"])
def test_same_deny_rule_blocks_dataset_exports_before_writing(tmp_path, actor):
    from workbench.app import app
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.tools import ToolContext
    from workbench.services.data_export import export_dataset

    root, run_id, _ = dataset_case(tmp_path)
    deny_exports(root)
    args = {"run_id": run_id, "node_id": "stage:source", "format": "csv"}
    if actor == "manual":
        response = TestClient(app).post(f"/runs/{run_id}/datasets/export",
            params={"project_root": str(root)}, json={k: v for k, v in args.items() if k != "run_id"})
        assert response.status_code == 403, response.text
        assert "HOOK_DENIED" in response.text
    elif actor == "agent":
        tools = {tool.tool_id: tool for tool in NodeOperationContextProvider(root).tool_definitions(chain_id="c1", session_id="s1")}
        with pytest.raises(ValueError, match="HOOK_DENIED"):
            tools["export_dataset"].handler(args, ToolContext(session_id="s1", metadata={}))
    else:
        with pytest.raises(ValueError, match="HOOK_DENIED"):
            export_dataset(root, run_id, "stage:source", "csv")
    assert not (root / "runs" / run_id / "exports").exists()


def test_same_deny_rule_blocks_saved_manual_report(report_case):
    client, project, run, _ = report_case
    assert post(report_case, request_for(draft(report_case))).status_code == 200
    deny_exports(project.root)
    response = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root)})
    assert response.status_code == 403, response.text
    assert "HOOK_DENIED" in response.text


@pytest.mark.parametrize("format", ["html", "pdf-print", "docx", "tex"])
def test_same_deny_rule_blocks_report_renderer(tmp_path, format):
    from workbench.report_export import export_report
    root = tmp_path / "project"
    run = root / "runs" / "source"
    run.mkdir(parents=True)
    deny_exports(root)
    with pytest.raises(ValueError, match="HOOK_DENIED"):
        export_report(run, markdown="# Findings", figures=[], format=format)


def test_deny_enabled_after_creation_blocks_existing_artifact_download(tmp_path):
    from workbench.app import app
    from workbench.services.data_export import export_dataset
    root, run_id, _ = dataset_case(tmp_path)
    result = export_dataset(root, run_id, "stage:source", "csv")
    deny_exports(root)
    response = TestClient(app).get(result["download_url"], params={"project_root": str(root)})
    assert response.status_code == 403, response.text
    assert "HOOK_DENIED" in response.text


@pytest.mark.parametrize("endpoint,body", [
    ("/report/export?format=html", {"markdown": "# Findings", "figures": []}),
    ("/report/result-table-export", {"sections": ["regression_table"]}),
])
def test_same_deny_rule_blocks_other_report_export_routes(tmp_path, endpoint, body):
    from workbench.app import app
    root, run_id, _ = dataset_case(tmp_path)
    deny_exports(root)
    response = TestClient(app).post(f"/runs/{run_id}{endpoint}",
        params={"project_root": str(root), "format": "html"}, json=body)
    assert response.status_code == 403, response.text


def test_manual_report_nested_renderer_uses_original_project_once(report_case):
    client, project, run, _ = report_case
    assert post(report_case, request_for(draft(report_case))).status_code == 200
    doc = manifest()
    doc["hooks"][0].update(operation_ids=["export"], action="record")
    install(project.root, doc)
    response = client.get(f"/runs/{run.run_id}/manual-reports/mrpt_first/export",
                          params={"project_root": str(project.root)})
    assert response.status_code == 200, response.text
    assert len(list((project.root / "workbench").glob("extension-event-*.json"))) == 1


def test_deny_rule_blocks_agent_audit_before_assembly(tmp_path):
    from workbench.agent.audit_export import build_agent_audit
    deny_exports(tmp_path)
    with pytest.raises(ValueError, match="HOOK_DENIED"):
        build_agent_audit(tmp_path, "session")
