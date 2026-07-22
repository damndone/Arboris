from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest
from arch.univariate import StudentsT

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate
from workbench.engine.packs.arma_garch.input import (
    PARSED_TIME_COLUMN,
    PARSED_VALUE_COLUMN,
    ROW_ID_COLUMN,
)
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN
from workbench.engine.packs.arma_garch.volatility import search_joint_variance_candidates


def _contract(*, transform: str = "level", refit_every: int = 2) -> ArmaGarchAnalysisContract:
    return ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "dataset:rolling:1",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "business_or_trading_observations",
            "transform": transform,
            "transform_confirmed": True,
            "selection_mode": "manual",
            "arma": {"p": 1, "q": 0, "constant_mode": "include"},
            "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
            "estimation_strategy": "joint",
            "innovation_distribution": "normal",
            "validation": {"validation_n": 4, "refit_every": refit_every},
        }
    )


def _garch_values(n: int = 150, seed: int = 20260720) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = np.zeros(n)
    errors = np.zeros(n)
    variances = np.ones(n)
    for index in range(1, n):
        variances[index] = 0.08 + 0.10 * errors[index - 1] ** 2 + 0.84 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
        values[index] = 0.2 + 0.45 * values[index - 1] + errors[index]
    return values


def _frame(values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            ROW_ID_COLUMN: [f"row-{index}" for index in range(len(values))],
            PARSED_TIME_COLUMN: pd.date_range("2020-01-01", periods=len(values), freq="B", tz="UTC"),
            PARSED_VALUE_COLUMN: values,
            TRANSFORMED_VALUE_COLUMN: values,
        }
    )


def _frozen_candidates(frame: pd.DataFrame, contract: ArmaGarchAnalysisContract):
    split = freeze_train_validation_split(frame, contract)
    training = split.training_view[TRANSFORMED_VALUE_COLUMN].to_numpy(dtype=float)
    mean = fit_arma_candidate(
        training,
        ArmaCandidateSpec(candidate_id="arma-p1-q0-c", p=1, q=0, constant=True),
    )
    search = search_joint_variance_candidates(
        training,
        contract,
        mean_candidate_id=mean.candidate_id,
        mean_order=(mean.p, mean.q),
        mean_constant=mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )
    return split, mean, selected


@pytest.mark.parametrize(
    ("transform", "last_level", "point", "expected_point", "method", "statistic"),
    [
        ("level", 10.0, 1.5, 1.5, "identity", "conditional_mean"),
        ("log_level", 10.0, math.log(12.0), 12.0, "exp_quantiles", "conditional_median"),
        ("diff_1", 10.0, 1.5, 11.5, "last_level_plus_quantile", "conditional_mean"),
        ("log_return_pct", 10.0, 100.0 * math.log(1.2), 12.0, "last_level_times_exp_quantile_pct", "conditional_median"),
    ],
)
def test_backtransform_preserves_quantile_semantics(
    transform: str,
    last_level: float,
    point: float,
    expected_point: float,
    method: str,
    statistic: str,
) -> None:
    from workbench.engine.packs.arma_garch.forecast import backtransform_forecast

    result = backtransform_forecast(
        transform=transform,
        last_level=last_level,
        point=point,
        lower=point - 0.2,
        upper=point + 0.3,
        lower_quantile=point - 0.1,
    )

    assert result["point_or_median"] == pytest.approx(expected_point)
    assert result["backtransform_method"] == method
    assert result["point_statistic"] == statistic
    assert "conditional_variance" not in result


def test_student_t_quantiles_use_arch_standardized_distribution() -> None:
    from workbench.engine.packs.arma_garch.forecast import innovation_quantiles

    actual = innovation_quantiles(
        distribution="student_t",
        probabilities=(0.025, 0.05, 0.975),
        fitted_parameters={"nu": 8.0},
    )

    expected = StudentsT().ppf([0.025, 0.05, 0.975], [8.0])
    assert actual == pytest.approx(tuple(float(value) for value in expected))


def test_expanding_one_step_uses_frozen_spec_and_fixed_parameter_updates() -> None:
    from workbench.engine.packs.arma_garch.forecast import run_rolling_validation

    values = _garch_values()
    frame = _frame(values)
    source_before = frame.copy(deep=True)
    contract = _contract(refit_every=2)
    split, mean, variance = _frozen_candidates(frame, contract)

    result = run_rolling_validation(
        frame,
        split,
        contract,
        mean_candidate=mean,
        variance_candidate=variance,
    )

    assert len(result.rows) == 4
    assert [row.fit_method for row in result.rows] == [
        "refit",
        "fixed_parameters_update",
        "refit",
        "fixed_parameters_update",
    ]
    assert [row.target_row_id for row in result.rows] == list(split.validation_row_ids)
    assert result.selection_repeated_during_validation is False
    assert result.frozen_spec["mean_candidate_id"] == mean.candidate_id
    assert result.frozen_spec["variance_candidate_id"] == variance.candidate_id
    assert result.metrics.validation_n == 4
    assert result.metrics.successful_forecast_n == 4
    assert result.metrics.coverage_count <= result.metrics.validation_n
    assert result.metrics.coverage_interval[0] <= result.metrics.interval_coverage <= result.metrics.coverage_interval[1]
    assert result.comparison["locked_target_row_ids"] == split.validation_row_ids
    assert result.comparison["comparison_validation_n"] == 4
    assert result.comparison["arma_only"]["validation_n"] == 4
    assert all(row.predictive_interval == "plugin_conditional" for row in result.rows)
    assert all(row.parameter_uncertainty_included is False for row in result.rows)
    pd.testing.assert_frame_equal(frame, source_before)
    json.dumps(result.to_dict(), allow_nan=False)

    with pytest.raises(TypeError):
        result.frozen_spec["mean_candidate_id"] = "changed"


