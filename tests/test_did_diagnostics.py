import numpy as np
import pandas as pd
import pytest

pytest.importorskip("linearmodels")

from workbench.econometrics.runner import run_did
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.did_diagnostics import build_did_diagnostics


def _panel(staggered=False):
    rng = np.random.default_rng(2)
    cohorts = ({"A": 2019, "B": 2021, "C": 0} if staggered
               else {"A": 2020, "B": 2020, "C": 0})
    rows = []
    for ent, cohort in cohorts.items():
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    return pd.DataFrame(rows)


def test_bundle_has_all_four_sections_and_is_json_safe():
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    _, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, norm.frame, covariance="robust")
    assert set(diag) >= {"att", "event_study", "parallel_trends", "goodman_bacon", "spec"}
    assert isinstance(diag["att"]["estimate"], float)
    assert diag["parallel_trends"]["verdict"] in {"not_rejected", "rejected"}
    import json
    json.dumps(diag)  # must not raise


def test_staggered_panel_attaches_interpretation_restriction():
    norm = normalize_did_input(_panel(staggered=True), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    _, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, norm.frame, covariance="robust")
    assert diag["spec"]["staggered"] is True
    assert "interpretation_restriction" in diag
    assert "Layer 2" in diag["interpretation_restriction"]


def test_unbalanced_panel_skips_bacon_gracefully():
    # Drop rows so the panel is unbalanced; ATT + event study still run, Bacon skips.
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    frame = norm.frame.drop(norm.frame.index[:2])  # unbalance it
    _, fitted = run_did(frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, frame, covariance="robust")
    assert diag["goodman_bacon"]["applicable"] is False
    assert "att" in diag and isinstance(diag["att"]["estimate"], float)
    import json
    json.dumps(diag)


from workbench.engine.did_diagnostics import _parallel_trends


def test_parallel_trends_rejects_on_violated_pretrend():
    # Large, precise lead coefficients => joint pre-trend test rejects.
    es = {"event_time": [-2, -1, 0, 1], "coef": [5.0, 4.0, 2.0, 2.1],
          "se": [0.1, 0.1, 0.1, 0.1], "ci_lower": [], "ci_upper": [], "ref_period": -1}
    pt = _parallel_trends(es)
    assert pt["verdict"] == "rejected"
    assert pt["pvalue"] < 0.05
    assert pt["n_pre_leads"] == 2  # only event_time < 0 leads counted


def test_parallel_trends_not_rejected_when_leads_flat():
    es = {"event_time": [-2, -1, 0, 1], "coef": [0.01, 0.0, 2.0, 2.1],
          "se": [0.2, 0.2, 0.2, 0.2], "ci_lower": [], "ci_upper": [], "ref_period": -1}
    pt = _parallel_trends(es)
    assert pt["verdict"] == "not_rejected"


def test_parallel_trends_tolerates_none_coef_or_se():
    # Fix 1: a None coef/se (absorbed lead) must be skipped, not crash.
    es = {"event_time": [-2, -1, 0, 1], "coef": [None, 0.0, 2.0, 2.1],
          "se": [None, 0.2, 0.2, 0.2], "ci_lower": [], "ci_upper": [], "ref_period": -1}
    pt = _parallel_trends(es)  # must not raise
    assert pt["verdict"] in {"not_rejected", "rejected"}


def test_att_from_fitted_absorbed_raises_value_error():
    # Fix 1: missing/absorbed _did_D => catchable ValueError, not bare KeyError.
    from workbench.engine.did_diagnostics import _att_from_fitted

    class _Fitted:
        params = {}  # _did_D absent

    with pytest.raises(ValueError, match="DID_ATT_ABSORBED"):
        _att_from_fitted(_Fitted())


def test_unidentified_event_study_skipped_but_keeps_att():
    # Reference period event_time=-1 (year 2020) absent (gappy years) + single
    # cohort => event study unidentified, skipped gracefully; ATT still reported,
    # run does not crash.
    rows = []
    for ent, cohort in [("A", 2021), ("B", 2021), ("C", 2021), ("D", 0), ("E", 0), ("F", 0)]:
        for year in [2018, 2019, 2021, 2022]:  # 2020 (the -1 reference) is missing
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year, "y": 1.0 + 2.0 * d, "first_treat": cohort})
    norm = normalize_did_input(pd.DataFrame(rows), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    _, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, norm.frame, covariance="robust")
    assert diag["event_study"]["applicable"] is False
    assert "DID_EVENT_STUDY_UNIDENTIFIED" in diag["event_study"]["message"]
    assert isinstance(diag["att"]["estimate"], float)
    import json
    json.dumps(diag)
