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
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    d2 = d[~((d.first_treat == 0) & (d.period == 6))]
    b = estimate_att_gt(normalize_did_input(d2, mode="cohort", entity="unit",
            time="period", y="y", cohort="first_treat"),
        control_group="never", est_method="dr", base_period="varying",
        anticipation=0, covariates=["x1"], cluster_var=None)
    invalid = [i for i, m in enumerate(b.cell_metadata) if not m["valid"]]
    assert invalid                                       # cells actually dropped
    for i in invalid:
        assert np.isnan(b.estimates[i])                  # NaN, not 0.0
        assert np.allclose(b.influence_func[:, i], 0.0)  # IF column zeroed
    assert b.diagnostics["omitted_cells"]                # diagnostic populated

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

def test_single_cohort_aggregated_if_equals_cell_if():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    d = d[d.first_treat.isin([0, 4])]             # one treated cohort + never
    from workbench.engine.cs_aggregate import aggregate
    b = estimate_att_gt(normalize_did_input(d, mode="cohort", entity="unit",
        time="period", y="y", cohort="first_treat"), control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        covariates=["x1"], cluster_var=None)
    out = aggregate(b, "dynamic")
    # each dynamic label maps to exactly one cell (single cohort); its component IF
    # must equal that cell's bundle IF column (weight term is zero with one cohort).
    for lab, comp in zip(out["label"], out["component_if"].T):
        k = out["weights_used"][lab]["cells"][0]
        assert len(out["weights_used"][lab]["cells"]) == 1
        assert np.allclose(comp, b.influence_func[:, k], atol=1e-10)
