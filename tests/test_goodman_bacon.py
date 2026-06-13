import numpy as np
import pandas as pd
import pytest

from workbench.goodman_bacon_ref import twfe_did_coefficient
from workbench.engine.goodman_bacon import goodman_bacon_decompose


def _staggered_panel():
    # Two timing groups (treated 2019 and 2021) + a never-treated group.
    rng = np.random.default_rng(0)
    rows = []
    cohorts = {"A": 2019, "B": 2019, "C": 2021, "D": 2021, "E": 0, "F": 0}
    for ent, cohort in cohorts.items():
        unit_fe = rng.normal()
        for year in range(2017, 2023):
            treated = 1 if (cohort and year >= cohort) else 0
            y = unit_fe + 0.1 * (year - 2017) + 2.0 * treated + rng.normal(0, 0.01)
            rows.append({"id": ent, "year": year, "y": y, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_components_have_three_types_and_weights_sum_to_one():
    frame = _staggered_panel()
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    types = {c["type"] for c in res["components"]}
    assert types <= {"treated_vs_untreated", "earlier_vs_later", "later_vs_earlier"}
    assert "later_vs_earlier" in types  # staggered => forbidden comparison present
    total_w = sum(c["weight"] for c in res["components"])
    assert total_w == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= res["forbidden_weight"] <= 1.0


def test_weighted_average_equals_twfe_estimate():
    # The decomposition identity: sum(weight * estimate) == TWFE DiD coefficient.
    frame = _staggered_panel()
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    twfe = twfe_did_coefficient(frame, y="y", entity="id", time="year",
                                cohort="first_treat")
    assert res["weighted_avg"] == pytest.approx(twfe, abs=1e-6)


def test_no_forbidden_comparison_when_single_cohort_plus_never():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0), ("D", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": float(year >= cohort and cohort > 0),
                         "first_treat": cohort})
    res = goodman_bacon_decompose(pd.DataFrame(rows), y="y", entity="id",
                                  time="year", cohort="first_treat")
    assert res["forbidden_weight"] == pytest.approx(0.0, abs=1e-9)


def test_identity_holds_with_no_never_treated_all_staggered():
    # All units treated at staggered times; NO never-treated group.
    rng = np.random.default_rng(11)
    rows = []
    for ent, cohort in [("A", 2018), ("B", 2018), ("C", 2020), ("D", 2020),
                        ("E", 2022), ("F", 2022)]:
        fe = rng.normal()
        for year in range(2016, 2024):
            d = 1 if year >= cohort else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2016) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    frame = pd.DataFrame(rows)
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    twfe = twfe_did_coefficient(frame, y="y", entity="id", time="year",
                                cohort="first_treat")
    assert res["weighted_avg"] == pytest.approx(twfe, abs=1e-6)
    assert res["forbidden_weight"] > 0.0  # staggered => forbidden comparisons exist


def test_identity_holds_with_three_treated_cohorts():
    rng = np.random.default_rng(12)
    rows = []
    for ent, cohort in [("A", 2018), ("B", 2020), ("C", 2022), ("D", 0)]:
        fe = rng.normal()
        for year in range(2016, 2024):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2016) + 1.5 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    frame = pd.DataFrame(rows)
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    twfe = twfe_did_coefficient(frame, y="y", entity="id", time="year",
                                cohort="first_treat")
    assert res["weighted_avg"] == pytest.approx(twfe, abs=1e-6)


def test_unbalanced_panel_raises():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": 1.0, "first_treat": cohort})
    frame = pd.DataFrame(rows).iloc[:-1]  # drop one row -> unbalanced
    with pytest.raises(ValueError, match="DID_UNBALANCED_PANEL"):
        goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                cohort="first_treat")
