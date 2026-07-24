"""Fail-closed input policy for the ETS pack (locked contract point 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.fixtures.models.ets.known_truth import short_stable_series
from workbench.contracts.model.ets import ETSContractError
from workbench.engine.packs.ets.errors import ETSInputError
from workbench.engine.packs.ets.input import ETSModelOptions, prepare_ets_input
from workbench.engine.packs.ets.runner import fit_ets


def _options(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "time_column": "date",
        "value_column": "y",
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
    }
    payload.update(overrides)
    return payload


def _frame() -> pd.DataFrame:
    return short_stable_series().frame()


def _prepare(frame: pd.DataFrame, **overrides):
    return prepare_ets_input(frame, ETSModelOptions.from_dict(_options(**overrides)))


def test_absent_column_is_blocking() -> None:
    frame = _frame().drop(columns=["y"])
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_INPUT_COLUMN_MISSING"
    assert excinfo.value.diagnostic.severity == "blocking"
    assert excinfo.value.evidence["column"] == "y"


def test_interior_missing_value_is_blocking() -> None:
    frame = _frame()
    frame.loc[57, "y"] = np.nan
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    error = excinfo.value
    assert error.code == "ETS_INTERIOR_MISSING_VALUE"
    assert error.diagnostic.severity == "blocking"
    assert error.evidence["interior_missing_count"] == 1
    assert error.evidence["first_missing_timestamp"].startswith("2015-02-27")


def test_edge_missing_values_are_excluded_and_counted() -> None:
    frame = _frame()
    frame.loc[0, "y"] = np.nan
    frame.loc[1, "y"] = np.nan
    frame.loc[119, "y"] = np.nan
    prepared = _prepare(frame)

    assert prepared.audit.source_row_count == 120
    assert prepared.audit.n_obs == 117
    assert prepared.audit.n_excluded == 3
    assert prepared.audit.exclusion_reasons == {
        "leading_missing_value": 2,
        "trailing_missing_value": 1,
    }
    assert prepared.audit.first_timestamp.startswith("2015-01-03")


def test_interior_time_gap_is_blocking() -> None:
    frame = _frame().drop(index=[40, 41]).reset_index(drop=True)
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    error = excinfo.value
    assert error.code == "ETS_INTERIOR_TIME_GAP"
    assert error.diagnostic.severity == "blocking"
    assert error.evidence["modal_step_seconds"] == 86400.0
    assert error.evidence["distinct_step_count"] == 2


def test_business_observation_semantics_allows_calendar_weekends_and_survives_result(
    ) -> None:
    frame = _frame()
    frame["date"] = pd.bdate_range("2015-01-05", periods=len(frame))
    options = _options(time_index_semantics="business_or_trading_observations")

    prepared = prepare_ets_input(frame, ETSModelOptions.from_dict(options))
    assert prepared.options.time_index_semantics == "business_or_trading_observations"

    outcome = fit_ets(frame, options)
    assert outcome.result.time_index_semantics == "business_or_trading_observations"


def test_duplicate_timestamp_is_blocking() -> None:
    frame = _frame()
    frame.loc[10, "date"] = frame.loc[9, "date"]
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_DUPLICATE_TIMESTAMP"
    assert excinfo.value.evidence["duplicate_count"] == 1


def test_unparseable_timestamp_is_blocking() -> None:
    frame = _frame()
    frame.loc[3, "date"] = "not-a-date"
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_TIME_PARSE_FAILED"
    assert excinfo.value.evidence["invalid_count"] == 1


def test_unsorted_input_is_sorted_not_rejected() -> None:
    frame = _frame()
    shuffled = frame.sample(frac=1.0, random_state=7).reset_index(drop=True)
    ordered = _prepare(frame)
    reordered = _prepare(shuffled)

    assert reordered.audit.n_obs == 120
    assert reordered.sample_fingerprint == ordered.sample_fingerprint


def test_insufficient_observations_are_blocking() -> None:
    frame = _frame().iloc[:9].reset_index(drop=True)
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_INSUFFICIENT_OBSERVATIONS"
    assert excinfo.value.evidence["n_obs"] == 9
    assert excinfo.value.evidence["required"] == 10


def test_seasonal_specification_requires_two_full_cycles_plus_margin() -> None:
    frame = _frame().iloc[:28].reset_index(drop=True)
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame, seasonal="add", seasonal_periods=12)
    assert excinfo.value.code == "ETS_INSUFFICIENT_OBSERVATIONS"
    assert excinfo.value.evidence["required"] == 29


def test_multiplicative_component_rejects_non_positive_values() -> None:
    frame = _frame()
    frame["y"] = frame["y"].abs() + 100.0
    frame.loc[5, "y"] = -1.0
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame, error="mul")
    assert excinfo.value.code == "ETS_NONPOSITIVE_FOR_MULTIPLICATIVE"
    assert excinfo.value.evidence["minimum_value"] == -1.0


def test_constant_series_is_blocking() -> None:
    frame = _frame()
    frame["y"] = 3.0
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_CONSTANT_SERIES"
    assert excinfo.value.evidence["value"] == 3.0


def test_all_missing_series_is_blocking() -> None:
    frame = _frame()
    frame["y"] = np.nan
    with pytest.raises(ETSInputError) as excinfo:
        _prepare(frame)
    assert excinfo.value.code == "ETS_NO_MODELLED_OBSERVATIONS"


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"error": "log"}, "error must be one of"),
        ({"trend": "flat"}, "trend must be one of"),
        ({"seasonal": "add"}, "seasonal_periods is required"),
        ({"seasonal": None, "seasonal_periods": 4}, "seasonal_periods is only allowed"),
        ({"trend": None, "damped_trend": True}, "damped_trend requires a trend"),
        ({"seasonal": "add", "seasonal_periods": 1}, "seasonal_periods must be an int"),
        ({"damped_trend": "yes"}, "damped_trend must be a boolean"),
        ({"time_column": ""}, "time_column must be a non-empty string"),
    ],
)
def test_option_validation_rejects_undeclared_specifications(overrides, fragment) -> None:
    with pytest.raises(ETSContractError) as excinfo:
        ETSModelOptions.from_dict(_options(**overrides))
    assert fragment in str(excinfo.value)


def test_option_validation_rejects_unknown_and_missing_fields() -> None:
    payload = _options()
    payload["lookahead"] = 3
    with pytest.raises(ETSContractError) as excinfo:
        ETSModelOptions.from_dict(payload)
    assert "unknown ets model_options field: lookahead" in str(excinfo.value)

    incomplete = _options()
    incomplete.pop("value_column")
    with pytest.raises(ETSContractError) as excinfo:
        ETSModelOptions.from_dict(incomplete)
    assert "missing ets model_options field: value_column" in str(excinfo.value)


def test_excluded_edge_rows_are_reported_in_the_result() -> None:
    frame = _frame()
    frame.loc[0, "y"] = np.nan
    outcome = fit_ets(frame, _options())

    assert outcome.result.n_obs == 119
    assert outcome.result.n_excluded == 1
    assert outcome.result.exclusion_reasons == {"leading_missing_value": 1}
