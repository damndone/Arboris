"""Independent public GLM-NB entry, native alpha sweep, and provenance attacks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.admission import ADMISSION_EVIDENCE, PLANNED
from workbench.api import app
from workbench.artifacts import read_json, write_json
from workbench.agent.postestimation_steps import execute_postestimation_step, postestimation_step_contracts
from workbench.agent.workflow import WorkflowExecutionError, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.postestimation.registry import validated_operations
from workbench.projects import create_project

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'tests/fixtures/postestimation/data.csv'
NATIVE = Path(__file__).with_name('glm_nb_public_review_native.json')
SPECS = {
    'wald': {'constraints': [{'terms': {'x2': 1, 'x3': 1}, 'value': 0}]},
    'lincom': {'terms': {'x2': 1, 'x3': -.3}, 'constant': .2},
    'nlcom': {'expression': 'exp(x3)'},
    'margins_average': {'variables': ['x3'], 'at': 'average'},
    'margins_means': {'variables': ['x3'], 'at': 'means'},
    'lr': {},
}


@pytest.fixture(scope='module')
def owners(tmp_path_factory):
    base = tmp_path_factory.mktemp('glm-nb-public-independent')
    client = TestClient(app)
    response = client.post('/projects', json={'parent': str(base), 'name': 'native-owner'})
    assert response.status_code == 200
    project = Path(response.json()['project_root']); runs = {}
    for alpha in [.5, 1., 2.]:
        for role, x in [('full', ['x1', 'x2', 'x3']), ('restricted', ['x1'])]:
            reply = client.post('/runs', data={'project_root': str(project), 'mode': 'auto',
                'model_type': 'glm:negative_binomial', 'y': 'ynb', 'x': json.dumps(x),
                'model_options': json.dumps({'alpha': alpha})},
                files={'file': (DATA.name, DATA.read_bytes(), 'text/csv')})
            assert reply.status_code == 200, reply.text
            run_id = reply.json()['run_id']; deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                detail = client.get('/runs/'+run_id, params={'project_root': str(project)}).json()
                if detail.get('status') in {'completed','failed','partial','blocked'}: break
                time.sleep(.05)
            assert detail['status'] == 'completed', detail
            root = project / 'runs' / run_id
            packet = read_json(root/'model_results/glm_1.json')
            kernel = read_json(root/kernel_relative_path('glm_1'))
            assert packet['alpha_fixed_value'] == alpha and not packet['alpha_estimated']
            assert kernel['model_type'] == 'glm:negative_binomial'
            assert kernel['reference_distribution'] == 'z'
            assert set(kernel['param_names']) == {'Intercept', *x}
            print(json.dumps({'http_owner': str(root), 'alpha': alpha, 'role': role,
                'kernel_sha256': hashlib.sha256((root/kernel_relative_path('glm_1')).read_bytes()).hexdigest()}))
            runs[(alpha,role)] = root
    return client, project, runs


def execute_agent(project, target, operation, spec, *, label):
    draft = compile_workflow(workflow_id='glm-nb-independent-'+label,
        target={'run_id': target.name, 'node_ref': 'stage:cleaned', 'artifact_id': 'cleaned_dataset'},
        preconditions={'context_fingerprint': 'sha256:glm-nb-independent',
            'context_version': 'node-operation-context/v1', 'active_head_run_id': target.name,
            'owner_resolution': 'single_candidate'},
        available_columns=list(pd.read_csv(DATA).columns),
        steps=[{'step_id': label, 'operation_id': 'postestimation.'+operation,
            'spec': {'model_ref': 'model:glm_1', **spec}}])
    step = draft.steps[0]
    result = build_workflow_step_executor(project,draft)(step,{})
    return result


@pytest.mark.parametrize('alpha', [.5,1.,2.])
@pytest.mark.parametrize('case', list(SPECS))
def test_http_completed_owners_and_agent_operations_match_fresh_native_r(owners,alpha,case):
    client,project,runs = owners; root = runs[(alpha,'full')]
    operation = 'margins' if case.startswith('margins_') else case
    spec = dict(SPECS[case])
    if operation == 'lr': spec.update(restricted_model_ref='model:glm_1',
        restricted_model_run_id=runs[(alpha,'restricted')].name)
    step_result = execute_agent(project,root,operation,spec,label=case+'_'+str(alpha).replace('.','_'))
    actual = step_result.payload['result']
    reference = read_json(NATIVE)['full_precision'][str(alpha).removesuffix('.0')]
    expected = reference['margins'][case.removeprefix('margins_')] if operation == 'margins' else reference[operation]
    numeric = actual['effects'][0] if operation == 'margins' else actual
    for key in ['statistic','estimate','std_error','loglik_full','loglik_restricted']:
        if key in expected:
            assert numeric[key] == pytest.approx(float(expected[key]),rel=1e-5 if key=='std_error' and operation=='margins' else 1e-6), (alpha,case,key)
    for key in ['p_value','df','df_num']:
        if key in expected:
            assert numeric[key] == pytest.approx(float(expected[key]),rel=1e-5 if key=='p_value' else 0)
    if operation != 'lr': assert actual['model_type'] == 'glm:negative_binomial' and actual['model_id'] == 'glm_1'
    detail = client.get('/runs/'+root.name,params={'project_root':str(project)}).json()
    visible = [row for row in detail['post_estimation_results'] if row['artifact_id'] in step_result.artifact_ids]
    assert len(visible)==1 and visible[0]['model_run_id']==root.name
    assert visible[0]['result'] == actual
    index = read_json(root/'artifacts_index.json')['artifacts']
    record = next(row for row in index if row['artifact_id']==step_result.artifact_ids[0])
    artifact = read_json(root/record['path'])
    assert record['sha256']==hashlib.sha256((root/record['path']).read_bytes()).hexdigest()
    assert artifact['source']['model_run_id']==root.name
    assert artifact['source']['model_artifact_id']=='glm_1'
    dataset = next(row for row in index if row['artifact_id']=='cleaned_dataset')
    assert artifact['source']['sha256']==dataset['sha256']
    json.dumps(actual,allow_nan=False)
    print(json.dumps({'native_public_result':actual,'alpha':alpha,'case':case,'artifact':str(root/record['path'])}))


@pytest.mark.parametrize('full_alpha,restricted_alpha',[(.5,1.),(1.,2.),(2.,.5)])
def test_glm_nb_different_fixed_alpha_public_lr_refuses(owners,full_alpha,restricted_alpha):
    _,project,runs=owners
    with pytest.raises(WorkflowExecutionError,match='different fixed likelihood.*alpha_fixed_value'):
        execute_agent(project,runs[(full_alpha,'full')],'lr',{'restricted_model_ref':'model:glm_1',
            'restricted_model_run_id':runs[(restricted_alpha,'restricted')].name},label='different_alpha_'+str(full_alpha).replace('.','_'))


@pytest.mark.parametrize('term',['alpha','lnalpha'])
@pytest.mark.parametrize('operation',['wald','lincom','nlcom','margins'])
def test_auxiliary_parameter_is_not_a_beta_or_margin_variable(owners,term,operation):
    _,project,runs=owners
    spec={'wald':{'constraints':[{'terms':{term:1},'value':0}]},'lincom':{'terms':{term:1}},
        'nlcom':{'expression':'exp('+term+')'},'margins':{'variables':[term]}}[operation]
    with pytest.raises(WorkflowExecutionError,match='coefficient|parameter|Unknown|unknown|regressor'):
        execute_agent(project,runs[(1.,'full')],operation,spec,label='bad_'+term+'_'+operation)


def test_capabilities_derive_from_validated_declaration_without_certifying_live_eval(monkeypatch):
    from workbench.agent import postestimation_steps
    from workbench.agent.workflow_contracts import workflow_step_vocabulary
    offered=set(validated_operations('glm:negative_binomial'))
    assert offered=={'wald','lincom','nlcom','lr','margins'}
    contracts=postestimation_step_contracts()
    vocabulary=workflow_step_vocabulary()['step_operations']
    for operation in offered:
        key='postestimation.'+operation
        assert 'glm:negative_binomial' in contracts[key].summary
        assert key in vocabulary
        assert contracts[key].dispatcher_key=='workbench.agent.workflow_runtime.postestimation'
    reduced={pair:value for pair,value in postestimation_steps.VALIDATED.items() if pair[0]!='glm:negative_binomial'}
    monkeypatch.setattr(postestimation_steps,'VALIDATED',reduced)
    assert all('glm:negative_binomial' not in value.summary for value in postestimation_step_contracts().values())
    assert any(item.fixture.endswith('glm_negative_binomial_v1811/native-r/oracle.json')
        for item in ADMISSION_EVIDENCE['glm:negative_binomial']['oracle'])
    assert not ADMISSION_EVIDENCE['glm:negative_binomial']['live_eval']
    assert PLANNED['glm:negative_binomial']['live_eval']=='v1.8.11'


@pytest.mark.parametrize('asset',['kernel','processed','diagnostic','completion'])
def test_glm_nb_margins_refuses_changed_owner_provenance_without_restoring_mutant(tmp_path,owners,asset):
    _,_,runs=owners; project=create_project(tmp_path,'mutant').root
    original=runs[(2.,'full')];root=project/'runs'/original.name;root.parent.mkdir(exist_ok=True)
    shutil.copytree(original,root)
    path={'kernel':root/kernel_relative_path('glm_1'),'processed':root/'processed/cleaned_dataset.parquet',
        'diagnostic':root/'diagnostic_summary.json','completion':root/'run_manifest.json'}[asset]
    if asset=='processed':
        frame=pd.read_parquet(path);frame.loc[frame.index[0],'x3']+=20.;frame.to_parquet(path)
    elif asset=='completion':
        payload=read_json(path);payload['status']='running';write_json(path,payload)
    else:path.write_bytes(path.read_bytes()+b'\n')
    print(json.dumps({'mutant_owner':str(root),'path':str(path),'mutation':asset,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
    with pytest.raises(WorkflowExecutionError,match='changed|hash|completed|binding|data'):
        execute_agent(project,root,'margins',{'variables':['x3']},label='mutant_'+asset)
