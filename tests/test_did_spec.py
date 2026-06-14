import numpy as np
import pandas as pd
import pytest

from workbench.engine.did_spec import (
    DIDSpecError,
    NormalizedDID,
    normalize_did_input,
    validate_did_spec,
)


def _panel():
    # entities A,B treated in 2020; C never treated; years 2018-2021.
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": 1.0, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_cohort_mode_derives_D_and_event_time():
    norm = normalize_did_input(
        _panel(), mode="cohort", entity="id", time="year", y="y", cohort="first_treat"
    )
    assert isinstance(norm, NormalizedDID)
    f = norm.frame
    # A in 2020 is treated (year >= cohort), in 2019 not.
    a2020 = f[(f["id"] == "A") & (f["year"] == 2020)].iloc[0]
    a2019 = f[(f["id"] == "A") & (f["year"] == 2019)].iloc[0]
    assert a2020["_did_D"] == 1 and a2020["_did_event_time"] == 0
    assert a2019["_did_D"] == 0 and a2019["_did_event_time"] == -1
    # never-treated C: D always 0, event_time NaN, cohort NaN.
    c = f[f["id"] == "C"]
    assert (c["_did_D"] == 0).all()
    assert c["_did_event_time"].isna().all()
    assert norm.summary["n_treated_units"] == 2
    assert norm.summary["n_never_treated"] == 1
    assert norm.summary["staggered"] is False


def test_two_by_two_mode_maps_to_cohort():
    rows = []
    for ent, treat in [("A", 1), ("B", 0)]:
        for year, post in [(2018, 0), (2021, 1)]:
            rows.append({"id": ent, "year": year, "y": 1.0, "treat": treat, "post": post})
    norm = normalize_did_input(
        pd.DataFrame(rows), mode="two_by_two", entity="id", time="year", y="y",
        treat="treat", post="post",
    )
    # treated A gets cohort = earliest year where post==1 (2021); control B never.
    a = norm.frame[norm.frame["id"] == "A"]
    assert a[a["year"] == 2021].iloc[0]["_did_D"] == 1
    assert norm.summary["n_never_treated"] == 1


def test_status_mode_requires_absorbing_treatment():
    rows = [
        {"id": "A", "year": 2019, "y": 1.0, "D": 0},
        {"id": "A", "year": 2020, "y": 1.0, "D": 1},
        {"id": "A", "year": 2021, "y": 1.0, "D": 0},  # turns OFF -> non-absorbing
    ]
    with pytest.raises(DIDSpecError, match="DID_NON_ABSORBING"):
        normalize_did_input(
            pd.DataFrame(rows), mode="status", entity="id", time="year", y="y", status="D"
        )


def test_validate_requires_two_periods_and_comparison_group():
    one_period = pd.DataFrame([{"id": "A", "year": 2020, "y": 1.0, "first_treat": 2020}])
    with pytest.raises(DIDSpecError, match="DID_TOO_FEW_PERIODS"):
        validate_did_spec(one_period, mode="cohort", entity="id", time="year", y="y",
                          cohort="first_treat")
    # all units treated at the same time, no never/not-yet group at the boundary
    all_treated = pd.DataFrame(
        [{"id": e, "year": yr, "y": 1.0, "first_treat": 2018}
         for e in ("A", "B") for yr in (2018, 2019)]
    )
    with pytest.raises(DIDSpecError, match="DID_NO_COMPARISON_GROUP"):
        validate_did_spec(all_treated, mode="cohort", entity="id", time="year", y="y",
                          cohort="first_treat")


def test_role_column_overlap_with_y_rejected():
    with pytest.raises(DIDSpecError, match="DID_INVALID_PARTITION"):
        validate_did_spec(_panel(), mode="cohort", entity="id", time="year", y="y",
                          cohort="y")  # cohort == y


def test_staggered_flag_true_for_multiple_cohorts():
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2021), ("C", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": 1.0, "first_treat": cohort})
    norm = normalize_did_input(pd.DataFrame(rows), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    assert norm.summary["staggered"] is True


from workbench.engine.did_spec import _coerce_cohort_value


@pytest.mark.parametrize("value,expected_nan,expected_val", [
    (0, True, None),
    ("0", True, None),
    ("", True, None),
    ("never", True, None),
    ("NA", True, None),
    (float("inf"), True, None),
    ("2020", False, 2020.0),
    (2019, False, 2019.0),
    ("garbage", True, None),
    (-5, True, None),       # Fix 5: non-positive cohort => never-treated
    (-2020.0, True, None),
])
def test_coerce_cohort_value(value, expected_nan, expected_val):
    result = _coerce_cohort_value(value)
    if expected_nan:
        assert np.isnan(result)
    else:
        assert result == expected_val


# --- Fix 2: string-typed time column -----------------------------------------

def test_non_numeric_time_raises_structured_error():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0)]:
        for yr in ("alpha", "beta", "gamma", "delta"):
            rows.append({"id": ent, "year": yr, "y": 1.0, "first_treat": cohort})
    with pytest.raises(DIDSpecError, match="DID_TIME_NOT_NUMERIC"):
        validate_did_spec(pd.DataFrame(rows), mode="cohort", entity="id",
                          time="year", y="y", cohort="first_treat")


def test_numeric_coercible_string_time_still_works():
    rows = []
    for ent, cohort in [("A", "2020"), ("B", "2020"), ("C", "0")]:
        for yr in ("2018", "2019", "2020", "2021"):
            rows.append({"id": ent, "year": yr, "y": 1.0, "first_treat": cohort})
    # must not raise; coercible string years are valid periods
    validate_did_spec(pd.DataFrame(rows), mode="cohort", entity="id",
                      time="year", y="y", cohort="first_treat")


# --- Fix 4: duplicate (entity, time) rows ------------------------------------

def test_duplicate_entity_time_rows_rejected():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0)]:
        for yr in (2018, 2019, 2020, 2021):
            rows.append({"id": ent, "year": yr, "y": 1.0, "first_treat": cohort})
    df = pd.concat([pd.DataFrame(rows), pd.DataFrame(rows[:1])], ignore_index=True)
    with pytest.raises(DIDSpecError, match="DID_DUPLICATE_OBS"):
        validate_did_spec(df, mode="cohort", entity="id", time="year", y="y",
                          cohort="first_treat")


# --- Fix 5: negative cohort never-treated + inconsistent cohort ---------------

def test_negative_cohort_is_never_treated():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", -1)]:
        for yr in range(2018, 2022):
            rows.append({"id": ent, "year": yr, "y": 1.0, "first_treat": cohort})
    norm = normalize_did_input(pd.DataFrame(rows), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    c = norm.frame[norm.frame["id"] == "C"]
    assert (c["_did_D"] == 0).all()
    assert c["_did_event_time"].isna().all()
    assert norm.summary["n_never_treated"] == 1


def test_inconsistent_cohort_per_entity_rejected():
    rows = [
        {"id": "A", "year": 2018, "y": 1.0, "first_treat": 2020},
        {"id": "A", "year": 2019, "y": 1.0, "first_treat": 2021},  # different cohort
        {"id": "B", "year": 2018, "y": 1.0, "first_treat": 0},
        {"id": "B", "year": 2019, "y": 1.0, "first_treat": 0},
    ]
    with pytest.raises(DIDSpecError, match="DID_INCONSISTENT_COHORT"):
        validate_did_spec(pd.DataFrame(rows), mode="cohort", entity="id",
                          time="year", y="y", cohort="first_treat")
