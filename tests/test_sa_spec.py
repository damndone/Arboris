import numpy as np, pandas as pd, pytest
from workbench.engine.sa_spec import select_reference_cohort, validate_sa_input, SASpecError

def test_reference_cohort_never_when_present():
    cohort = np.array([2003., 2005., np.inf, np.nan])   # inf & nan = never
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is True and ref is None

def test_reference_cohort_last_treated_when_no_never():
    # The helper still computes the last-treated cohort for the no-never case; this is
    # dormant scaffolding for a future, validated no-never path. The ESTIMATOR blocks
    # no-never panels upstream (validate_sa_input -> SA_NO_NEVER_TREATED, tested below),
    # so this branch is unreachable through estimate_sa_saturated. See sa_spec.py.
    cohort = np.array([2003., 2005., 2004.])
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is False and ref == 2005.0

def test_validate_blocks_no_never_treated():
    # v1.5.8 hardening: every entity eventually treated (no non-finite cohort) -> blocked.
    with pytest.raises(SASpecError, match="SA_NO_NEVER_TREATED"):
        validate_sa_input(cohort=np.array([2003., 2004., 2005.]), times=np.array([1, 2, 3]))

def test_validate_passes_with_never_treated():
    # A never-treated group (NaN/inf cohort) present -> validation passes.
    assert validate_sa_input(cohort=np.array([2003., 2004., np.nan]),
                             times=np.array([1, 2, 3])) is True

def test_validate_requires_two_periods_and_a_treated_cohort():
    with pytest.raises(SASpecError, match="SA_NO_TREATED_COHORT"):
        validate_sa_input(cohort=np.array([np.inf, np.inf]), times=np.array([1, 2]))

def test_validate_requires_two_periods():
    with pytest.raises(SASpecError, match="SA_TOO_FEW_PERIODS"):
        validate_sa_input(cohort=np.array([2003., np.inf]), times=np.array([1, 1]))
