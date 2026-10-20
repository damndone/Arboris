"""Native LMM residual/source evidence, without a provider or holdout run."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import register_artifact
from workbench.canonical import sha256_canonical
from workbench.engine.packs.linear_mixed_effects.input import prepare_lmm_input
from workbench.engine.packs.linear_mixed_effects.runner import _fit_prepared, fit_from_context
from workbench.model_options import ModelOptionsBinding, canonical_options_hash
from workbench.services.pinned_run_directory import (
    _new_test_lmm_execution_admission, open_pinned_run_directory, seal_executed_input_v1,
)

DATA = Path(__file__).parent / 'fixtures/postestimation/lmm_v1811/random_slope.csv'


def native_run(project, name='main', *, random_slope=True, missing=False):
    """Real pack/FD writer, with test-only admission; not containment certification."""
    run = project / 'runs' / name
    run.mkdir(parents=True)
    frame = pd.read_csv(DATA, float_precision='round_trip')
    if missing:
        frame.loc[3, 'x'] = np.nan
    (run / 'artifacts_index.json').write_text(json.dumps({'schema_version': 1, 'artifacts': []}))
    source = run / 'input.csv'
    frame.to_csv(source, index=False)
    frame = pd.read_csv(source, float_precision='round_trip')
    register_artifact(run, 'data', source, 'raw_data', 'source', [])
    options = dict(subject_id='g', time='time', group='arm', fit_method='reml', random_slope=random_slope)
    binding = ModelOptionsBinding('linear_mixed_effects', 'linear_mixed_effects_1',
        'linear_mixed_effects@1.0', '1.0', canonical_options_hash(options)).to_dict()
    seal_input = dict(schema_version=1, model_type='linear_mixed_effects', model_options=options,
                      model_options_binding=binding)
    (run / 'run_inputs.json').write_text(json.dumps({'executed_payload': seal_input}))
    with open_pinned_run_directory(project / 'runs', name) as pinned:
        seal = seal_executed_input_v1(pinned, seal_input)
        admission = _new_test_lmm_execution_admission(pinned, seal)
        try:
            ctx = SimpleNamespace(data=SimpleNamespace(frame=frame, artifact_id='data'), y_col='y', x_cols=['x'],
                artifacts={'_model_options': options, '_model_options_binding': binding,
                           '_upload_hash': hashlib.sha256(source.read_bytes()).hexdigest()})
            env = SimpleNamespace(lmm_execution_admission=admission, run_root=run,
                                  progress=lambda *_: None, checkpoint=lambda: None)
            _, result, fitted = fit_from_context(ctx, env)
        finally:
            admission._close_for_test()
    return run, frame, result, fitted


def evidence_file(run):
    return run / 'artifacts/diagnostics/linear_mixed_effects_1.analysis_evidence.json'


def test_native_lmm_has_explicit_residuals_and_actual_retained_row_positions(tmp_path):
    run, frame, result, fitted = native_run(tmp_path, missing=True)
    assert evidence_file(run).is_file(), 'native LMM must publish residual/source sidecar'
    evidence = json.loads(evidence_file(run).read_text())['payload']
    assert evidence['status'] == 'complete'
    assert evidence['execution_binding'] == result['payload']['execution_binding']
    assert evidence['terminal_sha256'] == hashlib.sha256((run / 'artifacts/model_results/linear_mixed_effects_1.result.json').read_bytes()).hexdigest()
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import residual_arrays
    from workbench.services.completion_products import sample_metadata, array_fingerprint
    arrays = residual_arrays(fitted)
    positions = np.array([i for i in range(len(frame)) if i != 3])
    assert evidence['sample'] == sample_metadata(positions, len(frame))
    assert 'rows' not in evidence
    np.testing.assert_allclose(arrays['conditional'], fitted.resid, atol=1e-12)
    np.testing.assert_allclose(arrays['marginal'], fitted.model.endog - fitted.model.exog @ fitted.fe_params, atol=1e-12)
    assert evidence['residual_fingerprints'] == {k: array_fingerprint(v) for k,v in arrays.items()}
    assert evidence['residual_definitions']['conditional'] == 'y - X beta - Z b_hat'
    assert evidence['residual_definitions']['scaled_conditional'] == 'conditional_residual / sqrt(residual_variance); not studentized or independent'
    assert evidence['source']['artifact_id'] == 'data'
    assert evidence['source']['sha256'] == hashlib.sha256((run / 'input.csv').read_bytes()).hexdigest()
    assert evidence['analysis_sample_sha256'] == sample_metadata(positions, len(frame))['positions_sha256']
    # Existing packet stays strict and unchanged in shape.
    from workbench.services.lmm_result_adapter import parse_lmm_result_payload_v1
    assert parse_lmm_result_payload_v1(result['payload']) == result['payload']


def test_lmm_completion_reads_native_packet_and_bounded_evidence_after_reopen(tmp_path):
    from workbench.agent.context_compiler import read_completion_artifact
    from workbench.agent.completion import _model
    run, _, result, _ = native_run(tmp_path)
    terminal = read_completion_artifact(run, 'linear_mixed_effects_1.result')
    model = _model(terminal)
    assert model and model['model_type'] == 'linear_mixed_effects'
    assert model['coefficients'] == result['payload']['coefficients']
    evidence = read_completion_artifact(run, 'linear_mixed_effects_1.analysis_evidence')
    assert evidence is not None
    assert evidence.payload['status'] == 'complete'
    assert 'rows' not in evidence.payload, 'the completion projection must not expose raw rows'
    assert evidence.payload['nobs'] == result['payload']['nobs']
    assert 'data' in terminal.inputs
    assert 'linear_mixed_effects_1.result' in evidence.inputs


def test_lmm_missing_or_tampered_companion_cannot_complete_native_model(tmp_path):
    from workbench.agent.context_compiler import read_completion_artifact
    from workbench.agent.completion import _model
    run, _, _, _ = native_run(tmp_path)
    path = evidence_file(run)
    assert path.is_file(), 'source/diagnostic companion is required'
    path.write_text('{}')
    assert read_completion_artifact(run, 'linear_mixed_effects_1.analysis_evidence') is None
    assert _model(read_completion_artifact(run, 'linear_mixed_effects_1.result')) is None


def test_native_lmm_completes_only_with_distinct_fitted_sensitivity_and_linked_report(tmp_path):
    from workbench.agent.completion import evaluate
    from workbench.reporting import render_html_report
    main, _, _, _ = native_run(tmp_path)
    alternate, _, _, _ = native_run(tmp_path, 'alternate', random_slope=False)
    source_sha = hashlib.sha256((main / 'input.csv').read_bytes()).hexdigest()
    contract = {'playbooks': ['lmm'], 'source': {'run_id': 'main', 'artifact_id': 'data', 'sha256': source_sha}}
    evidence = {'models': [{'run_id': 'main', 'artifact_id': 'linear_mixed_effects_1.result'}],
        'diagnostics': [{'run_id': 'main', 'artifact_id': 'linear_mixed_effects_1.analysis_evidence'}],
        'sensitivity': [{'run_id': 'alternate', 'artifact_id': 'linear_mixed_effects_1.result'}],
        'report': {'run_id': 'main', 'artifact_id': 'report'}}
    from tests.test_agent_completion import artifact
    artifact(tmp_path, 'main', 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed', 'steps': {
            'main': {'status': 'completed', 'artifact_ids': ['main:linear_mixed_effects_1.result',
                'main:linear_mixed_effects_1.analysis_evidence', 'alternate:linear_mixed_effects_1.result']}}})
    render_html_report({'title': 'LMM analysis', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        main, artifact_id='report', inputs=['collection'])
    checked = evaluate(tmp_path, contract, evidence)
    assert checked['status'] == 'requirements_met', checked['missing']
    assert checked['scientific_validity'] == 'not_certified'
    evidence['sensitivity'] = evidence['models']
    assert 'lmm:sensitivity:distinct_point_estimation' in evaluate(tmp_path, contract, evidence)['missing']
    evidence['diagnostics'] = []
    assert any('lmm:diagnostics:' in m for m in evaluate(tmp_path, contract, evidence)['missing'])


@pytest.mark.parametrize('mutation', ['source', 'terminal', 'seal', 'row_mapping', 'definition'])
def test_lmm_companion_rejects_changed_dependencies_even_with_reindexed_companion(tmp_path, mutation):
    from workbench.agent.context_compiler import read_completion_artifact
    run, _, _, _ = native_run(tmp_path)
    path = evidence_file(run)
    assert path.is_file()
    packet = json.loads(path.read_text())
    if mutation == 'source':
        (run / 'input.csv').write_text('wrong input')
    elif mutation == 'terminal':
        packet['payload']['terminal_sha256'] = '0' * 64
    elif mutation == 'seal':
        (run / 'artifacts/execution/executed_input_v1.json').write_text('{}')
    elif mutation == 'row_mapping':
        packet['payload']['sample']['positions_sha256'] = '0'*64
    else:
        packet['payload']['residual_definitions']['conditional'] = 'not actual conditional residuals'
    path.write_text(json.dumps(packet))
    index_path = run / 'artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(a for a in index['artifacts'] if a['artifact_id'] == 'linear_mixed_effects_1.analysis_evidence')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    assert read_completion_artifact(run, 'linear_mixed_effects_1.analysis_evidence') is None
    assert read_completion_artifact(run, 'linear_mixed_effects_1.result') is None


@pytest.mark.parametrize('setting', ['intercept_reml', 'intercept_ml', 'slope_reml', 'slope_ml', 'unbalanced_missing'])
def test_native_residuals_agree_with_independent_lme4_producer(setting):
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import build_analysis_evidence
    oracle = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/agent_completion/lmm/residuals_r.json.gz').read_bytes()))
    record = oracle['cases'][setting]
    path = Path(record['source'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['source_sha256']
    frame = pd.read_csv(path, float_precision='round_trip')
    options = dict(subject_id='g', time='time', group='arm', fit_method=record['fit_method'], random_slope=record['random_slope'])
    prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=options)
    fitted = _fit_prepared(prepared)
    # Diagnostic-only builder: no attempt to mint an execution admission.
    payload = dict(model_id='linear_mixed_effects_1', model_type='linear_mixed_effects',
                   execution_binding={}, result_identity='diagnostic-only', status='complete', nobs=int(fitted.nobs))
    evidence = build_analysis_evidence(source={'artifact_id': 'data', 'sha256': record['source_sha256'], 'row_count': len(frame)}, prepared=prepared,
                                       result={'payload': payload}, fitted=fitted)['payload']
    from workbench.services.completion_products import sample_metadata
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import residual_arrays
    assert evidence['sample'] == sample_metadata(record['source_row_positions'], len(frame))
    arrays = residual_arrays(fitted)
    arrays['conditional_fitted'] = fitted.model.endog-arrays['conditional']
    for key in ('conditional_residual', 'marginal_residual', 'conditional_fitted', 'scaled_conditional_residual'):
        np.testing.assert_allclose(arrays[{'conditional_residual': 'conditional', 'marginal_residual': 'marginal', 'scaled_conditional_residual': 'scaled_conditional', 'conditional_fitted': 'conditional_fitted'}[key]], record[key], rtol=2e-6, atol=2e-6)


def test_native_companion_reopens_in_fresh_process_without_fit_or_provider(tmp_path):
    import os
    import subprocess
    import sys
    run, _, _, _ = native_run(tmp_path)
    command = [sys.executable, '-c',
        'import json, sys; from pathlib import Path; from workbench.agent.context_compiler import read_completion_artifact; '
        'v=read_completion_artifact(Path(sys.argv[1]), "linear_mixed_effects_1.analysis_evidence"); '
        'print(json.dumps({"status":v.payload["status"], "has_rows":"rows" in v.payload}))', str(run)]
    env = {**os.environ, 'PYTHONPATH': str(Path('backend').resolve())}
    reopened = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
    assert json.loads(reopened.stdout) == {'status': 'complete', 'has_rows': False}


@pytest.mark.parametrize('admission', [None, object()])
def test_sidecar_requires_original_execution_admission(tmp_path, admission):
    from workbench.services.pinned_run_directory import _persist_lmm_analysis_evidence, PinnedRunError
    with pytest.raises(PinnedRunError, match='LMM_EXECUTION_BINDING_REQUIRED'):
        _persist_lmm_analysis_evidence(admission=admission, packet={}, terminal=object())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('setting', ['intercept_reml', 'intercept_ml', 'slope_reml', 'slope_ml', 'unbalanced_missing'])
def test_native_residuals_agree_with_stata_mixed_predictions(setting):
    oracle = pd.read_csv(Path(__file__).parent / 'fixtures/agent_completion/lmm/residuals_stata.csv.gz')
    r = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/agent_completion/lmm/residuals_r.json.gz').read_bytes()))['cases'][setting]
    prepared = prepare_lmm_input(pd.read_csv(r['source'], float_precision='round_trip'), outcome='y', controls=['x'],
        options=dict(subject_id='g', time='time', group='arm', fit_method=r['fit_method'], random_slope=r['random_slope']))
    fitted = _fit_prepared(prepared)
    selected = oracle[oracle.setting == setting]
    assert list(selected.source_row_position) == list(prepared.source_row_positions)
    for column, actual in [('conditional_fitted', fitted.fittedvalues), ('conditional_residual', fitted.resid),
                           ('marginal_residual', fitted.model.endog - fitted.model.exog @ fitted.fe_params)]:
        np.testing.assert_allclose(actual, selected[column], atol=2e-6, rtol=2e-6)


def test_native_companion_publication_is_idempotent_and_closed_admission_cannot_republish(tmp_path, monkeypatch):
    from workbench.services import pinned_run_directory as persistence
    original = persistence._persist_lmm_analysis_evidence
    captured = {}
    def publish_twice(**kwargs):
        first = original(**kwargs)
        captured.update(kwargs)
        assert original(**kwargs) is first
        return first
    monkeypatch.setattr(persistence, '_persist_lmm_analysis_evidence', publish_twice)
    run, _, _, _ = native_run(tmp_path)
    index = json.loads((run / 'artifacts_index.json').read_text())
    assert sum(a['artifact_type'] == 'lmm_analysis_evidence' for a in index['artifacts']) == 1
    before = evidence_file(run).read_bytes()
    with pytest.raises(persistence.PinnedRunError):
        original(**captured)
    assert evidence_file(run).read_bytes() == before


def test_failed_fit_cannot_publish_successful_residual_evidence(tmp_path, monkeypatch):
    from workbench.engine.packs.linear_mixed_effects import runner
    monkeypatch.setattr(runner, '_fit_prepared', lambda prepared: SimpleNamespace(converged=False, nobs=len(prepared.frame)))
    run, _, result, _ = native_run(tmp_path)
    assert result['payload']['status'] == 'failed'
    evidence = json.loads(evidence_file(run).read_text())['payload']
    assert evidence['status'] == 'unavailable'
    assert evidence['reason'] == 'fit_incomplete'
    assert evidence['sample'] is None and 'rows' not in evidence
    from workbench.agent.context_compiler import read_completion_artifact
    assert read_completion_artifact(run, 'linear_mixed_effects_1.result') is None


def test_retained_row_positions_do_not_depend_on_dataframe_labels():
    frame = pd.read_csv(DATA, float_precision='round_trip')
    frame.index = ['duplicate'] * len(frame)
    frame.loc[:, 'irrelevant'] = np.nan
    frame.iloc[7, frame.columns.get_loc('x')] = np.nan
    prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=dict(
        subject_id='g', time='time', group='arm', fit_method='reml', random_slope=True))
    assert prepared.source_row_positions == tuple(i for i in range(len(frame)) if i != 7)


def test_legacy_dictionary_cannot_impersonate_native_lmm_result(tmp_path):
    from tests.test_agent_completion import artifact
    from workbench.agent.context_compiler import read_completion_artifact
    from workbench.agent.completion import _model
    artifact(tmp_path, 'r', 'fake', 'model_result', {'model_id': 'linear_mixed_effects_1',
        'model_type': 'linear_mixed_effects', 'nobs': 30, 'coefficients': {'x': {'estimate': 1, 'std_error': .1}}})
    assert _model(read_completion_artifact(tmp_path / 'runs/r', 'fake')) is None


def test_source_artifact_rename_cannot_count_as_different_estimation():
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import build_analysis_evidence
    frame = pd.read_csv(DATA, float_precision='round_trip')
    prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=dict(
        subject_id='g', time='time', group='arm', fit_method='reml', random_slope=True))
    fitted = _fit_prepared(prepared)
    payload = dict(model_id='linear_mixed_effects_1', model_type='linear_mixed_effects',
                   execution_binding={}, result_identity='diagnostic-only', status='complete', nobs=int(fitted.nobs))
    fingerprints = []
    for name in ('data', 'renamed'):
        fingerprints.append(build_analysis_evidence(source={'artifact_id': name, 'sha256': 'a' * 64, 'row_count': len(prepared.frame)},
            prepared=prepared, result={'payload': payload}, fitted=fitted)['payload']['point_estimation_fingerprint'])
    assert fingerprints[0] == fingerprints[1]


def test_native_executable_payload_is_verified_and_conflicting_executed_metadata_is_rejected(tmp_path):
    from workbench.agent.context_compiler import read_completion_artifact
    run, _, _, _ = native_run(tmp_path)
    path = run / 'run_inputs.json'
    snapshot = json.loads(path.read_text())
    snapshot['executable_payload'] = snapshot.pop('executed_payload')
    path.write_text(json.dumps(snapshot))
    assert read_completion_artifact(run, 'linear_mixed_effects_1.result') is not None
    snapshot['executed_payload'] = {**snapshot['executable_payload'], 'model_options': {}}
    path.write_text(json.dumps(snapshot))
    assert read_completion_artifact(run, 'linear_mixed_effects_1.result') is None


def test_numeric_reference_manifest_binds_commands_versions_inputs_and_raw_outputs():
    root = Path(__file__).parent / 'fixtures/agent_completion/lmm'
    manifest = json.loads((root / 'manifest.json').read_text())
    assert manifest['tolerance'] == {'atol': 2e-6, 'rtol': 2e-6}
    assert manifest['independent_producers'] == ['R lme4', 'Stata mixed']
    for path, digest in manifest['repository_files'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    for path, digest in manifest.get('decoded_sha256', {}).items():
        assert hashlib.sha256(gzip.decompress(Path(path).read_bytes())).hexdigest() == digest


def test_changing_unused_source_values_cannot_count_as_lmm_sensitivity():
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import build_analysis_evidence
    frame = pd.read_csv(DATA, float_precision='round_trip')
    frame['unused'] = 0
    options = dict(subject_id='g', time='time', group='arm', fit_method='reml', random_slope=True)
    fingerprints = []
    for value in (0, 7):
        frame['unused'] = value
        prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=options)
        fitted = _fit_prepared(prepared)
        payload = dict(model_id='linear_mixed_effects_1', model_type='linear_mixed_effects',
            execution_binding={}, result_identity='diagnostic-only', status='complete', nobs=int(fitted.nobs))
        fingerprints.append(build_analysis_evidence(source={'artifact_id': 'data', 'sha256': str(value) * 64, 'row_count': len(prepared.frame)},
            prepared=prepared, result={'payload': payload}, fitted=fitted)['payload']['point_estimation_fingerprint'])
    assert fingerprints[0] == fingerprints[1]


def test_failed_fit_with_nonfinite_inputs_keeps_its_failure_evidence():
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import build_analysis_evidence
    frame = pd.read_csv(DATA)
    frame.loc[0, 'y'] = np.inf
    prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=dict(
        subject_id='g', time='time', group='arm', fit_method='reml', random_slope=True))
    failed = {'payload': dict(model_id='linear_mixed_effects_1', model_type='linear_mixed_effects',
        execution_binding={}, result_identity='failed', status='failed', nobs=len(frame))}
    evidence = build_analysis_evidence(source=None, prepared=prepared, result=failed, fitted=None)['payload']
    assert evidence['status'] == 'unavailable' and evidence['reason'] == 'fit_incomplete'
    assert evidence['point_estimation_fingerprint'] is None


def test_historical_row_evidence_remains_readable(tmp_path):
    from workbench.agent.context_compiler import read_completion_artifact
    from workbench.engine.packs.linear_mixed_effects.analysis_evidence import residual_arrays
    run, frame, _, fitted = native_run(tmp_path, random_slope=False)
    path = evidence_file(run)
    packet = json.loads(path.read_text())
    value = packet['payload']
    options = dict(subject_id='g', time='time', group='arm', fit_method='reml', random_slope=False)
    prepared = prepare_lmm_input(frame, outcome='y', controls=['x'], options=options)
    controls = list(prepared.fixed_effects[4:])
    old_frame = prepared.frame
    value['point_estimation_fingerprint'] = sha256_canonical({
        'fixed': prepared.formula, 'random': prepared.random_effects, 'method': prepared.input.fit_method,
        'numeric_values': np.asarray(old_frame[[prepared.outcome, prepared.input.time, *controls]], dtype=float).tolist(),
        'subject_partition': pd.factorize(old_frame[prepared.input.subject_id], sort=False)[0].tolist(),
        'comparison_group': (old_frame[prepared.input.group] == prepared.comparison_group_value).tolist()})
    values = residual_arrays(fitted)
    value['schema_version'] = 1
    positions = list(prepared.source_row_positions)
    value['analysis_sample_sha256'] = sha256_canonical(positions)
    value['rows'] = [{'source_row_position': p, 'conditional_residual': float(c),
        'marginal_residual': float(m), 'scaled_conditional_residual': float(s), 'conditional_fitted': float(y-c)}
        for p,c,m,s,y in zip(positions,values['conditional'],values['marginal'],values['scaled_conditional'],fitted.model.endog)]
    path.write_text(json.dumps(packet))
    index_path = run/'artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(r for r in index['artifacts'] if r['artifact_id']=='linear_mixed_effects_1.analysis_evidence')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    assert read_completion_artifact(run, 'linear_mixed_effects_1.result') is not None
