import numpy as np, pandas as pd, pytest
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt, CSSpecError, EffectEstimateBundle

def _norm():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")

def _bundle():
    return estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)

def test_bundle_shape_and_cluster_rows():
    b = _bundle()
    assert isinstance(b, EffectEstimateBundle)
    assert b.influence_func.shape[0] == b.cluster_ids.shape[0]      # G rows
    assert b.influence_func.shape[1] == b.estimates.shape[0]        # K cols
    assert len(b.cell_metadata) == b.estimates.shape[0]

def test_invalid_cell_marked_not_zero():
    b = _bundle()
    for i, m in enumerate(b.cell_metadata):
        if not m["valid"]:
            assert np.isnan(b.estimates[i])      # invalid => nan, NOT 0.0

def test_metadata_fields_present():
    b = _bundle()
    m = b.cell_metadata[0]
    for k in ("g","t","event_time","estimand_type","control_group_rule",
              "reference_period","n_treated","n_control","valid"):
        assert k in m
    assert b.weights and b.vcov_config and "overlap" in b.diagnostics

def test_no_valid_cells_raises():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    d.loc[d.first_treat == 0, "first_treat"] = 3      # remove never-treated; all cohort 3
    # normalize may already reject (no comparison group), or estimate_att_gt raises:
    with pytest.raises((CSSpecError, ValueError)):
        n = normalize_did_input(d, mode="cohort", entity="unit", time="period",
            y="y", cohort="first_treat")
        estimate_att_gt(n, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)

def test_influence_columns_mean_zero_per_valid_cell():
    b = _bundle()
    for i, m in enumerate(b.cell_metadata):
        if m["valid"]:
            assert abs(b.influence_func[:, i].mean()) < 1e-7
