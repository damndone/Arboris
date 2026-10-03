"""v1.8.10 inference engine v2: Stata's finite-sample rules for OLS.

Robust OLS (HC1) reports t(N - K) and F(q, N - K); clustered OLS (CR1) reports
t(G - 1) and F(q, G - 1). The coefficient table, the confidence intervals, the
kernel and every post-estimation test come from the same inference context,
and agree with R (sandwich + lmtest::coeftest with the same df).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import wald_test
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "postestimation"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())["families"]
CASES = {
    "ols_robust": {},
    "ols_cluster": {"covariance": "clustered", "entity_col": "g"},
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("inference-v2")
    out = {}
    for name, extra in CASES.items():
        project = create_project(root, name)
        outcome = run_workflow(
            project.root, [FIXTURES / "data.csv"], mode="auto", model_type="ols", y="y",
            x=["x1", "x2", "x3"], **extra,
        )
        assert outcome["status"] == "completed", outcome
        out[name] = project.root / "runs" / outcome["run_id"]
    return out


@pytest.mark.parametrize("case", list(CASES))
def test_the_coefficient_table_agrees_with_r(runs, case) -> None:
    # The packet stores six decimals, so it is compared to that precision.
    packet = read_json(runs[case] / "model_results" / "ols_1.json")
    for term, expected in ORACLE[case]["coef_tests"].items():
        row = packet["coefficients"][term]
        assert row["estimate"] == pytest.approx(expected["estimate"], abs=5e-7)
        assert row["std_error"] == pytest.approx(expected["std_error"], abs=5e-7)
        assert row["p_value"] == pytest.approx(expected["p_value"], abs=5e-7)
        assert [row["ci_lower"], row["ci_upper"]] == pytest.approx(expected["ci"], abs=5e-7)


def test_the_kernel_records_where_its_degrees_of_freedom_come_from(runs) -> None:
    robust = read_json(runs["ols_robust"] / kernel_relative_path("ols_1"))
    cluster = read_json(runs["ols_cluster"] / kernel_relative_path("ols_1"))
    assert (robust["reference_distribution"], robust["df_resid"], robust["df_method"]) == ("t", 296.0, "residual")
    assert (cluster["reference_distribution"], cluster["df_resid"], cluster["df_method"]) == (
        "t", float(ORACLE["ols_cluster"]["n_clusters"] - 1), "clusters_minus_one",
    )
    assert cluster["n_clusters"] == ORACLE["ols_cluster"]["n_clusters"]


@pytest.mark.parametrize("case", list(CASES))
def test_one_restriction_gives_the_coefficients_own_p_value(runs, case) -> None:
    """F(1, df) = t(df)^2: a joint test of one coefficient is that coefficient's test."""
    from scipy import stats

    kernel = read_json(runs[case] / kernel_relative_path("ols_1"))
    index = kernel["param_names"].index("x1")
    t = kernel["params"][index] / kernel["vcov"][index][index] ** 0.5
    result = wald_test(kernel, [{"terms": {"x1": 1}, "value": 0}])
    assert result["distribution"] == "F"
    assert result["statistic"] == pytest.approx(t**2, rel=1e-10)
    assert result["p_value"] == pytest.approx(2 * stats.t.sf(abs(t), kernel["df_resid"]), rel=1e-9)
    assert result["p_value"] == pytest.approx(ORACLE[case]["coef_tests"]["x1"]["p_value"], rel=1e-6)


def test_the_result_states_its_inference(runs) -> None:
    cluster = read_json(runs["ols_cluster"] / "model_results" / "ols_1.json")
    evidence = cluster.get("covariance_evidence") or cluster.get("inference_config")
    assert evidence["inference_version"] == "workbench.inference.v2"
    assert evidence["df_method"] == "clusters_minus_one"
    assert evidence["inference_distribution"] == "t"
    assert evidence["effective_df"] == ORACLE["ols_cluster"]["n_clusters"] - 1
    assert evidence["cluster_count"] == ORACLE["ols_cluster"]["n_clusters"]
    robust = read_json(runs["ols_robust"] / "model_results" / "ols_1.json")
    robust_evidence = robust.get("covariance_evidence") or robust.get("inference_config")
    assert robust_evidence["small_sample_correction"] is True


def test_the_agent_sees_how_the_inference_was_computed(runs) -> None:
    from workbench.agent.context_tools import _bounded_persisted_model_facts

    packet = read_json(runs["ols_cluster"] / "model_results" / "ols_1.json")
    [facts] = _bounded_persisted_model_facts([packet])
    assert facts["inference"]["df_method"] == "clusters_minus_one"
    assert facts["inference"]["cluster_count"] == ORACLE["ols_cluster"]["n_clusters"]
    assert facts["inference"]["legacy_asymptotic"] is False
    legacy = json.loads(json.dumps(packet))
    for key in ("covariance_evidence", "inference_config"):
        if isinstance(legacy.get(key), dict):
            legacy[key].pop("inference_version", None)
            legacy[key]["inference_distribution"] = "normal"
    [old] = _bounded_persisted_model_facts([legacy])
    assert old["inference"]["legacy_asymptotic"] is True
