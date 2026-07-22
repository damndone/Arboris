from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract


def _contract(
    *,
    transform: str = "level",
    semantics: str = "business_or_trading_observations",
) -> ArmaGarchAnalysisContract:
    return ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "dataset:test:1",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": semantics,
            "transform": transform,
            "transform_confirmed": True,
            "validation": {},
        }
    )


def _positive_frame(n: int = 100) -> pd.DataFrame:
    index = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "when": pd.bdate_range("2024-01-02", periods=n),
            "value": np.exp(2.0 + 0.004 * index + 0.05 * np.sin(index / 3.0)),
            "untouched": [f"row-{position}" for position in range(n)],
        }
    )


def _input_api():
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    from workbench.engine.packs.arma_garch.input import (
        PARSED_TIME_COLUMN,
        ROW_ID_COLUMN,
        audit_time_value_input,
        prepare_arma_garch_input,
    )

    return (
        ArmaGarchInputError,
        PARSED_TIME_COLUMN,
        ROW_ID_COLUMN,
        audit_time_value_input,
        prepare_arma_garch_input,
    )


def _transform_api():
    from workbench.engine.packs.arma_garch.transforms import (
        LINEAGE_COLUMN,
        TRANSFORMED_VALUE_COLUMN,
        apply_transform,
        build_transform_profiles,
    )

    return LINEAGE_COLUMN, TRANSFORMED_VALUE_COLUMN, apply_transform, build_transform_profiles


def test_audit_uses_a_stably_sorted_copy_and_never_mutates_source() -> None:
    _, parsed_time, row_id, audit_input, _ = _input_api()
    source = _positive_frame(80).iloc[::-1]
    source.index = [f"original-{position}" for position in range(len(source))]
    before = source.copy(deep=True)

    audited = audit_input(source, _contract())

    assert_frame_equal(source, before)
    assert audited.source_hash_before == audited.source_hash_after
    assert audited.source_unchanged is True
    assert audited.time_index.already_sorted is False
    assert audited.analysis_view[parsed_time].is_monotonic_increasing
    assert audited.analysis_view[row_id].is_unique
    assert audited.analysis_view.iloc[0][row_id] == "source-row:0000000079"
    assert "untouched" not in audited.analysis_view.columns


def test_audit_and_prepared_views_are_isolated_from_callers_and_source_objects() -> None:
    _, _, _, audit_input, prepare = _input_api()
    source = _positive_frame(80)
    source["nested"] = [{"position": position} for position in range(len(source))]
    before = source.copy(deep=True)

    audited = audit_input(source, _contract())
    exposed_audit = audited.analysis_view
    exposed_audit.loc[0, "value"] = -999_999.0
    prepared = prepare(source, _contract())
    exposed_prepared = prepared.transformed_view
    exposed_prepared.loc[0, "value"] = -999_999.0

    assert "nested" not in audited.analysis_view.columns
    assert float(audited.analysis_view.loc[0, "value"]) != -999_999.0
    assert float(prepared.transformed_view.loc[0, "value"]) != -999_999.0
    assert_frame_equal(source, before)


def test_duplicate_timestamp_is_a_structured_blocking_error() -> None:
    error_type, _, _, audit_input, prepare = _input_api()
    source = _positive_frame(80)
    source.loc[1, "when"] = source.loc[0, "when"]
    before = source.copy(deep=True)

    audited = audit_input(source, _contract())
    assert audited.time_index.duplicate_timestamp_count == 2
    assert "DUPLICATE_TIMESTAMP" in {item.code for item in audited.diagnostics}

    with pytest.raises(error_type) as exc_info:
        prepare(source, _contract())

    assert exc_info.value.code == "DUPLICATE_TIMESTAMP"
    assert exc_info.value.to_dict()["severity"] == "blocking"
    assert exc_info.value.to_dict()["evidence"]["duplicate_timestamp_count"] == 2
    assert_frame_equal(source, before)


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda frame: frame.__setitem__("when", ["bad"] + list(frame["when"].iloc[1:])), "TIME_PARSE_FAILED"),
        (lambda frame: frame.__setitem__("value", ["bad"] + list(frame["value"].iloc[1:])), "VALUE_PARSE_FAILED"),
        (lambda frame: frame.__setitem__("value", [np.inf] + list(frame["value"].iloc[1:])), "NONFINITE_VALUES"),
        (lambda frame: frame.__setitem__("value", np.ones(len(frame))), "CONSTANT_SERIES"),
    ],
)
def test_data_quality_blockers_are_machine_readable(mutate, expected_code: str) -> None:
    error_type, _, _, _, prepare = _input_api()
    source = _positive_frame(80)
    mutate(source)
    before = source.copy(deep=True)

    with pytest.raises(error_type) as exc_info:
        prepare(source, _contract())

    assert exc_info.value.code == expected_code
    assert exc_info.value.evidence
    assert exc_info.value.impact
    assert isinstance(exc_info.value.to_dict()["recommended_actions"], list)
    assert_frame_equal(source, before)


