import numpy as np, pandas as pd, pytest
from workbench.engine.sa_spec import select_reference_cohort, validate_sa_input, SASpecError

def test_reference_cohort_never_when_present():
    cohort = np.array([2003., 2005., np.inf, np.nan])   # inf & nan = never
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is True and ref is None

def test_reference_cohort_last_treated_when_no_never():
    cohort = np.array([2003., 2005., 2004.])
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is False and ref == 2005.0

def test_validate_requires_two_periods_and_a_treated_cohort():
    with pytest.raises(SASpecError, match="SA_NO_TREATED_COHORT"):
        validate_sa_input(cohort=np.array([np.inf, np.inf]), times=np.array([1, 2]))

def test_validate_requires_two_periods():
    with pytest.raises(SASpecError, match="SA_TOO_FEW_PERIODS"):
        validate_sa_input(cohort=np.array([2003., np.inf]), times=np.array([1, 1]))
