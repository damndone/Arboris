"""v1.8.10 step 3: what the check library does to real runs.

The objective's acceptance scenarios, deterministically: a perfect fit is
named and shows no inference; collinearity reaches the run's issues; a factor
gets a GVIF; separated binary data are named, whether the fit completes or not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import PostestimationRefusal, wald_test
from workbench.projects import create_project

ROOT = Path(__file__).resolve().parents[1]
CROSS = ROOT / "examples" / "datasets" / "cross_section.csv"
SEPARATION = ROOT / "tests" / "fixtures" / "checks" / "separation.csv"


def _run(tmp_path: Path, name: str, source: Path, **kwargs) -> tuple[dict, Path]:
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    return outcome, project.root / "runs" / outcome["run_id"]


def _checks(run_root: Path, model_id: str) -> dict[str, dict]:
    payload = read_json(run_root / "model_results" / f"checks_{model_id}.json")
    return {item["check_id"]: item for item in payload["checks"]}


def test_a_perfect_fit_is_named_and_shows_no_inference(tmp_path) -> None:
    outcome, run_root = _run(tmp_path, "perfect", CROSS, model_type="ols", y="wage", x=["education", "experience"])
    assert outcome["status"] == "completed"
    checks = _checks(run_root, "ols_1")
    assert checks["fit.perfect"]["status"] == "fails"
    assert checks["fit.heteroskedasticity"]["status"] == "not_applicable"
    assert checks["collinearity.gvif"]["status"] == "caution" and "VIF 75.7" in checks["collinearity.gvif"]["summary"]

    packet = read_json(run_root / "model_results" / "ols_1.json")
    assert packet["inference_suppressed"]["check_id"] == "fit.perfect"
    assert all(row["p_value"] is None and row["std_error"] is None for row in packet["coefficients"].values())
    kernel = read_json(run_root / kernel_relative_path("ols_1"))
    with pytest.raises(PostestimationRefusal, match="fits the data exactly"):
        wald_test(kernel, [{"terms": {"education": 1}, "value": 0}])

    summary = read_json(run_root / "diagnostic_summary.json")
    codes = {issue["code"] for bucket in ("warnings", "cautions") for issue in summary["diagnostics"][bucket]}
    assert {"CHECK_FIT_PERFECT", "CHECK_COLLINEARITY_GVIF"} <= codes
    assert summary["run_status"]["has_warnings"] is True


def test_a_factor_gets_a_generalized_vif(tmp_path) -> None:
    _, run_root = _run(tmp_path, "factor", CROSS, model_type="ols", y="wage", x=["education", "experience", "region"])
    terms = _checks(run_root, "ols_1")["collinearity.gvif"]["evidence"]["terms"]
    assert terms["region"]["df"] == 2 and terms["region"]["gvif"] == pytest.approx(1.04, abs=0.01)


def test_a_separated_probit_is_named(tmp_path) -> None:
    outcome, run_root = _run(tmp_path, "probit", SEPARATION, model_type="probit", y="complete", x=["x1", "x2"])
    assert outcome["status"] == "completed"
    separation = _checks(run_root, "probit_1")["fit.separation"]
    assert separation["status"] == "fails" and separation["evidence"]["infinite_estimates"] == ["x1 (+inf)"]
    assert read_json(run_root / "model_results" / "probit_1.json")["inference_suppressed"]["check_id"] == "fit.separation"


def test_a_logit_that_cannot_be_fitted_names_the_separation(tmp_path) -> None:
    outcome, run_root = _run(tmp_path, "logit", SEPARATION, model_type="logit", y="quasi", x=["x1", "x2"])
    assert outcome["status"] == "failed"
    messages = [issue["message"] for issue in read_json(run_root / "errors.json")["issues"]]
    assert any("separated by x1" in message and "Firth" in message for message in messages), messages
