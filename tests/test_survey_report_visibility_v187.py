"""v1.8.7 A1-1 — the design has to be visible where the user reads results.

§6 opens by rejecting "the function is implemented and unit-tested" as an
acceptance criterion, because v1.8.6 shipped five features that passed their
tests and no user could reach. A design-based standard error that appears only
in a JSON artifact is the same shape of failure: the number a reader takes away
comes from the report and the exported table, and if the design is absent there,
the report silently claims a precision the analysis did not have.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "survey"


@pytest.fixture(scope="module")
def survey_run(tmp_path_factory) -> Path:
    tmp_path = tmp_path_factory.mktemp("survey_report")
    source = tmp_path / "design.csv"
    source.write_text((FIXTURES / "design.csv").read_text())
    project = create_project(tmp_path, "survey_report")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols",
        y="y", x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu", survey_fpc_col="fpc",
    )
    assert outcome["status"] == "completed", outcome
    return project.root / "runs" / outcome["run_id"]


def test_the_report_states_that_the_standard_errors_are_design_based(survey_run):
    """Otherwise the reader has no way to know which variance they are reading."""
    html = (survey_run / "reports" / "report.html").read_text().lower()

    assert "design" in html, "the report never mentions the design at all"
    for token in ("stratum", "psu"):
        assert token in html, f"the report does not name the {token} column"
    # The two numbers that qualify every interval in the document.
    design = read_json(survey_run / "model_results" / "ols_1.json")["survey_design"]
    assert str(design["degf"]) in html, "the design degrees of freedom are absent"
    assert f"{design['design_effect']:.2f}" in html, "the design effect is absent"


def test_the_report_omits_the_design_section_when_none_was_declared(tmp_path):
    """A section that appears on every run stops carrying information."""
    frame = pd.read_csv(FIXTURES / "design.csv")
    source = tmp_path / "plain.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "plain_report")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2"]
    )
    assert outcome["status"] == "completed", outcome

    html = (
        project.root / "runs" / outcome["run_id"] / "reports" / "report.html"
    ).read_text().lower()
    assert "design effect" not in html
    assert "design-based" not in html


def test_the_exported_result_table_carries_the_design(survey_run):
    """The XLSX export is what gets pasted into a paper; it has to travel too."""
    from workbench.report_view_model import (
        build_regression_table,
        regression_table_export_rows,
    )

    result = read_json(survey_run / "model_results" / "ols_1.json")
    table = build_regression_table([("ols_1", result)])
    rows = regression_table_export_rows(table)
    assert rows, "no export rows were produced"

    text = "\n".join(
        f"{key} {value}" for row in rows for key, value in row.items()
    ).lower()

    design = result["survey_design"]
    assert "design" in text, "the exported table never mentions the design"
    assert str(design["degf"]) in text, "the exported table omits the design degf"
