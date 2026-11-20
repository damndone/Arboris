"""Frozen component evidence controls; no timing/RSS/benchmark workers run."""
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


@pytest.fixture
def bench(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'native/kendall_counts/bench.py'
    spec = importlib.util.spec_from_file_location('kendall_component_driver', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'local/perf-evidence').mkdir(parents=True)
    csv = tmp_path / 'local/input.csv'
    csv.write_text('x,y\n1,2\n')
    monkeypatch.setattr(module, 'fixed_input', lambda: (csv, 'fixed-input-sha', {'rows': 1}))
    monkeypatch.setattr(module.evidence, 'require_space', lambda *args, **kwargs: 1)
    frozen = {'git_commit': 'fixed-commit', 'native_module': str(tmp_path / 'native.so'),
              'source_sha256': {'kernel': 'original-sha'}, 'versions': {'scipy': '1.18.0'}}
    monkeypatch.setattr(module, 'provenance', lambda _: frozen)
    monkeypatch.setattr(module, 'idle_snapshot', lambda _: None)
    args = SimpleNamespace(source_manifest=tmp_path / 'local/source.json',
        extension_dir=tmp_path, implementation='legacy', allow_low_space_this_run=True,
        out=tmp_path / 'local/perf-evidence/comparison', frozen_commit=None, native_sha256=None)
    module.freeze(args)
    return module, args, frozen


def test_changed_frozen_sources_refuse_before_workers(bench, monkeypatch):
    module, args, frozen = bench
    frozen['source_sha256']['kernel'] = 'changed-sha'
    monkeypatch.setattr(module, 'launch', lambda *a, **k: pytest.fail('worker launched'))
    with pytest.raises(ValueError, match='frozen source manifest differs'):
        module.run(args)
    assert not args.out.exists()


def test_low_space_waiver_is_part_of_the_frozen_request(bench, monkeypatch):
    module, args, _ = bench
    args.allow_low_space_this_run = False
    monkeypatch.setattr(module, 'launch', lambda *a, **k: pytest.fail('worker launched'))
    with pytest.raises(ValueError, match='frozen source manifest differs'):
        module.run(args)


def test_manifest_mutation_during_verification_refuses_measurement(bench, monkeypatch):
    module, args, _ = bench
    def verification(directory, *unused, **options):
        args.source_manifest.write_text(args.source_manifest.read_text() + '\n')
        return 0, None, []
    monkeypatch.setattr(module, 'launch', verification)
    with pytest.raises(ValueError, match='source manifest changed'):
        module.run(args)
    report = json.loads((args.out / 'summary.json').read_text())
    assert report['status'] == 'failed'
    assert report['runs'] == []


@pytest.mark.parametrize('native_workspace,expected_status,exit_code', [
    (20, 'memory_component_comparison_only', 0), (40, 'component_memory_regression', 2),
])
def test_traced_lane_counts_native_workspace_and_never_accepts_time(
        bench, monkeypatch, native_workspace, expected_status, exit_code):
    module, args, _ = bench
    args.implementation = 'product'
    args.trace_memory = True
    args.source_manifest = args.source_manifest.with_name('trace-source.json')
    module.freeze(args)
    expected = {'tau': 0.1, 'p': 0.5, 'binary64_hex': 'same-test-signature'}
    baseline_count = 0
    def fake_worker(directory, *unused, lane=None, **options):
        nonlocal baseline_count
        if lane is None:
            module.save(directory / 'verification.json', {'A': expected, 'B': expected})
            return 0, None, []
        baseline_count += lane == 'A'
        traced = 100 if lane == 'A' else 80
        workspace = 0 if lane == 'A' else native_workspace
        module.save(directory / 'result.json', expected)
        module.save(directory / 'measurement.json', {'status': 'completed',
            'seconds': 1. if lane == 'A' else .7, 'time_acceptance_eligible': False,
            'tracemalloc_peak_bytes': traced, 'workspace_bytes': workspace,
            'conservative_allocation_peak_bytes': traced + workspace})
        return 0, 100 + 20 * (baseline_count % 2), []
    def fake_retention(active, *unused):
        shutil.rmtree(active)  # protocol-test scratch, never measurement evidence
        return {}
    monkeypatch.setattr(module, 'launch', fake_worker)
    monkeypatch.setattr(module, 'retain', fake_retention)
    assert module.run(args) == exit_code
    report = json.loads((args.out / 'summary.json').read_text())
    assert report['status'] == expected_status
    assert report['time_acceptance_eligible'] is False
    assert report['stable_component_time_benefit'] is False
    assert report['native_rss_noise_below_five_percent'] is False
    assert report['workspace_bytes_by_lane']['B'] == [native_workspace] * 5
