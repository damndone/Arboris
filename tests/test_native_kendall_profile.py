"""Attribution controls only; do not call observers or launch RSS workers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def observer(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'native/kendall_counts/profile_rss.py'
    spec = importlib.util.spec_from_file_location('kendall_rss_observer', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    parent = tmp_path / 'local/perf-evidence'
    parent.mkdir(parents=True)
    csv = tmp_path / 'local/input.csv'
    csv.write_text('x,y\n1,2\n')
    frozen = {'kind': 'kendall-stage-rss-diagnostic', 'input': {'path': str(csv)}, 'workers': 5}
    manifest = tmp_path / 'local/source.json'
    manifest.write_text(json.dumps(frozen))
    monkeypatch.setattr(module, 'frozen_request', lambda *a, **k: frozen)
    monkeypatch.setattr(module.bench, 'fixed_input', lambda: (csv, 'fixed-sha', {}))
    monkeypatch.setattr(module.bench.evidence, 'require_space', lambda *a, **k: 1)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: pytest.fail('RSS worker launched'))
    args = SimpleNamespace(source_manifest=manifest, out=parent / 'profile',
                           extension_dir=tmp_path, allow_low_space_this_run=True)
    return module, args, frozen, parent


def test_changed_attribution_sources_refuse_before_rss_workers(observer):
    module, args, frozen, _ = observer
    frozen['observer_sha256'] = 'changed-source'
    with pytest.raises(ValueError, match='frozen observer/source/input/options differ'):
        module.run(args)
    assert not args.out.exists()


def test_attribution_refuses_parallel_active_tree_and_retains_failure(observer):
    module, args, _, parent = observer
    active = parent / 'other/active'
    active.mkdir(parents=True)
    with pytest.raises(RuntimeError, match='active benchmark tree'):
        module.run(args)
    report = json.loads((args.out / 'summary.json').read_text())
    assert report['acceptance'] is False
    assert report['workers'] == []
    assert report['status'] == 'failed'
    assert active.is_dir()