def test_rolling_rejects_changed_split_or_candidate_binding_before_fit() -> None:
    from dataclasses import replace

    from workbench.engine.packs.arma_garch.forecast import run_rolling_validation

    frame = _frame(_garch_values())
    contract = _contract()
    split, mean, variance = _frozen_candidates(frame, contract)

    with pytest.raises(ValueError, match="split contract hash"):
        run_rolling_validation(
            frame,
            replace(split, contract_hash="0" * 64),
            contract,
            mean_candidate=mean,
            variance_candidate=variance,
        )
    with pytest.raises(ValueError, match="mean binding"):
        run_rolling_validation(
            frame,
            split,
            contract,
            mean_candidate=replace(mean, candidate_id="changed"),
            variance_candidate=variance,
        )
    changed = frame.copy(deep=True)
    changed.loc[changed.index[-1], TRANSFORMED_VALUE_COLUMN] += 100.0
    with pytest.raises(ValueError, match="view hash"):
        run_rolling_validation(
            changed,
            split,
            contract,
            mean_candidate=mean,
            variance_candidate=variance,
        )
    with pytest.raises(ValueError, match="distribution"):
        run_rolling_validation(
            frame,
            split,
            contract,
            mean_candidate=mean,
            variance_candidate=replace(variance, distribution="student_t"),
        )


def test_first_forecast_does_not_read_future_validation_values() -> None:
    from workbench.engine.packs.arma_garch.forecast import run_rolling_validation

    frame = _frame(_garch_values())
    contract = _contract()
    split, mean, variance = _frozen_candidates(frame, contract)
    original = run_rolling_validation(
        frame,
        split,
        contract,
        mean_candidate=mean,
        variance_candidate=variance,
    )
    changed = frame.copy(deep=True)
    changed.loc[changed.index[-1], TRANSFORMED_VALUE_COLUMN] += 100.0
    changed.loc[changed.index[-1], PARSED_VALUE_COLUMN] += 100.0
    changed_split = freeze_train_validation_split(changed, contract)
    rerun = run_rolling_validation(
        changed,
        changed_split,
        contract,
        mean_candidate=mean,
        variance_candidate=variance,
    )

    assert rerun.rows[0].conditional_mean == pytest.approx(original.rows[0].conditional_mean)
    assert rerun.rows[0].conditional_variance == pytest.approx(original.rows[0].conditional_variance)


def test_comparison_uses_only_origins_where_both_models_succeeded(monkeypatch) -> None:
    from workbench.engine.packs.arma_garch import forecast

    frame = _frame(_garch_values())
    contract = _contract()
    split, mean, variance = _frozen_candidates(frame, contract)
    original_baseline = forecast._sequential_point_forecast
    calls = 0

    def fail_first_baseline(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("injected baseline failure")
        return original_baseline(*args, **kwargs)

    monkeypatch.setattr(forecast, "_sequential_point_forecast", fail_first_baseline)
    result = forecast.run_rolling_validation(
        frame,
        split,
        contract,
        mean_candidate=mean,
        variance_candidate=variance,
    )

    assert result.metrics.validation_n == 4
    assert result.metrics.successful_forecast_n == 4
    assert result.comparison["comparison_validation_n"] == 3
    assert result.comparison["arma_garch"]["validation_n"] == 3
    assert result.comparison["arma_only"]["validation_n"] == 3
    assert result.comparison["comparison_target_row_ids"] == split.validation_row_ids[1:]


def test_full_sample_next_forecast_keeps_fixed_spec_and_unknown_next_time() -> None:
    from workbench.engine.packs.arma_garch.forecast import forecast_next_observation

    frame = _frame(_garch_values())
    contract = _contract(refit_every=1)
    _, mean, variance = _frozen_candidates(frame, contract)

    result = forecast_next_observation(
        frame,
        contract,
        mean_candidate=mean,
        variance_candidate=variance,
        next_timestamp=None,
    )
    payload = result.to_dict()

    assert result.forecast_origin_row_id == "row-149"
    assert result.target_time is None
    assert result.target_label == "next_observation"
    assert result.conditional_variance > 0.0
    assert result.lower_bound < result.conditional_mean < result.upper_bound
    assert payload["fit_method"] == "full_sample_refit"
    assert payload["frozen_spec"]["mean_candidate_id"] == mean.candidate_id
    assert payload["predictive_interval"] == "plugin_conditional"
    assert payload["parameter_uncertainty_included"] is False
    assert payload["original_scale"]["variance_available"] is False
    json.dumps(payload, allow_nan=False)
