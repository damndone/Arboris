"""v1.8.11 step 2: panel, DID and event-study fits cluster by entity by default.

Reference: Stata 18 `xtreg, fe vce(cluster)` (tests/fixtures/panel_cluster/).
`xtreg, fe vce(robust)` clusters by panel, with CR1 scaled by
G/(G-1) * (N-1)/(N-K) -- K counting every parameter except the fixed effects
nested within the clusters -- and t(G - 1) inference. Heteroskedasticity-robust
standard errors that ignore the clustering are inconsistent with a fixed number
of periods (Stock & Watson 2008), so they remain only as an explicit choice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = json.loads((FIXTURES / "panel_cluster" / "oracle.json").read_text())["results"]
PANEL = FIXTURES / "admission" / "panel_ols" / "data.csv"
DID = FIXTURES / "admission" / "did" / "data.csv"
STAGGERED = FIXTURES / "panel_cluster" / "staggered.csv"


def _run(tmp_path: Path, data: Path, name: str, **kwargs) -> Path:
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [data], mode="auto", **kwargs)
    root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root / "errors.json") if (root / "errors.json").exists() else outcome
    return root


def _assert_matches(coefficient: dict, prefix: str, term: str) -> None:
    assert coefficient["estimate"] == pytest.approx(ORACLE[f"{prefix}b_{term}"], abs=1e-9)
    assert coefficient["std_error"] == pytest.approx(ORACLE[f"{prefix}se_{term}"], rel=1e-8)
    assert coefficient["p_value"] == pytest.approx(ORACLE[f"{prefix}p_{term}"], abs=1e-6)
    assert coefficient["ci_lower"] == pytest.approx(ORACLE[f"{prefix}lo_{term}"], rel=1e-8)
    assert coefficient["ci_upper"] == pytest.approx(ORACLE[f"{prefix}hi_{term}"], rel=1e-8)


def _assert_cluster_kernel(kernel: dict, prefix: str) -> None:
    assert kernel["covariance_estimator"] == "cluster"
    assert kernel["reference_distribution"] == "t"
    assert kernel["df_method"] == "clusters_minus_one"
    assert kernel["n_clusters"] == int(ORACLE[f"{prefix}g"])
    assert kernel["df_resid"] == ORACLE[f"{prefix}df"]


def test_panel_ols_clusters_by_entity_by_default_as_stata_xtreg(tmp_path) -> None:
    root = _run(tmp_path, PANEL, "panel", model_type="panel_ols", y="y", x=["x1", "x2"],
                entity_col="g", time_col="time")
    result = read_json(root / "model_results" / "panel_ols_1.json")
    for term in ("x1", "x2"):
        _assert_matches(result["coefficients"][term], "panel_", term)
    evidence = result["covariance_evidence"]
    assert evidence["covariance"] == "clustered"
    assert evidence["cluster_variable"] == "g"
    assert evidence["cluster_count"] == 50
    assert evidence["inference_distribution"] == "t"
    assert evidence["effective_df"] == 49
    _assert_cluster_kernel(read_json(root / kernel_relative_path("panel_ols_1")), "panel_")


def test_panel_ols_clusters_at_a_coarser_nested_level(tmp_path) -> None:
    frame = pd.read_csv(PANEL)
    frame["region"] = frame["g"] % 10
    data = tmp_path / "panel_region.csv"
    frame.to_csv(data, index=False)
    root = _run(tmp_path, data, "region", model_type="panel_ols", y="y", x=["x1", "x2"],
                entity_col="g", time_col="time", model_options={"cluster": "region"})
    result = read_json(root / "model_results" / "panel_ols_1.json")
    for term in ("x1", "x2"):
        _assert_matches(result["coefficients"][term], "region_", term)
    assert result["covariance_evidence"]["cluster_variable"] == "region"
    _assert_cluster_kernel(read_json(root / kernel_relative_path("panel_ols_1")), "region_")


def test_two_by_two_did_clusters_by_unit_by_default(tmp_path) -> None:
    root = _run(tmp_path, DID, "did", model_type="did", y="y", x=[], entity_col="g", time_col="time",
                did_mode="cohort", did_cohort_col="first_treat")
    result = read_json(root / "model_results" / "did_1.json")
    _assert_matches(result["coefficients"]["_did_D"], "did_", "D")
    _assert_cluster_kernel(read_json(root / kernel_relative_path("did_1")), "did_")


def test_staggered_did_and_its_event_study_cluster_by_unit(tmp_path) -> None:
    root = _run(tmp_path, STAGGERED, "staggered", model_type="did", y="y", x=["x1"], entity_col="g",
                time_col="time", did_mode="cohort", did_cohort_col="first_treat")
    result = read_json(root / "model_results" / "did_1.json")
    _assert_matches(result["coefficients"]["_did_D"], "stag_", "D")
    _assert_matches(result["coefficients"]["x1"], "stag_", "x1")

    diagnostics = read_json(root / "did_diagnostics.json")
    study = diagnostics["event_study"]
    assert study["event_time"] == [k for k in json.loads((FIXTURES / "panel_cluster" / "oracle.json").read_text())["event_times"]]
    for k, coef, se, low, high in zip(study["event_time"], study["coef"], study["se"], study["ci_lower"], study["ci_upper"]):
        term = f"_evt_{'m' if k < 0 else 'p'}{abs(k)}"
        assert coef == pytest.approx(ORACLE[f"evt_b_{term}"], abs=1e-9)
        assert se == pytest.approx(ORACLE[f"evt_se_{term}"], rel=1e-8)
        assert low == pytest.approx(ORACLE[f"evt_lo_{term}"], rel=1e-8)
        assert high == pytest.approx(ORACLE[f"evt_hi_{term}"], rel=1e-8)
    assert study["n_clusters"] == 60

    # The pre-trend test is the joint Wald test of the leads under the
    # clustered covariance (Stata `testparm`), F(q, G - 1).
    trends = diagnostics["parallel_trends"]
    assert trends["statistic"] == pytest.approx(ORACLE["evt_pre_F"], rel=1e-8)
    assert trends["df_num"] == ORACLE["evt_pre_df"]
    assert trends["df_den"] == ORACLE["evt_pre_df_r"]
    assert trends["pvalue"] == pytest.approx(ORACLE["evt_pre_p"], abs=1e-6)


def test_heteroskedasticity_robust_without_clustering_is_an_explicit_choice_with_a_warning(tmp_path) -> None:
    root = _run(tmp_path, PANEL, "robust", model_type="panel_ols", y="y", x=["x1", "x2"],
                entity_col="g", time_col="time", covariance="robust")
    result = read_json(root / "model_results" / "panel_ols_1.json")
    assert result["covariance_evidence"]["covariance"] == "robust"
    assert any("not consistent" in warning and "fixed number of periods" in warning for warning in result["warnings"])
    assert read_json(root / kernel_relative_path("panel_ols_1"))["covariance_estimator"] != "cluster"


def test_a_cluster_column_that_is_not_in_the_data_is_refused(tmp_path) -> None:
    project = create_project(tmp_path, "missing")
    outcome = run_workflow(project.root, [PANEL], mode="auto", model_type="panel_ols", y="y", x=["x1", "x2"],
                           entity_col="g", time_col="time", model_options={"cluster": "state"})
    assert outcome["status"] != "completed"


@pytest.mark.parametrize(("clusters", "status", "phrase"), [
    (8, "caution", "wild cluster bootstrap"),
    (20, "caution", "rely on many clusters"),
    (30, "holds", "30 clusters"),
])
def test_cluster_count_check_has_one_threshold_source_and_a_severe_tier(clusters, status, phrase) -> None:
    from workbench.analysis_loop.policy import _CLUSTER_COUNT_CAUTION
    from workbench.checks.context import CheckContext
    from workbench.checks.fit_checks import CLUSTER_COUNT, cluster_count

    assert _CLUSTER_COUNT_CAUTION == CLUSTER_COUNT.threshold("caution_below") == 30
    context = CheckContext(model_id="panel_ols_1", model_type="panel_ols", traits=frozenset({"vce.cluster"}),
                           nobs=400, kernel={"n_clusters": clusters})
    outcome = cluster_count(context, CLUSTER_COUNT)
    assert outcome.status == status
    assert phrase in f"{outcome.summary} {outcome.remedy or ''}"
