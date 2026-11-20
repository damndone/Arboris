"""outcome.type_served: a fit whose family is not declared for the run's outcome type says so."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.checks.context import outcome_traits
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> Path:
    rng = np.random.default_rng(1014)
    income = rng.gamma(4, 5, 1200)
    frame = pd.DataFrame({
        "owns_home": rng.binomial(1, 1 / (1 + np.exp(-(-3 + 0.12 * income)))),
        "visits": rng.poisson(np.exp(0.2 + 0.02 * income)),
        "wage": 2 + 0.3 * income + rng.normal(size=1200),
        "income_k": income,
    })
    path = tmp_path_factory.mktemp("outcome") / "data.csv"
    frame.to_csv(path, index=False)
    return path


def _checks(tmp_path: Path, source: Path, *, y: str, model_type: str, model_id: str, covariance: str = "") -> dict:
    project = create_project(tmp_path, f"{model_type}-{y}")
    outcome = run_workflow(project.root, [source], mode="auto", model_type=model_type, y=y, x=["income_k"],
                           covariance=covariance)
    assert outcome["status"] == "completed"
    run = project.root / "runs" / outcome["run_id"]
    checks = json.loads((run / "model_results" / f"checks_{model_id}.json").read_text())
    issues = [issue["code"] for issue in json.loads((run / "errors.json").read_text())["issues"]]
    served = {item["check_id"]: item for item in checks["checks"]}.get("outcome.type_served")
    return {"check": served, "traits": checks["traits"], "issues": issues}


@pytest.mark.parametrize("covariance", ["", "unadjusted"])
def test_ols_on_a_binary_outcome_is_named_a_linear_probability_model(tmp_path, source, covariance):
    found = _checks(tmp_path, source, y="owns_home", model_type="ols", model_id="ols_1", covariance=covariance)
    check = found["check"]
    assert check["status"] == "caution" and "CHECK_OUTCOME_TYPE_SERVED" in found["issues"]
    evidence = check["evidence"]
    assert evidence["outcome_type"] == "binary" and evidence["family_serves"] == ["continuous"]
    assert {"logit", "probit"} <= set(evidence["families_serving_outcome_type"])
    assert evidence["default_family_for_outcome_type"] == "logit"
    assert evidence["fitted_values"] == 1200 and evidence["fitted_outside_unit_interval"] > 0
    assert "linear probability model" in check["summary"]


def test_ols_on_a_count_outcome_names_the_count_families(tmp_path, source):
    check = _checks(tmp_path, source, y="visits", model_type="ols", model_id="ols_1")["check"]
    assert check["status"] == "caution" and check["evidence"]["outcome_type"] == "count"
    assert "poisson" in check["evidence"]["families_serving_outcome_type"]
    assert "fitted_outside_unit_interval" not in check["evidence"]


@pytest.mark.parametrize("y, model_type, model_id", [("owns_home", "logit", "logit_1"), ("wage", "ols", "ols_1")])
def test_a_family_declared_for_the_outcome_adds_neither_the_check_nor_its_trait(tmp_path, source, y, model_type, model_id):
    found = _checks(tmp_path, source, y=y, model_type=model_type, model_id=model_id)
    assert found["check"] is None and "outcome.type_unserved" not in found["traits"]


def test_an_unregistered_family_or_an_outcome_type_nobody_serves_adds_nothing():
    import workbench.engine.stages.estimation  # noqa: F401 - registers the core families

    assert outcome_traits("ols", "ols_1", {"outcome_type": "binary"}) == {"outcome.type_unserved"}
    assert outcome_traits("not_registered", "unknown_1", {"outcome_type": "binary"}) == frozenset()
    assert outcome_traits("ols", "ols_1", {"outcome_type": "declared_by_no_family"}) == frozenset()
    assert outcome_traits("ols", "ols_1", {}) == frozenset()
