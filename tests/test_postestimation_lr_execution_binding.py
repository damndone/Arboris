"""Public LR must bind actual response, shared inputs and completed owner runs."""
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from workbench.agent.postestimation_steps import execute_postestimation_step
from workbench.agent.workflow import WorkflowExecutionError
from workbench.artifacts import read_json,write_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

DATA=Path(__file__).parent/'fixtures/postestimation/data.csv'

@pytest.fixture(scope='module')
def fitted(tmp_path_factory):
    root=tmp_path_factory.mktemp('lr-binding')
    project=create_project(root,'lr').root
    def fit(source,x):
        result=run_workflow(project,[source],mode='auto',model_type='glm:poisson',y='yc',x=x)
        assert result['status']=='completed',result
        return project/'runs'/result['run_id']
    full=fit(DATA,['x1','x2','x3'])
    restricted=fit(DATA,['x1'])
    changed=pd.read_csv(DATA);changed['x1']=-changed['x1']
    source=root/'changed.csv';changed.to_csv(source,index=False)
    other=fit(source,['x1'])
    return project,full,restricted,other

def compare(project,full,restricted):
    step=SimpleNamespace(operation_id='postestimation.lr',depends_on=(),spec={
        'model_ref':'model:glm_1','restricted_model_ref':'model:glm_1',
        'restricted_model_run_id':restricted.name})
    return execute_postestimation_step(project,full.name,step)[0]

def test_same_response_and_shared_data_still_has_native_validated_lr(fitted):
    project,full,restricted,_=fitted
    result=compare(project,full,restricted)
    oracle=read_json(DATA.parent/'oracle.json')['families']['poisson']['lr_drop_x2_x3']
    assert result['statistic']==pytest.approx(oracle['statistic'],rel=1e-6)

def test_same_rows_and_response_cannot_hide_changed_shared_predictor(fitted):
    project,full,_,other=fitted
    with pytest.raises(WorkflowExecutionError,match='data|input|comparable'):
        compare(project,full,other)

def test_changed_processed_source_bytes_are_not_trusted(fitted):
    project,full,restricted,_=fitted
    path=restricted/'processed/cleaned_dataset.parquet'
    original=path.read_bytes()
    frame=pd.read_parquet(path);frame.loc[frame.index[0],'yc']+=1
    frame.to_parquet(path)
    try:
        with pytest.raises(WorkflowExecutionError,match='changed|fingerprint|hash|data'):
            compare(project,full,restricted)
    finally:
        path.write_bytes(original)

@pytest.mark.parametrize('consumer',['branch','covariance','recorded'])
def test_other_kernel_consumers_refuse_foreign_owner_identity(fitted,consumer):
    from workbench.agent.workflow_runtime import _branch_kernel
    from workbench.agent.context_tools import _executed_covariance
    from workbench.contracts.model.inference_kernel import resolve_inference_kernel,InferenceKernelError,kernel_relative_path
    project,full,_,_=fitted
    path=full/kernel_relative_path('glm_1')
    original=path.read_bytes();foreign=read_json(path);foreign['model_id']='foreign_999'
    if consumer=='recorded':
        with pytest.raises(InferenceKernelError,match='identity|owner|match'):
            resolve_inference_kernel(model_id='glm_1',model_type='glm:poisson',primary={},fitted=None,recorded=foreign)
        return
    write_json(path,foreign)
    try:
        if consumer=='branch':
            with pytest.raises(WorkflowExecutionError,match='identity|owner|match'):
                _branch_kernel(project,{'run_id':full.name,'model_id':'glm_1'})
        else:
            assert _executed_covariance(full,'glm_1') is None
    finally:
        path.write_bytes(original)

def test_changed_diagnostic_input_binding_is_not_trusted(fitted):
    project,full,restricted,_=fitted
    path=full/'diagnostic_summary.json';original=path.read_bytes()
    summary=read_json(path);summary['model_identity']['x_variables']=[]
    write_json(path,summary)
    try:
        with pytest.raises(WorkflowExecutionError,match='changed|hash|binding|data'):
            compare(project,full,restricted)
    finally:
        path.write_bytes(original)

@pytest.mark.parametrize('mutation',['kernel','status'])
def test_public_postestimation_requires_unchanged_kernel_and_completed_owner(fitted,mutation):
    project,full,_,_=fitted
    path=(full/'model_results/inference_kernels/glm_1.json') if mutation=='kernel' else full/'run_manifest.json'
    original=path.read_bytes();payload=read_json(path)
    if mutation=='kernel': payload['params'][1]+=1.
    else: payload['status']='running'
    write_json(path,payload)
    try:
        step=SimpleNamespace(operation_id='postestimation.wald',depends_on=(),spec={
            'model_ref':'model:glm_1','constraints':[{'terms':{'x1':1},'value':0}]})
        with pytest.raises(WorkflowExecutionError,match='changed|completed|hash|binding'):
            execute_postestimation_step(project,full.name,step)
    finally:
        path.write_bytes(original)

def test_margins_reads_the_unchanged_registered_estimation_artifact(fitted):
    project,full,_,_=fitted
    path=full/'processed/cleaned_dataset.parquet';original=path.read_bytes()
    frame=pd.read_parquet(path);frame['x1']+=20.;frame.to_parquet(path)
    try:
        step=SimpleNamespace(operation_id='postestimation.margins',depends_on=(),spec={
            'model_ref':'model:glm_1','variables':['x1'],'at':'means'})
        with pytest.raises(WorkflowExecutionError,match='changed|hash|data'):
            execute_postestimation_step(project,full.name,step)
    finally:
        path.write_bytes(original)
