"""Tests for categorical encoding, batch y routing, and p-value display."""

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


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def csv_path(tmp_path_factory):
    temp = tmp_path_factory.mktemp("catbatch_data")
    csv_path = temp / "test.csv"
    rng = np.random.default_rng(20260505)
    n = 100
    x1 = rng.normal(0, 1, n)

    df = pd.DataFrame({
        "continuous_score_y": (10 + 3 * x1 + rng.normal(0, 2, n)).round(2),
        "binary_success_y": rng.binomial(
            1, 1 / (1 + np.exp(-(-0.5 + 1.2 * x1))), n
        ),
        "count_events_y": rng.poisson(np.exp(0.8 + 0.4 * x1), n).astype(int),
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
    assert 3 <= df["count_events_y"].nunique() <= 20
    df.to_csv(csv_path, index=False)
    return csv_path


# ---------------------------------------------------------------------------
# Test 1: Categorical encoding in formula — Patsy produces C(...) / [T.]
# ---------------------------------------------------------------------------

def test_categorical_encoding_in_formula(csv_path, tmp_path):
    """x7_region_code (string) should be encoded as C(...) in model formula."""
    source = Path(csv_path)
    project = create_project(tmp_path, "cat_formula")

    result = run_workflow(
        project.root, [source], mode="auto",
        y="continuous_score_y", x=X_VARS,
    )
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "ols_1.json")

    cat_terms = [
        t for t in model_result["coefficients"]
        if "C(" in t or "[T." in t
    ]
    assert len(cat_terms) >= 1, (
        "No C(...) or [T. terms found in coefficients — "
        "x7_region_code was not encoded as categorical"
    )


# ---------------------------------------------------------------------------
# Test 2: Categorical interpretation — typed claims avoid numeric units
# ---------------------------------------------------------------------------

def test_categorical_interpretation_contract(csv_path, tmp_path):
    """Typed claims should acknowledge categorical encoding, not numeric units."""
    source = Path(csv_path)
    project = create_project(tmp_path, "cat_claims")

    result = run_workflow(
        project.root, [source], mode="auto",
        y="continuous_score_y", x=X_VARS,
    )
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    summary = read_json(run_root / "diagnostic_summary.json")
    categorical_rows = [
        row for row in summary["coefficients_summary"]["rows"]
        if row["display_name"] == "x7_region_code"
    ]
    assert categorical_rows
    assert all(row["interpretation_guide"] == "categorical_level" for row in categorical_rows)
    assert all(row["template_key"] == "coef_categorical" for row in categorical_rows)
    contract = summary["narrative_contract"]
    assert contract["constraints"]["must_note_categorical_encoded"] is True
    assert contract["constraints"]["allowed_effect_language"] == "association_only"
    assert "categorical auto-encoding" in contract["required_mentions"]
    assert summary["run_status"]["report_render_status"] == "failed"
    assert summary["run_status"]["report_available"] is False


def test_numeric_region_code_encoded_but_team_size_remains_numeric(tmp_path):
    """Integer region/code variables should be categorical; team size remains numeric."""
    rng = np.random.default_rng(20260506)
    n = 180
    x1 = rng.normal(0, 1, n)
    team_size = rng.integers(1, 13, n)
    region = rng.choice([1, 2, 3, 4], n)
    prob = 1 / (1 + np.exp(-(-0.4 + 0.7 * x1 + 0.08 * team_size)))
    frame = pd.DataFrame({
        "binary_success_y": rng.binomial(1, prob, n),
        "x1_budget": x1,
        "x5_team_size": team_size,
        "x7_region_code": region,
    })
    source = tmp_path / "numeric_region.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "numeric_region")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="binary_success_y",
        x=["x1_budget", "x5_team_size", "x7_region_code"],
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "logit_1.json")
    terms = list(model_result["coefficients"])
    assert "x5_team_size" in terms
    assert "x7_region_code" not in terms
    assert any("C(Q('x7_region_code'))" in term for term in terms)

    summary = read_json(run_root / "diagnostic_summary.json")
    rows = summary["coefficients_summary"]["rows"]
    team_rows = [row for row in rows if row["display_name"] == "x5_team_size"]
    region_rows = [row for row in rows if row["display_name"] == "x7_region_code"]
    assert team_rows
    assert all(row["interpretation_guide"] == "standard" for row in team_rows)
    assert region_rows
    assert all(row["interpretation_guide"] == "categorical_level" for row in region_rows)
    assert summary["narrative_contract"]["constraints"]["allowed_effect_language"] == "association_only"
    assert summary["run_status"]["report_render_status"] == "failed"
    assert summary["run_status"]["report_available"] is False


# ---------------------------------------------------------------------------
# Test 3: Batch y parametrized — each y kind infers correct model type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("y,expected_type,model_file", [
    ("continuous_score_y", "ols_robust", "ols_1"),
    ("binary_success_y", "logit", "logit_1"),
    ("count_events_y", "poisson", "poisson_1"),
])
def test_batch_y_model_type(y, expected_type, model_file, csv_path, tmp_path):
    source = Path(csv_path)
    project = create_project(tmp_path, f"batch_{y}")

    result = run_workflow(
        project.root, [source], mode="auto", y=y, x=X_VARS,
    )
    assert result["status"] == "completed", f"Workflow for y={y} failed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / f"{model_file}.json")
    assert model_result["model_type"] == expected_type, (
        f"y={y}: expected {expected_type}, got {model_result['model_type']}"
    )


# ---------------------------------------------------------------------------
# Test 4: p-value display — tiny p-values show as "< 0.001" not "0.0000"
# ---------------------------------------------------------------------------

def test_p_value_preserves_typed_significance_label(csv_path, tmp_path):
    """Very small p-values retain their typed significance label without HTML."""
    source = Path(csv_path)
    project = create_project(tmp_path, "pval")

    result = run_workflow(
        project.root, [source], mode="auto",
        y="count_events_y", x=["x1"],
    )
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "poisson_1.json")
    x1_coef = model_result["coefficients"].get("x1", {})
    assert x1_coef
    pval = x1_coef.get("p_value")
    assert pval is not None, "x1 p_value missing"
    assert round(float(pval), 4) < 0.001, (
        "x1 should be highly significant"
    )
    summary = read_json(run_root / "diagnostic_summary.json")
    x1_rows = [
        row for row in summary["coefficients_summary"]["rows"]
        if row["display_name"] == "x1"
    ]
    assert len(x1_rows) == 1
    assert x1_rows[0]["significance_label"] in {
        "significant at the 1% level",
        "significant at the 5% level",
    }
    assert summary["run_status"]["report_render_status"] == "failed"
    assert summary["run_status"]["report_available"] is False