def test_time_semantics_control_lag_units_gaps_and_next_timestamp() -> None:
    _, _, _, audit_input, _ = _input_api()
    regular = pd.DataFrame(
        {
            "when": pd.date_range("2025-01-01", periods=80, freq="D"),
            "value": np.linspace(10.0, 20.0, 80),
        }
    )
    trading = pd.DataFrame(
        {
            "when": pd.bdate_range("2025-01-02", periods=80),
            "value": np.linspace(10.0, 20.0, 80),
        }
    )
    ordered = pd.DataFrame(
        {"when": list(range(80, 0, -1)), "value": np.linspace(10.0, 20.0, 80)}
    )

    regular_audit = audit_input(
        regular, _contract(semantics="regular_calendar")
    ).time_index
    trading_audit = audit_input(trading, _contract()).time_index
    ordered_audit = audit_input(
        ordered, _contract(semantics="observation_order")
    ).time_index

    assert regular_audit.inferred_frequency == "D"
    assert regular_audit.internal_gap_count == 0
    assert regular_audit.lag_unit == "calendar interval"
    assert regular_audit.next_timestamp == "2025-03-22T00:00:00Z"
    assert trading_audit.inferred_frequency == "B"
    assert trading_audit.lag_unit == "trading observation"
    assert trading_audit.next_timestamp is not None
    assert ordered_audit.lag_unit == "observation"
    assert ordered_audit.next_timestamp is None


def test_regular_calendar_internal_gap_is_not_silently_compressed() -> None:
    error_type, _, _, audit_input, prepare = _input_api()
    source = pd.DataFrame(
        {
            "when": pd.date_range("2025-01-01", periods=81, freq="D").delete(40),
            "value": np.linspace(10.0, 20.0, 80),
        }
    )
    contract = _contract(semantics="regular_calendar")

    audited = audit_input(source, contract)

    assert audited.time_index.internal_gap_count == 1
    with pytest.raises(error_type) as exc_info:
        prepare(source, contract)
    assert exc_info.value.code == "INTERNAL_GAPS_UNCONFIRMED"


@pytest.mark.parametrize(
    "semantics", ["regular_calendar", "business_or_trading_observations"]
)
def test_numeric_observation_index_cannot_be_misread_as_calendar_time(
    semantics: str,
) -> None:
    error_type, _, _, audit_input, prepare = _input_api()
    source = pd.DataFrame(
        {"when": range(1, 81), "value": np.linspace(10.0, 20.0, 80)}
    )
    contract = _contract(semantics=semantics)

    audited = audit_input(source, contract)

    assert audited.time_index.parsed_time_count == 0
    assert audited.time_index.next_timestamp is None
    with pytest.raises(error_type) as exc_info:
        prepare(source, contract)
    assert exc_info.value.code == "TIME_PARSE_FAILED"


def test_timezone_offset_in_string_input_is_preserved_in_audit_evidence() -> None:
    _, _, _, audit_input, _ = _input_api()
    source = pd.DataFrame(
        {
            "when": [
                timestamp.isoformat()
                for timestamp in pd.date_range(
                    "2025-01-01 09:00:00-05:00", periods=80, freq="D"
                )
            ],
            "value": np.linspace(10.0, 20.0, 80),
        }
    )

    audited = audit_input(
        source, _contract(semantics="regular_calendar")
    )

    assert audited.time_index.timezone == "UTC-05:00"


def test_timezone_audit_scans_all_rows_and_warns_on_mixed_inputs() -> None:
    _, _, _, audit_input, _ = _input_api()
    naive = [
        timestamp.isoformat()
        for timestamp in pd.date_range("2025-01-01", periods=10, freq="D")
    ]
    offset = [
        timestamp.isoformat()
        for timestamp in pd.date_range(
            "2025-01-11 00:00:00-05:00", periods=70, freq="D"
        )
    ]
    source = pd.DataFrame(
        {"when": [*naive, *offset], "value": np.linspace(10.0, 20.0, 80)}
    )

    audited = audit_input(source, _contract())

    assert audited.time_index.timezone == "mixed[UTC-05:00,naive]"
    diagnostic_by_code = {item.code: item for item in audited.diagnostics}
    assert diagnostic_by_code["MIXED_TIMEZONE_INPUT"].severity == "warning"


