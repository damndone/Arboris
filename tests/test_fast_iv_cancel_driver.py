"""Driver failure control only; no real benchmark workers are launched."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def driver():
    spec = importlib.util.spec_from_file_location('fast_iv_cancel_driver', Path(__file__).parents[1] / 'scripts/perf_fast_iv_cancel.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('last_timeout', [False, True])
def test_watchdog_terminate_kill_and_final_wait_are_bounded(driver, last_timeout):
    class Process:
        def __init__(self):
            self.calls = []
        def terminate(self):
            self.calls.append('terminate')
        def kill(self):
            self.calls.append('kill')
        def communicate(self, *, timeout):
            self.calls.append(timeout)
            if len(self.calls) == 2 or last_timeout:
                raise subprocess.TimeoutExpired('worker', timeout)
            return 'stdout', 'stderr'
    process = Process()
    if last_timeout:
        with pytest.raises(subprocess.TimeoutExpired):
            driver.terminate_bounded(process)
    else:
        assert driver.terminate_bounded(process) == ('stdout', 'stderr')
    assert process.calls == ['terminate', 2, 'kill', 2]


@pytest.mark.parametrize('exercise', ['failed', 'not_exercised'])
def test_nonpassing_exercise_is_recorded_then_stops_without_repeating(driver, tmp_path, monkeypatch, exercise):
    source = tmp_path / 'input.csv'
    source.write_text('y\n1\n')
    payload = {'case': 'iv', 'rows': 1_000_000, 'sha256': 'c' * 64}
    identity = {'native_build': {'build_identity_sha256': 'a' * 64}}
    started, recorded = [], []
    monkeypatch.setattr(driver, 'validate_family_manifest', lambda *a: payload)
    monkeypatch.setattr(driver, 'registered_source', lambda *a: source)
    monkeypatch.setattr(driver, 'measurement_identity', lambda: identity)
    monkeypatch.setattr(driver, 'require_idle', lambda: None)
    monkeypatch.setattr(driver, 'require_space', lambda *a, **k: 6_000_000_000)
    monkeypatch.setattr(driver.subprocess, 'check_output', lambda *a, **k: 'head-sha\n')
    monkeypatch.setattr(driver, 'retain_worker_logs', lambda *a: [])
    class Monitor:
        summary = {'valid': True}
        def __init__(self, *a):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def popen(self, command, **kwargs):
            active = Path(command[command.index('--out') + 1])
            value = {'status': 'failed', 'exercise_status': exercise, 'failures': [], 'delay_ms': 50,
                     'verified_worker_build': identity['native_build'], 'actual_loaded_worker_build': None}
            (active / 'worker-result.json').write_text(json.dumps(value))
            started.append(command)
            return SimpleNamespace(returncode=1, communicate=lambda **kwargs: ('', ''))
    def journal(active, out, label, value):
        recorded.append(label)
        shutil.rmtree(active)
        return {'recorded': label}
    monkeypatch.setattr(driver, 'monitor_host', Monitor)
    monkeypatch.setattr(driver, 'journal_then_cleanup', journal)
    out = tmp_path / 'campaign'
    args = SimpleNamespace(out=out, manifest=tmp_path / 'manifest.json', delays=[50], delay_ms=50,
                           allow_low_space_this_campaign=True)
    assert driver.campaign(args) == 1
    assert len(started) == len(recorded) == 1
    report = json.loads((out / 'report.json').read_text())
    assert report['passed'] is False and len(report['runs']) == 1
    assert report['runs'][0]['exercise_status'] == exercise


@pytest.mark.parametrize('expected', [False, True])
def test_unexpected_worker_errors_keep_full_traceback(driver, expected):
    from workbench.engine.context import RunInterruptionRequested
    def original_failure():
        raise RunInterruptionRequested('cancelled') if expected else ValueError('original worker failure')
    try:
        original_failure()
    except Exception as error:
        value = driver.exception_evidence(error, expected_interruption=expected)
    if expected:
        assert value['reason'] == 'cancelled' and 'traceback' not in value
    else:
        assert 'original_failure' in value['traceback']
        assert 'ValueError: original worker failure' in value['traceback']
