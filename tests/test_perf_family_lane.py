"""The acceptance lane must not measure its own input generator."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def lane(monkeypatch):
    import shutil
    # Unit/40-row functional fixtures do not measure the host. The actual
    # storage boundary has separate tests and remains enabled in AB workers.
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
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
    assert metrics['measurement_scope'] == 'fresh_worker_default_product_path'
    assert metrics['tracemalloc_peak_bytes'] is None
    assert metrics['run_bytes'] > 0


def test_low_space_worker_exception_is_explicit_and_does_not_patch_product(lane, tmp_path, monkeypatch):
    manifest = lane.prepare_family('panel', tmp_path / 'input', rows=40)
    checks = []
    monkeypatch.setattr(lane, 'require_space', lambda path, **kwargs: checks.append(kwargs))
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setattr(lane, 'create_project', lambda *_: SimpleNamespace(root=project))
    def workflow(root, sources, **kwargs):
        assert 'allow_low_space' not in kwargs
        assert sources == [Path(json.loads(manifest.read_text())['source'])]
        model = root / 'runs/r1/model_results'
        model.mkdir(parents=True)
        (model / 'panel_ols_1.json').write_text('{"nobs":40}')
        return {'status': 'completed', 'run_id': 'r1'}
    monkeypatch.setattr(lane, 'run_workflow', workflow)
    assert lane.family_run('panel', tmp_path/'active', manifest=manifest, allow_low_space=True) == 0
    assert checks == [{'allow_low_space': True}]
    assert json.loads((tmp_path/'active/metrics.json').read_text())['allow_low_space_this_run'] is True


def test_source_inventory_captures_untracked_product_and_native_binaries(lane, tmp_path):
    (tmp_path/'backend/workbench').mkdir(parents=True)
    (tmp_path/'native/ar_exact').mkdir(parents=True)
    (tmp_path/'local/native-ar').mkdir(parents=True)
    source = tmp_path/'backend/workbench/new_untracked.py'
    source.write_text('NEW = True\n')
    (tmp_path/'native/ar_exact/ar_exact.cpp').write_text('// exact kernel\n')
    (tmp_path/'local/native-ar/_ar_exact.test.so').write_bytes(b'binary')
    (tmp_path/'local/native-ar/old-report.json').write_text('not an executable')
    rows = lane.product_sources(tmp_path)
    assert set(rows) == {'backend/workbench/new_untracked.py', 'native/ar_exact/ar_exact.cpp',
                         'local/native-ar/_ar_exact.test.so'}
    original = rows['backend/workbench/new_untracked.py']
    source.write_text('NEW = False\n')
    assert lane.product_sources(tmp_path)['backend/workbench/new_untracked.py'] != original


@pytest.mark.parametrize('changed_name', ['perf_1m.py', 'perf_evidence.py'])
def test_shared_driver_and_retention_helper_are_frozen_across_both_lanes(lane, tmp_path, monkeypatch, changed_name):
    import subprocess
    baseline = tmp_path/'baseline'
    baseline.mkdir()
    prepare = lane.prepare_family
    monkeypatch.setattr(lane, 'prepare_family', lambda case, out: prepare(case, out, rows=40))
    monkeypatch.setattr(lane, 'idle_processes', lambda _: None)
    monkeypatch.setattr(lane, 'product_sources', lambda _: {})
    monkeypatch.setattr(subprocess, 'check_output', lambda cmd, cwd=None, text=False:
                        b'' if cmd[1] == 'diff' else
                        'baseline' if cwd == baseline or cmd[-1] == 'v1.9.0^{commit}' else 'candidate')
    digest = lane.source_digest
    changed = False
    def source_digest(path):
        return '0'*64 if changed and path.name == changed_name else digest(path)
    monkeypatch.setattr(lane, 'source_digest', source_digest)
    out = tmp_path/'measured'
    def worker(*args, **kwargs):
        nonlocal changed
        (out/'active').mkdir()
        (out/'active/partial').write_text('retain the interrupted evidence')
        run = out/'active/benchmark'
        run.mkdir()
        (out/'active/metrics.json').write_text(json.dumps({'seconds': 1., 'rss_bytes': 1000,
            'run_bytes': 1, 'ru_maxrss': 1000, 'run_root': str(run), 'tracemalloc_peak_bytes': None,
            'input_sha256': 'a'*64, 'numeric_signature': {'coefficient': '0x1p0'}}))
        changed = True
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', worker)
    with pytest.raises(SystemExit, match='Shared measurement source changed'):
        lane.ab_main(['--ab', '--baseline-repo', str(baseline), '--out', str(out),
                      '--inputs', str(tmp_path/'inputs'), '--cases', 'panel'])
    assert (out/'active/partial').read_text() == 'retain the interrupted evidence'


def test_profile_explicit_waiver_retains_source_identity_without_changing_workflow(lane, tmp_path, monkeypatch):
    import shutil
    import subprocess
    import sys
    path = Path(__file__).parents[1]/'scripts/profile_ols_objective.py'
    spec = importlib.util.spec_from_file_location('ols_profile', path)
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    lane.prepare_family('ols', tmp_path/'local/perf-inputs/ols', rows=40)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=2_000_000_000))
    monkeypatch.setattr(profile, 'idle_processes', lambda _: None, raising=False)
    monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: 'candidate')
    def workflow(root, sources, **kwargs):
        assert 'allow_low_space' not in kwargs
        assert kwargs['model_type'] == 'ols'
        model = root/'runs/r1/model_results'
        model.mkdir(parents=True)
        (model/'ols_1.json').write_text('{"coefficients":{"x":{"estimate":1.0}}}')
        return {'status': 'completed', 'run_id': 'r1'}
    monkeypatch.setattr(profile, 'run_workflow', workflow)
    monkeypatch.setattr(sys, 'argv', ['profile_ols_objective.py', '--out', str(tmp_path/'profile'),
                                    '--allow-low-space-this-run'])
    profile.main()
    metadata = json.loads((tmp_path/'profile/profile.json').read_text())['metadata']
    assert metadata['allow_low_space_this_run'] is True
    assert str(path.resolve()) in metadata['shared_source_sha256']
    assert metadata['measurement'] == 'diagnostic_cProfile_not_gate'
    assert not (tmp_path/'profile/active').exists()


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
                 traced_before=10, traced_after=15,
                 high_water_before=200, high_water_after=200)]
    assert lane.stage_summary(rows)['source']['rss_delta_bytes'] == -20
    assert lane.stage_summary(rows)['source']['traced_delta_bytes'] == 5


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


@pytest.mark.parametrize('candidate_seconds,expected_exit,baseline_seconds', [(10.1, 0, 10.), (10000., 1, 10.), (14., 1, 14.)])
@pytest.mark.parametrize('traced', [False, True])
@pytest.mark.parametrize('rss_jump', [False, True])
@pytest.mark.parametrize('case', ['panel', 'ols'])
def test_trace_lane_journals_then_deletes_each_run_and_gates_relative_time(lane, tmp_path, monkeypatch,
                                                                       candidate_seconds, expected_exit, baseline_seconds, traced, rss_jump, case):
    import shutil
    import subprocess
    # Protocol unit test: mock the machine resource boundary along with the
    # worker. Real acceptance measurements retain the actual free-space gate.
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    original_prepare = lane.prepare_family
    def temporary_prepare(case, out):
        assert out.is_relative_to(tmp_path), 'unit test must never register real benchmark inputs'
        return original_prepare(case, out, rows=40)
    monkeypatch.setattr(lane, 'prepare_family', temporary_prepare)
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
        assert 'env' not in kwargs, 'benchmark must inherit the environment unchanged'
        assert '--profile-stages' not in command
        assert ('--trace-memory' in command) is traced
        destination = Path(command[command.index('--out')+1])
        destination.mkdir(parents=True)
        manifest = json.loads(Path(command[command.index('--manifest')+1]).read_text())
        assert destination.name == 'active'
        # The previous worker must have been recorded and removed before this
        # sole active tree is created again.
        previous = lane.finalize_active.__globals__['read_records'](destination.parent/'measurements.jsonl')
        assert len(previous) == len(calls)
        candidate = kwargs['cwd'] != baseline
        calls.append('B' if candidate else 'A')
        run = destination/'benchmark/runs/r1'
        (run/'model_results').mkdir(parents=True)
        (run/'model_results/panel_ols_1.json').write_text('{"coefficients":{"x":{"estimate":1.0,"std_error":0.5}}}')
        rss = 1000 if rss_jump and len(calls) == 6 else 100
        metrics = dict(seconds=candidate_seconds if candidate else baseline_seconds, rss_bytes=rss, ru_maxrss=rss,
                       run_bytes=1, tracemalloc_peak_bytes=10, input_sha256=manifest['sha256'],
                       run_root=str(run), numeric_signature={'coefficient': '0x1p0'})
        (destination / 'metrics.json').write_text(json.dumps(metrics))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, 'run', worker)
    out = tmp_path / 'measured'
    command = ['--ab', '--baseline-repo', str(baseline), '--out', str(out),
               '--inputs', str(tmp_path/'inputs'), '--cases', case]
    if traced:
        command.append('--trace-memory')
    # Traced time is diagnostic; only the uninstrumented lane certifies time.
    expected = 0 if traced else (1 if rss_jump or case == 'ols' else expected_exit)
    assert lane.ab_main(command) == expected
    assert calls == ['A']*5+list('AB'*5)
    assert not (out/'active').exists()
    report = json.loads((out/'ab-results.json').read_text())
    assert report['default_product_path'] is True
    assert report['time_acceptance_eligible'] is not traced
    keys = {'tracemalloc_peak_bytes', 'run_bytes'} if traced else {'seconds', 'run_bytes'}
    if not rss_jump:
        keys.add('rss_bytes')
    assert set(report['cases'][case]['budgets']) == keys
    if case == 'ols' and not traced:
        assert report['cases'][case]['absolute_seconds_cap'] == 8.0
        assert 'seconds' in report['cases'][case]['failed']


def test_traced_stage_memory_difference_is_reported_separately_from_rss(lane):
    a = dict(seconds=10., rss_bytes=1000, tracemalloc_peak_bytes=100,
             stages={'source':dict(seconds=5., rss_delta_bytes=0, traced_delta_bytes=10)})
    b = dict(seconds=10., rss_bytes=1000, tracemalloc_peak_bytes=100,
             stages={'source':dict(seconds=5., rss_delta_bytes=0, traced_delta_bytes=20)})
    difference = lane.compare_stages(a, b)['source']
    assert difference['traced_increment_delta_bytes'] == 10
    assert difference['over_one_percent']


def test_real_workflow_reuses_registered_input_and_retains_numeric_results(lane, tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    manifest = lane.prepare_family('panel', tmp_path/'input', rows=40)
    payload = json.loads(manifest.read_text())
    assert lane.family_run('panel', tmp_path/'active', manifest=manifest) == 0
    metrics = json.loads((tmp_path/'active/metrics.json').read_text())
    assert metrics['default_product_path'] is True
    links = [p for p in (tmp_path/'active').rglob('*') if p.is_file()
             and p.stat().st_ino == Path(payload['source']).stat().st_ino]
    assert len(links) == 0
    copies = [p for p in (tmp_path/'active').rglob('*') if p.is_file() and p.stat().st_size == Path(payload['source']).stat().st_size]
    assert len(copies) == 2
    assert all(lane.source_digest(p) == payload['sha256'] for p in copies)
    assert metrics['numeric_signature']['coefficients']['x1']['estimate']['binary64']


def test_default_worker_does_not_replace_product_io_or_stage_functions(lane, tmp_path, monkeypatch):
    import shutil
    from workbench.lineage import upload_store
    from workbench.engine.stages import PIPELINE
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    manifest = lane.prepare_family('panel', tmp_path/'input', rows=40)
    copy, store = shutil.copy2, upload_store.store_upload_bytes
    stages = [type(stage).run for stage in PIPELINE]
    def workflow(root, sources, **kwargs):
        assert shutil.copy2 is copy
        assert upload_store.store_upload_bytes is store
        assert [type(stage).run for stage in PIPELINE] == stages
        run = root/'runs/r1/model_results'
        run.mkdir(parents=True)
        (run/'panel_ols_1.json').write_text('{"nobs":40,"coefficients":{"x":{"estimate":1.0,"std_error":0.5}}}')
        return {'status':'completed','run_id':'r1'}
    monkeypatch.setattr(lane, 'run_workflow', workflow)
    assert lane.family_run('panel', tmp_path/'active', manifest=manifest) == 0
