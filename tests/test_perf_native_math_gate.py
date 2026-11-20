"""The default-path optimization driver cannot certify overlapping or regressed runs."""
import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('native_math_gate', SCRIPTS / 'perf_native_math.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def runs():
    return {lane: [dict(call_seconds=1., worker_seconds=2., rss_bytes=1000,
                        run_bytes=100, host_monitor={'valid': True},
                        input_identity_unchanged=True,
                        source_identity_before={'sources': {'x.py': 'a'}},
                        source_identity_after={'sources': {'x.py': 'a'}}) for _ in range(5)]
            for lane in ('calibration', 'baseline', 'candidate')}


def test_an_intruding_test_invalidates_the_whole_measurement():
    rows = runs()
    rows['candidate'][2]['host_monitor']['valid'] = False
    assert 'candidate:host_exclusivity' in driver.acceptance('workflow:ols', rows, {'identical_result': True})


@pytest.mark.parametrize('metric', ['call_seconds', 'worker_seconds', 'rss_bytes', 'run_bytes'])
def test_a_stable_resource_regression_is_not_hidden_by_speed(metric):
    rows = runs()
    for row in rows['candidate']:
        row[metric] *= 1.06
    assert f'regression:{metric}' in driver.acceptance('workflow:ols', rows, {'identical_result': True})


def test_noise_in_either_lane_is_not_certified():
    rows = runs()
    rows['candidate'][0]['rss_bytes'] = 3000
    assert 'candidate:noise_rss_bytes' in driver.acceptance('workflow:ols', rows, {'identical_result': True})


def test_matching_fast_outputs_dont_hide_changed_scientific_results():
    assert 'result_identity' in driver.acceptance('statistical_tests', runs(), {'identical_result': False})


def test_invalid_disk_metric_is_a_failure_not_a_nan_comparison():
    rows = runs()
    rows['candidate'][0]['run_bytes'] = float('nan')
    assert 'candidate:invalid_run_bytes' in driver.acceptance('workflow:ols', rows, {'identical_result': True})


def test_source_or_library_changes_during_a_worker_invalidate_measurement():
    rows = runs()
    for lane in rows.values():
        for row in lane:
            row['source_identity_before'] = row['source_identity_after'] = {'sources': {'x.py':'a'}, 'native': {'x.so':'a'}}
    rows['candidate'][0]['source_identity_after'] = {'sources': {'x.py':'b'}, 'native': {'x.so':'a'}}
    assert 'source_identity_changed' in driver.acceptance('workflow:ols', rows, {'identical_result': True})


def test_workflow_report_uses_its_own_registered_input(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, 'workflow_manifest', lambda family, out: (
        out / f'{family}.json', {'source': '/fixed/wide.csv', 'sha256': 'wide-sha'}))
    monkeypatch.setattr(driver, 'registered_input', lambda: pytest.fail('OLS input is unrelated'))
    assert driver.case_input('workflow:wide', tmp_path) == {
        'source': '/fixed/wide.csv', 'sha256': 'wide-sha', 'manifest': str(tmp_path / 'wide.json')}


def test_source_snapshot_does_not_inherit_parent_checkout_revision(monkeypatch, tmp_path):
    from subprocess import CompletedProcess
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: CompletedProcess(
        a[0], 0, str(tmp_path.parent) + '\n', ''))
    assert driver.checkout_metadata(tmp_path) == {
        'kind': 'source_snapshot', 'revision': None, 'tracked_changes': None}
