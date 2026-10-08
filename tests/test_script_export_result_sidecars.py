"""Actual persisted result assets, never expected values as computed results."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import pandas as pd
import pytest
from workbench.contracts.common.envelope import thaw_json
from workbench.econometrics.runner import run_ols
from workbench.postestimation.registry import run_operation
from workbench.script_export.plan import LANGUAGES,ScriptPlan,ScriptStep,ScriptSnapshot,ScriptExportRefusal
from workbench.script_export.result_snapshot import ResultSnapshotRef,result_snapshot_binding,build_result_snapshot
from test_script_export_data_oracles import fresh_directory,source,execute
from test_script_export_render import renderer
from test_script_export_survey_oracles import executed_oracle,FIXTURES,BACKEND


def model_values(actual):
    coefficients=actual['coefficients'];df=actual['survey_design']['inference_degf']
    return {'nobs':actual['nobs'],'coefficients':{k:v['estimate'] for k,v in coefficients.items()},
            'std_errors':{k:v['std_error'] for k,v in coefficients.items()},
            'statistics':{k:{'value':v['estimate']/v['std_error'],'df':df,'df_denominator':None,'p_value':v['p_value'],'distribution':'t'} for k,v in coefficients.items()}}


def post_values(actual):
    return {'nobs':None,'coefficients':{},'std_errors':{},'statistics':{'test':{
        'value':actual['statistic'],'df':actual['df_num'],'df_denominator':actual['df_den'],
        'p_value':actual['p_value'],'distribution':actual['distribution']}}}


def assets(directory):
    (directory/'case.json').write_text(json.dumps({'case':os.environ.get('PYTEST_CURRENT_TEST'),'supplier_sha256':hashlib.sha256((BACKEND/'workbench/script_export/result_snapshot.py').read_bytes()).hexdigest()}))
    frame=pd.read_csv(FIXTURES/'design.csv')
    # A replicate design is executed by Workbench but not reproduced natively,
    # so its numbers must come from the sidecar (FPC linearization is native
    # since v1.8.11 and would no longer exercise it).
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_replicate_type':'jackknife','survey_df':'design'}
    expected,kernel,primary=executed_oracle(frame,design)
    parameters={'model_type':'ols','y':'y','x':['x1','x2'],'categorical_x':[],
                'covariance':'survey_design','weights':{'kind':'sampling','column':'weight'},'model_options':{'survey_design':design}}
    snapshot_path=directory/'completed.csv';frame.to_csv(snapshot_path,index=False)
    snapshot=ScriptSnapshot(snapshot_path.name,'csv',hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),len(frame),tuple(frame.columns))
    model=ScriptStep('completed','model','model.ols',parameters,('source',),expected=expected,snapshot=snapshot,label='Sampling OLS completed in Workbench')
    spec={'constraints':[{'terms':{'x1':1},'value':.2},{'terms':{'x2':1},'value':0}]}
    actual_post=run_operation('wald',[kernel],spec)
    post=ScriptStep('post','postestimation','postestimation.wald',{**spec,'models':['completed']},('completed',),expected={'statistics':post_values(actual_post)['statistics']},label='Actual persisted design Wald')
    subset=ScriptStep('selected','data_operation','data.subset',{'columns':['y','x1','x2']},('post',),expected={'nrows':len(frame),'columns':['y','x1','x2']})
    independent,fit=run_ols(frame,'y',['x1','x2'],False,'independent')
    native_expected={'nobs':independent['nobs'],'coefficients':{k:v['estimate'] for k,v in independent['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in independent['coefficients'].items()}}
    native=ScriptStep('independent','model','model.ols',{'model_type':'ols','y':'y','x':['x1','x2'],'covariance':'unadjusted'},('selected',),expected=native_expected)
    plan=ScriptPlan('sidecar','executed',(source(directory,frame,'data.csv','source'),),(model,post,subset,native),'1.8.11','f'*64)
    refs={}
    for step,actual,projector in ((model,primary,model_values),(post,actual_post,post_values)):
        path=directory/(step.step_id+'_artifact.json');path.write_text(json.dumps(actual))
        raw=build_result_snapshot(path,binding=result_snapshot_binding(plan,step),artifact_id=step.step_id+':actual',result_contract='Workbench executed result',projector=projector)
        name=step.step_id+'_result.json';(directory/name).write_bytes(raw)
        refs[step.step_id]=ResultSnapshotRef(name,hashlib.sha256(raw).hexdigest())
    return plan,refs


@pytest.mark.parametrize('language',LANGUAGES)
def test_actual_model_post_closure_then_independent_native_model(language,monkeypatch):
    directory=fresh_directory();plan,refs=assets(directory)
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    exported=renderer()(plan,language,result_snapshots=refs)
    assert [e.status for e in exported.coverage]==['snapshot','snapshot','native','native']
    assert 'sidecar' in exported.coverage[0].note and 'sidecar' in exported.coverage[1].note
    code,output=execute(exported,directory,plan)
    assert code==0,output
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,result_snapshots=refs,require_native=True)
    assert caught.value.code=='NOT_FULLY_NATIVE'
    assert caught.value.steps==('completed','post')


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('tamper',('bytes','identity','duplicates','symlink','oversize','schema','expected','post_expected'))
def test_result_asset_tampering_or_poisoned_expected_exits_nonzero(language,tamper,monkeypatch):
    directory=fresh_directory();plan,refs=assets(directory)
    path=directory/refs['completed'].filename
    if tamper=='bytes':path.write_bytes(path.read_bytes()+b' ')
    elif tamper=='identity':
        payload=json.loads(path.read_bytes());payload['binding']['run_id']='wrong';path.write_text(json.dumps(payload))
    elif tamper=='duplicates':path.write_bytes(path.read_bytes()[:-1]+b',"schema_version":1}')
    elif tamper=='schema':
        payload=json.loads(path.read_bytes());payload['values']['std_errors']['x1']=-1;path.write_text(json.dumps(payload))
    elif tamper=='symlink':
        saved=directory/'symlink_target.json';shutil.copyfile(path,saved)
        link=directory/'symlink.json';link.symlink_to(saved)
        refs['completed']=ResultSnapshotRef(link.name,refs['completed'].sha256)
    elif tamper=='oversize':path.write_bytes(b' '*((16*1024*1024)+1))
    elif tamper in {'expected','post_expected'}:
        index=0 if tamper=='expected' else 1;step=plan.steps[index];expected=thaw_json(step.expected)
        if index==0:expected['coefficients']['x1']=99.
        else:expected['statistics']['test']['value']=99.
        steps=list(plan.steps);steps[index]=replace(step,expected=expected);plan=replace(plan,steps=tuple(steps))
    if tamper in {'identity','duplicates','schema','oversize'}:
        refs['completed']=replace(refs['completed'],sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    exported=renderer()(plan,language,result_snapshots=refs)
    code,output=execute(exported,directory,plan)
    assert code!=0,output


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('invalid',('unknown','type','unconsumed','missing_model','missing_post'))
def test_result_reference_admission_rejects_unused_or_missing_assets(language,invalid):
    directory=fresh_directory();plan,refs=assets(directory)
    if invalid=='unknown':refs['unknown']=refs['completed']
    elif invalid=='type':refs['completed']={'filename':'bad.json'}
    elif invalid=='unconsumed':refs['independent']=refs['completed']
    elif invalid=='missing_model':refs.pop('completed')
    else:refs.pop('post')
    with pytest.raises(ScriptExportRefusal):renderer()(plan,language,result_snapshots=refs)


@pytest.mark.parametrize('language',LANGUAGES)
def test_no_sidecar_argument_retains_old_refusal(language):
    directory=fresh_directory();plan,refs=assets(directory)
    with pytest.raises(ScriptExportRefusal) as old:renderer()(plan,language)
    with pytest.raises(ScriptExportRefusal) as explicit:renderer()(plan,language,result_snapshots=None)
    assert explicit.value.code==old.value.code=='SNAPSHOT_CANNOT_REPRODUCE_MODEL_NUMBERS'


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('expect_numeric',(False,True))
def test_nullable_contract_probe_preserves_raw_distribution(language,expect_numeric,monkeypatch):
    """Synthetic nullable projection tests the parser, not a new estimator."""
    directory=fresh_directory();plan,refs=assets(directory)
    artifact=directory/'post_artifact.json';actual=json.loads(artifact.read_text())
    probe={'value':None,'df':None,'df_denominator':None,'p_value':None,'distribution':'Recorded custom reference label'}
    actual['nullable_contract_probe']=probe;artifact.write_text(json.dumps(actual))
    expected=thaw_json(plan.steps[1].expected);expected['statistics']['probe']=dict(probe)
    if expect_numeric:expected['statistics']['probe']['value']=3.
    steps=list(plan.steps);steps[1]=replace(steps[1],expected=expected);plan=replace(plan,steps=tuple(steps))
    def projector(value):
        values=post_values(value);values['statistics']['probe']=value['nullable_contract_probe'];return values
    raw=build_result_snapshot(artifact,binding=result_snapshot_binding(plan,plan.steps[1]),artifact_id='post:parser-probe',result_contract='nullable-parser-probe',projector=projector)
    ref=refs['post'];(directory/ref.filename).write_bytes(raw);refs['post']=replace(ref,sha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    exported=renderer()(plan,language,result_snapshots=refs)
    if expect_numeric:
        # The generic numerical trace assumes a numeric actual. Disable only
        # that optional trace for an intentionally NULL actual; keep every
        # generated runtime assertion and capture its real exit unchanged.
        exported=replace(exported,text=exported.text.replace('Closing self-checks','Closing nullable self-checks'))
    code,output=execute(exported,directory,plan)
    assert (code==0)==(not expect_numeric),output


@pytest.mark.parametrize('language',LANGUAGES)
def test_result_runtime_missing_declared_dependency_fails_explicitly(language,monkeypatch):
    directory=fresh_directory();plan,refs=assets(directory)
    exported=renderer()(plan,language,result_snapshots=refs)
    assert 'workbench' in exported.required_packages
    if language=='python':text=exported.text.replace('from workbench.script_export.result_snapshot import','from wb_missing_result_dependency import')
    else:
        assert 'python3' in exported.required_packages
        text=exported.text.replace('python3','wb_missing_python_bridge')
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(replace(exported,text=text),directory,plan)
    assert code!=0,output


@pytest.mark.parametrize('language',LANGUAGES)
def test_none_sidecars_preserve_basic_program_except_native_reader_corrections(language):
    path=Path(__file__).parent/'fixtures/script_export/validated_basic/plan.json'
    plan=ScriptPlan.from_dict(json.loads(path.read_text()))
    exported=renderer()(plan,language,result_snapshots=None)
    baseline=Path(__file__).parent/f'fixtures/script_export/sidecar_none_baseline_92c90b59/analysis.{language}'
    text=exported.text
    if language=='stata':
        # Retain the old snapshot; only the reviewed CSV reader correction may differ.
        correction=' bindquotes(strict) maxquotedrows(unlimited)'
        assert text.count(correction)==1
        text=text.replace(correction,'')
    if language=='r':
        import re
        for label in ['double parser','CSV double precision']:
            text,count=re.subn(r'^# Native '+label+r'\n.*?^# End native '+label+r'\n','',text,flags=re.M|re.S)
            assert count==1
        text,count=re.subn(r'^data\[\[.*?\]\] <- wb_csv_precision\(.*\)\n','',text,flags=re.M)
        assert count==1
    if language=='python':
        # Reviewed v1.8.12 correction (V1811-PUBLIC-TERM-QUOTE): wb_public decodes the Q() literal.
        corrected='''import ast
import statsmodels.formula.api as smf
from scipy import stats

def wb_public(name):
    # Q(<string literal>) names a column; the literal may use either quote and escapes.
    if name.startswith("Q(") and name.endswith(")"):
        try:
            column = ast.literal_eval(name[2:-1])
        except (ValueError, SyntaxError):
            return name
        if isinstance(column, str):
            return column
    return name
'''
        original='''import statsmodels.formula.api as smf
from scipy import stats

def wb_public(name):
    if name.startswith("Q('") and name.endswith("')"):
        return name[3:-2]
    return name
'''
        assert text.count(corrected)==1
        text=text.replace(corrected,original)
    assert text==baseline.read_text()
    assert exported==renderer()(plan,language)


@pytest.mark.parametrize('language',LANGUAGES)
def test_require_native_rejects_completed_closure_without_loading_assets(language):
    directory=fresh_directory();plan,refs=assets(directory)
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,result_snapshots={},require_native=True)
    assert caught.value.code=='NOT_FULLY_NATIVE'
    assert caught.value.steps==('completed','post')


@pytest.mark.parametrize('language',LANGUAGES)
def test_independent_native_model_postestimation_retains_real_fit_state(language,monkeypatch):
    from workbench.contracts.model.inference_kernel import build_inference_kernel
    directory=fresh_directory();plan,refs=assets(directory)
    frame=pd.read_csv(directory/'data.csv');actual,fit=run_ols(frame,'y',['x1','x2'],False,'independent')
    kernel=build_inference_kernel(model_id='independent',model_type='ols',param_names=list(actual['coefficients']),params=fit.params,vcov=fit.cov_params(),reference_distribution='t',df_resid=fit.df_resid,nobs=int(fit.nobs),covariance_estimator='nonrobust',loglik=fit.llf)
    spec={'terms':{'x1':1,'x2':2},'constant':-.5}
    result=run_operation('lincom',[kernel],spec)
    from test_script_export_postestimation_oracles import expected_from
    native_post=ScriptStep('native_post','postestimation','postestimation.lincom',{**spec,'models':['independent']},('independent',),expected=expected_from(result))
    plan=replace(plan,steps=(*plan.steps,native_post))
    exported=renderer()(plan,language,result_snapshots=refs)
    assert exported.coverage[-1].status=='native'
    if language=='stata':
        assert 'estimates store wb_model1' not in exported.text
        assert 'estimates store wb_model2' not in exported.text
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(exported,directory,plan)
    assert code==0,output
