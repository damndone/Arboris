"""Panel fixed effects follow the declaration (v1.9.1).

An entity-only panel_ols request used to pick up the auto-detected time column
too, so "firm fixed effects" and "firm + year fixed effects" produced the same
fit (the paid pass-back round, panel_fe.specific). Once either panel column is
declared, an undeclared one adds no effects; with neither declared, detection
still supplies both.
"""

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

linearmodels = pytest.importorskip("linearmodels")


def _frame() -> pd.DataFrame:
    # 40 firms x 6 years; year shocks correlated with the regressor, so one-way
    # and two-way fixed effects give clearly different slopes.
    rng = np.random.default_rng(20261022)
    rows = []
    for firm in range(40):
        level = rng.normal(0, 2)
        for year in range(2015, 2021):
            shock = (year - 2015) * 0.8
            x = 0.5 * level + shock + rng.normal(0, 1)
            rows.append({"firm_id": f"F{firm:02d}", "year": year, "x": x,
                         "y": 1.0 + 0.5 * x + level + 2.0 * shock + rng.normal(0, 0.5)})
    return pd.DataFrame(rows)


def _fit(tmp_path, **panel):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "panel.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"], model_type="panel_ols", **panel)
    run_root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed", (result, (run_root / "errors.json").read_text() if (run_root / "errors.json").exists() else None)
    return read_json(project.root / "runs" / result["run_id"] / "model_results" / "panel_ols_1.json")


def _reference(*, entity_effects, time_effects):
    frame = _frame().set_index(["firm_id", "year"])
    terms = ["1", "x"] + (["EntityEffects"] if entity_effects else []) + (["TimeEffects"] if time_effects else [])
    fitted = linearmodels.panel.PanelOLS.from_formula("y ~ " + " + ".join(terms), data=frame).fit()
    return float(fitted.params["x"])


def test_an_entity_only_declaration_fits_entity_effects_only(tmp_path):
    result = _fit(tmp_path, entity_col="firm_id")
    assert result["entity_col"] == "firm_id"
    assert result["time_col"] is None
    assert result["coefficients"]["x"]["estimate"] == pytest.approx(
        _reference(entity_effects=True, time_effects=False), rel=1e-12)


def test_declaring_both_columns_fits_two_way_effects(tmp_path):
    one_way = _fit(tmp_path / "one", entity_col="firm_id")
    two_way = _fit(tmp_path / "two", entity_col="firm_id", time_col="year")
    assert two_way["time_col"] == "year"
    assert two_way["coefficients"]["x"]["estimate"] == pytest.approx(
        _reference(entity_effects=True, time_effects=True), rel=1e-12)
    assert abs(two_way["coefficients"]["x"]["estimate"] - one_way["coefficients"]["x"]["estimate"]) > 0.05


def test_a_time_only_declaration_fits_time_effects_only(tmp_path):
    result = _fit(tmp_path, time_col="year", covariance="robust")
    assert result["entity_col"] is None and result["time_col"] == "year"
    assert result["coefficients"]["x"]["estimate"] == pytest.approx(
        _reference(entity_effects=False, time_effects=True), rel=1e-12)


def test_a_time_only_clustered_fit_asks_for_the_cluster_instead_of_borrowing_the_entity(tmp_path):
    # It used to cluster by (and add effects for) the detected firm column unasked.
    source = tmp_path / "panel.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"], model_type="panel_ols", time_col="year")
    assert result["status"] == "failed"
    errors = read_json(project.root / "runs" / result["run_id"] / "errors.json")
    assert any("PANEL_CLUSTER_ENTITY_REQUIRED" in str(issue.get("message")) for issue in errors["issues"])


def test_with_nothing_declared_detection_still_supplies_both_panel_columns(tmp_path):
    result = _fit(tmp_path)
    assert (result["entity_col"], result["time_col"]) == ("firm_id", "year")
    assert result["coefficients"]["x"]["estimate"] == pytest.approx(
        _reference(entity_effects=True, time_effects=True), rel=1e-12)


def test_lineage_roles_name_the_columns_the_fit_used():
    from types import SimpleNamespace
    from workbench.lineage.role_inputs_from_ctx import build_resolved_inputs

    ctx = SimpleNamespace(artifacts={
        "_model_results": [("panel_ols_1", {})], "_normalized_y": "y", "_normalized_x": ["x"],
        "_id_candidates": ["firm_id"], "_time_candidates": ["year"],
        "_panel_effect_columns": ("firm_id", None)})
    roles = build_resolved_inputs(ctx)
    assert (roles.unit, roles.time) == ("firm_id", None)
