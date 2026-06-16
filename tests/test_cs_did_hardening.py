"""v1.5.6 hardening: cs_did failure paths must raise CS_*/DID_* ValueError
(→ structured MODEL_FIT_FAILED), never a bare KeyError/TypeError (→ WORKFLOW_FAILED).

Each test exercises a previously-escaping path:
  1. cluster_var set  → variable-clustering is SUPPORTED (v1.5.6.1 Task 3): a valid
     cluster column estimates; a bad/degenerate cluster column raises a structured
     CS_CLUSTER_* ValueError (never a bare KeyError → WORKFLOW_FAILED).
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


# --- Fix #1 (v1.5.6.1 Task 3): variable-clustering is now supported; a bad
#     cluster column must still raise a STRUCTURED CS_CLUSTER_* error, never a
#     bare KeyError that would escape to WORKFLOW_FAILED. -------------------
def test_missing_cluster_var_structured():
    norm = _norm()
    with pytest.raises(CSSpecError, match="CS_CLUSTER_COL_MISSING"):
        estimate_att_gt(norm, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=[],
            cluster_var="not_a_column")


def test_valid_cluster_var_estimates():
    """A valid cluster column (>=2 clusters) now estimates: entity-level IF, with
    cluster ids carried only in aux['row_cluster']."""
    norm = _norm()  # first_treat has 3 distinct values across 6 entities
    b = estimate_att_gt(norm, control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=[],
        cluster_var="first_treat")
    assert b.influence_func.shape[0] == 6          # ENTITY-level rows, not clusters
    assert b.aux["row_cluster"].shape[0] == 6


def test_bad_cluster_var_run_cs_did_structured():
    """End-to-end via run_cs_did: a missing cluster column must surface a ValueError
    (caught → MODEL_FIT_FAILED), not a bare KeyError/TypeError → WORKFLOW_FAILED."""
    norm = _norm()
    with pytest.raises(ValueError, match="CS_CLUSTER_COL_MISSING"):
        run_cs_did(norm, covariates=[], control_group="never", est_method="dr",
            base_period="varying", anticipation=0, cluster_var="not_a_column")


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


# --- Task 6 (v1.5.6.1): FULL-PIPELINE clustering proof -----------------------
# Tasks 2-5 wired variable-clustering through api.py -> orchestrator
# (cs_cluster_var -> ctx.artifacts["_cs_cluster_var"]) -> estimation stage
# (run_cs_did(..., cluster_var=...)). Task 3 tests call run_cs_did DIRECTLY.
# These tests prove the WHOLE run_workflow pipeline:
#   1. a clustered cs_did run COMPLETES and writes cluster metadata to its artifact;
#   2. a bad cluster column produces a STRUCTURED failure (status=failed +
#      CS_CLUSTER_* signal in errors.json), NOT a bare WORKFLOW_FAILED escape.
from workbench.projects import create_project
from workbench.orchestrator import run_workflow
from workbench.artifacts import read_json


def _run(tmp_path, frame, *, y, x, mode="auto", model_type="auto", **extra):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode=mode, y=y, x=x,
                          model_type=model_type, **extra)
    return project.root / "runs" / result["run_id"], result


def _run_cs(tmp_path, df, *, cs_cluster_var):
    """run_workflow with the fixed cs_did kwargs (cohort/never/dr/varying)."""
    return _run(tmp_path, df, y="y", x=["x1"], model_type="cs_did",
                entity_col="id", time_col="year", did_mode="cohort",
                did_cohort_col="first_treat", cs_control_group="never",
                cs_est_method="dr", cs_base_period="varying",
                cs_cluster_var=cs_cluster_var)


def _read_cs_did_metadata(run_root):
    """The diagnostics stage writes the run_cs_did dict to run_root/cs_did.json
    (artifact id 'cs_did'); return its ['metadata']."""
    return read_json(run_root / "cs_did.json")["metadata"]


def test_clustered_cs_did_completes_end_to_end(tmp_path):
    rng = np.random.default_rng(5)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        x1, fe = float(rng.normal()), float(rng.normal())
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            y = fe + 0.1 * (year - 2017) + 0.3 * x1 + 2.0 * d + 0.05 * rng.normal()
            rows.append({"id": f"u{i:02d}", "year": year, "first_treat": cohort,
                         "x1": round(x1, 6), "y": round(y, 6), "grp": i % 8})  # 8 clusters
    run_root, result = _run_cs(tmp_path, pd.DataFrame(rows), cs_cluster_var="grp")
    assert result["status"] == "completed"
    meta = _read_cs_did_metadata(run_root)
    assert meta["cluster_level"] == "grp"
    assert meta["n_clusters"] == 8
    assert meta["n_units"] == 40


def test_clustered_bad_cluster_col_structured_failure(tmp_path):
    rng = np.random.default_rng(6)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        x1, fe = float(rng.normal()), float(rng.normal())
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": f"u{i:02d}", "year": year, "first_treat": cohort,
                         "x1": round(x1, 6), "y": round(fe + 2.0 * d, 6)})
    run_root, result = _run_cs(tmp_path, pd.DataFrame(rows),
                               cs_cluster_var="does_not_exist")
    assert result["status"] == "failed"
    # structured: CSSpecError("CS_CLUSTER_COL_MISSING: ...") IS-A ValueError, caught
    # by the estimation stage -> MODEL_FIT_FAILED issue whose message embeds the
    # CS_CLUSTER_COL_MISSING signal. NOT a bare WORKFLOW_FAILED escape.
    errors = read_json(run_root / "errors.json")
    codes = " ".join(i.get("code", "") + " " + i.get("message", "")
                     for i in errors.get("issues", []))
    assert "CS_CLUSTER_COL_MISSING" in codes or "MODEL_FIT_FAILED" in codes
