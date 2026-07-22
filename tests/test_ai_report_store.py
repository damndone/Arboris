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
    }
    client = TestClient(app)
    saved = client.post(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)}, json=payload)
    assert saved.status_code == 200
    history = client.get(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)})
    assert history.status_code == 200
    assert history.json()["reports"][0]["id"] == "rpt_abc123"
    payload["scope"]["run_id"] = "other-run"
    mismatch = client.post(f"/runs/{run.run_id}/ai-reports", params={"project_root": str(project.root)}, json=payload)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "AI_REPORT_SCOPE_MISMATCH"
