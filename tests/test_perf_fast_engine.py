"""Acceptance fails closed without running a large benchmark."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def perf():
    spec = importlib.util.spec_from_file_location('perf_fast_engine', Path(__file__).parents[1] / 'scripts/perf_fast_engine.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bits(value):
    if isinstance(value, float):
        return {'binary64': value.hex()}
    if isinstance(value, dict):
        return {k: bits(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bits(v) for v in value]
    return value


def signature():
    return bits({
        'packet': {'coefficients': {'x': {'estimate': 0., 'std_error': .5, 'p_value': 1.,
                                        'ci_lower': -1., 'ci_upper': 1.}},
                   'nobs': 20, 'df_model': 1., 'df_resid': 19., 'r_squared': 0., 'r_squared_adj': 0.},
        'kernel': {'params': [0.], 'param_names': ['x'], 'vcov': [[.25]], 'vcov_scope': 'full',
                   'vcov_param_names': ['x'], 'nobs': 20, 'df_resid': 19.,
                   'reference_distribution': 'z', 'df_method': 'asymptotic',
                   'covariance_estimator': 'robust', 'n_clusters': None, 'loglik': None,
                   'unavailable': {'loglik': 'not a likelihood model'}},
        'coefficient_inference': {'x': {'statistic': 0., 'p_value': 1.}},
        'diagnostics': {'identification': 'over',
                        'weak_instruments': {'per_endogenous': {'d': {'statistic': 2., 'p_value': .36787944117144233,
                                                                     'reference_distribution': 'chi2(2)'}}},
                        'endogeneity': {'statistic': 1., 'pvalue': .31731050786291115, 'reference_distribution': 'chi2(1)'},
                        'overidentification': {'applicable': True, 'test': 'wooldridge_overid',
                                               'statistic': 0., 'pvalue': 1., 'reference_distribution': 'chi2(1)'}},
        'sample': {'retained_count': 20, 'missing_count': 0, 'positions_sha256': 'a' * 64,
                   'fingerprint_version': 'numpy-bytes.v1'},
        'point_definition': {'family': 'iv_2sls', 'actual_design_sha256': 'b' * 64},
    })


def report():
    build = {'build_identity_sha256': 'b' * 64, 'binary_sha256': 'e' * 64,
             'binary': '/build/libarboris_engine.dylib'}
    identity = {'sources': {'backend/a.py': 'a' * 64}, 'native_build': build}
    def run(label, engine):
        return {'label': label, 'estimation_engine': engine, 'status': 'completed', 'returncode': 0,
                'seconds': 10. if engine == 'reference' else 5., 'rss_bytes': 100., 'footprint_bytes': 90., 'run_bytes': 100.,
                'acceptance_signature': signature(), 'disk_free_bytes_before': 6_000_000_000,
                'host_monitor': {'samples': 3, 'overlap': [], 'errors': [], 'max_gap_seconds': .1,
                                 'covers_worker': True, 'raw_evidence_verified': True}, 'source_identity_before': identity,
                'source_identity_after': identity, 'input_sha256': 'c' * 64,
                'input_manifest_sha256_before': 'd' * 64, 'input_manifest_sha256_after': 'd' * 64,
                'engine_used': 'linearmodels' if engine == 'reference' else 'arboris-engine',
                'runtime_engine_selection': {'requested': 'fast', 'used': 'arboris-engine',
                                             'build': dict(build)} if engine == 'fast' else None,
                'requested_delivery': {'status': 'completed', 'seconds': 12. if engine == 'reference' else 7.,
                                       'rss_bytes': 120., 'footprint_bytes': 110., 'run_bytes': 150., 'figure_count': 1,
                                       'figure_artifact_ids': ['figure_residual'],
                                       'requirements': 'same requested figures'}}
    return {'source_identity': identity, 'input_sha256': 'c' * 64, 'input_manifest_sha256': 'd' * 64,
            'calibration': [run(f'calibration-{i}', 'reference') for i in range(5)],
            'pairs': [{engine: run(f'pair-{i}-{engine}', engine) for engine in
                       (('fast', 'reference') if i % 2 == 0 else ('reference', 'fast'))} for i in range(5)]}


def evaluate(perf, value):
    return perf.evaluate_report(value)


def test_valid_report_passes_and_reports_noise_for_every_lane(perf):
    summary = evaluate(perf, report())
    assert summary['passed'] is True
    assert set(summary['noise']) == {'calibration', 'reference_pairs', 'all_reference', 'fast'}
    assert summary['failures'] == []


@pytest.mark.parametrize('path,value', [
    (('packet', 'coefficients', 'x', 'estimate'), 1e-3),
    (('kernel', 'vcov', 0, 0), .3),
    (('coefficient_inference', 'x', 'statistic'), .1),
    (('coefficient_inference', 'x', 'p_value'), .9),
    (('packet', 'df_resid'), 18.),
    (('packet', 'nobs'), 19),
    (('diagnostics', 'endogeneity', 'statistic'), 1.1),
    (('sample', 'positions_sha256'), 'd' * 64),
])
def test_every_scientific_difference_fails_acceptance(perf, path, value):
    evidence = report()
    for pair in evidence['pairs']:
        obj = pair['fast']['acceptance_signature']
        for part in path[:-1]:
            obj = obj[part]
        obj[path[-1]] = bits(value)
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), None])
def test_invalid_estimates_fail_even_when_all_runs_repeat_them(perf, value):
    evidence = report()
    for run in evidence['calibration'] + [r for p in evidence['pairs'] for r in p.values()]:
        run['acceptance_signature']['packet']['coefficients']['x']['estimate'] = bits(value)
    assert not evaluate(perf, evidence)['passed']


def test_missing_fields_and_zero_resources_do_not_silently_pass(perf):
    for change in ('missing_coef', 'missing_covariance', 'zero_time', 'zero_rss', 'zero_disk', 'missing_signature'):
        evidence = report()
        run = evidence['pairs'][0]['fast']
        if change == 'missing_coef':
            del run['acceptance_signature']['packet']['coefficients']['x']['p_value']
        elif change == 'missing_covariance':
            del run['acceptance_signature']['kernel']['vcov']
        elif change == 'missing_signature':
            del run['acceptance_signature']
        else:
            run[{'zero_time': 'seconds', 'zero_rss': 'footprint_bytes', 'zero_disk': 'run_bytes'}[change]] = 0
        assert not evaluate(perf, evidence)['passed'], change


@pytest.mark.parametrize('lane,index', [('calibration', 3), ('reference', 2), ('fast', 4)])
def test_each_engine_repeats_its_own_bits_including_calibrations(perf, lane, index):
    evidence = report()
    run = evidence['calibration'][index] if lane == 'calibration' else evidence['pairs'][index][lane]
    run['acceptance_signature']['packet']['coefficients']['x']['estimate'] = bits(1e-15)
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('metric', ['seconds', 'footprint_bytes', 'run_bytes'])
def test_resource_regression_fails_and_each_lane_noise_is_gated(perf, metric):
    evidence = report()
    for pair in evidence['pairs']:
        pair['fast'][metric] = pair['reference'][metric] * 1.051
    assert not evaluate(perf, evidence)['passed']
    evidence = report()
    evidence['pairs'][0]['fast'][metric] *= 2
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('kind', ['overlap', 'ps_error', 'gap', 'no_coverage', 'source', 'input', 'manifest', 'space', 'fallback'])
def test_observation_integrity_is_required(perf, kind):
    evidence = report()
    run = evidence['pairs'][1]['fast']
    if kind == 'overlap':
        run['host_monitor']['overlap'] = ['999 pytest']
    elif kind == 'ps_error':
        run['host_monitor']['errors'] = ['ps denied']
    elif kind == 'gap':
        run['host_monitor']['max_gap_seconds'] = 10.
    elif kind == 'no_coverage':
        run['host_monitor']['covers_worker'] = False
    elif kind == 'source':
        run['source_identity_after'] = {'changed': True}
    elif kind == 'input':
        run['input_sha256'] = 'd' * 64
    elif kind == 'manifest':
        run['input_manifest_sha256_after'] = 'f' * 64
    elif kind == 'space':
        run['disk_free_bytes_before'] = 4_999_999_999
    else:
        run['engine_used'] = 'linearmodels'
    assert not evaluate(perf, evidence)['passed']


def test_minimum_repeats_and_alternation_are_required(perf):
    evidence = report()
    evidence['calibration'].pop()
    assert not evaluate(perf, evidence)['passed']
    evidence = report()
    evidence['pairs'].pop()
    assert not evaluate(perf, evidence)['passed']
    evidence = report()
    evidence['pairs'][1] = dict(reversed(list(evidence['pairs'][1].items())))
    assert not evaluate(perf, evidence)['passed']


@pytest.fixture
def input_manifest(perf, tmp_path):
    from perf_1m import source_identity

    source = tmp_path / 'iv.csv'
    source.write_text('y,d,z\n1,2,3\n')
    payload = {'sha256': perf.source_digest(source), 'case': 'iv',
               'source': str(source), 'source_stat': source_identity(source)}
    manifest = tmp_path / 'source.json'
    manifest.write_text(json.dumps(payload))
    return manifest, payload


@pytest.mark.parametrize(('kind', 'expected_failure'), [
    ('resource', 'seconds: resource_ratio_above_1.05'),
    ('scientific', 'cross_engine_numerical_disagreement'),
    ('determinism', 'reference: repeated_bits_differ'),
    ('receipt', 'pair-0-fast: runtime_build_identity_mismatch'),
    ('host', 'measurement_aborted: RuntimeError: calibration-0: host_exclusivity_unverified'),
])
def test_main_exit_uses_scientific_and_resource_failures(
    perf, monkeypatch, tmp_path, input_manifest, kind, expected_failure,
):
    evidence = report()
    if kind == 'resource':
        for pair in evidence['pairs']:
            pair['fast']['seconds'] = 11.
    elif kind == 'scientific':
        for pair in evidence['pairs']:
            pair['fast']['acceptance_signature']['packet']['coefficients']['x']['estimate'] = bits(.5)
    elif kind == 'determinism':
        evidence['calibration'][1]['acceptance_signature']['packet']['coefficients']['x']['estimate'] = bits(1e-15)
    elif kind == 'receipt':
        evidence['pairs'][0]['fast']['runtime_engine_selection']['build']['binary_sha256'] = 'f' * 64
    else:
        evidence['calibration'][0]['host_monitor']['overlap'] = ['999 pytest']
    manifest, payload = input_manifest
    digest = perf.source_digest(manifest)
    runs = evidence['calibration'] + [r for pair in evidence['pairs'] for r in pair.values()]
    for run in runs:
        run['input_sha256'] = payload['sha256']
        run['input_manifest_sha256_before'] = run['input_manifest_sha256_after'] = digest
    observations = iter(runs)
    monkeypatch.setattr(perf, 'observe', lambda *a, **k: next(observations))
    monkeypatch.setattr(perf, 'measurement_identity', lambda: evidence['source_identity'])
    monkeypatch.setattr(perf.subprocess, 'check_output', lambda *a, **k: 'abc\n')
    monkeypatch.setattr(sys, 'argv', ['perf_fast_engine.py', '--out', str(tmp_path / 'report'),
                                     '--manifest', str(manifest)])
    assert perf.main() == 1
    saved = json.loads((tmp_path / 'report/report.json').read_text())
    assert saved['summary']['failures'] == [expected_failure]
    if kind == 'host':
        assert saved['calibration'] == evidence['calibration'][:1]
        assert saved['pairs'] == []
        assert next(observations)['label'] == 'calibration-1'
    else:
        assert len(saved['calibration']) == len(saved['pairs']) == 5


def test_cli_preserves_the_completed_pair_when_the_next_worker_cannot_start(
    perf, monkeypatch, tmp_path, input_manifest,
):
    evidence = report()
    manifest, _ = input_manifest
    observed = iter(evidence["calibration"] + list(evidence["pairs"][0].values()))

    def observe(*args):
        run = next(observed, None)
        if run is None:
            raise SystemExit("disk floor")
        return run

    monkeypatch.setattr(perf, "observe", observe)
    monkeypatch.setattr(perf, "measurement_identity", lambda: evidence["source_identity"])
    monkeypatch.setattr(perf.subprocess, "check_output", lambda *args, **kwargs: "abc\n")
    out = tmp_path / "report"
    monkeypatch.setattr(sys, "argv", ["perf_fast_engine.py", "--out", str(out), "--manifest", str(manifest)])
    assert perf.main() == 1
    saved = json.loads((out / "report.json").read_bytes())
    assert saved["summary"]["failures"] == ["measurement_aborted: SystemExit: disk floor"]
    assert len(saved["calibration"]) == 5
    assert saved["pairs"] == evidence["pairs"][:1]
    partial = perf.evaluate_report(saved)
    assert "at_least_five_calibrations_and_pairs_required" in partial["failures"]
    assert "fast: repeat_evidence_unavailable" in partial["failures"]
    assert partial["engine_repeats_own_bits"]["fast"] is False


def test_main_pins_current_mount_device_after_validating_original_source(
    perf, monkeypatch, tmp_path, input_manifest,
):
    from perf_1m import registered_source

    manifest, payload = input_manifest
    old_payload = {**payload, 'source_stat': {**payload['source_stat'], 'device': -1}}
    original = json.dumps(old_payload).encode()
    manifest.write_bytes(original)
    out = tmp_path / 'report'
    monkeypatch.setattr(perf, 'measurement_identity', lambda: report()['source_identity'])
    monkeypatch.setattr(perf.subprocess, 'check_output', lambda *a, **k: 'abc\n')
    monkeypatch.setattr(sys, 'argv', ['perf_fast_engine.py', '--out', str(out), '--manifest', str(manifest)])

    def observe(_, pinned_manifest, *args):
        pinned = json.loads(pinned_manifest.read_bytes())
        assert pinned == payload
        assert registered_source(pinned) == Path(payload['source'])
        raise RuntimeError('test stopped before starting workers')

    monkeypatch.setattr(perf, 'observe', observe)
    assert perf.main() == 1
    saved = json.loads((out / 'report.json').read_bytes())
    assert saved['summary']['failures'] == ['measurement_aborted: RuntimeError: test stopped before starting workers']
    assert manifest.read_bytes() == original
    assert saved['original_input_manifest_sha256'] == perf.source_digest(manifest)
    assert saved['input_manifest_sha256'] == perf.source_digest(out / 'input-manifest.json')
    assert saved['original_input_manifest_sha256'] != saved['input_manifest_sha256']


@pytest.mark.parametrize(('change', 'expected_error'), [
    ('contents', 'source_digest_mismatch'),
    ('inode', 'registered_source_changed'),
])
def test_main_refuses_changes_other_than_mount_device(
    perf, monkeypatch, tmp_path, input_manifest, change, expected_error,
):
    manifest, payload = input_manifest
    payload['source_stat']['device'] = -1
    if change == 'contents':
        Path(payload['source']).write_text('y,d,z\n7,8,9\n')
    else:
        payload['source_stat']['inode'] += 1
    manifest.write_text(json.dumps(payload))
    out = tmp_path / 'report'
    monkeypatch.setattr(sys, 'argv', ['perf_fast_engine.py', '--out', str(out), '--manifest', str(manifest)])
    monkeypatch.setattr(perf, 'observe', lambda *a, **k: pytest.fail('must not start workers'))
    assert perf.main() == 1
    saved = json.loads((out / 'report.json').read_bytes())
    assert saved['summary']['failures'] == [f'measurement_aborted: ValueError: {expected_error}']
    assert not (out / 'input-manifest.json').exists()


def test_duplicate_labels_cannot_replace_reference_signature(perf):
    evidence = report()
    for i, pair in enumerate(evidence['pairs']):
        pair['fast']['label'] = evidence['calibration'][i]['label']
        pair['fast']['acceptance_signature']['packet']['coefficients']['x']['estimate'] = bits(.5)
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('kind', ['missing', 'wrong_binary', 'fallback'])
def test_runtime_receipt_must_match_immutable_build_pin(perf, kind):
    evidence = report()
    run = evidence['pairs'][0]['fast']
    if kind == 'missing':
        run.pop('runtime_engine_selection')
    elif kind == 'wrong_binary':
        run['runtime_engine_selection']['build']['binary_sha256'] = 'f' * 64
    else:
        run['runtime_engine_selection']['used'] = 'reference'
    assert 'pair-0-fast: runtime_build_identity_mismatch' in evaluate(perf, evidence)['failures']


def test_observe_retains_actual_runtime_receipt_and_verifies_raw_host_trace(perf, tmp_path, monkeypatch):
    out = tmp_path / 'out'
    out.mkdir()
    manifest = tmp_path / 'source.json'
    manifest.write_text(json.dumps({'source': 'input.csv', 'sha256': 'c' * 64}))
    expected = report()['pairs'][0]['fast']['runtime_engine_selection']
    monkeypatch.setattr(perf, 'wait_until_idle', lambda: 0.)
    monkeypatch.setattr(perf, 'require_space', lambda *a: 6_000_000_000)
    monkeypatch.setattr(perf, 'measurement_identity', lambda: report()['source_identity'])
    monkeypatch.setattr(perf, 'finalize_active', lambda *a, **k: {})
    def worker(command, evidence_path, **kwargs):
        worker_root = out / 'active/worker'
        run_root = worker_root / 'benchmark/runs/r1'
        model = run_root / 'model_results/iv_2sls_1.json'
        model.parent.mkdir(parents=True)
        model.write_text(json.dumps({'model_id': 'iv_2sls_1', 'model_type': 'iv_2sls',
                                     'engine': 'arboris-engine', 'engine_selection': expected}))
        (worker_root / 'metrics.json').write_text(json.dumps({'status': 'completed', 'run_root': str(run_root),
                                                            'input_sha256': 'c' * 64}))
        evidence_path.parent.mkdir()
        samples = [{'monotonic_seconds': time, 'other_heavy_runs': []} for time in (1., 1.25, 1.5)]
        evidence_path.write_text(''.join(json.dumps(sample) + '\n' for sample in samples))
        return 0, '', '', {'evidence': str(evidence_path), 'sha256': perf.source_digest(evidence_path),
                           'samples': 3, 'overlap': [], 'errors': [], 'max_gap_seconds': .25,
                           'worker_started_monotonic': 1.1, 'worker_ended_monotonic': 1.4, 'covers_worker': True}
    monkeypatch.setattr(perf, 'monitored_worker', worker)
    actual = perf.observe(out, manifest, 'fast', 'pair-0-fast', out / 'journal.jsonl', 'abc')
    assert actual['runtime_engine_selection'] == expected
    assert actual['host_monitor']['raw_evidence_verified'] is True


def test_ps_failure_is_not_an_idle_host(perf, monkeypatch):
    def denied(*a, **k):
        raise OSError('ps unavailable')
    monkeypatch.setattr(perf.subprocess, 'check_output', denied)
    with pytest.raises((OSError, RuntimeError)):
        perf.other_heavy_runs()


def test_monitor_catches_overlap_between_endpoints_and_ps_failure(perf, tmp_path, monkeypatch):
    import perf_host
    rows = iter([[], ['900 pytest'], OSError('ps failed'), [], []])
    def sample(*a):
        value = next(rows, [])
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(perf_host, 'other_heavy_runs', sample)
    with perf_host.monitor_host(tmp_path / 'host.jsonl', interval=.005) as monitor:
        import time
        time.sleep(.025)
    assert monitor.summary['overlap'] == ['900 pytest']
    assert 'ps failed' in monitor.summary['errors'][0]
    assert monitor.summary['covers_worker'] is True
    assert (tmp_path / 'host.jsonl').read_text().count('\n') >= 4


@pytest.fixture
def controlled_host(perf, tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    import perf_host

    clock = SimpleNamespace(now=100., delays=dict(lock=0., scan=0., write=0., flush=0.),
                            ps_error=None, ps_calls=[], writes=0, flushes=0)
    monkeypatch.setattr(perf_host, 'time', SimpleNamespace(monotonic=lambda: clock.now))

    def snapshot(command, **kwargs):
        clock.ps_calls.append((command, kwargs))
        clock.now += clock.delays['scan']
        if clock.ps_error:
            raise clock.ps_error
        return f'{os.getpid()} {os.getppid()} python scripts/perf_fast_engine.py\n'

    monkeypatch.setattr(perf_host.subprocess, 'check_output', snapshot)
    monitor = perf_host.monitor_host(tmp_path / 'host.jsonl')

    class ControlledLock:
        def __enter__(self):
            clock.now += clock.delays['lock']

        def __exit__(self, *exc):
            pass

    class ControlledStream:
        def __init__(self):
            self.stream = monitor.evidence.open('x')

        def write(self, value):
            clock.writes += 1
            clock.now += clock.delays['write']
            return self.stream.write(value)

        def flush(self):
            clock.flushes += 1
            clock.now += clock.delays['flush']
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

        def close(self):
            self.stream.close()

    monitor.lock = ControlledLock()
    monitor.stream = ControlledStream()
    # Exercise real sample/exit without a background thread, worker or real ps.
    monitor.thread = SimpleNamespace(join=lambda: None)
    yield clock, monitor
    monitor.stream.close()


def test_monitor_reports_sample_phases_without_extra_log_writes(perf, controlled_host):
    clock, monitor = controlled_host
    clock.delays.update(lock=.05, scan=.1, write=.02, flush=.03)
    monitor.sample()
    monitor.started = clock.now
    clock.now += .2
    monitor.sample()
    clock.now += .2
    monitor.__exit__(None, None, None)

    rows = [json.loads(line) for line in monitor.evidence.read_text().splitlines()]
    assert [row['monotonic_seconds'] for row in rows] == pytest.approx([100.05, 100.45, 100.85])
    assert [row['lock_wait_seconds'] for row in rows] == pytest.approx([.05] * 3)
    assert [row['process_snapshot_seconds'] for row in rows] == pytest.approx([.1] * 3)
    assert 'previous_sample_write' not in rows[0]
    writes = [rows[1]['previous_sample_write'], rows[2]['previous_sample_write'],
              monitor.summary['last_sample_write']]
    for index, write in enumerate(writes):
        assert write['sample_monotonic_seconds'] == rows[index]['monotonic_seconds']
        assert write['started_monotonic_seconds'] == pytest.approx(100.15 + index * .4)
        assert write['finished_monotonic_seconds'] == pytest.approx(100.2 + index * .4)
    assert clock.writes == clock.flushes == len(rows) == 3
    assert clock.ps_calls == [(['ps', '-Ao', 'pid=,ppid=,command='], dict(text=True, timeout=5))] * 3
    assert monitor.summary['max_gap_seconds'] == pytest.approx(.4)
    assert monitor.summary['valid'] is True
    perf.verify_host_trace(monitor.summary, monitor.evidence)
    assert perf.has_verified_host({'host_monitor': monitor.summary | {'raw_evidence_verified': True}})


@pytest.mark.parametrize('phase', ['lock', 'scan', 'write', 'flush'])
def test_monitor_phase_attribution_keeps_long_gap_invalid(perf, controlled_host, phase):
    clock, monitor = controlled_host
    monitor.sample()
    monitor.started = clock.now
    clock.now += .2
    clock.delays[phase] = 3.0456
    monitor.sample()
    clock.delays[phase] = 0.
    clock.now += .2
    monitor.__exit__(None, None, None)

    rows = [json.loads(line) for line in monitor.evidence.read_text().splitlines()]
    assert rows[1]['lock_wait_seconds'] == pytest.approx(3.0456 if phase == 'lock' else 0.)
    assert rows[1]['process_snapshot_seconds'] == pytest.approx(3.0456 if phase == 'scan' else 0.)
    write = rows[2]['previous_sample_write']
    assert write['sample_monotonic_seconds'] == rows[1]['monotonic_seconds']
    assert write['finished_monotonic_seconds'] - write['started_monotonic_seconds'] == pytest.approx(
        3.0456 if phase in ('write', 'flush') else 0.)
    assert monitor.summary['max_gap_seconds'] == pytest.approx(3.2456)
    assert monitor.summary['covers_worker'] is True
    assert monitor.summary['overlap'] == monitor.summary['errors'] == []
    assert monitor.summary['valid'] is False
    perf.verify_host_trace(monitor.summary, monitor.evidence)
    assert not perf.has_verified_host({'host_monitor': monitor.summary | {'raw_evidence_verified': True}})


def test_monitor_times_failed_process_snapshot(controlled_host):
    import subprocess

    clock, monitor = controlled_host
    monitor.sample()
    monitor.started = clock.now
    clock.ps_error = subprocess.TimeoutExpired('ps', 5)
    clock.delays['scan'] = 5.
    monitor.sample()
    clock.ps_error = None
    clock.delays['scan'] = 0.
    monitor.__exit__(None, None, None)

    rows = [json.loads(line) for line in monitor.evidence.read_text().splitlines()]
    assert rows[1]['process_snapshot_seconds'] == 5.
    assert rows[1]['error'].startswith('TimeoutExpired:')
    assert monitor.summary['errors'] == [rows[1]['error']]
    assert monitor.summary['max_gap_seconds'] == 5.
    assert monitor.summary['valid'] is False


def test_worker_signature_reads_persisted_covariance_diagnostics_and_sample(perf, tmp_path):
    import perf_1m
    evidence = signature()
    decoded = perf.decoded(evidence)
    models = tmp_path / 'model_results'
    (models / 'inference_kernels').mkdir(parents=True)
    (models / 'inference_kernels/iv_2sls_1.json').write_text(json.dumps(decoded['kernel']))
    (tmp_path / 'iv_diagnostics.json').write_text(json.dumps(decoded['diagnostics']))
    (models / 'iv_2sls_1.completion.json').write_text(json.dumps({
        'sample': decoded['sample'], 'point_definition': decoded['point_definition']}))
    result = perf_1m.iv_acceptance_signature(tmp_path, decoded['packet'])
    assert perf.validate_signature(result)['kernel']['vcov'] == [[.25]]
    assert perf.decoded(result)['coefficient_inference']['x']['statistic'] == 0.


@pytest.mark.parametrize('metric', ['seconds', 'footprint_bytes', 'run_bytes'])
def test_requested_delivery_has_its_own_resource_budget(perf, metric):
    evidence = report()
    for pair in evidence['pairs']:
        pair['fast']['requested_delivery'][metric] = pair['reference']['requested_delivery'][metric] * 1.051
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('kind', ['not_requested', 'render_failed', 'different_figures', 'missing_time'])
def test_requested_delivery_must_be_complete_and_comparable(perf, kind):
    evidence = report()
    delivery = evidence['pairs'][0]['fast']['requested_delivery']
    if kind == 'not_requested':
        delivery['status'] = 'not_requested'
    elif kind == 'render_failed':
        delivery['status'] = 'failed'
    elif kind == 'different_figures':
        delivery['figure_artifact_ids'] = ['other']
    else:
        del delivery['seconds']
    assert not evaluate(perf, evidence)['passed']


def test_figure_materialization_is_explicit_and_service_errors_are_retained(perf, tmp_path, monkeypatch):
    import perf_1m
    from workbench import figure_plans
    calls = []
    def materialize(root):
        calls.append(root)
        (root / 'figures').mkdir(exist_ok=True)
        (root / 'figures/rendered.json').write_text(json.dumps({'figures': [], 'error': 'ValueError'}))
    monkeypatch.setattr(figure_plans, 'ensure_figures', materialize)
    assert perf_1m.requested_figure_delivery(tmp_path, started=0., requested=False)['status'] == 'not_requested'
    assert calls == []
    (tmp_path / 'artifacts_index.json').write_text(json.dumps({'artifacts': []}))
    (tmp_path / 'figures').mkdir()
    (tmp_path / 'figures/plan.json').write_text('{}')
    result = perf_1m.requested_figure_delivery(tmp_path, started=0., requested=True)
    assert calls == [tmp_path]
    assert result['status'] == 'failed' and result['error'] == 'ValueError'


def test_host_gate_detects_another_driver_and_does_not_exclude_siblings(perf, monkeypatch):
    import os
    import perf_host
    rows = (f'{os.getpid()} {os.getppid()} python perf_fast_engine.py\n'
            f'{os.getppid()} 1 shell\n'
            f'900001 {os.getppid()} python perf_fast_engine.py\n'
            f'900002 {os.getpid()} python perf_1m.py\n')
    monkeypatch.setattr(perf_host.subprocess, 'check_output', lambda *a, **k: rows)
    assert perf_host.other_heavy_runs(ignore_pids=(900002,)) == ['900001 python perf_fast_engine.py']
    with pytest.raises(RuntimeError, match='host_busy'):
        perf_host.require_idle()


def test_host_does_not_count_scratch_heredoc_text_as_a_running_test(perf, monkeypatch):
    import os
    import perf_host

    own, parent = os.getpid(), os.getppid()
    rows = (f'{own} {parent} python scripts/perf_1m.py\n'
            f'{parent} 1 shell\n'
            "900001 1 /bin/zsh -lc cat > local/test-draft.md <<'EOF'\\012import pytest\\012EOF\n"
            "900002 900001 python -m pytest -q tests/model.py\n")
    monkeypatch.setattr(perf_host.subprocess, 'check_output', lambda *args, **kwargs: rows)
    assert perf_host.other_heavy_runs() == ['900002 python -m pytest -q tests/model.py']


def test_worker_checks_registered_input_identity_before_starting(perf, tmp_path):
    import perf_1m
    source = tmp_path / 'iv.csv'
    source.write_text('x\n1\n')
    payload = {'source': str(source), 'source_stat': perf_1m.source_identity(source),
               'kwargs': {}, 'rows': 1, 'case': 'iv'}
    manifest = tmp_path / 'source.json'
    manifest.write_text(json.dumps(payload))
    source.write_text('x\n2\n3\n')
    with pytest.raises(ValueError, match='registered_source_changed'):
        perf_1m.family_run('iv', tmp_path / 'worker', manifest=manifest)


def test_empty_ps_output_is_not_evidence_of_idle(perf, monkeypatch):
    import perf_host
    monkeypatch.setattr(perf_host.subprocess, 'check_output', lambda *a, **k: '')
    with pytest.raises(RuntimeError, match='process_snapshot'):
        perf_host.require_idle()


@pytest.mark.parametrize('field', ['r_squared', 'r_squared_adj'])
def test_shared_missing_or_null_fit_statistic_is_invalid(perf, field):
    evidence = report()
    for run in evidence['calibration'] + [r for p in evidence['pairs'] for r in p.values()]:
        run['acceptance_signature']['packet'][field] = None
    assert not evaluate(perf, evidence)['passed']


def test_missing_na_reason_is_invalid_even_when_both_engines_omit_it(perf):
    evidence = report()
    for run in evidence['calibration'] + [r for p in evidence['pairs'] for r in p.values()]:
        run['acceptance_signature']['kernel']['unavailable'] = {}
    assert not evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('kind', ['se', 'covariance', 'tail'])
def test_scientific_tolerance_cannot_hide_small_se_covariance_or_tail(perf, kind):
    from scipy import stats
    evidence = report()
    for run in evidence['calibration'] + [r for p in evidence['pairs'] for r in p.values()]:
        sig = run['acceptance_signature']
        sig['packet']['coefficients']['x']['std_error'] = bits(1e-20)
        sig['kernel']['vcov'] = bits([[1e-40]])
        sig['diagnostics']['endogeneity']['statistic'] = bits(100.)
        sig['diagnostics']['endogeneity']['pvalue'] = bits(float(stats.chi2.sf(100., 1)))
    for pair in evidence['pairs']:
        sig = pair['fast']['acceptance_signature']
        if kind == 'se':
            sig['packet']['coefficients']['x']['std_error'] = bits(2e-20)
        elif kind == 'covariance':
            sig['kernel']['vcov'] = bits([[1.5e-40]])
        else:
            sig['diagnostics']['endogeneity']['pvalue'] = bits(1e-30)
    assert not evaluate(perf, evidence)['passed']


def test_reference_cdf_cancellation_uses_declared_distribution_survival_tail(perf):
    from scipy import stats
    evidence = report()
    for run in evidence['calibration'] + [r for p in evidence['pairs'] for r in p.values()]:
        sig = run['acceptance_signature']
        sig['diagnostics']['endogeneity']['statistic'] = bits(100.)
        sig['diagnostics']['endogeneity']['pvalue'] = bits(
            float(stats.chi2.sf(100., 1)) if run['engine_used'] == 'arboris-engine' else 0.)
    assert evaluate(perf, evidence)['passed']


@pytest.mark.parametrize('metrics_kind', ['missing', 'invalid_json'])
def test_failed_worker_logs_survive_registered_active_cleanup(perf, tmp_path, monkeypatch, metrics_kind):
    from perf_evidence import read_records
    out = tmp_path / 'evidence'
    out.mkdir()
    source = tmp_path / 'input.csv'
    source.write_text('y,w\n1,2\n')
    manifest = tmp_path / 'source.json'
    manifest.write_text(json.dumps({'source': str(source), 'sha256': perf.source_digest(source)}))
    identity = {'sources': {'a.py': 'a' * 64}}
    monkeypatch.setattr(perf, 'wait_until_idle', lambda: 0.)
    monkeypatch.setattr(perf, 'require_space', lambda *args: 6_000_000_000)
    monkeypatch.setattr(perf, 'measurement_identity', lambda: identity)
    def failed_worker(*args, **kwargs):
        worker = out / 'active/worker'
        raw = worker / 'benchmark/runs/broken/workflow_log.jsonl'
        raw.parent.mkdir(parents=True)
        raw.write_text('{"error":"original raw worker error"}\n')
        if metrics_kind == 'invalid_json':
            (worker / 'metrics.json').write_text('{broken')
        return 1, 'original stdout\n', 'original traceback\n', {'valid': True}
    monkeypatch.setattr(perf, 'monitored_worker', failed_worker)
    value = perf.observe(out, manifest, 'fast', 'pair-0-fast', out / 'journal.jsonl', 'abc')
    assert value['status'] == 'failed'
    assert not (out / 'active').exists()
    retained = value['retained_logs']
    paths = {row['relative_path']: Path(row['path']) for row in retained}
    assert paths['stdout.log'].read_text() == 'original stdout\n'
    assert paths['stderr.log'].read_text() == 'original traceback\n'
    assert paths['worker/benchmark/runs/broken/workflow_log.jsonl'].read_text() == '{"error":"original raw worker error"}\n'
    saved = read_records(out / 'journal.jsonl')[0]['metadata']['retained_logs']
    assert saved == retained
    assert all(perf.source_digest(Path(row['path'])) == row['sha256'] for row in retained)


@pytest.mark.parametrize('damage', ['missing_file', 'empty_file', 'partial_rendering', 'wrong_hash', 'none'])
def test_figure_delivery_requires_every_rendered_artifact_to_exist_and_match(perf, tmp_path, monkeypatch, damage):
    import hashlib
    import perf_1m
    from workbench import figure_plans
    monkeypatch.setattr(figure_plans, 'ensure_figures', lambda root: None)
    (tmp_path / 'figures').mkdir()
    (tmp_path / figure_plans.FIGURE_PLAN).write_text('{}')
    image = tmp_path / 'figures/example.png'
    if damage != 'missing_file':
        image.write_bytes(b'' if damage == 'empty_file' else b'actual image bytes')
    rendered_ids = [] if damage == 'partial_rendering' else ['example']
    (tmp_path / 'figures/rendered.json').write_text(json.dumps({'figures': rendered_ids}))
    (tmp_path / 'artifacts_index.json').write_text(json.dumps({'artifacts': [{
        'artifact_id': 'example', 'artifact_type': 'figure', 'path': 'figures/example.png',
        'sha256': 'wrong' if damage == 'wrong_hash' else hashlib.sha256(b'actual image bytes').hexdigest()}]}))
    value = perf_1m.requested_figure_delivery(tmp_path, started=0., requested=True)
    assert value['status'] == ('completed' if damage == 'none' else 'failed')


def test_host_ignores_only_explicit_worker_subtree_and_keeps_unrelated_children(perf, monkeypatch):
    import os
    import perf_host
    own, parent = os.getpid(), os.getppid()
    rows = (f'{own} {parent} python perf_fast_engine.py\n'
            f'{parent} 1 shell\n'
            f'900001 {own} python perf_1m.py\n'
            f'900002 {own} python -m pytest unrelated.py\n'
            f'900003 900001 python perf_helper.py\n')
    monkeypatch.setattr(perf_host.subprocess, 'check_output', lambda *a, **k: rows)
    assert perf_host.other_heavy_runs(ignore_pids=(900001,)) == ['900002 python -m pytest unrelated.py']
