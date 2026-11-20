"""The public HAC label selects the existing kernel estimator, never a new method."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.panel_iv import run_iv_2sls


@pytest.mark.parametrize("engine", ["reference", "fast"])
@pytest.mark.parametrize("fixture,exog,endog,instruments", [
    ("fast_engine_iv", ["w"], ["d1"], ["z1", "z2"]),
    ("postestimation/iv_two_endogenous_v1811", ["x1"], ["xe1", "xe2"], ["z1", "z2"]),
])
def test_hac_alias_matches_existing_kernel_bits_and_named_engine_route(engine, fixture, exog, endog, instruments):
    frame = pd.read_csv(Path(__file__).parent / "fixtures" / fixture / "data.csv", float_precision="round_trip")
    kwargs = dict(y="y", exog=exog, endog=endog, instruments=instruments,
                  model_id="iv_hac_alias", estimation_engine=engine)
    expected, reference = run_iv_2sls(frame, covariance="kernel", **kwargs)
    actual, fitted = run_iv_2sls(frame, covariance="hac", **kwargs)

    assert actual == expected
    assert fitted.cov_type == reference.cov_type == "kernel"
    assert fitted.cov_config == reference.cov_config
    assert fitted.nobs == reference.nobs == len(frame)
    assert fitted.df_resid == reference.df_resid
    assert fitted.params.index.equals(reference.params.index)
    for field in ("params", "cov", "std_errors", "tstats", "pvalues", "resids", "wresids", "fitted_values"):
        left, right = np.asarray(getattr(fitted, field)), np.asarray(getattr(reference, field))
        assert left.shape == right.shape
        assert left.dtype == right.dtype
        assert left.tobytes() == right.tobytes(), field
    assert fitted.conf_int().to_numpy().tobytes() == reference.conf_int().to_numpy().tobytes()
    left, right = fitted.first_stage.diagnostics, reference.first_stage.diagnostics
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    assert left.select_dtypes("number").to_numpy().tobytes() == right.select_dtypes("number").to_numpy().tobytes()
    for field in ("f_statistic", "sargan", "wooldridge_regression", "wooldridge_overid"):
        left, right = getattr(fitted, field), getattr(reference, field)
        assert np.float64(left.stat).tobytes() == np.float64(right.stat).tobytes()
        assert np.float64(left.pval).tobytes() == np.float64(right.pval).tobytes()
        assert left.df == right.df
    if engine == "fast":
        assert actual["engine_selection"]["requested"] == "fast"
        assert actual["engine_selection"]["used"] == "reference"
        assert "covariance 'kernel' is not covered" in actual["engine_selection"]["reason"]
    else:
        assert "engine_selection" not in actual


@pytest.mark.parametrize("covariance", ["hac", "kernel"])
def test_export_accepts_only_the_iv_kernel_aliases(covariance):
    from workbench.contracts.model.script_results import DEFAULT_SCRIPT_RESULT_LAYOUT
    from workbench.script_export.builder import _export_covariance

    assert _export_covariance({"covariance": covariance}, {}, {},
        {"model_type": "iv_2sls", "covariance_estimator": "kernel"}, DEFAULT_SCRIPT_RESULT_LAYOUT) == "hac"


@pytest.mark.parametrize("model,covariance,actual", [
    ("iv_2sls", "robust", "kernel"), ("iv_2sls", "hac", "robust"), ("ols", "hac", "kernel"),
])
def test_export_still_refuses_a_different_covariance_or_a_different_family(model, covariance, actual):
    from workbench.contracts.model.script_results import DEFAULT_SCRIPT_RESULT_LAYOUT
    from workbench.script_export.builder import _export_covariance
    from workbench.script_export.plan import ScriptExportRefusal

    with pytest.raises(ScriptExportRefusal, match="disagrees"):
        _export_covariance({"covariance": covariance}, {}, {},
            {"model_type": model, "covariance_estimator": actual}, DEFAULT_SCRIPT_RESULT_LAYOUT)


def test_completed_hac_workflow_is_bound_but_native_script_coverage_stays_closed(tmp_path):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.script_export.builder import build_script_plan
    from workbench.script_export.plan import LANGUAGES, ScriptExportRefusal
    from workbench.script_export.render import export_script

    project = create_project(tmp_path, "hac-export")
    source = Path(__file__).parent / "fixtures/fast_engine_iv/data.csv"
    outcome = run_workflow(project.root, [source], mode="auto", model_type="iv_2sls", y="y", x=["w"],
        iv_endog=["d1"], iv_instruments=["z1", "z2"], covariance="hac", estimation_engine="fast")
    assert outcome["status"] == "completed"
    built = build_script_plan(project.root, outcome["run_id"], "model:iv_2sls_1")
    assert built.plan.steps[-1].parameters["covariance"] == "hac"
    for language in LANGUAGES:
        with pytest.raises(ScriptExportRefusal) as caught:
            export_script(built.plan, language, require_native=True)
        assert caught.value.code == "NOT_FULLY_NATIVE"
        assert caught.value.steps == (built.plan.steps[-1].step_id,)
