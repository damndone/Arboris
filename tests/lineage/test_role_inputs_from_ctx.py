# tests/lineage/test_role_inputs_from_ctx.py
from workbench.lineage.role_inputs_from_ctx import build_resolved_inputs


class _Ctx:
    def __init__(self, artifacts, exposure_col=None):
        self.artifacts = artifacts
        self.exposure_col = exposure_col


def test_regression_inputs_mapped():
    ctx = _Ctx({
        "_model_results": [("ols_1", {"model_type": "ols"})],
        "_normalized_y": "y", "_normalized_x": ["education", "age"],
        "_poisson_x": ["education", "age"], "_focal_x": ["education"],
    })
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "regression" and ri.estimator_key == "ols"
    assert ri.outcome == "y" and ri.rhs == ["education", "age"]
    assert ri.focal_x == ["education"] and ri.exposure is None


def test_poisson_rate_uses_poisson_x_and_exposure():
    ctx = _Ctx({
        "_model_results": [("poisson_1", {"model_type": "poisson_rate"})],
        "_normalized_y": "claims", "_normalized_x": ["age", "exposure_years"],
        "_poisson_x": ["age"], "_focal_x": [],
    }, exposure_col="exposure_years")
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "regression"
    assert ri.rhs == ["age"] and ri.exposure == "exposure_years"


def test_iv_inputs_mapped():
    ctx = _Ctx({
        "_model_results": [("iv_2sls_1", {"model_type": "iv_2sls"})],
        "_normalized_y": "wage", "_normalized_x": ["age"],
        "_poisson_x": ["age"], "_focal_x": [],
        "_iv_endog": ["schooling"], "_iv_instruments": ["qob"],
    })
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "iv"
    assert ri.endog == ["schooling"] and ri.instruments == ["qob"]
    assert ri.outcome == "wage" and ri.rhs == ["age"]


def test_panel_unit_time_from_candidates():
    ctx = _Ctx({
        "_model_results": [("panel_ols_1", {"model_type": "panel_ols"})],
        "_normalized_y": "y", "_normalized_x": ["x1"], "_focal_x": ["x1"],
        "_id_candidates": ["firm"], "_time_candidates": ["year"],
    })
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "panel"
    assert ri.unit == "firm" and ri.time == "year" and ri.focal_x == ["x1"]


def test_cs_did_treatment_unit_time_cluster():
    class _Norm:
        entity = "county"
        time = "year"
    ctx = _Ctx({
        "_model_results": [("cs_did_1", {"model_type": "cs_did"})],
        "_normalized_y": "emp", "_normalized_x": ["sector"],
        "_did_normalized": _Norm(), "_did_cohort_col": "cohort",
        "_cs_cluster_var": "county",
    })
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "did" and ri.estimator_key == "cs_did"
    assert ri.treatment == ["cohort"]
    assert ri.unit == "county" and ri.time == "year" and ri.cluster == "county"
