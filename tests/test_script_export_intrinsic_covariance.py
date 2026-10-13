import pytest
from workbench.contracts.model.script_results import SCRIPT_RESULT_LAYOUTS, DEFAULT_SCRIPT_RESULT_LAYOUT
from workbench.script_export.builder import _export_covariance
from workbench.script_export.plan import ScriptExportRefusal


def test_family_intrinsic_variance_requires_exact_kernel_and_no_conflicting_request():
    layout = SCRIPT_RESULT_LAYOUTS['linear_mixed_effects']
    kernel = {'covariance_estimator': 'lmm_gls_conditional'}
    assert _export_covariance({}, {}, {}, kernel, layout) == 'lmm_gls_conditional'
    with pytest.raises(ScriptExportRefusal):
        _export_covariance({}, {}, {}, kernel, DEFAULT_SCRIPT_RESULT_LAYOUT)
    with pytest.raises(ScriptExportRefusal):
        _export_covariance({}, {}, {'covariance': 'robust'}, kernel, layout)
    with pytest.raises(ScriptExportRefusal):
        _export_covariance({}, {}, {}, {'covariance_estimator': 'unknown'}, layout)


def test_transport_default_is_not_an_executed_covariance_for_a_family_without_that_option():
    layout = SCRIPT_RESULT_LAYOUTS['quantile_regression']
    kernel = {'model_type': 'quantile_regression', 'covariance_estimator': 'nonrobust'}
    evidence = {'model_type': 'quantile_regression', 'covariance_applies': False,
                'covariance_explicit': False, 'covariance': None}
    assert _export_covariance({'covariance': 'robust'}, {}, {}, kernel, layout,
                              request_summary=evidence) == 'unadjusted'
    for form, summary in [({'covariance': 'robust'}, evidence), ({}, {}),
                          ({}, {**evidence, 'covariance_explicit': True})]:
        with pytest.raises(ScriptExportRefusal):
            _export_covariance({'covariance': 'robust'}, {}, form, kernel, layout, request_summary=summary)
    with pytest.raises(ScriptExportRefusal):
        _export_covariance({'covariance': 'robust'}, {}, {},
                           {**kernel, 'model_type': 'ols'}, layout,
                           request_summary={**evidence, 'model_type': 'ols'})
