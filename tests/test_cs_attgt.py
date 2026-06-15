import numpy as np, pandas as pd, pytest
from workbench.engine.cs_attgt import comparison_mask, CSSpecError

def _panel():
    return pd.read_csv("tests/fixtures/cs_did/panel.csv")

def test_never_treated_comparison_excludes_all_finite_cohorts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="never", anticipation=0)
    assert set(cohort[m].unique()) == {np.inf}

def test_not_yet_treated_boundary_delta0():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=0)
    qualifying = set(cohort[m].unique())
    assert np.inf in qualifying and 5 in qualifying
    assert 3 not in qualifying and 4 not in qualifying

def test_not_yet_treated_boundary_delta1_shifts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=1)
    assert 5 not in set(cohort[m].unique())

from workbench.engine.cs_attgt import base_period_for, effective_treatment_start, reference_period

def test_reference_and_effective_start_use_anticipation():
    assert effective_treatment_start(g=4, anticipation=1) == 3
    assert reference_period(g=4, anticipation=1) == 2

def test_post_period_base_is_reference():
    assert base_period_for(g=4, t=5, base_period="varying", anticipation=0) == 3

def test_varying_pre_period_is_sequential():
    # t < effective_treatment_start(=4): varying base = t-1
    assert base_period_for(g=4, t=2, base_period="varying", anticipation=0) == 1

def test_universal_pre_period_is_fixed_reference():
    assert base_period_for(g=4, t=2, base_period="universal", anticipation=0) == 3
