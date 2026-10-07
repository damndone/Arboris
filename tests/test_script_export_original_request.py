"""Reindexed test evidence must retain the original compiled model owner."""
import pytest
from fastapi.testclient import TestClient

from test_script_export_lineage_builder import data_path, model_path, wald_path, finished
from test_script_export_public_integrity import clone, reindex_json, require_refusal
from workbench.app import app
from workbench.artifacts import read_json
from workbench.postestimation.registry import run_operation
from workbench.script_export.builder import build_script_plan


def test_changed_model_owner_cannot_hide_behind_original_wald_request(wald_path, tmp_path):
    model, artifact_id = wald_path
    project, run_id, data = clone(model, tmp_path)
    source_run, derived = data[1], data[3]
    with TestClient(app) as client:
        response = client.post('/data-operations/model-run', params={'project_root': str(project)}, json={
            'source_run_id': source_run, 'source_node_id': derived.child_node_id, 'source_artifact_id': derived.artifact_id,
            'model_type': 'ols', 'y': 'y', 'x': ['x', 'z', 'xz'], 'covariance': 'unadjusted'})
        assert response.status_code == 200, response.text
        changed_run = response.json()['run_id']
        finished(client, project, changed_run)
    assert build_script_plan(project, changed_run, 'model:ols_1').plan.steps[-1].parameters['covariance'] == 'unadjusted'
    root = project / 'runs' / run_id
    changed_root = project / 'runs' / changed_run
    kernel = read_json(changed_root / 'model_results/inference_kernels/ols_1.json')
    relative = next(item['path'] for item in read_json(root / 'artifacts_index.json')['artifacts']
                    if item['artifact_id'] == artifact_id)
    state_path = project / 'workbench/workflows/wf-script-cluster-wald.jsonl'
    original_state = state_path.read_bytes()
    original_execution = read_json(root / relative)['execution']
    # Resolve the new dataset through its real server registry, not a guessed path.
    record = next(item for item in read_json(changed_root / 'artifacts_index.json')['artifacts']
                  if item['artifact_id'] == 'cleaned_dataset')
    def actual_change(payload):
        payload['source']['model_run_id'] = changed_run
        payload['source']['sha256'] = record['sha256']
        payload['result'].update(run_operation('wald', [kernel], original_execution['steps'][0]['spec'], {}))
        payload['result']['model_run_id'] = changed_run
    reindex_json(root, relative, actual_change)
    assert state_path.read_bytes() == original_state
    assert read_json(root / relative)['execution'] == original_execution
    require_refusal('wald_changed_model_owner_unchanged_request', project, run_id, 'artifact:' + artifact_id)


@pytest.fixture(scope='module')
def fitted_lr_path(model_path):
    from workbench.agent.workflow import compile_workflow, WorkflowExecutor
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    project, run_id, _ = model_path
    steps = [
        {'step_id': 'full', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'ols', 'covariance': 'unadjusted',
            'branches': [{'branch_id': 'full', 'outcome': 'y', 'predictors': ['x', 'z', 'xz']}]}},
        {'step_id': 'restricted', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'ols', 'covariance': 'unadjusted',
            'branches': [{'branch_id': 'restricted', 'outcome': 'y', 'predictors': ['x']}]}},
        {'step_id': 'lr', 'operation_id': 'postestimation.lr', 'spec': {
            'model_ref': 'step:full:full', 'restricted_model_ref': 'step:restricted:restricted'}},
    ]
    draft = compile_workflow(workflow_id='wf-script-fit-then-lr',
        target={'run_id':run_id, 'node_ref':'stage:cleaned', 'artifact_id':'cleaned_dataset'},
        preconditions={'context_version':'node-operation-context/v1',
            'context_fingerprint':'sha256:script-fit-then-lr', 'active_head_run_id':run_id,
            'owner_resolution':'single_candidate'}, available_columns=['g','x','z','xz','y','keep'], steps=steps)
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed', {key:step.error for key,step in state.steps.items() if step.error}
    return project, run_id, state.steps['lr'].artifact_ids[0]


@pytest.mark.parametrize('language', ['stata', 'r', 'python'])
def test_completed_step_model_bindings_export_two_fits_and_lr(fitted_lr_path, language, monkeypatch):
    from test_script_export_executed_parameters import execute_completed_owner
    project, run_id, artifact_id = fitted_lr_path
    plan = build_script_plan(project, run_id, 'artifact:'+artifact_id).plan
    assert plan.steps[-1].operation == 'postestimation.lr'
    assert len(plan.steps[-1].parameters['models']) == 2
    assert plan.steps[-1].expected['statistics']['test']['df'] == 2
    execute_completed_owner(project, run_id, 'artifact:'+artifact_id, language, monkeypatch)
