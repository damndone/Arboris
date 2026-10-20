"""A specification curve retains the frozen set, failures and native numbers."""
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_agent_completion_time_series import series, products


def test_frozen_set_exists_before_the_first_workflow_step_and_cannot_be_replaced(tmp_path):
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow, WorkflowStepResult, WorkflowExecutionError
    target = {'run_id': 'source', 'artifact_id': 'data', 'node_ref': 'stage:source'}
    draft = compile_workflow(workflow_id='fixed', target=target,
        preconditions={'context_fingerprint': 'source'}, steps=[{'step_id': 'a', 'operation_id': 'report.compose', 'spec': {}}])
    def execute(step, previous):
        value = json.loads((tmp_path / 'workbench/workflows/fixed.plan.json').read_text())
        assert value['draft'] == draft.to_dict()
        return WorkflowStepResult()
    state = WorkflowExecutor(tmp_path).execute(draft, execute)
    assert state.status == 'completed', state.to_dict()
    changed = compile_workflow(workflow_id='fixed', target=target,
        preconditions={'context_fingerprint': 'source'}, steps=[{'step_id': 'b', 'operation_id': 'report.compose', 'spec': {}}])
    with pytest.raises(WorkflowExecutionError):
        WorkflowExecutor(tmp_path).execute(changed, execute)


def report_curve(project, workflow_id, term):
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    snapshot = json.loads((project / 'workbench/workflows' / f'{workflow_id}.plan.json').read_text())['draft']
    draft = compile_workflow(workflow_id='curve-report', target=snapshot['target'], preconditions=snapshot['preconditions'],
        steps=[{'step_id': 'report', 'operation_id': 'report.compose', 'spec': {
            'specification_curve': {'workflow_id': workflow_id, 'term': term,
                'estimand': 'Conditional AR coefficient on the observed level scale'}}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed', state.to_dict()
    run = project / 'runs' / snapshot['target']['run_id']
    payload = json.loads((run / 'artifacts/specification_curves/curve-report.json').read_text())
    return payload, run


def test_native_arima_curve_retains_all_members_and_exact_values(tmp_path):
    project, contract, evidence = products(tmp_path, series())
    curve, run = report_curve(project, 'native-arima', 'ar.L1')
    assert len(curve['rows']) == 2
    assert curve['set_fixed_before_its_execution'] is True
    assert curve['preregistration_verified'] is False
    assert curve['comparison_group_count'] == 1 and curve['distinct_point_estimation_count'] == 2
    for row in curve['rows']:
        assert row['status'] == 'estimated'
        index = json.loads((run / 'artifacts_index.json').read_text())['artifacts']
        record = next(a for a in index if a['artifact_id'] == row['result_ref']['artifact_id'])
        native = json.loads((run / record['path']).read_text())['result']['result']['analysis_evidence']
        expected = native['coefficients']['ar.L1']
        assert row['estimate'] == expected['estimate'] and row['std_error'] == expected['std_error']
        assert row['nobs'] == 300 and row['model_type'] == 'arima'
        assert row['ci_lower'] is None and row['ci_upper'] is None
        assert row['interval_status'] == 'not_reported'
    assert (run / 'artifacts/specification_curves/curve-report.svg').is_file()
    assert (run / 'artifacts/specification_curves/curve-report.png').is_file()
    index = json.loads((run / 'artifacts_index.json').read_text())['artifacts']
    assert any(a['artifact_type'] == 'figure' and a['path'].endswith('curve-report.png') for a in index)


def test_failed_and_unattempted_specifications_are_not_dropped(tmp_path):
    from tests.test_data_column_cast import _source_project
    from workbench.artifacts import register_artifact, write_json
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow, WorkflowExecutionError
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    project, run, source = _source_project(tmp_path, series())
    run_root = project / 'runs' / run
    write_json(run_root / 'artifacts_index.json', {'schema_version': 1, 'artifacts': []})
    register_artifact(run_root, source, run_root / 'data.csv', 'raw_data', 'ingestion', [])
    draft = compile_workflow(workflow_id='failed-set',
        target={'run_id': run, 'node_ref': 'stage:source', 'artifact_id': source},
        preconditions={'context_fingerprint': 'source'}, steps=[{'step_id': label, 'operation_id': 'time_series.arima',
            'spec': {'input_mode': 'frame', 'column_bindings': {'time': 'time', 'value': 'y'},
                     'options': {'time_order': 'declared_monotonic', 'order': [p, 0, 0], 'trend': 'c'}}}
            for label,p in [('first',1),('failed',2),('unattempted',3)]], available_columns=['time','y'])
    real = build_workflow_step_executor(project, draft)
    def execute(step, previous):
        if step.step_id == 'failed':
            raise WorkflowExecutionError('recorded singular specification')
        return real(step, previous)
    state = WorkflowExecutor(project).execute(draft, execute)
    assert state.status == 'failed'
    curve, _ = report_curve(project, 'failed-set', 'ar.L1')
    assert [row['step_id'] for row in curve['rows']] == ['first', 'failed', 'unattempted']
    assert [row['status'] for row in curve['rows']] == ['estimated', 'failed', 'pending']
    assert 'singular' in curve['rows'][1]['reason']
    assert curve['rows'][1]['estimate'] is None and curve['rows'][2]['estimate'] is None


def test_curve_is_embedded_in_standalone_html_and_pdf_and_numeric_xlsx(tmp_path):
    from openpyxl import load_workbook
    project, _, _ = products(tmp_path, series())
    curve, run = report_curve(project, 'native-arima', 'ar.L1')
    html = (run / 'reports/curve-report.html').read_text()
    assert 'data:image/png;base64,' in html and 'Specification curve' in html
    for row in curve['rows']:
        assert str(row['estimate']) in html
    workbook = load_workbook(run / 'exports/curve-report.xlsx', data_only=True)
    assert 'specification_curve' in workbook.sheetnames
    rows = list(workbook['specification_curve'].values)
    estimate_index = rows[0].index('estimate')
    for actual, expected in zip(rows[1:], curve['rows'], strict=True):
        assert actual[estimate_index] == pytest.approx(expected['estimate'], abs=1e-14)
    pdf = (run / 'reports/curve-report.pdf').read_bytes()
    assert b'/Subtype /Image' in pdf


def test_missing_term_retains_unverified_rows_without_invented_zeroes(tmp_path):
    from workbench.agent.specification_curves import collect_curve
    project, contract, _ = products(tmp_path, series())
    curve = collect_curve(project, contract['source'], {'workflow_id': 'native-arima',
        'term': 'not_a_fitted_term', 'estimand': 'unavailable'})
    assert len(curve['rows']) == 2
    assert all(r['status'] == 'unverified' and r['estimate'] is None for r in curve['rows'])


def test_changed_frozen_set_cannot_be_reinterpreted_after_results(tmp_path):
    from workbench.agent.specification_curves import collect_curve
    from workbench.agent.workflow import WorkflowExecutionError
    project, contract, _ = products(tmp_path, series())
    path = project / 'workbench/workflows/native-arima.plan.json'
    snapshot = json.loads(path.read_text())
    snapshot['draft']['steps'].pop()
    path.write_text(json.dumps(snapshot))
    with pytest.raises(WorkflowExecutionError, match='changed'):
        collect_curve(project, contract['source'], {'workflow_id': 'native-arima', 'term': 'ar.L1', 'estimand': 'AR'})
