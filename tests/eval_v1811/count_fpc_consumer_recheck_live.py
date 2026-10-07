"""LIVE independent count/FPC recheck, with immutable old RED evidence."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from workbench.agent.context_tools import _executed_covariance
from workbench.agent.postestimation_steps import _load_kernel, execute_postestimation_step
from workbench.agent.workflow import WorkflowExecutionError
from workbench.agent.workflow_runtime import _branch_kernel
from workbench.artifacts import read_json, write_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.projects import create_project
from workbench.report_view_model import _survey_design_facts
from tests.eval_v1811.count_public_review_adversarial import POST, fit
from tests.eval_v1811.fpc_public_review_adversarial import FIXTURES, public_run, result


def compare(project, full, restricted, model_id='glm_1'):
    step = SimpleNamespace(operation_id='postestimation.lr', depends_on=(), spec={
        'model_ref': 'model:' + model_id, 'restricted_model_ref': 'model:' + model_id,
        'restricted_model_run_id': restricted.name})
    return execute_postestimation_step(project, full.name, step)[0]


def change_one_csv_value(source, destination, column, increment):
    """Keep every other original CSV value, rather than rounding a whole frame."""
    with source.open(newline='') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    rows[0][column] = str(float(rows[0][column]) + increment)
    with destination.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


@pytest.fixture(scope='module')
def executed(tmp_path_factory):
    base = tmp_path_factory.mktemp('count-fpc-independent-live')
    project = create_project(base, 'actual-owners').root
    runs = {}
    for key, family, y, x, options, source in [
        ('full', 'glm:poisson', 'yc', ['x1', 'x2', 'x3'], {}, POST),
        ('restricted', 'glm:poisson', 'yc', ['x1'], {}, POST),
        ('fixed_full', 'negative_binomial', 'ynb', ['x1', 'x2', 'x3'], {'alpha': .5}, POST),
        ('fixed_other', 'negative_binomial', 'ynb', ['x1'], {'alpha': .8}, POST),
    ]:
        runs[key] = fit(project, source, family, y, x, model_options=options)[0]
    for key, column, increment in [('changed_shared_x', 'x1', 2.), ('changed_response', 'yc', 1.)]:
        source = base / (key + '.csv')
        change_one_csv_value(POST, source, column, increment)
        runs[key] = fit(project, source, 'glm:poisson', 'yc', ['x1'])[0]
    return project, runs


def isolated(tmp_path, runs):
    """Preserve every altered artifact: copy fresh review runs, never restore bytes."""
    project = create_project(tmp_path, 'isolated-owner-attack').root
    copied = {}
    for key in ('full', 'restricted'):
        path = project / 'runs' / runs[key].name
        path.parent.mkdir(exist_ok=True)
        shutil.copytree(runs[key], path)
        copied[key] = path
    return project, copied


def record_attack(root, path, mutation):
    print(json.dumps({'retained_attack': mutation, 'run_root': str(root), 'path': str(path),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))


def test_live_valid_lr_remains_equal_to_existing_real_r_reference(executed):
    project, runs = executed
    actual = compare(project, runs['full'], runs['restricted'])
    native = read_json(POST.parent / 'oracle.json')['families']['poisson']['lr_drop_x2_x3']
    assert actual['statistic'] == pytest.approx(native['statistic'], rel=1e-6)
    json.dumps(actual, allow_nan=False)
    print(json.dumps({'live_valid_lr': actual}))


@pytest.mark.parametrize('key,column', [('changed_shared_x', 'x1'), ('changed_response', 'yc')])
def test_actual_completed_reruns_with_same_column_names_but_changed_values_refuse_lr(executed, key, column):
    project, runs = executed
    left = read_json(runs['full'] / kernel_relative_path('glm_1'))
    right = read_json(runs[key] / kernel_relative_path('glm_1'))
    assert left['nobs'] == right['nobs']
    assert left['estimation_sample_fingerprint'] == right['estimation_sample_fingerprint']
    with pytest.raises(WorkflowExecutionError, match='different actual data|shared input|comparable') as caught:
        compare(project, runs['full'], runs[key])
    assert column in str(caught.value)
    print(json.dumps({'refused_true_rerun': key, 'reason': str(caught.value)}))


def test_different_owner_fixed_alpha_refuses_before_emitting_lr(executed):
    project, runs = executed
    a = read_json(runs['fixed_full'] / 'model_results/negative_binomial_1.json')
    b = read_json(runs['fixed_other'] / 'model_results/negative_binomial_1.json')
    assert a['alpha_fixed_value'] == .5 and b['alpha_fixed_value'] == .8
    assert a['dispersion'] == b['dispersion'] == 'mean'
    assert not a['alpha_estimated'] and not b['alpha_estimated']
    with pytest.raises(WorkflowExecutionError, match='different fixed likelihood.*alpha_fixed_value'):
        compare(project, runs['fixed_full'], runs['fixed_other'], 'negative_binomial_1')


@pytest.mark.parametrize('asset', ['diagnostic_summary.json', 'model_results/glm_1.json',
    'model_results/inference_kernels/glm_1.json'])
def test_semantically_identical_json_bytes_cannot_bypass_registered_sha(tmp_path, executed, asset):
    _, runs = executed; project, cloned = isolated(tmp_path, runs)
    path = cloned['restricted'] / asset
    before = read_json(path)
    path.write_bytes(path.read_bytes() + b'\n ')
    assert read_json(path) == before
    record_attack(cloned['restricted'], path, 'identical_JSON_changed_bytes')
    with pytest.raises(WorkflowExecutionError, match='changed|hash|binding'):
        compare(project, cloned['full'], cloned['restricted'])


@pytest.mark.parametrize('column', ['x1', 'yc'])
def test_changed_processed_values_refuse_lr_and_margins_without_restoring_assets(tmp_path, executed, column):
    import pandas as pd
    _, runs = executed; project, cloned = isolated(tmp_path, runs)
    path = cloned['full'] / 'processed/cleaned_dataset.parquet'
    frame = pd.read_parquet(path); frame.loc[frame.index[0], column] += 1
    frame.to_parquet(path)
    record_attack(cloned['full'], path, 'processed_' + column)
    with pytest.raises(WorkflowExecutionError, match='changed|hash|data'):
        compare(project, cloned['full'], cloned['restricted'])
    step = SimpleNamespace(operation_id='postestimation.margins', depends_on=(), spec={
        'model_ref': 'model:glm_1', 'variables': ['x1'], 'at': 'means'})
    with pytest.raises(WorkflowExecutionError, match='changed|hash|data'):
        execute_postestimation_step(project, cloned['full'].name, step)


@pytest.mark.parametrize('mutation', ['wrong_hash', 'duplicate_registration', 'missing_registration'])
def test_no_unique_current_registered_kernel_hash_refuses_all_public_readers(tmp_path, executed, mutation):
    _, runs = executed; project, cloned = isolated(tmp_path, runs)
    path = cloned['full'] / 'artifacts_index.json'; index = read_json(path)
    relative = kernel_relative_path('glm_1')
    entries = [row for row in index['artifacts'] if row['path'] == relative]
    assert len(entries) == 1
    if mutation == 'wrong_hash': entries[0]['sha256'] = '0' * 64
    elif mutation == 'duplicate_registration': index['artifacts'].append(deepcopy(entries[0]))
    else: index['artifacts'] = [row for row in index['artifacts'] if row['path'] != relative]
    write_json(path, index); record_attack(cloned['full'], path, mutation)
    with pytest.raises(WorkflowExecutionError, match='hash|binding|recorded'):
        _load_kernel(cloned['full'], 'glm_1')
    with pytest.raises(WorkflowExecutionError, match='hash|binding|recorded'):
        _branch_kernel(project, {'run_id': cloned['full'].name, 'model_id': 'glm_1'})
    assert _executed_covariance(cloned['full'], 'glm_1') is None


@pytest.mark.parametrize('status', ['running', 'failed', 'partial', 'blocked'])
def test_only_completed_owner_admits_all_public_kernel_readers(tmp_path, executed, status):
    _, runs = executed; project, cloned = isolated(tmp_path, runs)
    path = cloned['full'] / 'run_manifest.json'; manifest = read_json(path)
    manifest['status'] = status; write_json(path, manifest)
    record_attack(cloned['full'], path, 'completion_' + status)
    with pytest.raises(WorkflowExecutionError, match='completed'):
        _load_kernel(cloned['full'], 'glm_1')
    with pytest.raises(WorkflowExecutionError, match='completed'):
        _branch_kernel(project, {'run_id': cloned['full'].name, 'model_id': 'glm_1'})
    assert _executed_covariance(cloned['full'], 'glm_1') is None


@pytest.mark.parametrize('field', ['model_id', 'params'])
def test_foreign_owner_or_changed_numeric_kernel_never_reaches_any_reader(tmp_path, executed, field):
    _, runs = executed; project, cloned = isolated(tmp_path, runs)
    path = cloned['full'] / kernel_relative_path('glm_1'); kernel = read_json(path)
    if field == 'model_id': kernel[field] = 'foreign_999'
    else: kernel[field][1] += 1
    write_json(path, kernel); record_attack(cloned['full'], path, 'kernel_' + field)
    with pytest.raises(WorkflowExecutionError, match='identity|owner|match|changed|hash|binding'):
        _load_kernel(cloned['full'], 'glm_1')
    with pytest.raises(WorkflowExecutionError, match='identity|owner|match|changed|hash|binding'):
        _branch_kernel(project, {'run_id': cloned['full'].name, 'model_id': 'glm_1'})
    assert _executed_covariance(cloned['full'], 'glm_1') is None


def test_fpc_live_report_projects_each_real_full_design_stratum_and_numbers(tmp_path):
    outcome, root = public_run(tmp_path, 'subpop', survey_fpc_col='population_fpc', survey_subpop='subpop == 1')
    assert outcome['status'] == 'completed'
    packet, _ = result(root); rows = packet['survey_design']['fpc']['strata']
    facts = _survey_design_facts(root)
    for row in rows:
        matches = [text for text in facts if text.startswith('FPC stratum ' + row['stratum'] + ':')]
        assert len(matches) == 1
        line = matches[0]
        assert f"{row['sampled_psus']} sampled PSUs" in line
        assert f"sampling fraction {row['sampling_fraction']:.6g}" in line
        assert f"variance factor {row['variance_factor']:.6g}" in line
        assert f"population PSUs {row['population_psus']}" in line
    print(json.dumps({'live_fpc_report_facts': facts}))


def test_fpc_live_census_owner_warning_shared_identity_and_finite_packets(tmp_path):
    import pandas as pd
    frame = pd.read_csv(FIXTURES / 'design.csv'); frame['live_census'] = 1.0
    source = tmp_path / 'census.csv'; frame.to_csv(source, index=False)
    outcome, root = public_run(tmp_path / 'projects', source, survey_fpc_col='live_census')
    assert outcome['status'] == 'completed'
    packet, kernel = result(root)
    code = 'SURVEY_ZERO_VARIANCE_INFERENCE_UNAVAILABLE'
    raw = next(warning for warning in packet['warnings'] if warning.get('code') == code)
    shared = [issue for issue in read_json(root / 'errors.json')['issues'] if issue.get('code') == code]
    assert len(shared) == 1 and shared[0]['message'] == raw['message']
    assert shared[0]['evidence']['artifact_id'] == 'ols_1'
    assert shared[0]['evidence']['model_id'] == packet['model_id']
    assert np.count_nonzero(np.asarray(kernel['vcov'])) == 0
    assert all(row['p_value'] is None and row['std_error'] == 0 for row in packet['coefficients'].values())
    from workbench.report_view_model import build_report_view_model
    view = build_report_view_model(read_json(root / 'diagnostic_summary.json'), root)
    assert any(row['code'] == code and row['text'] == raw['message'] for row in view['warnings'])
    json.dumps({'packet': packet, 'kernel': kernel, 'issue': shared}, allow_nan=False)
    print(json.dumps({'live_fpc_census_issue': shared}))


def test_count_warning_projection_bounds_record_count_labels_and_excludes_extra_payload(tmp_path):
    from workbench.agent.family_evidence import bounded_model_family_evidence
    packet = {'model_type': 'negative_binomial', 'warnings': [
        {'code': 'OWNER_CODE_' + 'x' * 1000, 'message': 'OWNER_REASON_' + 'x' * 1000,
         'raw_rows': ['private'], 'extra_payload': {'private': [1, 2, 3]}}
        for _ in range(100)]}
    projected = bounded_model_family_evidence(tmp_path, [packet])['warnings']
    assert len(projected) == 16
    assert all(set(row) == {'code', 'message'} for row in projected)
    assert all(len(row['code']) <= 128 and len(row['message']) <= 128 for row in projected)
    assert 'private' not in json.dumps(projected)
    json.dumps(projected, allow_nan=False)


def test_count_warning_projection_does_not_coerce_nonstring_owner_code_or_message(tmp_path):
    from workbench.agent.family_evidence import bounded_model_family_evidence
    packet = {'model_type': 'glm', 'kernel_family': 'glm:negative_binomial',
        'warnings': [{'code': True, 'message': 10**1000}, {'code': ['private'], 'message': {'private': 1}}]}
    projected = bounded_model_family_evidence(tmp_path, [packet])['warnings']
    assert all(not row for row in projected)
    json.dumps(projected, allow_nan=False)
