"""E5: actual uploaded data path, three public ZIPs, snapshot and runtime SHA."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from workbench.api import app
from workbench.projects import create_project
from workbench.data_operations import DataTransformSpecV1, FeatureRecipeOperationSpecV1, apply_data_transform,preview_data_transform,apply_feature_recipe_operation,preview_feature_recipe
from workbench.predictive_research.contracts import FeatureRecipeV1
from workbench.agent.workflow import compile_workflow,WorkflowExecutor
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.script_export.builder import build_script_plan
from workbench.script_export.render import export_script
from workbench.script_export.plan import ScriptExportRefusal
from workbench.script_export.result_snapshot import ResultSnapshotRef
from support import OUT,finished,fit,execute_script,save


def retain(directory,name):
    target=OUT/name;target.mkdir()
    for path in directory.iterdir():
        if path.is_file() and path.suffix!='.log':shutil.copy2(path,target/path.name)
    save(name+'-retention',{'directory':directory,'public':target,'raw_logs_0600':[str(p) for p in directory.glob('*.log')]})


@pytest.fixture(scope='module')
def path_owner(tmp_path_factory):
    temp=tmp_path_factory.mktemp('e05-public');project=create_project(temp,'script').root
    rng=np.random.default_rng(18112090);n=640;x,z=rng.normal(size=(2,n))
    frame=pd.DataFrame({'g':np.repeat(np.arange(20),32),'x':x,'z':z,'keep':np.tile([0,1],n//2),'y':1+.6*x-.2*z+.35*x*z+rng.normal(size=n)})
    source=temp/'public.dta';frame.to_stata(source,write_index=False,value_labels={'keep':{0:'out',1:'in'}})
    with TestClient(app) as client:
        response=client.post('/runs',data={'project_root':str(project),'mode':'auto','model_type':'ols','y':'y','x':'x,z'},files={'file':(source.name,source.read_bytes(),'application/octet-stream')})
        assert response.status_code==200,response.text
        run_id=response.json()['run_id'];finished(client,project,run_id)
    subset=DataTransformSpecV1(source_run_id=run_id,source_node_id='stage:cleaned',source_artifact_id='cleaned_dataset',operation='subset',parameters={'columns':list(frame),'equals':{'keep':1}})
    selected=apply_data_transform(project,subset,preview_data_transform(project,subset))
    recipe=FeatureRecipeV1(recipe_id='e05_multiply',operation_id='derived_variable',operation_version=1,inputs=('x','z'),outputs=('xz',),output_types=('numeric',),parameters={'operator':'multiply'},fit_scope='stateless',source_artifact=selected.artifact_id,lineage_parent=selected.child_node_id)
    spec=FeatureRecipeOperationSpecV1(source_run_id=run_id,source_node_id=selected.child_node_id,source_artifact_id=selected.artifact_id,recipe=recipe)
    derived=apply_feature_recipe_operation(project,spec,preview_feature_recipe(project,spec))
    with TestClient(app) as client:
        response=client.post('/data-operations/model-run',params={'project_root':str(project)},json={'source_run_id':run_id,'source_node_id':derived.child_node_id,'source_artifact_id':derived.artifact_id,'model_type':'ols','y':'y','x':['x','z','xz'],'covariance':'clustered','entity_col':'g'})
        assert response.status_code==200,response.text
        model_run=response.json()['run_id'];finished(client,project,model_run)
    draft=compile_workflow(workflow_id='e05-real-wald',target={'run_id':model_run,'node_ref':'stage:cleaned','artifact_id':'cleaned_dataset'},preconditions={'context_version':'node-operation-context/v1','context_fingerprint':'sha256:e05','active_head_run_id':model_run,'owner_resolution':'single_candidate'},available_columns=[*frame,'xz'],steps=[{'step_id':'joint','operation_id':'postestimation.wald','spec':{'model_ref':'model:ols_1','constraints':[{'terms':{'x':1},'value':0},{'terms':{'xz':1},'value':0}]}}])
    state=WorkflowExecutor(project).execute(draft,build_workflow_step_executor(project,draft))
    assert state.status=='completed'
    return project,model_run,'artifact:'+state.steps['joint'].artifact_ids[0]


@pytest.mark.parametrize('language',['stata','r','python'])
def test_real_public_zip_path_runs_natively_and_changed_source_refuses(path_owner,language,tmp_path):
    project,run,target=path_owner
    with TestClient(app) as client:
        reply=client.post('/runs/'+run+'/script-export',params={'project_root':str(project)},json={'target':target,'language':language,'require_native':True})
        assert reply.status_code==200,reply.text
        summary=reply.json();download=client.get(summary['download_url']);assert download.status_code==200
    built=build_script_plan(project,run,target)
    assert [s.operation for s in built.plan.steps]==['data.cleaning','data.subset','data.feature_recipe','data.cleaning','model.ols','postestimation.wald']
    assert built.plan.steps[-1].expected['statistics']['test']['df_denominator']==19
    directory=tmp_path/'actual';directory.mkdir()
    with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:bundle.extractall(directory)
    exported=export_script(built.plan,language,result_snapshots={},require_native=True)
    assert summary['fully_native'] and all(c.status=='native' for c in exported.coverage)
    code,output=execute_script(exported,directory,built.plan);retain(directory,'e05-native-'+language)
    assert code==0,output
    source=built.plan.sources[0]
    corrupt=tmp_path/'changed';shutil.copytree(directory,corrupt,ignore=shutil.ignore_patterns('*.log','numeric_actual.tsv'))
    (corrupt/source.filename).write_bytes((corrupt/source.filename).read_bytes()+b'forbidden-new-bytes')
    code,output=execute_script(exported,corrupt,built.plan);retain(corrupt,'e05-corrupt-'+language)
    save('e05-'+language,{'summary':summary,'zip_sha256':hashlib.sha256(download.content).hexdigest(),'native_exit':0,'tampered_exit':code,'owner':str(project/'runs'/run)})
    assert code!=0 and ('SHA' in output or 'hash' in output or 'assert' in output.lower()),output


@pytest.fixture(scope='module')
def snapshot_owner(tmp_path_factory):
    temp=tmp_path_factory.mktemp('e05-snapshot');project=create_project(temp,'snapshot').root
    rng=np.random.default_rng(18112091);x,z=rng.normal(size=(2,1000));mu=np.exp(.4+.3*x-.2*z)
    data=temp/'nb1.csv';pd.DataFrame({'y':rng.negative_binomial(mu/.7,1/1.7),'x1':x,'x2':z}).to_csv(data,index=False,float_format='%.17g')
    root,_,_=fit(project,data,'negative_binomial','y',['x1','x2'],model_options={'dispersion':'constant'})
    return project,root.name


@pytest.mark.parametrize('language',['stata','r','python'])
def test_actual_snapshot_continues_but_fully_native_refuses(snapshot_owner,language,tmp_path):
    project,run=snapshot_owner;built=build_script_plan(project,run,'model:negative_binomial_1')
    exported=export_script(built.plan,language,result_snapshots={k:ResultSnapshotRef(name,hashlib.sha256(raw).hexdigest()) for k,(name,raw) in built.result_sidecars.items()})
    assert any(c.status=='snapshot' for c in exported.coverage)
    directory=tmp_path/'snapshot';directory.mkdir()
    for name,raw in built.files.items():(directory/name).write_bytes(raw)
    for name,raw in built.result_sidecars.values():(directory/name).write_bytes(raw)
    code,output=execute_script(exported,directory,built.plan);retain(directory,'e05-snapshot-'+language)
    assert code==0,output
    with pytest.raises(ScriptExportRefusal) as caught:export_script(built.plan,language,result_snapshots={k:ResultSnapshotRef(name,hashlib.sha256(raw).hexdigest()) for k,(name,raw) in built.result_sidecars.items()},require_native=True)
    assert caught.value.code=='NOT_FULLY_NATIVE'
