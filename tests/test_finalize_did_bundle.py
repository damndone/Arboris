import inspect, re
from workbench.econometrics import runner


def test_finalize_did_bundle_has_no_estimator_branch():
    src = inspect.getsource(runner._finalize_did_bundle)
    assert not re.search(r'estimator\s*==', src), "no estimator-name branch allowed"
    assert '"cs"' not in src and "'cs'" not in src
    assert '"sa"' not in src and "'sa'" not in src


def test_finalize_did_bundle_signature_is_estimator_agnostic():
    params = set(inspect.signature(runner._finalize_did_bundle).parameters)
    assert "bundle" in params and "extra_metadata" in params
    assert "estimator" not in params