def test_manual_single_spec_does_not_receive_auto_grid_size_warning() -> None:
    _, _, _, audit_input, _ = _input_api()
    contract = ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "dataset:manual:1",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "business_or_trading_observations",
            "transform": "level",
            "transform_confirmed": True,
            "validation": {},
            "selection_mode": "manual",
            "arma": {"p": 1, "q": 0, "constant_mode": "include"},
            "variance": {"model": "constant_variance"},
        }
    )

    audited = audit_input(_positive_frame(80), contract)

    assert audited.data_quality.estimated_candidate_count == 1
    assert audited.data_quality.candidate_count_exceeds_sample is False
    assert "CANDIDATE_LIMIT_EXCEEDED" not in {
        item.code for item in audited.diagnostics
    }


def test_auto_candidate_budget_counts_sequential_searches_not_a_cartesian_grid() -> None:
    _, _, _, audit_input, _ = _input_api()

    audited = audit_input(_positive_frame(80), _contract())

    # 13 bounded (p, q) orders × two constant choices, then 12 variance fits.
    assert audited.data_quality.estimated_candidate_count == 38
    assert audited.data_quality.candidate_count_exceeds_sample is False


def test_four_transform_profiles_and_lineage_are_explicit() -> None:
    _, _, row_id, audit_input, _ = _input_api()
    lineage, transformed, apply_transform, build_profiles = _transform_api()
    source = _positive_frame(100)
    audited = audit_input(source, _contract())

    profiles = build_profiles(audited.analysis_view)

    assert set(profiles) == {"level", "log_level", "diff_1", "log_return_pct"}
    assert all(profile.eligible for profile in profiles.values())
    assert profiles["level"].n_effective == 100
    assert profiles["level"].lost_rows == ()
    assert profiles["diff_1"].n_effective == 99
    assert profiles["diff_1"].lost_rows == ("source-row:0000000000",)
    assert profiles["log_return_pct"].adf_statistic is not None
    assert profiles["log_return_pct"].adf_p_value is not None
    assert profiles["log_return_pct"].acf_decay_summary
    assert profiles["log_return_pct"].recommendation_reason

    result = apply_transform(audited.analysis_view, "log_return_pct")
    expected_first = 100.0 * math.log(source.loc[1, "value"] / source.loc[0, "value"])
    assert result.iloc[0][transformed] == pytest.approx(expected_first)
    assert result.iloc[0][lineage] == (
        "source-row:0000000000",
        "source-row:0000000001",
    )
    assert result.iloc[0][row_id] == "source-row:0000000001"
    assert "value" in result.columns
    assert result.iloc[0]["value"] == source.loc[1, "value"]


def test_outlier_profile_does_not_hide_shocks_when_mad_is_zero() -> None:
    _, _, _, audit_input, _ = _input_api()
    _, _, _, build_profiles = _transform_api()
    source = pd.DataFrame(
        {
            "when": pd.bdate_range("2025-01-02", periods=80),
            "value": [1.0] * 79 + [1_000.0],
        }
    )

    profiles = build_profiles(audit_input(source, _contract()).analysis_view)

    summary = profiles["level"].outlier_sensitivity_summary
    assert summary["robust_z_above_4_count"] == 1
    assert summary["share"] == pytest.approx(1 / 80)


def test_log_transform_ineligibility_never_changes_values_or_auto_corrects() -> None:
    error_type, _, _, audit_input, prepare = _input_api()
    _, _, _, build_profiles = _transform_api()
    source = _positive_frame(80)
    source.loc[10, "value"] = 0.0
    source.loc[11, "value"] = -1.0
    before = source.copy(deep=True)
    contract = _contract(transform="log_return_pct")

    audited = audit_input(source, contract)
    profiles = build_profiles(audited.analysis_view)

    assert profiles["log_level"].eligible is False
    assert profiles["log_return_pct"].eligible is False
    assert profiles["log_return_pct"].ineligibility_code == "LOG_REQUIRES_POSITIVE_VALUES"
    with pytest.raises(error_type) as exc_info:
        prepare(source, contract)
    assert exc_info.value.code == "LOG_REQUIRES_POSITIVE_VALUES"
    assert_frame_equal(source, before)
