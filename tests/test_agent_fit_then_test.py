"""Fit within a single authorized plan, then read its persisted inference."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import pytest
from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import WorkflowExecutor, WorkflowExecutionError, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor, collect_post_estimation_results
from workbench.agent.read_only_policy import decide
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes

DATA = Path(__file__).parent / 'fixtures/postestimation/data.csv'
ORACLE = json.loads((DATA.parent / 'oracle.json').read_text())['families']['ols']

def _steps():
    return [
        {'step_id': 'full', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'ols', 'covariance': 'unadjusted',
            'branches': [{'branch_id': 'full', 'outcome': 'y', 'predictors': ['x1','x2','x3']}]}},
        {'step_id': 'restricted', 'operation_id': 'model.genesis', 'spec': {
            'model_family': 'ols', 'covariance': 'unadjusted',
            'branches': [{'branch_id': 'restricted', 'outcome': 'y', 'predictors': ['x1']}]}},
        {'step_id': 'lr', 'operation_id': 'postestimation.lr', 'spec': {
            'model_ref': 'step:full:full', 'restricted_model_ref': 'step:restricted:restricted'}},
    ]

def _compile(steps, run_id='run_source', artifact='source_data'):
    return compile_workflow(workflow_id='wf-fit-then-test',
        target={'run_id':run_id,'node_ref':'stage:source','artifact_id':artifact},
        preconditions={'context_version':'node-operation-context/v1',
            'context_fingerprint':'sha256:fit-then-test','active_head_run_id':run_id,
            'owner_resolution':'single_candidate'}, steps=steps,
        available_columns=list(pd.read_csv(DATA).columns))

def _project(tmp_path):
    frame=pd.read_csv(DATA)
    root, run_id, artifact=_source_project(tmp_path,frame)
    upload=store_upload_bytes(root,DATA.read_bytes(),filename='data.csv')
    write_run_inputs(root/'runs'/run_id,form={'model_type':'auto','y':'','x':''},
        upload={'sha256':upload,'filename':'data.csv'},rerun_of=None,from_node=None,
        rerun_reason='initial',override_hash=None,dag_hash='fit-then-test')
    return root, _compile(_steps(),run_id,artifact)

def test_future_model_refs_compile_to_real_dependencies():
    draft=_compile(_steps()[::-1])
    assert draft.steps[-1].step_id=='lr'
    assert set(draft.steps[-1].depends_on)=={'full','restricted'}
    assert not decide('operation.multi_step',{'steps':_steps()},prior_inferential_steps=0).allowed

@pytest.mark.parametrize(('ref','run','message'),[
    ('step:missing:full',None,'unknown step'),
    ('step:restricted:missing',None,'branch'),
    ('step:lr:full',None,'itself'),
    ('step:full:full','forged-run','run'),
])
def test_invalid_future_refs_are_refused_at_compile_time(ref,run,message):
    steps=_steps(); steps[-1]['spec']['model_ref']=ref
    if run: steps[-1]['spec']['model_run_id']=run
    with pytest.raises(OperationValidationError,match=message): _compile(steps)

def test_lr_after_two_fits_reads_new_runs_and_matches_r(tmp_path):
    root,draft=_project(tmp_path)
    state=WorkflowExecutor(root).execute(draft,build_workflow_step_executor(root,draft))
    assert state.status=='completed',{k:s.error for k,s in state.steps.items() if s.error}
    results=collect_post_estimation_results(root,draft.target['run_id'],keep_latest=True)
    result=next(r['result'] for r in results if r['result'].get('operation')=='lr')
    expected=ORACLE['lr_drop_x2_x3']
    assert result['statistic']==pytest.approx(expected['statistic'],abs=1e-9)
    assert result['df']==expected['df']
    assert result['p_value']==pytest.approx(expected['p_value'],rel=1e-9)
    branches=state.steps['full'].model_branches
    assert branches[0]['model_id']=='ols_1'
    assert result['model_run_id']==branches[0]['run_id']
    assert branches[0]['run_id']!=draft.target['run_id']

def test_resume_retains_fitted_bindings_without_refitting(tmp_path):
    root,draft=_project(tmp_path); real=build_workflow_step_executor(root,draft)
    def interrupted(step,previous):
        if step.step_id=='lr': raise WorkflowExecutionError('simulated interruption')
        return real(step,previous)
    first=WorkflowExecutor(root).execute(draft,interrupted)
    assert first.steps['full'].status=='completed'
    calls=[]; fresh=build_workflow_step_executor(root,draft)
    def counting(step,previous): calls.append(step.step_id); return fresh(step,previous)
    resumed=WorkflowExecutor(root).execute(draft,counting)
    assert resumed.status=='completed',{k:s.error for k,s in resumed.steps.items() if s.error}
    assert calls==['lr']
    assert resumed.steps['full'].artifact_ids==first.steps['full'].artifact_ids

def test_future_reference_to_a_non_model_producer_is_refused():
    steps=_steps(); steps[0]={'step_id':'full','operation_id':'postestimation.wald',
        'spec':{'model_ref':'model:ols_1','constraints':[{'terms':{'x1':1},'value':0}]}}
    with pytest.raises(OperationValidationError,match='does not produce model branches'): _compile(steps)

def test_future_model_dependency_cycle_is_refused():
    steps=_steps(); steps[0]['depends_on']=['lr']
    with pytest.raises(OperationValidationError,match='cycle'): _compile(steps)

def test_lr_contract_explains_variance_refits_and_original_wald_alternative():
    from workbench.agent.postestimation_steps import postestimation_step_contracts
    text=postestimation_step_contracts()['postestimation.lr'].summary
    assert 'Wald' in text and 'original' in text and 'explain' in text.lower()
    assert 'Do not automatically add' in text

@pytest.mark.parametrize('tamper',['checksum','incomplete','missing_binding'])
def test_future_model_binding_is_not_guessed_when_evidence_changes(tmp_path,tamper):
    root,draft=_project(tmp_path); real=build_workflow_step_executor(root,draft)
    previous={step.step_id:real(step,{}) for step in draft.steps[:2]}
    branch=previous['full'].payload['branches'][0]
    if tamper=='checksum':
        path=root/'runs'/branch['run_id']/'model_results/inference_kernels/ols_1.json'
        path.write_text(path.read_text()+'\n')
    elif tamper=='incomplete':
        path=root/'runs'/branch['run_id']/'run_manifest.json'
        value=json.loads(path.read_text());value['status']='running';path.write_text(json.dumps(value))
    else:
        branch.pop('model_id')
    with pytest.raises(WorkflowExecutionError): real(draft.steps[-1],previous)

def test_wald_after_fit_preserves_the_declared_robust_covariance(tmp_path):
    root,draft=_project(tmp_path)
    steps=_steps()[:1];steps[0]['spec']['covariance']='robust'
    steps.append({'step_id':'wald','operation_id':'postestimation.wald','spec':{
        'model_ref':'step:full:full','constraints':[{'terms':{'x1':1},'value':0},{'terms':{'x2':1},'value':0}]}})
    draft=_compile(steps)
    state=WorkflowExecutor(root).execute(draft,build_workflow_step_executor(root,draft))
    assert state.status=='completed',{k:s.error for k,s in state.steps.items() if s.error}
    result=next(r['result'] for r in collect_post_estimation_results(root,draft.target['run_id'],keep_latest=True)
                if r['result'].get('operation')=='wald')
    from workbench.postestimation import wald_test
    branch=state.steps['full'].model_branches[0]
    kernel=json.loads((root/'runs'/branch['run_id']/'model_results/inference_kernels/ols_1.json').read_text())
    assert kernel['covariance_estimator']=='HC1'
    expected=wald_test(kernel,steps[-1]['spec']['constraints'])
    assert result['statistic']==expected['statistic']
    reference=ORACLE if kernel['covariance_estimator']=='nonrobust' else json.loads((DATA.parent/'oracle.json').read_text())['families']['ols_robust']
    assert result['statistic']==pytest.approx(reference['wald_joint']['statistic'],abs=1e-8)
    assert result['p_value']==pytest.approx(reference['wald_joint']['p_value'],rel=1e-8)

@pytest.mark.parametrize('language',['zh','en'])
def test_server_proposal_reply_retains_the_lr_reason_and_wald_choice(language):
    from workbench.agent.turn_messages import proposal_summary
    reply=proposal_summary({'operation_id':'operation.multi_step','changes':{'steps':_steps()}},language)
    assert 'Wald' in reply
    assert ('似然' in reply and '原模型' in reply) if language=='zh' else ('likelihood' in reply and 'original' in reply)
