"""Synthetic protocol checks only; no timed product worker or provider runs."""
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import runpy
import time
from types import SimpleNamespace

import pytest


def load(name):
    root = Path(__file__).resolve().parents[1]
    path = root / ('native/canonical_numbers/agent_benchmark.py' if name == 'benchmark'
                   else 'scripts/perf_agent_pipeline.py')
    spec = importlib.util.spec_from_file_location('protocol_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('changed', ['native/kernel.cpp', 'local/native/kernel.so'])
def test_registered_native_runtime_source_and_so_are_checked(tmp_path, changed):
    pipeline = load('pipeline')
    source = tmp_path / 'backend/workbench/agent/context.py'
    source.parent.mkdir(parents=True)
    source.write_text('# backend\n')
    native_source, binary = tmp_path / 'native/kernel.cpp', tmp_path / 'local/native/kernel.so'
    native_source.parent.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    native_source.write_text('// reviewed native source\n')
    binary.write_bytes(b'reviewed native binary')
    manifest = tmp_path / 'source-manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': str(source.relative_to(tmp_path)), 'sha256': sha(source)}],
        'runtime_files': [{'path': str(path.relative_to(tmp_path)), 'sha256': sha(path), 'bytes': path.stat().st_size}
                          for path in [native_source, binary]]}))
    pinned = sha(manifest)
    pipeline.verify_source_snapshot(tmp_path, pinned)
    (tmp_path / changed).write_bytes(b'changed registered runtime')
    with pytest.raises(ValueError, match='runtime file digest changed'):
        pipeline.verify_source_snapshot(tmp_path, pinned)


def test_registered_runtime_cannot_escape_the_snapshot(tmp_path):
    pipeline = load('pipeline')
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'source-manifest.json').write_text(json.dumps({'files': [],
        'runtime_files': [{'path': '../outside.so', 'sha256': 'a' * 64}]}))
    with pytest.raises(ValueError, match='runtime path outside'):
        pipeline.verify_source_snapshot(tmp_path)


def test_work_directory_storage_counts_files_and_refuses_symlinks(tmp_path):
    pipeline = load('pipeline')
    work = tmp_path / 'active/work'
    (work / 'nested').mkdir(parents=True)
    (work / 'one').write_bytes(b'123')
    (work / 'nested/two').write_bytes(b'45678')
    (tmp_path / 'active/control.json').write_bytes(b'not product storage')
    counter = getattr(pipeline, '_work_directory_bytes', None)
    assert counter is not None, 'worker does not report actual product storage bytes'
    assert counter(work) == 8
    (work / 'alias').symlink_to(work / 'one')
    with pytest.raises(ValueError, match='symlink'):
        counter(work)


def synthetic_benchmark(tmp_path, monkeypatch, *, candidate_storage=1000, change_last_helper=False,
                        noisy_storage=False):
    benchmark = load('benchmark')
    product = tmp_path / 'product'
    scripts = product / 'scripts'
    scripts.mkdir(parents=True)
    worker, helper = scripts / 'perf_agent_pipeline.py', scripts / 'perf_evidence.py'
    worker.write_text('# pinned synthetic worker\n')
    helper.write_text('# pinned synthetic helper\n')
    driver = product / 'native/canonical_numbers/agent_benchmark.py'
    driver.parent.mkdir(parents=True)
    driver.write_text('# pinned synthetic driver\n')
    monkeypatch.setattr(benchmark, 'ROOT', product)
    monkeypatch.setattr(benchmark, '__file__', str(driver))
    trees = []
    for role in ['baseline', 'candidate']:
        tree = tmp_path / role
        registered = []
        for name in benchmark.MODULES:
            source = tree / 'backend/workbench' / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('# same backend source\n')
            registered.append({'path': str(source.relative_to(tree)), 'sha256': sha(source)})
        (tree / 'source-manifest.json').write_text(json.dumps({'files': registered}))
        trees.append(tree)
    fixture = tmp_path / 'fixture'
    fixture.mkdir()
    (fixture / 'manifest.json').write_text('{}\n')
    out, calls = tmp_path / 'output', []

    def fake_worker(command, **unused):
        work = Path(command[command.index('--work-dir') + 1])
        work.mkdir()
        (work / 'payload').write_bytes(b'same output')
        role = Path(command[command.index('--source-tree') + 1]).name
        calls.append(role)
        if change_last_helper and len(calls) == 15:
            helper.write_text('# changed during final worker\n')
        storage = candidate_storage if role == 'candidate' else 1000
        if noisy_storage and role == 'baseline':
            storage = 1000 if len(calls) % 2 else 1400
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'seconds': .1, 'local_pipeline_seconds': .05, 'rss_bytes': 1000,
            'work_dir_bytes': storage,
            'result_sha256': '1' * 64, 'manifest_sha256': sha(fixture / 'manifest.json'),
            'stage_seconds': {'context_build': .03}}))

    clock = itertools.count(step=.1)
    monkeypatch.setattr(benchmark, 'perf_counter', lambda: next(clock))
    monkeypatch.setattr(benchmark.subprocess, 'run', fake_worker)
    monkeypatch.setattr(benchmark, 'host_idle_snapshot', lambda: {'processes_checked': 1, 'competing': []})
    monkeypatch.setattr(benchmark, 'require_space', lambda *a, **k: 10_000_000_000)
    monkeypatch.setattr(benchmark.sys, 'argv', [str(driver), '--baseline-source', str(trees[0]),
        '--candidate-source', str(trees[1]), '--fixture', str(fixture), '--sha256', sha(fixture / 'manifest.json'),
        '--out', str(out)])
    return benchmark, out, calls


