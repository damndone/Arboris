import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.econometrics.runner import run_fixed_effects, run_panel_ols
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("linearmodels")


def _panel_frame() -> pd.DataFrame:
    import random
    rng = random.Random(42)
    rows = []
    for firm in ("A", "B", "C", "D", "E", "F", "G", "H"):
        base = {"A": 10, "B": 20, "C": 30, "D": 40,
                "E": 15, "F": 25, "G": 35, "H": 45}[firm]
        for year in (2018, 2019, 2020, 2021, 2022):
            rows.append({
                "firm": firm, "yr": year,
                "profit": base + (year - 2018) * 2.0 + rng.uniform(-1, 1),
                "rnd": base / 2 + (year - 2018) + rng.uniform(-0.5, 0.5),
            })
    return pd.DataFrame(rows)


def _run(tmp_path, **kwargs):
    source = tmp_path / "data.csv"
    _panel_frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], **kwargs)
    return project.root / "runs" / result["run_id"], result


def test_clustered_covariance_runs(tmp_path):
    run_root, result = _run(
        tmp_path, mode="auto", y="profit", x=["rnd"],
        model_type="panel_ols", entity_col="firm", time_col="yr",
        covariance="clustered",
    )
    assert result["status"] == "completed"
    model = read_json(run_root / "model_results" / "panel_ols_1.json")
    assert model["model_type"] == "panel_ols"
    assert model["y_column"] == "profit"
    assert model["entity_col"] == "firm"
    assert model["time_col"] == "yr"
    assert model["df_model"] is not None
    assert model["df_resid"] is not None
    assert model["covariance"] == "clustered"
    assert model["covariance_evidence"]["cluster_variable"] == "firm"
    assert model["covariance_evidence"]["cluster_count"] == 8


def test_default_covariance_runs(tmp_path):
    run_root, result = _run(
        tmp_path, mode="auto", y="profit", x=["rnd"],
        model_type="panel_ols", entity_col="firm", time_col="yr",
    )
    assert result["status"] == "completed"


def test_two_way_panel_effects_match_explicit_dummy_fixed_effects() -> None:
    """PanelOLS and the equivalent dummy specification share point estimates.

    This is a model-family oracle, not a comparison of covariance estimators:
    both estimators use the same balanced panel and unadjusted inference.  The
    entity and time effects are represented by the PanelOLS absorber in one
    branch and by explicit dummy terms in the independent reference branch.
    """

    frame = _panel_frame()
    panel, _ = run_panel_ols(
        frame,
        "profit",
        ["rnd"],
        "firm",
        "yr",
        "panel_reference",
        covariance="unadjusted",
    )
    dummy, _ = run_fixed_effects(
        frame,
        "profit",
        ["rnd"],
        "firm",
        "yr",
        "dummy_reference",
    )

    assert panel["model_type"] == "panel_ols"
    assert dummy["model_type"] == "fixed_effects"
    assert panel["coefficients"]["rnd"]["estimate"] == pytest.approx(
        dummy["coefficients"]["rnd"]["estimate"],
        abs=1e-8,
    )


def test_panel_ols_forwards_requested_covariance(tmp_path, monkeypatch):
    import workbench.orchestrator as orch
    captured = {}
    real = orch.run_panel_ols
    def spy(*a, **kw):
        captured["covariance"] = kw.get("covariance")
        return real(*a, **kw)
    monkeypatch.setattr(orch, "run_panel_ols", spy)
    _run(tmp_path, mode="auto", y="profit", x=["rnd"],
         model_type="panel_ols", entity_col="firm", time_col="yr",
         covariance="clustered")
    assert captured["covariance"] == "clustered"


def test_panel_ols_defaults_covariance_to_robust(tmp_path, monkeypatch):
    import workbench.orchestrator as orch
    captured = {}
    real = orch.run_panel_ols
    def spy(*a, **kw):
        captured["covariance"] = kw.get("covariance")
        return real(*a, **kw)
    monkeypatch.setattr(orch, "run_panel_ols", spy)
    _run(tmp_path, mode="auto", y="profit", x=["rnd"],
         model_type="panel_ols", entity_col="firm", time_col="yr")
    assert captured["covariance"] == "robust"
