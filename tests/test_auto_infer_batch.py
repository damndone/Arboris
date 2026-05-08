"""Tests for auto-infer model routing and variable handling."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


X_VARS = [
    "x1", "x2", "x3", "x4_time_on_task", "x5", "x6",
    "x7_region_code", "x8", "x9", "x10",
]

ALL_Y = ["continuous_score_y", "binary_success_y", "count_events_y"]


# ---------------------------------------------------------------------------
# Shared data fixture (module-scoped so all tests share one CSV)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def auto_infer_csv_path(tmp_path_factory):
    temp = tmp_path_factory.mktemp("auto_infer_data")
    csv_path = temp / "auto_infer_test.csv"
    rng = np.random.default_rng(20260505)
    n = 100

    x1 = rng.normal(0, 1, n)

    # Continuous y — clear signal, many unique values
    continuous_y = 10 + 3 * x1 + rng.normal(0, 2, n)

    # Binary y — moderate signal, 0/1
    logodds = -0.5 + 1.2 * x1
    binary_y = rng.binomial(1, 1 / (1 + np.exp(-logodds)))

    # Count y — Poisson with varying lambda
    lam = np.exp(0.8 + 0.4 * x1)
    count_y = rng.poisson(lam).astype(int)

    df = pd.DataFrame({
        "continuous_score_y": continuous_y.round(2),
        "binary_success_y": binary_y,
        "count_events_y": count_y,
        "x1": x1.round(3),
        "x2": rng.normal(0, 1, n).round(3),
        "x3": rng.normal(0, 1, n).round(3),
        "x4_time_on_task": rng.integers(0, 120, n),
        "x5": rng.normal(0, 1, n).round(3),
        "x6": rng.normal(0, 1, n).round(3),
        "x7_region_code": rng.choice(["region_A", "region_B", "region_C"], n),
        "x8": rng.normal(0, 1, n).round(3),
        "x9": rng.normal(0, 1, n).round(3),
        "x10": rng.normal(0, 1, n).round(3),
    })

    # Sanity-check count_y qualifies for auto-detection as COUNT
    assert 3 <= df["count_events_y"].nunique() <= 20, (
        f"count_events_y has {df['count_events_y'].nunique()} unique values, "
        f"expected 3-20 for COUNT detection"
    )
    assert df["count_events_y"].min() >= 0
    assert (df["count_events_y"] == df["count_events_y"].astype(int)).all()

    df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Tests 1-3: auto-infer model type for each y kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("y,expected_type,model_file", [
    ("continuous_score_y", "ols_robust", "ols_1"),
    ("binary_success_y", "logit", "logit_1"),
    ("count_events_y", "poisson", "poisson_1"),
])
def test_y_auto_infers_model_type(y, expected_type, model_file,
                                   auto_infer_csv_path, tmp_path):
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, f"test_{y}")

    result = run_workflow(project.root, [source], mode="auto", y=y, x=X_VARS)

    assert result["status"] == "completed", f"Workflow failed for y={y}"
    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / f"{model_file}.json")
    assert model_result["model_type"] == expected_type, (
        f"Expected {expected_type} for y={y}, got {model_result['model_type']}"
    )


# ---------------------------------------------------------------------------
# Test 4: x4_time_on_task is present in coefficients (not silently dropped)
# ---------------------------------------------------------------------------

def test_x4_time_on_task_in_coefficients(auto_infer_csv_path, tmp_path):
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, "test_x4")

    result = run_workflow(project.root, [source], mode="auto",
                          y="continuous_score_y", x=X_VARS)
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "ols_1.json")
    assert "x4_time_on_task" in model_result["coefficients"], (
        "x4_time_on_task was silently dropped from model coefficients"
    )


# ---------------------------------------------------------------------------
# Test 5: x7_region_code diagnostics match final model preprocessing
# ---------------------------------------------------------------------------

def test_x7_region_code_reports_auto_dummy_coded_diagnostic(auto_infer_csv_path, tmp_path):
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, "test_x7")

    result = run_workflow(project.root, [source], mode="auto",
                          y="continuous_score_y", x=X_VARS)
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "ols_1.json")
    assert any("C(Q('x7_region_code'))" in term for term in model_result["coefficients"])

    errors = read_json(run_root / "errors.json")
    auto_dummy = [
        i for i in errors["issues"]
        if i["code"] == "CATEGORICAL_AUTO_DUMMY_CODED"
        and i.get("evidence", {}).get("column") == "x7_region_code"
    ]
    assert len(auto_dummy) == 1
    assert auto_dummy[0]["severity"] == "INFO"
    assert auto_dummy[0]["message"] == (
        "Column 'x7_region_code' was detected as categorical and automatically dummy-coded."
    )
    assert "Consider one-hot encoding" not in auto_dummy[0]["message"]
    assert not any(
        i["code"] == "CATEGORICAL_CANDIDATE"
        and i.get("evidence", {}).get("column") == "x7_region_code"
        for i in errors["issues"]
    )

    html = (run_root / "reports" / "report.html").read_text()
    assert "Column &#39;x7_region_code&#39; was detected as categorical and automatically dummy-coded." in html
    assert "Column &#39;x7_region_code&#39; may be categorical" not in html
    assert "Consider one-hot encoding" not in html


# ---------------------------------------------------------------------------
# Test 6: Sibling y variables are not present in model coefficients
# ---------------------------------------------------------------------------

def test_sibling_y_excluded_from_x(auto_infer_csv_path, tmp_path):
    """Other y-type columns should not appear as model predictors."""
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, "test_sibling")

    result = run_workflow(project.root, [source], mode="auto",
                          y="continuous_score_y", x=X_VARS)
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "ols_1.json")
    for sibling in ["binary_success_y", "count_events_y"]:
        assert sibling not in model_result["coefficients"], (
            f"Sibling y '{sibling}' leaked into model coefficients"
        )


# ---------------------------------------------------------------------------
# Test 7: Each y run produces independent run_id and different formula
# ---------------------------------------------------------------------------

def test_independent_run_ids(auto_infer_csv_path, tmp_path):
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, "multi")

    r1 = run_workflow(project.root, [source], mode="auto",
                      y="continuous_score_y", x=X_VARS)
    assert r1["status"] == "completed"

    r2 = run_workflow(project.root, [source], mode="auto",
                      y="binary_success_y", x=X_VARS)
    assert r2["status"] == "completed"

    # Different run IDs
    assert r1["run_id"] != r2["run_id"], "Run IDs must be unique"

    # Different model types / formulas
    run_root1 = project.root / "runs" / r1["run_id"]
    run_root2 = project.root / "runs" / r2["run_id"]
    m1 = read_json(run_root1 / "model_results" / "ols_1.json")
    m2 = read_json(run_root2 / "model_results" / "logit_1.json")
    assert m1["model_type"] != m2["model_type"], (
        "Expected different model types for continuous vs binary y"
    )


# ---------------------------------------------------------------------------
# Test 8: Report lists used/encoded/dropped variables in facts
# ---------------------------------------------------------------------------

def test_report_lists_variable_info(auto_infer_csv_path, tmp_path):
    source = Path(auto_infer_csv_path)
    project = create_project(tmp_path, "test_report")

    result = run_workflow(project.root, [source], mode="auto",
                          y="continuous_score_y", x=X_VARS)
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    html = (run_root / "reports" / "report.html").read_text()

    # The facts section always includes the "X = ..." line
    assert "X =" in html, "Facts should list X variables"

    # Check a sample of X vars appear somewhere in the report
    for xv in ("x1", "x4_time_on_task", "x10"):
        assert xv in html, f"X variable '{xv}' not mentioned in report"
