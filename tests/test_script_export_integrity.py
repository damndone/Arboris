"""Tampering, snapshots, closed syntax and deterministic rendering."""
from dataclasses import replace
import hashlib
import time
import pandas as pd
import pytest
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep, ScriptSnapshot, ScriptExportRefusal
from test_script_export_data_oracles import fresh_directory,execute,source
from test_script_export_render import renderer


def simple_plan(directory):
    s=source(directory,pd.DataFrame({'x':[1.,2.,3.]}),'data.csv','source')
    step=ScriptStep('step','data_operation','data.subset',{'columns':['x'],'filters':[{'column':'x','op':'gt','value':1}]},('source',),expected={'nrows':2,'columns':['x']})
    return ScriptPlan('integrity','run',(s,),(step,),'1.8.11','2'*64)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('tamper',('source','expected'))
def test_tampering_fails_closed(language,tamper):
    directory=fresh_directory();plan=simple_plan(directory)
    if tamper=='expected':plan=replace(plan,steps=(replace(plan.steps[0],expected={'nrows':99,'columns':['x']}),))
    exported=renderer()(plan,language)
    if tamper=='source':(directory/'data.csv').write_text('x\n999\n')
    code,output=execute(exported,directory,plan)
    assert code!=0,output
    assert 'SHA256 mismatch' in output if tamper=='source' else ('nrows' in output or 'assert' in output)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('tamper',('none','sha','nrows','columns'))
def test_snapshot_sha_shape_and_continuation(language,tamper):
    directory=fresh_directory();plan=simple_plan(directory)
    path=directory/'snapshot.csv';pd.DataFrame({'x':[8.,9.]}).to_csv(path,index=False)
    snap=ScriptSnapshot('snapshot.csv','csv',hashlib.sha256(path.read_bytes()).hexdigest(),2,('x',))
    if tamper=='nrows':snap=replace(snap,nrows=3)
    if tamper=='columns':snap=replace(snap,columns=('bad',))
    blocked=ScriptStep('snap','model','model.survival_cox',{},('source',),snapshot=snap,label='Cox completed locally')
    next_step=ScriptStep('next','data_operation','data.subset',{'columns':['x']},('snap',),expected={'nrows':2,'columns':['x']})
    plan=replace(plan,steps=(blocked,next_step))
    exported=renderer()(plan,language)
    assert exported.snapshots_required==('snap',)
    assert 'Cox completed locally' in exported.text
    if tamper=='sha':path.write_text('x\n6\n')
    code,output=execute(exported,directory,plan)
    assert (code==0)==(tamper=='none'),output
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,require_native=True)
    assert caught.value.steps==('snap',)


@pytest.mark.parametrize('language',LANGUAGES)
def test_fifty_steps_deterministic_performance(language):
    directory=fresh_directory();plan=simple_plan(directory)
    steps=tuple(ScriptStep(f'step{i}','data_operation','data.subset',{'columns':['x']},('source',),expected={'nrows':3}) for i in range(50))
    plan=replace(plan,steps=steps)
    start=time.perf_counter();first=renderer()(plan,language);elapsed=time.perf_counter()-start
    assert first.text==renderer()(plan,language).text
    assert elapsed<1
    print(f'{language}: 50 steps {elapsed:.6f}s')


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('bad',('x; shell echo bad','x\nprint(1)','x`bad','x$bad'))
def test_identifier_injection_is_rejected(language,bad):
    directory=fresh_directory();plan=simple_plan(directory)
    plan=replace(plan,steps=(replace(plan.steps[0],parameters={'columns':[bad]}),))
    with pytest.raises(ScriptExportRefusal):renderer()(plan,language)


@pytest.mark.parametrize('language',LANGUAGES)
def test_reference_distribution_cannot_be_changed_by_expected(language):
    from test_script_export_model_oracles import frame,oracle
    directory=fresh_directory();d=frame();params,expected=oracle('ols_unadjusted',d)
    expected['statistics']['x']['distribution']='z'
    s=source(directory,d,'data.csv','source')
    step=ScriptStep('model','model','model.ols',params,('source',),expected=expected)
    plan=ScriptPlan('tamper','distribution',(s,),(step,),'1.8.11','7'*64)
    try:export=renderer()(plan,language)
    except ScriptExportRefusal:return
    code,output=execute(export,directory,plan)
    assert code!=0,output


@pytest.mark.parametrize('language',LANGUAGES)
def test_nlcom_code_injection_is_rejected(language):
    directory=fresh_directory();plan=simple_plan(directory)
    model=ScriptStep('model','model','model.ols',{'model_type':'ols','y':'x','x':['x'],'covariance':'unadjusted','model_options':{}},('source',))
    test=ScriptStep('test','postestimation','postestimation.nlcom',{'models':['model'],'expression':'__import__("os").system("echo bad")'},('model',))
    plan=replace(plan,steps=(model,test))
    with pytest.raises(ScriptExportRefusal):renderer()(plan,language)


@pytest.mark.parametrize('language',LANGUAGES)
def test_reader_options_cannot_redirect_the_verified_source(language):
    directory=fresh_directory();plan=simple_plan(directory)
    plan=replace(plan,sources=(replace(plan.sources[0],read_options={'file':'/tmp/another.csv'}),))
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language)
    assert caught.value.code=='UNSUPPORTED_READ_OPTIONS'


@pytest.mark.parametrize('language',LANGUAGES)
def test_lr_rejects_models_using_different_dependent_variables(language):
    directory=fresh_directory();plan=simple_plan(directory)
    params={'model_type':'ols','y':'x','x':['x'],'covariance':'unadjusted','model_options':{}}
    a=ScriptStep('full','model','model.ols',params,('source',))
    b=ScriptStep('restricted','model','model.ols',{**params,'y':'other'},('source',))
    lr=ScriptStep('lr','postestimation','postestimation.lr',{'models':['full','restricted']},('full','restricted'))
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(replace(plan,steps=(a,b,lr)),language)
    assert caught.value.code=='INCOMPARABLE_LR_MODELS'


@pytest.mark.parametrize('language',LANGUAGES)
def test_lr_cannot_compare_different_estimation_samples(language):
    from test_script_export_model_oracles import frame
    directory=fresh_directory();d=frame();d.loc[0,'z']=float('nan')
    params={'model_type':'ols','y':'y','x':['x','z'],'covariance':'unadjusted','model_options':{}}
    a=ScriptStep('full','model','model.ols',params,('source',))
    b=ScriptStep('restricted','model','model.ols',{**params,'x':['x']},('source',))
    lr=ScriptStep('lr','postestimation','postestimation.lr',{'models':['full','restricted']},('full','restricted'))
    plan=ScriptPlan('tamper','lr_sample',(source(directory,d,'data.csv','source'),),(a,b,lr),'1.8.11','c'*64)
    code,output=execute(renderer()(plan,language),directory,plan)
    assert code!=0,output
