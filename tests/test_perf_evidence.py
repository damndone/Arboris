"""Retention is durable and complete before an authorized benchmark deletion."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def evidence():
    spec = importlib.util.spec_from_file_location('perf_evidence', Path(__file__).parents[1]/'scripts/perf_evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_record_roundtrip_keeps_numbers_and_every_file_before_removal(evidence, tmp_path):
    parent = tmp_path/'perf-regression-2026-10-20'
    root = parent/'fixed-ab-test'
    root.mkdir(parents=True)
    (root/'result.json').write_text('{"coefficients":{"x":{"estimate":1.25,"std_error":0.5}}}')
    (root/'raw.bin').write_bytes(b'original observations')
    ledger = tmp_path/'records.jsonl'
    record = evidence.snapshot(root, record_id='run1', metadata={'version_commit': 'a'*40, 'seconds': 1.25})
    evidence.append_record(ledger, record)
    assert root.exists()
    evidence.remove_recorded_tree(root, parent=parent, ledger=ledger, expected_ids=['run1'])
    assert not root.exists()
    saved = evidence.read_records(ledger)[0]
    assert saved['metadata']['seconds'] == 1.25
    assert len(saved['files']) == 2
    assert all(len(f['sha256']) == 64 for f in saved['files'])


def test_missing_file_record_or_changed_file_prevents_removal(evidence, tmp_path):
    parent = tmp_path/'perf-regression-2026-10-20'
    root = parent/'isolated-test'
    root.mkdir(parents=True)
    (root/'a').write_text('one')
    ledger = tmp_path/'records.jsonl'
    evidence.append_record(ledger, evidence.snapshot(root, record_id='run1', metadata={}))
    (root/'a').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        evidence.remove_recorded_tree(root, parent=parent, ledger=ledger, expected_ids=['run1'])
    assert root.exists()


def test_unknown_or_linked_cleanup_root_is_rejected(evidence, tmp_path):
    parent = tmp_path/'perf-regression-2026-10-20'
    root = parent/'agent-eval'
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match='authorized'):
        evidence.check_legacy_root(root, parent)
    alias = parent/'fixed-ab-link'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        evidence.check_legacy_root(alias, parent)
    assert root.exists()


def test_representative_archive_is_verified_by_each_original_digest(evidence, tmp_path):
    root = tmp_path/'run'
    root.mkdir()
    (root/'result.json').write_text('{"estimate":0.5}')
    (root/'nested').mkdir()
    (root/'nested/data.bin').write_bytes(b'rows')
    record = evidence.snapshot(root, record_id='run1', metadata={})
    archive = tmp_path/'representative.tar.gz'
    value = evidence.archive_verified(root, archive, record['files'])
    assert value['verified_files'] == 2
    assert value['sha256'] == evidence.digest(archive)
    assert root.exists()


def test_legacy_migration_preserves_controls_and_rejects_unaccounted_files(evidence, tmp_path):
    parent = tmp_path/'perf-regression-2026-10-20'
    root = parent/'fixed-ab-3'
    run = root/'panel/A1/benchmark/runs/r1'
    (run/'model_results').mkdir(parents=True)
    (run/'model_results/panel_ols_1.json').write_text('{"coefficients":{"x":{"estimate":2,"std_error":0.5}}}')
    (run/'run_manifest.json').write_text('{"status":"completed","requested_model_type":"panel_ols"}')
    (root/'panel/A1/metrics.json').write_text(json.dumps(dict(case='panel', seconds=2., ru_maxrss=100,
        run_bytes=100, run_root=str(run))))
    (root/'notes.log').write_text('original log')
    (root/'ab-results.json').write_text(json.dumps({'revisions':{'baseline':'a'*40,'candidate':'b'*40}}))
    protected = parent/'agent-eval'
    protected.mkdir()
    (protected/'keep').write_text('do not touch')
    report = evidence.migrate_legacy(parent, tmp_path/'evidence')
    assert not root.exists()
    assert (protected/'keep').read_text() == 'do not touch'
    records = evidence.read_records(Path(report['jsonl']))
    runs = [r for r in records if r['kind'] == 'workflow_run']
    assert len(runs) == 1
    assert runs[0]['metadata']['version_commit'] == 'a'*40
    assert runs[0]['metadata']['major_results']['panel_ols_1']['coefficients']['x']['estimate'] == 2
    assert (tmp_path/'evidence/controls/fixed-ab-3/notes.log').read_text() == 'original log'
    assert report['verified_file_count'] == 5


def test_only_primary_model_envelopes_are_read_not_observation_diagnostics(evidence, tmp_path, monkeypatch):
    model = tmp_path/'model_results'
    model.mkdir()
    (model/'panel_ols_1.json').write_text('{"coefficients":{"x":{"estimate":1,"std_error":0.5}}}')
    diagnostic = model/'panel_ols_1.diagnostics.json'
    diagnostic.write_text('{"retained_positions":[0,1,2]}')
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == diagnostic:
            pytest.fail('do not decode observation-level diagnostic data into the journal')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    results, _ = evidence.major_results(tmp_path)
    assert set(results) == {'panel_ols_1'}


def test_existing_ols_sample_arrays_are_not_reencoded_in_the_journal(evidence, tmp_path):
    model = tmp_path/'model_results'
    model.mkdir()
    (model/'ols_1.json').write_text(json.dumps({'coefficients':{'x':{'estimate':1.,'std_error':.5}},
                                              'analysis_sample':{'positions':list(range(1000))}}))
    results, tests = evidence.major_results(tmp_path)
    assert results['ols_1']['analysis_sample']['positions']['omitted_observation_items'] == 1000
    assert results['ols_1']['coefficients']['x']['estimate'] == 1.
    assert tests['ols_1']['x']['estimate_over_se'] == 2.


def test_ten_gb_floor_blocks_measurement(evidence, tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=9_999_999_999))
    with pytest.raises(SystemExit, match='10 GB'):
        evidence.require_space(tmp_path)


def test_active_run_is_removed_only_after_verified_journal(evidence, tmp_path):
    active = tmp_path/'active'
    run = active/'benchmark/runs/r1'
    (run/'model_results').mkdir(parents=True)
    (run/'model_results/ols_1.json').write_text('{"coefficients":{"x":{"estimate":1,"std_error":0.5}}}')
    ledger = tmp_path/'measurements.jsonl'
    result = evidence.finalize_active(active, ledger=ledger, record_id='panel-A1', metadata={'run_root':str(run)},
                                      archive_dir=tmp_path/'representatives', version='v1.9.1', case='panel')
    assert not active.exists()
    records = evidence.read_records(ledger)
    assert records[0]['record_id'] == 'panel-A1'
    assert result['journal_record_id'] == 'panel-A1'
    assert len(list((tmp_path/'representatives').glob('*.tar.gz'))) == 1


def test_failed_journal_write_keeps_active_tree(evidence, tmp_path, monkeypatch):
    active = tmp_path/'active'
    active.mkdir()
    (active/'partial').write_text('keep me')
    def fail(*args, **kwargs):
        raise OSError('disk write failed')
    monkeypatch.setattr(evidence, 'append_record', fail)
    with pytest.raises(OSError, match='disk write failed'):
        evidence.finalize_active(active, ledger=tmp_path/'measurements.jsonl', record_id='failed',
            metadata={'run_root':str(active/'uncompleted')}, archive_dir=tmp_path/'representatives',
            version='v1.9.1', case='panel')
    assert (active/'partial').read_text() == 'keep me'


def test_registered_input_hash_is_reused_for_its_hardlinks(evidence, tmp_path, monkeypatch):
    import os
    source = tmp_path/'fixed.csv'
    source.write_bytes(b'x,y\n1,2\n')
    tree = tmp_path/'active'
    tree.mkdir()
    os.link(source, tree/'snapshot.csv')
    os.link(source, tree/'upload.csv')
    sha = evidence.digest(source)
    monkeypatch.setattr(evidence, 'digest', lambda _: pytest.fail('registered CSV was re-read for validation'))
    rows = evidence.inventory(tree, registered_input=(source, sha))
    assert len(rows) == 2
    assert {r['sha256'] for r in rows} == {sha}


def test_native_test_statistics_and_their_definitions_are_retained(evidence, tmp_path):
    models = tmp_path/'model_results'
    models.mkdir()
    evidence_packet = {'checks':[{'check_id':'iv.exclusion_restriction',
        'evidence':{'test':'Wooldridge robust score', 'statistic':1.73, 'p_value':0.188}}]}
    (models/'checks_iv_2sls_1.json').write_text(json.dumps(evidence_packet))
    _, tests = evidence.major_results(tmp_path)
    assert tests['native_checks']['checks_iv_2sls_1'] == evidence_packet
