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
