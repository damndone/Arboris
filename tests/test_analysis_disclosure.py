"""v1.8.9 trust round — a report discloses the analysis path behind it."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench import analysis_ledger
from workbench.analysis_ledger import LedgerEntry, LedgerStep
from workbench.api import app
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(project_root: Path, tmp_path: Path, name: str, seed: int) -> str:
    rng = np.random.default_rng(seed)
    source = tmp_path / f"{name}.csv"
    pd.DataFrame({"y": rng.normal(size=60), "x": rng.normal(size=60)}).to_csv(source, index=False)
    outcome = run_workflow(project_root, [source], mode="auto", model_type="ols", y="y", x=["x"])
    assert outcome["status"] == "completed", outcome
    return outcome["run_id"]


@pytest.fixture()
def project(tmp_path: Path):
    root = create_project(tmp_path, "p").root
    main = _run(root, tmp_path, "survey", 1)
    other = _run(root, tmp_path, "unrelated", 2)
    analysis_ledger.record(root, LedgerEntry(
        actor="agent", authorized_by="read_only_policy", source="operation.multi_step", status="completed",
        steps=(LedgerStep.of("test.t_tests"), LedgerStep.of("test.anova"), LedgerStep.of("statistical.explore")),
        run_id=main,
    ))
    analysis_ledger.record_ui_action(root, source="POST /data-operations/transform/confirm",
                                     steps=["data.subset"], run_id=main, summary='{"condition": "age < 60"}')
    # A deleted run's files are gone; the entry stays attributable through the
    # upload hash recorded before deletion.
    analysis_ledger.record_ui_action(root, source="POST /runs/{run_id}/deletion-confirmation",
                                     steps=["run.delete"], run_id="run_deleted_earlier",
                                     source_upload_sha256=analysis_ledger.upload_sha(root, main))
    analysis_ledger.record(root, LedgerEntry(
        actor="agent", authorized_by="user", source="operation.multi_step", status="completed",
        steps=(LedgerStep.of("test.chi_square"),), run_id=other,
    ))
    return root, main, other


def test_the_disclosure_counts_what_was_done_to_the_same_data(project) -> None:
    root, main, _other = project
    value = TestClient(app).get(f"/runs/{main}/analysis-disclosure", params={"project_root": str(root)}).json()

    assert value["counts"]["inferential_tests"] == 2  # the chi-square on unrelated data is not counted
    assert value["counts"]["data_changes"] == 1
    assert value["counts"]["run_deletions"] == 1
    assert value["inferential_tests_by"] == {"agent_without_confirmation": 2, "user": 0}
    assert [item["what"] for item in value["changes"]] == ["data.subset", "run.delete"]
    assert "Inferential tests run on this data: 2 (Agent without confirmation: 2" in value["markdown"]
    assert "age < 60" in value["markdown"]
    assert value["settings"] == {"include_in_exports": True, "detail": "summary"}


def test_exported_reports_include_the_disclosure_unless_the_user_turns_it_off(project) -> None:
    root, main, _other = project
    client = TestClient(app)
    params = {"project_root": str(root)}

    def exported() -> str:
        response = client.post(
            f"/runs/{main}/report/export", params={**params, "format": "html"},
            json={"markdown": "# Findings\n\nx is associated with y.", "figures": []},
        )
        assert response.status_code == 200, response.text
        return response.text

    assert "Analysis path disclosure" in exported()

    full = client.put("/projects/report-disclosure", params=params, json={"include_in_exports": True, "detail": "full"})
    assert full.status_code == 200, full.text
    assert "Full analysis log" in exported()

    off = client.put("/projects/report-disclosure", params=params, json={"include_in_exports": False, "detail": "summary"})
    assert off.status_code == 200
    assert "Analysis path disclosure" not in exported()

    # Turning it off is recorded, and the next disclosure shows it.
    settings_changes = [entry for entry in analysis_ledger.read(root) if entry["source"] == "PUT /projects/report-disclosure"]
    assert [entry["summary"] for entry in settings_changes] == [
        "include_in_exports=True detail=full", "include_in_exports=False detail=summary",
    ]
    view = client.get(f"/runs/{main}/analysis-disclosure", params=params).json()
    assert [item["summary"] for item in view["entries"] if item["what"] == "report.disclosure_setting"] == [
        "include_in_exports=True detail=full", "include_in_exports=False detail=summary",
    ]
