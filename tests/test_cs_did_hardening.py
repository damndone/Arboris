"""v1.5.6 hardening: cs_did failure paths must raise CS_*/DID_* ValueError
(→ structured MODEL_FIT_FAILED), never a bare KeyError/TypeError (→ WORKFLOW_FAILED).

Each test exercises a previously-escaping path:
  1. cluster_var set  → CS_CLUSTERING_DEFERRED (variable-clustering deferred)
  2. non-numeric y    → structured numeric-y ValueError (mirrors run_did)
  3. all-NaN y        → CS_NO_VALID_CELLS (empty complete-case pivot, was bare KeyError)
"""
import numpy as np
import pandas as pd
import pytest

from workbench.engine.cs_attgt import estimate_att_gt, CSSpecError
from workbench.engine.did_spec import normalize_did_input
from workbench.econometrics.runner import run_cs_did


def _frame():
    """Small staggered panel: two treated cohorts + a never-treated group."""
    rng = np.random.default_rng(11)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"unit": ent, "period": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    return pd.DataFrame(rows)


def _norm(frame=None):
    return normalize_did_input(frame if frame is not None else _frame(),
        mode="cohort", entity="unit", time="period", y="y", cohort="first_treat")


# --- Fix #1: variable-clustering deferred with a structured guard ----------
def test_cluster_var_raises_clustering_deferred():
    norm = _norm()
    with pytest.raises(CSSpecError, match="CS_CLUSTERING_DEFERRED"):
        estimate_att_gt(norm, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=[],
            cluster_var="first_treat")


def test_cluster_var_run_cs_did_structured():
    """End-to-end via run_cs_did: must surface a ValueError (caught → MODEL_FIT_FAILED),
    not a bare KeyError/TypeError that would escape to WORKFLOW_FAILED."""
    norm = _norm()
    with pytest.raises(ValueError, match="CS_CLUSTERING_DEFERRED"):
        run_cs_did(norm, covariates=[], control_group="never", est_method="dr",
            base_period="varying", anticipation=0, cluster_var="first_treat")


# --- Fix #2: non-numeric outcome → structured failure ---------------------
def test_non_numeric_y_structured_failure():
    frame = _frame()
    frame["y"] = "not_a_number"
    norm = _norm(frame)
    with pytest.raises(ValueError, match="non-numeric"):
        run_cs_did(norm, covariates=[], control_group="never", est_method="dr",
            base_period="varying", anticipation=0, cluster_var=None)


# --- Fix #3: all-NaN y → CS_NO_VALID_CELLS, not bare KeyError --------------
def test_all_nan_y_no_valid_cells():
    frame = _frame()
    frame["y"] = np.nan
    norm = _norm(frame)
    with pytest.raises((CSSpecError, ValueError), match="CS_NO_VALID_CELLS"):
        estimate_att_gt(norm, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=[], cluster_var=None)


# --- Round 2 Fix #1: all-NaN COVARIATE → CS_NO_VALID_CELLS, not MissingDataError
def _frame_with_cov(cov_values):
    """_frame() plus an extra covariate column `x` set to `cov_values`
    (scalar broadcast)."""
    frame = _frame()
    frame["x"] = cov_values
    return frame


def _norm_cov(frame):
    return normalize_did_input(frame, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")


def test_all_nan_covariate_no_valid_cells():
    """An all-NaN covariate must make every cell invalid (its base-period covariate
    row is non-finite) → structured CS_NO_VALID_CELLS, NOT a statsmodels
    MissingDataError escaping `except ValueError` → WORKFLOW_FAILED."""
    norm = _norm_cov(_frame_with_cov(np.nan))
    with pytest.raises((CSSpecError, ValueError), match="CS_NO_VALID_CELLS"):
        estimate_att_gt(norm, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x"], cluster_var=None)


def test_all_nan_covariate_run_cs_did_structured():
    """End-to-end: an all-NaN covariate surfaces a ValueError (caught → MODEL_FIT_FAILED),
    never a bare MissingDataError that escapes to WORKFLOW_FAILED."""
    norm = _norm_cov(_frame_with_cov(np.nan))
    with pytest.raises(ValueError, match="CS_NO_VALID_CELLS"):
        run_cs_did(norm, covariates=["x"], control_group="never", est_method="dr",
            base_period="varying", anticipation=0, cluster_var=None)