def test_storage_regression_fails_even_with_identical_results_and_fast_workers(tmp_path, monkeypatch):
    benchmark, out, calls = synthetic_benchmark(tmp_path, monkeypatch, candidate_storage=1200)
    benchmark.main()
    report = json.loads((out / 'report.json').read_text())
    assert len(calls) == 15
    assert report['median_candidate_over_baseline'].get('work_dir_bytes') == 1.2
    assert report['noise'].get('work_dir_bytes') == 0
    assert report['accepted_local_replay'] is False and 'work_dir_bytes_regression' in report['failures']


def test_final_worker_change_to_shared_helper_is_retained_as_failure(tmp_path, monkeypatch):
    benchmark, out, calls = synthetic_benchmark(tmp_path, monkeypatch, change_last_helper=True)
    with pytest.raises(ValueError, match='source changed'):
        benchmark.main()
    assert len(calls) == 15
    rows = [json.loads(line) for line in (out / 'runs.jsonl').read_text().splitlines()]
    assert len(rows) == 15 and rows[-1]['status'] == 'failed'
    assert rows[-1]['measurement_started'] is True
    assert 'source changed' in rows[-1]['error']
    assert not (out / 'report.json').exists()


def test_storage_noise_keeps_the_original_five_percent_rule(tmp_path, monkeypatch):
    benchmark, out, calls = synthetic_benchmark(tmp_path, monkeypatch, noisy_storage=True)
    benchmark.main()
    report = json.loads((out / 'report.json').read_text())
    assert len(calls) == 15
    assert report['noise']['work_dir_bytes'] >= .05
    assert report['accepted_local_replay'] is False and 'work_dir_bytes_noise' in report['failures']


@pytest.mark.parametrize('storage,expected_exit', [(1200, 2), (1000, 0)])
def test_cli_exit_status_reports_the_actual_acceptance_gate(tmp_path, monkeypatch, storage, expected_exit):
    # Execute the actual __main__ block, with synthetic workers and clock.
    # This is an exit-contract test, not another performance observation.
    benchmark, out, calls = synthetic_benchmark(tmp_path, monkeypatch, candidate_storage=storage)
    import perf_evidence
    monkeypatch.setattr(perf_evidence, 'require_space', lambda *a, **k: 10_000_000_000)
    clock = itertools.count(step=.1)
    monkeypatch.setattr(time, 'perf_counter', lambda: next(clock))
    monkeypatch.setattr(benchmark.subprocess, 'check_output',
        lambda *a, **k: f'{os.getpid()} 1 synthetic protocol test\n')
    driver = Path(__file__).resolve().parents[1] / 'native/canonical_numbers/agent_benchmark.py'
    try:
        runpy.run_path(str(driver), run_name='__main__')
    except SystemExit as stopped:
        exit_code = stopped.code
    else:
        exit_code = 0
    assert exit_code == expected_exit
    assert len(calls) == 15
    report = json.loads((out / 'report.json').read_text())
    assert report['accepted_local_replay'] is (expected_exit == 0)
