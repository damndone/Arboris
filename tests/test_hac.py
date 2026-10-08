"""v1.8.10 step 6: HAC (Newey-West) standard errors for OLS.

Bartlett kernel, N/(N - K) scaling, t(N - K): the defaults of Stata's `newey`,
which R's sandwich::NeweyWest matches only with prewhite = FALSE and
adjust = TRUE. The fixture's rows are shuffled, so the estimator has to put
them in time order itself; every refusal names its reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.stata_oracle import emit, requires_stata, run
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.contracts.model.ols import OLSModelOptionsError, hac_default_lags, validate_ols_model_options
from workbench.orchestrator import run_workflow
from workbench.postestimation.registry import run_operation
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "hac"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())
TOLERANCE = float(ORACLE["tolerances"]["default"])


def _run(tmp_path: Path, name: str, options: dict, *, source: Path = FIXTURES / "data.csv", **extra):
    project = create_project(tmp_path, name)
    result = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2"],
                          model_options=options, **extra)
    return result, project.root / "runs" / result["run_id"]


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    root = tmp_path_factory.mktemp("hac")
    cache: dict[int | None, Path] = {}

    def run_root(lags: int | None) -> Path:
        if lags not in cache:
            options = {"covariance": "hac", "time_order": "year", **({"hac_lags": lags} if lags is not None else {})}
            result, path = _run(root, f"lag-{lags}", options)
            assert result["status"] == "completed", read_json(path / "errors.json")
            cache[lags] = path
        return cache[lags]

    return run_root


@pytest.mark.parametrize("case", sorted(ORACLE["cases"]))
def test_standard_errors_match_sandwich_neweywest(fitted, case: str) -> None:
    expected = ORACLE["cases"][case]
    packet = read_json(fitted(expected["lag"]) / "model_results" / "ols_1.json")
    for term, se in expected["std_error"].items():
        assert packet["coefficients"][term]["std_error"] == pytest.approx(se, rel=TOLERANCE), term
    for term, estimate in ORACLE["coefficients"].items():
        assert packet["coefficients"][term]["estimate"] == pytest.approx(estimate, rel=TOLERANCE)
    evidence = packet["covariance_evidence"]
    assert evidence["covariance_estimator"] == "HAC"
    assert evidence["inference_distribution"] == "t" and evidence["effective_df"] == ORACLE["meta"]["n"] - 3
    assert evidence["hac"]["lags"] == expected["lag"] and evidence["hac"]["kernel"] == "bartlett"


@pytest.mark.parametrize("case", sorted(ORACLE["cases"]))
def test_a_joint_wald_test_on_the_hac_kernel_matches_the_reference(fitted, case: str) -> None:
    expected = ORACLE["cases"][case]
    kernel = read_json(fitted(expected["lag"]) / kernel_relative_path("ols_1"))
    result = run_operation("wald", [kernel], {"constraints": [{"terms": {"x1": 1}, "value": 0},
                                                              {"terms": {"x2": 1}, "value": 0}]})
    reference = expected["wald_x1_x2"]
    assert result["statistic"] == pytest.approx(reference["F"], rel=1e-8)
    assert (result["df_num"], result["df_den"]) == (reference["df_num"], reference["df_den"])
    assert result["p_value"] == pytest.approx(reference["p_value"], rel=1e-6)


def test_the_default_lag_follows_newey_west_1994_and_says_so(fitted) -> None:
    hac = read_json(fitted(None) / "model_results" / "ols_1.json")["covariance_evidence"]["hac"]
    n = ORACLE["meta"]["n"]
    assert hac["lags"] == hac_default_lags(n) == ORACLE["meta"]["default_lag"]
    assert "Newey and West 1994" in hac["lag_rule"]
    assert (hac["first_period"], hac["last_period"]) == (1871, 1871 + n - 1)
    assert hac_default_lags(100) == 4 and hac_default_lags(1000) == 6


@requires_stata
def test_standard_errors_and_test_match_stata_newey(fitted, tmp_path) -> None:
    body = "\n".join([
        f'import delimited using "{FIXTURES / "data.csv"}", clear asdouble',
        "tsset year",
        "newey y x1 x2, lag(4)",
        emit("se_x1", "_se[x1]"), emit("se_x2", "_se[x2]"), emit("se_cons", "_se[_cons]"),
        emit("df_r", "e(df_r)"),
        "test x1 x2",
        emit("F", "r(F)"), emit("p", "r(p)"),
    ])
    stata = run(tmp_path, body, name="newey")
    packet = read_json(fitted(4) / "model_results" / "ols_1.json")
    coefficients = packet["coefficients"]
    for term, key in (("x1", "se_x1"), ("x2", "se_x2"), ("Intercept", "se_cons")):
        assert coefficients[term]["std_error"] == pytest.approx(stata[key], rel=1e-9), term
    assert packet["covariance_evidence"]["effective_df"] == stata["df_r"]
    kernel = read_json(fitted(4) / kernel_relative_path("ols_1"))
    wald = run_operation("wald", [kernel], {"constraints": [{"terms": {"x1": 1}, "value": 0},
                                                            {"terms": {"x2": 1}, "value": 0}]})
    assert wald["statistic"] == pytest.approx(stata["F"], rel=1e-8)
    assert wald["p_value"] == pytest.approx(stata["p"], rel=1e-6)


def _write(tmp_path: Path, frame: pd.DataFrame, name: str) -> Path:
    path = tmp_path / f"{name}.csv"
    frame.to_csv(path, index=False)
    return path


def _refusal(tmp_path, name: str, options: dict, frame: pd.DataFrame | None = None, **extra) -> str:
    source = _write(tmp_path, frame, name) if frame is not None else FIXTURES / "data.csv"
    try:
        result, run_root = _run(tmp_path, name, options, source=source, **extra)
    except Exception as error:  # refused before a run exists
        return str(error)
    assert result["status"] in {"failed", "blocked"}, result
    return " ".join(issue["message"] for issue in read_json(run_root / "errors.json")["issues"])


def test_a_gap_in_the_sample_is_refused_including_one_left_by_a_missing_value(tmp_path) -> None:
    frame = pd.read_csv(FIXTURES / "data.csv")
    with_missing = frame.copy()
    with_missing.loc[with_missing["year"] == 1900, "x1"] = np.nan
    message = _refusal(tmp_path, "gap", {"covariance": "hac", "time_order": "year"}, with_missing)
    assert "gaps" in message and "1899" in message


def test_repeated_periods_are_refused_as_panel_data(tmp_path) -> None:
    frame = pd.read_csv(FIXTURES / "data.csv")
    frame.loc[frame.index[:10], "year"] = frame["year"].iloc[10]
    message = _refusal(tmp_path, "panel", {"covariance": "hac", "time_order": "year"}, frame)
    assert "repeats a period" in message and "Driscoll-Kraay" in message


def test_hac_with_clustering_is_refused(tmp_path) -> None:
    frame = pd.read_csv(FIXTURES / "data.csv").assign(g=lambda d: d["year"] % 10)
    message = _refusal(tmp_path, "cluster", {"covariance": "hac", "time_order": "year"}, frame, entity_col="g")
    assert "Driscoll-Kraay" in message


def test_without_a_time_order_the_user_is_told_to_set_one() -> None:
    with pytest.raises(OLSModelOptionsError, match="set time_order") as caught:
        validate_ols_model_options({"covariance": "hac"})
    assert caught.value.error_code == "OLS_HAC_TIME_ORDER_MISSING"


def test_hac_fields_without_hac_and_hac_on_panel_ols_are_refused() -> None:
    with pytest.raises(OLSModelOptionsError, match="applies only to"):
        validate_ols_model_options({"covariance": "robust", "hac_lags": 4})
    with pytest.raises(OLSModelOptionsError, match="OLS only so far"):
        validate_ols_model_options({"covariance": "hac", "time_order": "year"}, family="panel_ols")


def test_dates_are_ordered_as_dates_and_checked_for_an_even_frequency(tmp_path) -> None:
    frame = pd.read_csv(FIXTURES / "data.csv")
    months = pd.period_range("2000-01", periods=len(frame), freq="M")
    frame["month"] = [str(months[year - 1871].to_timestamp().date()) for year in frame["year"]]
    frame = frame.drop(columns="year")
    result, run_root = _run(tmp_path, "monthly", {"covariance": "hac", "time_order": "month", "hac_lags": 4},
                            source=_write(tmp_path, frame, "monthly"))
    assert result["status"] == "completed"
    coefficients = read_json(run_root / "model_results" / "ols_1.json")["coefficients"]
    for term, se in ORACLE["cases"]["lag_4"]["std_error"].items():
        assert coefficients[term]["std_error"] == pytest.approx(se, rel=TOLERANCE)


def test_the_agent_requests_hac_on_model_genesis_and_on_a_rerun() -> None:
    from workbench.agent.recipes.registry import build_option_vocabulary
    from workbench.agent.workflow_contracts import validate_model_genesis_spec
    from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
    from workbench.contracts.common.errors import OperationValidationError

    branches = [{"branch_id": "b", "outcome": "y", "predictors": ["x1"]}]
    spec = {"model_family": "ols", "branches": branches, "covariance": "hac",
            "model_options": {"time_order": "year", "hac_lags": 4}}
    validate_model_genesis_spec(spec)
    params = MODEL_FAMILY_CONTRACTS["ols"].build_model_params(spec, branches[0], ["x1"], "hac")
    assert params["model_options"] == {"covariance": "hac", "time_order": "year", "hac_lags": 4}
    with pytest.raises(OperationValidationError, match="set time_order"):
        validate_model_genesis_spec({"model_family": "ols", "branches": branches, "covariance": "hac"})
    with pytest.raises(OperationValidationError, match="Driscoll-Kraay"):
        validate_model_genesis_spec({"model_family": "panel_ols", "branches": branches, "covariance": "hac",
                                     "entity_col": "g"})
    vocabulary = build_option_vocabulary("ols")
    assert "hac" in vocabulary["fields"]["covariance"]["allowed_values"]
    assert {"time_order", "hac_lags"} <= set(vocabulary["fields"])


def test_a_rerun_patch_to_hac_and_back_validates_against_the_merged_options() -> None:
    from workbench.agent.recipes.registry import _validate_ols_model_options_patch

    merged = _validate_ols_model_options_patch(
        current_contract={"covariance": "robust"}, patch={"covariance": "hac", "time_order": "year"}
    )
    assert merged == {"covariance": "hac", "time_order": "year"}
    back = _validate_ols_model_options_patch(current_contract=merged, patch={"covariance": "robust"})
    assert back == {"covariance": "robust"}
    with pytest.raises(OLSModelOptionsError, match="set time_order"):
        _validate_ols_model_options_patch(current_contract={"covariance": "robust"}, patch={"covariance": "hac"})


def test_every_agent_reading_names_the_kernel_lag_and_time_order(fitted) -> None:
    from workbench.agent.context_tools import _bounded_persisted_model_facts, _public_requested_model_coefficients

    run_root = fitted(None)
    packet = read_json(run_root / "model_results" / "ols_1.json")
    summary = _bounded_persisted_model_facts([packet], run_root=run_root)[0]
    project = _public_requested_model_coefficients(run_id="r", result=packet, requested_terms=("x1",))
    for hac in (summary["inference"]["hac"], project["covariance_details"]["hac"]):
        assert hac["kernel"] == "bartlett" and hac["lags"] == 4 and hac["time_order"] == "year"
        assert "Newey and West 1994" in hac["lag_rule"]
    assert summary["covariance_executed"] == "HAC" and project["covariance_estimator"] == "HAC"
