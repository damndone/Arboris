from __future__ import annotations

import json
from pathlib import Path


def test_ai_report_store_persists_auditable_record_and_registers_artifact(tmp_path: Path) -> None:
    from workbench.report_store import list_ai_reports, save_ai_report

    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    stored = save_ai_report(
        run_root,
        {
            "id": "rpt_abc123", "generatedAt": "2026-07-21T22:17:30Z", "model": "deepseek-v4-pro",
            "instruction": "Write an evidence-bound report.", "text": "# Result\n[[c:f1]]",
            "scope": {"run_id": "run-1", "node_count": 2}, "facts": [{"id": "f1", "value": 7.44}],
            "excluded_fact_ids": [], "figures": [],
        },
    )

    assert stored["record"]["model"] == "deepseek-v4-pro"
    assert stored["record"]["fact_snapshot_hash"].startswith("sha256:")
    assert stored["record"]["artifact_ids"] == []
    assert stored["record"]["validation_status"] == "exportable"
    assert (run_root / "reports" / "ai_report_rpt_abc123.json").is_file()
    assert list_ai_reports(run_root)[0]["id"] == "rpt_abc123"
    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert any(item["artifact_id"] == "ai_report_rpt_abc123" for item in index["artifacts"])


def test_ai_report_routes_reject_scope_mismatch_and_return_durable_history(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    payload = {
        "id": "rpt_abc123", "generatedAt": "2026-07-21T22:17:30Z", "instruction": "Write report", "text": "# Result",
        "scope": {"run_id": run.run_id, "node_count": 1}, "facts": [], "excluded_fact_ids": [], "figures": [],
        "excluded_figure_ids": ["histograms"],
    }
    client = TestClient(app)
    saved = client.post(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)}, json=payload)
    assert saved.status_code == 200
    history = client.get(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)})
    assert history.status_code == 200
    assert history.json()["reports"][0]["id"] == "rpt_abc123"
    assert history.json()["reports"][0]["excluded_figure_ids"] == ["histograms"]
    payload["scope"]["run_id"] = "other-run"
    mismatch = client.post(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)}, json=payload)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "AI_REPORT_SCOPE_MISMATCH"


def test_ai_report_route_validates_only_included_figures_from_full_snapshot(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "curated-figures")
    run = create_run(project.root, mode="auto")
    payload = {
        "id": "rpt_curated1",
        "generatedAt": "2026-07-21T22:17:30Z",
        "instruction": "Write report",
        "text": "# Report\nFinding [[c:c1]]\n[[fig:coef_plot]]",
        "scope": {"run_id": run.run_id, "node_count": 1},
        "facts": [
            {"id": "c1", "field": "param:estimate", "value": 1.0},
            {"id": "c2", "field": "figure:histograms:source:value", "value": 2.0},
        ],
        "excluded_fact_ids": [],
        "figures": [
            {"artifact_id": "coef_plot", "chart_type": "coefficient"},
            {"artifact_id": "histograms", "chart_type": "histogram"},
        ],
        "excluded_figure_ids": ["histograms"],
    }

    response = TestClient(app).post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["record"]["excluded_figure_ids"] == ["histograms"]


def test_ai_report_route_rejects_result_overwrite_fields(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "result-boundary")
    run = create_run(project.root, mode="auto")
    payload = {
        "id": "rpt_boundary1",
        "generatedAt": "2026-07-21T22:17:30Z",
        "instruction": "Write report",
        "text": "# Result",
        "scope": {"run_id": run.run_id, "node_count": 1},
        "facts": [],
        "excluded_fact_ids": [],
        "figures": [],
        "model_results": [{"estimate": 999}],
    }

    response = TestClient(app).post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=payload,
    )

    assert response.status_code == 422


def test_ai_report_route_rejects_result_fields_nested_in_revision(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "nested-boundary")
    run = create_run(project.root, mode="auto")
    scope = {"run_id": run.run_id, "node_count": 1}
    payload = {
        "id": "rpt_nested1",
        "generatedAt": "2026-07-21T22:17:30Z",
        "instruction": "Write report",
        "text": "# Result",
        "scope": scope,
        "facts": [],
        "excluded_fact_ids": [],
        "figures": [],
        "revision": {
            "schema_version": "workbench.report.revision/v1",
            "revision_id": "report-doc:rpt_nested1:revision:1",
            "document_id": "report-doc:rpt_nested1",
            "revision_number": 1,
            "created_at": "2026-07-21T22:17:30Z",
            "markdown": "# Result",
            "source": {
                "source_record_id": "rpt_nested1",
                "source_run_id": run.run_id,
                "scope": scope,
                "facts": [],
                "figures": [],
                "excluded_fact_ids": [],
                "dataset": {"rows": [{"y": 999}]},
            },
            "model_results": [{"estimate": 999}],
        },
    }

    response = TestClient(app).post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_REPORT_INVALID"


def test_ai_report_route_rejects_unknown_revision_fields(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "unknown-revision-field")
    run = create_run(project.root, mode="auto")
    scope = {"run_id": run.run_id, "node_count": 1}
    payload = {
        "id": "rpt_unknown_revision1",
        "generatedAt": "2026-07-21T22:17:30Z",
        "instruction": "Write report",
        "text": "# Result",
        "scope": scope,
        "facts": [],
        "excluded_fact_ids": [],
        "figures": [],
        "revision": {
            "schema_version": "workbench.report.revision/v1",
            "revision_id": "report-doc:rpt_unknown_revision1:revision:1",
            "document_id": "report-doc:rpt_unknown_revision1",
            "revision_number": 1,
            "created_at": "2026-07-21T22:17:30Z",
            "markdown": "# Result",
            "source": {
                "source_record_id": "rpt_unknown_revision1",
                "source_report_id": "rpt_unknown_revision1",
                "source_run_id": run.run_id,
                "scope": scope,
                "facts": [],
                "figures": [],
                "excluded_fact_ids": [],
                "unexpected": "must not be persisted",
            },
        },
    }

    response = TestClient(app).post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_REPORT_INVALID"


def test_ai_report_route_allows_new_revision_bound_to_parent_snapshot(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from workbench.app import app
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "report-revision-parent")
    run = create_run(project.root, mode="auto")
    client = TestClient(app)
    parent = {
        "id": "rpt_parent1",
        "generatedAt": "2026-07-21T22:17:30Z",
        "instruction": "Write report",
        "text": "# Original",
        "scope": {"run_id": run.run_id, "node_count": 1},
        "facts": [],
        "excluded_fact_ids": [],
        "figures": [],
    }
    saved_parent = client.post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=parent,
    )
    assert saved_parent.status_code == 200, saved_parent.text

    revision = {
        "schema_version": "workbench.report.revision/v1",
        "revision_id": "report-doc:rpt_parent1:revision:2",
        "document_id": "report-doc:rpt_parent1",
        "revision_number": 2,
        "parent_revision_id": "report-doc:rpt_parent1:revision:1",
        "created_at": "2026-07-21T22:18:30Z",
        "markdown": "# Edited",
        "source": {
            "source_record_id": "rpt_parent1",
            "source_report_id": "rpt_parent1",
            "source_run_id": run.run_id,
            "scope": parent["scope"],
            "facts": [],
            "figures": [],
            "excluded_fact_ids": [],
        },
    }
    child = {**parent, "id": "rpt_child1", "text": "# Edited", "revision": revision}

    saved_child = client.post(
        f"/runs/{run.run_id}/ai-reports",
        params={"project_root": str(project.root)},
        json=child,
    )

    assert saved_child.status_code == 200, saved_child.text
