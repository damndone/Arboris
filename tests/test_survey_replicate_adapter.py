from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.survey import EstimatorSpec, SurveyDesign

from workbench.engine.replicate_combine.survey_adapter import (
    MAX_SURVEY_REPLICATE_CELLS,
    SurveyPackAdapterError,
    run_survey_replicate_covariance,
)


FIXTURES = Path(__file__).parent / "fixtures" / "survey"


def _frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "design.csv")


def _oracle() -> dict:
    return json.loads((FIXTURES / "oracle.json").read_text())


def _weighted_ols(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
    x = np.column_stack(
        [np.ones(len(frame)), frame["x1"].to_numpy(), frame["x2"].to_numpy()]
    )
    y = frame["y"].to_numpy()
    w = np.asarray(weights, dtype=float)
    beta = np.linalg.solve((x.T * w) @ x, (x.T * w) @ y)
    return {"(Intercept)": beta[0], "x1": beta[1], "x2": beta[2]}


def _design(**overrides: object) -> SurveyDesign:
    values: dict[str, object] = {
        "frame": _frame(),
        "strata": "stratum",
        "psu": "psu",
        "weight": "weight",
    }
    values.update(overrides)
    return SurveyDesign(**values)


def _estimator() -> EstimatorSpec:
    return EstimatorSpec(name="survey-adapter-wls", refit=_weighted_ols)


def test_survey_adapter_reuses_jackknife_design_and_r_oracle() -> None:
    result = run_survey_replicate_covariance(
        _design(), _estimator(), replicate_type="jackknife", seed=17
    )

    assert result["batch"]["kind"] == "survey_replicate"
    assert result["batch"]["status"] == "completed"
    payload = result["result"]
    assert payload["method"] == "survey_replicate"
    assert payload["replicate_type"] == "jackknife"
    assert payload["design_degrees_of_freedom"] == 8
    oracle = _oracle()["replicate"]["jackknife"]
    for term, expected in oracle["se"].items():
        assert payload["standard_errors"][term] == pytest.approx(expected, rel=1e-10)


def test_survey_adapter_is_digest_bound_deterministic_and_aggregate_only() -> None:
    first = run_survey_replicate_covariance(
        _design(), _estimator(), replicate_type="jackknife", seed=17
    )
    second = run_survey_replicate_covariance(
        _design(), _estimator(), replicate_type="jackknife", seed=17
    )

    assert first == second
    serialized = json.dumps(first, allow_nan=False)
    assert '"replicate_values"' not in serialized
    assert '"replicate_rows"' not in serialized
    assert first["batch"]["digest"]
    assert first["batch"]["provenance"]["evidence_commitment"]


def test_survey_adapter_reuses_custom_brr_set_and_external_oracle() -> None:
    matrix = _oracle()["replicate"]["brr"]["hadamard"]["matrix"]
    result = run_survey_replicate_covariance(
        _design(hadamard_matrix=matrix), _estimator(), replicate_type="brr"
    )
    oracle = _oracle()["replicate"]["brr"]
    assert result["result"]["replicate_count"] == oracle["hadamard"]["order"]
    for term, expected in oracle["se"].items():
        assert result["result"]["standard_errors"][term] == pytest.approx(
            expected, rel=1e-10
        )


def test_survey_adapter_reports_allowed_replicate_failures_in_the_aggregate() -> None:
    calls = 0

    def one_replicate_fails(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
        nonlocal calls
        calls += 1
        if calls == 2:  # base fit is call one; the first replicate is call two.
            raise np.linalg.LinAlgError("synthetic replicate failure")
        return _weighted_ols(frame, weights)

    result = run_survey_replicate_covariance(
        _design(),
        EstimatorSpec(name="survey-adapter-one-failure", refit=one_replicate_fails),
        replicate_type="jackknife",
        max_failures=1,
    )

    summary = result["result"]["replicate_summary"]
    assert summary["attempted"] == 16
    assert summary["succeeded"] == 15
    assert summary["failed"] == 1
    assert summary["failure_reasons"] == {"REPLICATE_STRATEGY_EXCEPTION": 1}


def test_survey_adapter_rejects_ambiguous_or_unsafe_weight_boundaries() -> None:
    with pytest.raises(SurveyPackAdapterError, match="replicate_type"):
        run_survey_replicate_covariance(_design(), _estimator())
    with pytest.raises(SurveyPackAdapterError, match="finite"):
        run_survey_replicate_covariance(
            _design(frame=_frame().assign(weight=np.nan)),
            _estimator(),
            replicate_type="jackknife",
        )


def test_survey_adapter_rejects_an_allocation_above_the_hard_bound(monkeypatch) -> None:
    frame = _frame()
    design = _design(frame=frame)
    monkeypatch.setattr(
        "workbench.engine.replicate_combine.survey_adapter.MAX_SURVEY_REPLICATE_CELLS",
        len(frame) * 16 - 1,
    )
    with pytest.raises(SurveyPackAdapterError, match="allocation"):
        run_survey_replicate_covariance(design, _estimator(), replicate_type="brr")


def test_survey_adapter_exports_a_positive_allocation_limit() -> None:
    assert MAX_SURVEY_REPLICATE_CELLS > 0
