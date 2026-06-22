import numpy as np
import pandas as pd
import pytest

from workbench.engine.dcdh_spec import (
    normalize_treatment_path, TreatmentPathPanel, DCDHSpecError)


def _panel(rows):
    return pd.DataFrame(rows, columns=["id", "year", "d", "y"])


def _up_switcher_panel():
    rows = []
    for i in range(6):                    # 6 units, baseline d=0, switch up at year 3
        for yr in range(1, 6):
            rows.append([i, yr, int(yr >= 3), float(i + yr)])
    for i in range(6, 10):                # 4 never-switchers (controls)
        for yr in range(1, 6):
            rows.append([i, yr, 0, float(i + yr)])
    return _panel(rows)


def test_normalize_returns_panel_with_derived_columns():
    p = normalize_treatment_path(_up_switcher_panel(), entity="id", time="year",
                                 y="y", treatment="d")
    assert isinstance(p, TreatmentPathPanel)
    f = p.frame
    for col in ("_dcdh_D", "_dcdh_baseline", "_dcdh_first_switch",
                "_dcdh_first_switch_direction", "_dcdh_event_time"):
        assert col in f.columns
    u0 = f[f["id"] == 0].sort_values("year")
    assert u0["_dcdh_baseline"].iloc[0] == 0
    assert u0["_dcdh_first_switch"].iloc[0] == 3
    assert u0["_dcdh_first_switch_direction"].iloc[0] == "up"
    assert list(u0["_dcdh_event_time"]) == [-2, -1, 0, 1, 2]
    u6 = f[f["id"] == 6]
    assert (u6["_dcdh_first_switch_direction"] == "none").all()
    assert u6["_dcdh_event_time"].isna().all()


def test_baseline1_down_switcher_excluded_with_reason():
    rows = []
    for yr in range(1, 6):                # baseline=1 unit that switches 1->0
        rows.append([0, yr, int(yr <= 2), 1.0])
    for i in range(1, 5):                 # eligible up-switchers so the sample isn't empty
        for yr in range(1, 6):
            rows.append([i, yr, int(yr >= 3), float(i + yr)])
    p = normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")
    assert 0 in p.excluded_units
    assert p.frame.loc[p.frame["id"] == 0, "_dcdh_event_time"].isna().all()


def test_non_binary_raises():
    rows = [[0, yr, 2 * int(yr >= 3), 1.0] for yr in range(1, 6)]
    with pytest.raises(DCDHSpecError, match="DCDH_NON_BINARY_TREATMENT"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")


def test_no_switchers_raises():
    rows = [[i, yr, 0, 1.0] for i in range(4) for yr in range(1, 4)]
    with pytest.raises(DCDHSpecError, match="DCDH_NO_SWITCHERS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")


def test_no_eligible_up_switchers_raises():
    # switchers exist but all are baseline=1 down-switchers
    rows = [[i, yr, int(yr <= 2), 1.0] for i in range(4) for yr in range(1, 5)]
    with pytest.raises(DCDHSpecError, match="DCDH_NO_ELIGIBLE_UP_SWITCHERS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")


def test_too_few_periods_raises():
    rows = [[i, 1, 0, 1.0] for i in range(4)]
    with pytest.raises(DCDHSpecError, match="DCDH_TOO_FEW_PERIODS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")


def test_duplicate_obs_raises():
    rows = [[0, 1, 0, 1.0], [0, 1, 1, 2.0], [0, 2, 1, 3.0]]
    with pytest.raises(DCDHSpecError, match="DCDH_DUPLICATE_OBS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")


def test_missing_column_raises():
    rows = [[0, 1, 0, 1.0], [0, 2, 1, 2.0]]
    with pytest.raises(DCDHSpecError, match="DCDH_COLUMN_NOT_FOUND"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="nope")


def test_treatment_na_raises_structured():
    # Regression: a missing/NaN treatment cell must give a structured DCDH_TREATMENT_NA,
    # not a raw IntCastingNaNError from .astype(int).
    rows = [[0, 1, 0, 1.0], [0, 2, None, 2.0], [1, 1, 0, 1.0], [1, 2, 1, 2.0]]
    with pytest.raises(DCDHSpecError, match="DCDH_TREATMENT_NA"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")
