import numpy as np
import pandas as pd
import pytest

pytest.importorskip("linearmodels")

from workbench.econometrics.runner import run_did, run_event_study
from workbench.engine.did_spec import normalize_did_input


def _panel(effect=2.0):
    rng = np.random.default_rng(1)
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0), ("D", 0)]:
        fe = rng.normal()
        for year in range(2018, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            y = fe + 0.1 * (year - 2018) + effect * d + rng.normal(0, 0.01)
            rows.append({"id": ent, "year": year, "y": y, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_run_did_recovers_att():
    norm = normalize_did_input(_panel(effect=2.0), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    primary, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year",
                              model_id="did_1")
    assert primary["model_type"] == "did"
    assert "_did_D" in primary["coefficients"]
    assert primary["coefficients"]["_did_D"]["estimate"] == pytest.approx(2.0, abs=0.1)


def test_run_event_study_returns_path_with_reference_period_dropped():
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    es = run_event_study(norm.frame, y="y", x=[], entity="id", time="year",
                         event_time_col="_did_event_time", ref_period=-1)
    assert es["ref_period"] == -1
    assert -1 not in es["event_time"]            # reference period omitted
    assert len(es["coef"]) == len(es["event_time"]) == len(es["se"])
    # post-period effect is positive and ~2.0; pre-period near 0.
    idx0 = es["event_time"].index(0)
    assert es["coef"][idx0] == pytest.approx(2.0, abs=0.3)


def test_event_study_pre_trend_is_flat():
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    es = run_event_study(norm.frame, y="y", x=[], entity="id", time="year",
                         event_time_col="_did_event_time", ref_period=-1)
    # leads (event_time < 0) should be near zero: clean parallel pre-trend.
    for k, c in zip(es["event_time"], es["coef"]):
        if k < 0:
            assert abs(c) < 0.3, f"pre-trend lead at {k} not flat: {c}"


def test_run_did_accepts_covariates():
    # add a numeric covariate; run_did must thread x into the formula without error
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    frame = norm.frame.copy()
    # entity-and-time-varying control (not collinear with two-way FE)
    rng = np.random.default_rng(7)
    frame["ctrl"] = rng.normal(size=len(frame))
    primary, fitted = run_did(frame, y="y", x=["ctrl"], entity="id", time="year",
                              model_id="did_1")
    assert "_did_D" in primary["coefficients"]
    assert "ctrl" in primary["coefficients"]


def test_event_study_rejects_fractional_event_times():
    # Build a frame whose _did_event_time has a fractional value; run_event_study
    # must refuse rather than silently truncate periods together.
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    frame = norm.frame.copy()
    # corrupt one event-time to a non-integer period
    mask = frame["_did_event_time"].notna()
    first_idx = frame.index[mask][0]
    frame.loc[first_idx, "_did_event_time"] = 1.5
    with pytest.raises(ValueError, match="DID_EVENT_TIME_NONINTEGER"):
        run_event_study(frame, y="y", x=[], entity="id", time="year",
                        event_time_col="_did_event_time", ref_period=-1)


def test_run_event_study_raises_when_unidentified():
    # The reference period event_time=-1 (year 2020) is ABSENT (gappy years) and
    # there is a single cohort 2021 => event-time dummies are collinear with the
    # time fixed effects; the event study is not identified.
    rows = []
    for ent, cohort in [("A", 2021), ("B", 2021), ("C", 2021), ("D", 0), ("E", 0), ("F", 0)]:
        for year in [2018, 2019, 2021, 2022]:  # 2020 (the -1 reference) is missing
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year, "y": 1.0 + 2.0 * d, "first_treat": cohort})
    norm = normalize_did_input(pd.DataFrame(rows), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    with pytest.raises(ValueError, match="DID_EVENT_STUDY_UNIDENTIFIED"):
        run_event_study(norm.frame, y="y", x=[], entity="id", time="year",
                        event_time_col="_did_event_time", ref_period=-1)
