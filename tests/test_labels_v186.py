from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path: Path, *, labels: dict[str, object] | None = None) -> Path:
    source = tmp_path / "labels.csv"
    pd.DataFrame(
        {
            "outcome": [float(index) + 0.2 * (index % 3) for index in range(48)],
            "treatment": [float(index) for index in range(48)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "labels")
    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="outcome",
        x=["treatment"],
        model_type="ols",
        labels=labels,
    )
    assert result["status"] == "completed", result
    return project.root / "runs" / result["run_id"]


def test_declared_labels_reach_run_inputs_table_report_xlsx_and_axis_contract(tmp_path: Path) -> None:
    run_root = _run(
        tmp_path,
        labels={
            "variable_labels": {"outcome": "Outcome label", "treatment": "Treatment label"},
            "value_labels": {"treatment": {"0": "Control", "1": "Treated"}},
        },
    )

    inputs = read_json(run_root / "run_inputs.json")
    assert inputs["form"]["labels"]["variable_labels"]["outcome"] == "Outcome label"

    html = (run_root / "reports" / "report.html").read_text(encoding="utf-8")
    assert "Outcome label" in html
    assert "Treatment label" in html
    assert "Control" in html

    workbook = openpyxl.load_workbook(run_root / "exports" / "tables.xlsx", read_only=True)
    table_1 = workbook["table_1"]
    rows = list(table_1.iter_rows(values_only=True))
    assert any("Outcome label" in row for row in rows)
    assert any("Treatment label" in row for row in rows)

    figure_labels = read_json(run_root / "figures" / "figure_labels.json")
    assert figure_labels["scatter_plots"]["x_label"] == "Treatment label"
    assert figure_labels["scatter_plots"]["y_label"] == "Outcome label"


def test_undeclared_labels_use_explicit_column_name_fallback(tmp_path: Path) -> None:
    run_root = _run(tmp_path)
    html = (run_root / "reports" / "report.html").read_text(encoding="utf-8")
    assert "column_name_fallback" in html
    assert "Outcome label" not in html


def test_labels_reject_unknown_top_level_fields(tmp_path: Path) -> None:
    source = tmp_path / "invalid-labels.csv"
    pd.DataFrame({"y": [1.0, 2.0], "x": [1.0, 2.0]}).to_csv(source, index=False)
    project = create_project(tmp_path, "invalid-labels")
    with pytest.raises(ValueError, match="labels"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            labels={"unexpected": {}},
        )
