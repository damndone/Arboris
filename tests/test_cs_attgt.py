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
