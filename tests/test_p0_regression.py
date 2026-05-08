"""Regression tests for P0 bug fixes.

Each test verifies that a known P0 bug remains fixed.
Frontend tests (1, 2) are noted as skipped — see frontend/src/ for those.
"""

import re

import numpy as np
import pandas as pd
import pytest

from workbench.domain import Severity
from workbench.econometrics.diagnostics import compute_diagnostics
from workbench.econometrics.runner import run_ols
from workbench.orchestrator import (
    _check_categorical_candidates,
    _check_dropped_variables,
)
from workbench.router import YKind, detect_y_kind


# --- TEST 1 (Frontend): User X input not overwritten by suggestedX ---
# Bug: refreshPreview in App.tsx overwrote user's manually-entered X with
#       freshly-computed suggestedX on every sheet/transpose change.
# Fix: xManuallySet flag gates the overwrite.
# This is a frontend test — check frontend/src/App.tsx for the xManuallySet
# flag and its usage in refreshPreview.  Skipping here.


# --- TEST 2: suggestedX excludes Y-candidate columns (Frontend logic) ---
# The fix added isOutcomeCandidate() to api.ts to filter columns whose names
# end in outcome-like suffixes from suggestedX.  We mirror the regex in
# Python to verify the filtering logic.

_OUTCOME_SUFFIX_RE = re.compile(r"_y$|_outcome$|_target$|_label$|_response$|_dependent$")


def _is_outcome_candidate(name: str) -> bool:
    """Mirrors isOutcomeCandidate in frontend/src/api.ts."""
    return bool(_OUTCOME_SUFFIX_RE.search(name.lower()))


def test_suggested_x_excludes_outcome_candidates():
    """Columns with outcome-like suffixes are excluded from suggestedX."""
    # These should be identified as outcome candidates
    assert _is_outcome_candidate("binary_success_y")
    assert _is_outcome_candidate("count_events_y")
    assert _is_outcome_candidate("sales_outcome")
    assert _is_outcome_candidate("is_active_target")
    assert _is_outcome_candidate("fraud_label")
    assert _is_outcome_candidate("churn_response")
    assert _is_outcome_candidate("conversion_dependent")
    # These should NOT be identified
    assert not _is_outcome_candidate("x1")
    assert not _is_outcome_candidate("yearly_sales")
    assert not _is_outcome_candidate("binary_success")
    assert not _is_outcome_candidate("response_time")
    assert not _is_outcome_candidate("target_audience")


# --- TEST 3: Dropped variables reported in issues ---

def test_dropped_variables_reported(tmp_path):
    """Zero-variance X column produces a VARIABLE_DROPPED INFO issue."""
    frame = pd.DataFrame({
        "y": [1.0, 2.0, 3.0, 4.0, 5.0],
        "x1": [0.5, 1.0, 1.5, 2.0, 2.5],
        "x2": [1, 1, 1, 1, 1],  # zero variance — should be dropped
    })
    model_results = [
        ("ols_1", {
            "coefficients": {"x1": {"estimate": 2.0, "p_value": 0.01}},
        }),
    ]
    issue_dicts: list[dict] = []
    dropped = _check_dropped_variables(
        ["x1", "x2"], model_results, frame, issue_dicts, tmp_path
    )
    assert any("x2" in d for d in dropped)
    assert any(
        issue["code"] == "VARIABLE_DROPPED" and "x2" in issue["message"]
        for issue in issue_dicts
    )


# --- TEST 4: p-value formatting ---

def test_p_value_formatting():
    """Coefficient p-values < 0.001 display as '< 0.001', not '0.0000'."""
    frame = pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    )
    result, _ = run_ols(frame, y="y", x=["x"], robust=True, model_id="ols_1")
    coef = result["coefficients"]["x"]
    assert coef.get("p_value_display") == "< 0.001"


# --- TEST 5: Auto infer routes correctly ---

def test_auto_infer_routes_count_y_to_poisson():
    """Count outcome should be detected as COUNT (routing to Poisson)."""
    frame = pd.DataFrame({"y": [0, 1, 2, 3, 5, 1, 0, 2]})
    assert detect_y_kind(frame, "y") == YKind.COUNT


def test_auto_infer_routes_named_high_unique_count_y_to_poisson():
    """Named count outcomes with many unique integer values still route to COUNT."""
    frame = pd.DataFrame({"count_events_y": list(range(30))})
    assert detect_y_kind(frame, "count_events_y") == YKind.COUNT


def test_high_unique_count_y_workflow_uses_poisson(tmp_path):
    """End-to-end auto routing should not fall back to OLS for named count y."""
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    frame = pd.DataFrame({
        "count_events_y": list(range(30)) * 3,
        "x1": list(range(90)),
    })
    source = tmp_path / "count_unique_30.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "count_unique_30")

    result = run_workflow(project.root, [source], mode="auto", y="count_events_y", x=["x1"])

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson_result["model_type"] == "poisson"
    assert not (run_root / "model_results" / "ols_1.json").exists()
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["model_routing"] == {
        "requested_model_type": "auto",
        "current_y": "count_events_y",
        "dtype": "int64",
        "min": 0.0,
        "max": 29.0,
        "unique": 30,
        "integer_like": True,
        "data_detected_y_type": "count",
        "effective_y_type": "count",
        "effective_model_id": "poisson_1",
        "effective_model_type": "poisson",
    }


