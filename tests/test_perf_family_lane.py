"""The acceptance lane must not measure its own input generator."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def lane():
    path = Path(__file__).parents[1] / 'scripts/perf_1m.py'
    spec = importlib.util.spec_from_file_location('perf_lane', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepared_source_is_immutable_and_digest_is_checked(lane, tmp_path):
    manifest = lane.prepare_family('panel', tmp_path, rows=40)
    original = manifest.read_bytes()
    assert lane.prepare_family('panel', tmp_path, rows=40).read_bytes() == original
    source = Path(json.loads(original)['source'])
    source.write_text('changed')
    with pytest.raises(ValueError, match='source_digest_mismatch'):
        lane.validate_family_manifest(manifest)


def test_worker_only_runs_workflow_on_registered_input(lane, tmp_path, monkeypatch):
    manifest = lane.prepare_family('panel', tmp_path / 'input', rows=40)
    def forbidden(*args, **kwargs):
        raise AssertionError('input generation in measured process')
    monkeypatch.setattr(lane.np.random, 'default_rng', forbidden)
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setattr(lane, 'create_project', lambda *_: SimpleNamespace(root=project))
    def workflow(root, sources, **kwargs):
        assert sources == [Path(json.loads(manifest.read_text())['source'])]
        run = root / 'runs/r1/model_results'
        run.mkdir(parents=True)
        (run / 'panel_ols_1.json').write_text('{"coefficients":[{"estimate":1.0}]}')
        return {'status': 'completed', 'run_id': 'r1'}
    monkeypatch.setattr(lane, 'run_workflow', workflow)
    out = tmp_path / 'result'
    assert lane.family_run('panel', out, manifest=manifest) == 0
    metrics = json.loads((out / 'metrics.json').read_text())
    assert metrics['input_sha256'] == json.loads(manifest.read_text())['sha256']
    assert metrics['measurement_scope'] == 'fresh_worker_without_input_generation'
    assert metrics['run_bytes'] > 0


def test_noise_uses_all_baseline_repeats_and_all_resource_metrics(lane):
    runs = [dict(seconds=t, rss_bytes=100, run_bytes=200) for t in (10, 10, 10, 10, 11.2)]
    noise = lane.baseline_noise(runs)
    assert noise['seconds'] == pytest.approx(1.2 / (5**.5) / 10)
    assert noise['rss_bytes'] == 0
    assert not lane.noise_accepted(noise)
    with pytest.raises(ValueError, match='five'):
        lane.baseline_noise(runs[:4])


def test_stage_samples_current_rss_not_cumulative_high_water(lane):
    rows = [dict(stage='source', seconds=1., rss_before=100, rss_after=80,
                 high_water_before=200, high_water_after=200)]
    assert lane.stage_summary(rows)['source']['rss_delta_bytes'] == -20


def test_rss_sampler_reports_current_resident_bytes(lane):
    assert lane.current_rss() > 0


def test_stage_attribution_includes_time_outside_pipeline(lane):
    a = dict(seconds=10., rss_bytes=1000, stages={'source': dict(seconds=5., rss_delta_bytes=10)})
    b = dict(seconds=11., rss_bytes=1000, stages={'source': dict(seconds=5., rss_delta_bytes=10)})
    comparison = lane.compare_stages(a, b)
    assert comparison['outside_pipeline']['seconds_delta'] == 1
    assert comparison['outside_pipeline']['over_one_percent']


def test_per_repeat_source_check_does_not_reread_whole_input(lane, tmp_path, monkeypatch):
    manifest = lane.prepare_family('panel', tmp_path, rows=40)
    payload = json.loads(manifest.read_text())
    monkeypatch.setattr(lane, 'source_digest', lambda _: pytest.fail('unnecessary full input reread'))
    source = lane.registered_source(payload)
    source.write_text('modified')
    with pytest.raises(ValueError, match='registered_source_changed'):
        lane.registered_source(payload)


def test_trace_memory_noise_does_not_claim_native_rss_is_stable(lane):
    runs = [dict(seconds=20., rss_bytes=r, run_bytes=200,
                 tracemalloc_peak_bytes=100) for r in (100, 150, 200, 100, 170)]
    assert not lane.noise_accepted(lane.baseline_noise(runs))
    assert lane.noise_accepted(lane.baseline_noise(runs, metrics=('tracemalloc_peak_bytes', 'run_bytes')))


def test_trace_lane_runs_five_pairs_without_certifying_its_instrumented_time(lane, tmp_path, monkeypatch):
    import shutil
    import subprocess
    # Protocol unit test: mock the machine resource boundary along with the
    # worker. Real acceptance measurements retain the actual free-space gate.
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    original_prepare = lane.prepare_family
    monkeypatch.setattr(lane, 'prepare_family', lambda case, out: original_prepare(case, out, rows=40))
    monkeypatch.setattr(lane, 'idle_processes', lambda _: None)
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    def git(command, cwd=None, text=False):
        if command[1] == 'diff':
            return b''
        if command[1] == 'ls-files':
            return ''
        return 'baseline' if cwd == baseline or command[-1] == 'v1.9.0^{commit}' else 'candidate'
    monkeypatch.setattr(subprocess, 'check_output', git)
    calls = []
    def worker(command, **kwargs):
        destination = Path(command[command.index('--out')+1])
        destination.mkdir(parents=True)
        manifest = json.loads(Path(command[command.index('--manifest')+1]).read_text())
        candidate = destination.name.startswith('B')
        calls.append(destination.name)
        metrics = dict(seconds=10000. if candidate else 10., rss_bytes=100000 if candidate else 100,
                       run_bytes=1, tracemalloc_peak_bytes=10, input_sha256=manifest['sha256'],
                       numeric_signature={'coefficient': '0x1p0'})
        (destination / 'metrics.json').write_text(json.dumps(metrics))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', worker)
    out = tmp_path / 'measured'
    assert lane.ab_main(['--ab', '--baseline-repo', str(baseline), '--out', str(out),
                         '--cases', 'panel', '--trace-memory']) == 0
    assert calls == [f'A0_{i:02}' for i in range(1, 6)]+[f'{s}{i}' for i in range(1, 6) for s in 'AB']
    report = json.loads((out/'ab-results.json').read_text())
    assert report['time_acceptance_eligible'] is False
    assert set(report['cases']['panel']['budgets']) == {'tracemalloc_peak_bytes', 'run_bytes'}