def test_auto_poisson_overdispersion_emits_warning_issue(tmp_path):
    """Auto-inferred Poisson should surface overdispersion in errors.json."""
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    rng = np.random.default_rng(20260508)
    n = 240
    x1 = rng.normal(0, 1, n)
    mu = np.exp(1.0 + 0.25 * x1)
    # Gamma-Poisson mixture creates count data with variance well above mean.
    rates = rng.gamma(shape=0.7, scale=mu / 0.7)
    y = rng.poisson(rates).astype(int)
    frame = pd.DataFrame({"count_events_y": y, "x1_budget": x1})
    source = tmp_path / "overdispersed_count.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "overdispersed_count")

    result = run_workflow(
        project.root, [source], mode="auto", y="count_events_y", x=["x1_budget"]
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    diag = read_json(run_root / "model_results" / "diagnostics_poisson_1.json")
    assert diag["overdispersion"]["overdispersion_ratio"] > 2.0
    errors = read_json(run_root / "errors.json")
    assert any(issue["code"] == "OVERDISPERSION_DETECTED" for issue in errors["issues"])


def test_poisson_offset_is_not_reported_as_dropped_variable(tmp_path):
    """A positive exposure column used as offset should not be reported as dropped."""
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    rng = np.random.default_rng(20260509)
    n = 160
    x1 = rng.normal(0, 1, n)
    exposure = rng.integers(80, 220, n)
    y = rng.poisson(exposure * np.exp(-4.4 + 0.35 * x1)).astype(int)
    frame = pd.DataFrame({
        "count_events_y": y,
        "x1_budget": x1,
        "x2_exposure": exposure,
    })
    source = tmp_path / "poisson_offset.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "poisson_offset")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="count_events_y",
        x=["x1_budget", "x2_exposure"],
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    poisson = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson["model_type"] == "poisson_rate"
    errors = read_json(run_root / "errors.json")
    assert not any(
        issue["code"] == "VARIABLE_DROPPED"
        and issue.get("evidence", {}).get("variable") == "x2_exposure"
        for issue in errors["issues"]
    )
    html = (run_root / "reports" / "report.html").read_text()
    assert "Exposure/offset: log(x2_exposure), coefficient fixed at 1" in html
    assert "x2_exposure (dropped" not in html


def test_nonpositive_exposure_fallback_report_does_not_claim_offset(tmp_path):
    """If exposure is unusable, the report should describe the fitted plain Poisson."""
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    rng = np.random.default_rng(20260510)
    n = 120
    x1 = rng.normal(0, 1, n)
    exposure = rng.integers(0, 4, n)
    exposure[0] = 0
    y = rng.poisson(np.exp(0.7 + 0.3 * x1)).astype(int)
    frame = pd.DataFrame({
        "count_events_y": y,
        "x1_budget": x1,
        "x2_exposure": exposure,
    })
    source = tmp_path / "poisson_bad_offset.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "poisson_bad_offset")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="count_events_y",
        x=["x1_budget", "x2_exposure"],
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    poisson = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson["model_type"] == "poisson"
    html = (run_root / "reports" / "report.html").read_text()
    assert "Model: Poisson rate model" not in html
    assert "offset(log(x2_exposure))" not in html


def test_auto_infer_routes_binary_y_to_logit():
    """Binary outcome should be detected as BINARY (routing to Logit)."""
    frame = pd.DataFrame({"y": [0, 1, 0, 1, 1, 0]})
    assert detect_y_kind(frame, "y") == YKind.BINARY


# --- TEST 6: Categorical candidate detection ---

def test_categorical_candidate_detected(tmp_path):
    """Column with 'code' in name and <=10 unique values gets CATEGORICAL_CANDIDATE INFO."""
    frame = pd.DataFrame({
        "y": list(range(20)),
        "x1_region_code": [1, 2, 3, 4, 5] * 4,  # 5 unique values
    })
    issue_dicts: list[dict] = []
    _check_categorical_candidates(frame, issue_dicts, tmp_path)
    codes = [i["code"] for i in issue_dicts]
    assert "CATEGORICAL_CANDIDATE" in codes
    msg = next(
        i["message"] for i in issue_dicts if i["code"] == "CATEGORICAL_CANDIDATE"
    )
    assert "x1_region_code" in msg
    assert "5 unique values" in msg


# --- TEST 7: Heteroskedasticity message mentions robust SE ---

def test_heteroskedasticity_message_mentions_robust_se():
    """OLS with robust=True computes Breusch-Pagan and sets model_type to ols_robust."""
    rng = np.random.default_rng(42)
    n = 100
    x = rng.uniform(0, 10, n)
    # Heteroskedastic errors: variance grows with x
    y = 2 + 1.5 * x + rng.normal(0, 0.5 + 0.3 * x, n)
    frame = pd.DataFrame({"y": y, "x": x})
    result, fitted = run_ols(frame, y="y", x=["x"], robust=True, model_id="ols_1")
    exog = frame[["x"]]
    diag = compute_diagnostics(fitted, exog, model_id="ols_1", model_family="ols")
    assert "breusch_pagan" in diag
    bp = diag["breusch_pagan"]
    assert bp["lm"] is not None
    assert bp["p_value"] is not None
    assert result["model_type"] == "ols_robust"


# --- TEST 8: No outcome leakage ---

def test_no_outcome_leakage():
    """Only the explicitly specified X columns appear in model coefficients."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 10, n)
    y = 2 + 1.5 * x1 + rng.normal(0, 2, n)
    frame = pd.DataFrame({
        "y": y,
        "x1": x1,
        "another_outcome_y": rng.uniform(0, 1, n),
        "sales_target": rng.uniform(0, 1, n),
    })
    result, _ = run_ols(frame, y="y", x=["x1"], robust=True, model_id="ols_1")
    coefs = result["coefficients"]
    assert "x1" in coefs
    assert "another_outcome_y" not in coefs
    assert "sales_target" not in coefs
