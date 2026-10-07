"""The C3 basic DID path prepares its input in each native language."""
import pytest
import hashlib
import numpy as np
import pandas as pd
from dataclasses import replace

from test_script_export_complex_results import completed, Executable, ROOT
from test_script_export_data_oracles import execute
from workbench.services.script_export import _prepare


@pytest.mark.parametrize('completed',['did'],indirect=True)
@pytest.mark.parametrize('language',['python','r','stata'])
def test_completed_basic_did_path_is_entirely_native(completed,language,tmp_path,monkeypatch):
    _,project,root,node=completed
    monkeypatch.setenv('PYTHONPATH',str(ROOT/'backend'))
    files,summary,_=_prepare(project,root.name,node.id,language,True)
    assert all(row['status']!='snapshot' for row in summary['coverage'])
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    filename={'python':'analysis.py','r':'analysis.R','stata':'analysis.do'}[language]
    code,output=execute(Executable(language,filename,files[filename].decode()),tmp_path)
    assert code==0,output[-3000:]


@pytest.mark.parametrize('mode',['cohort','cohort_text','two_by_two','status','cohort_missing_entity','cohort_existing_helpers','two_by_two_boolean','cohort_as_helper','two_by_two_helper_treat','cohort_text_boolean_words','cohort_float_underscores','cohort_unicode_digits','cohort_arabic_digits','cohort_invalid_float','cohort_float_space_exponent','cohort_float_newlines'])
@pytest.mark.parametrize('language',['python','r','stata'])
def test_native_preparation_matches_all_executed_rows(mode,language,tmp_path):
    from workbench.engine.did_spec import normalize_did_input
    from workbench.script_export.plan import ScriptPlan,ScriptSource,ScriptStep
    from workbench.script_export.render import export_script
    frame=pd.DataFrame({'id':np.repeat(['unit_b','unit_a','unit_c'],4),
        'time':np.tile([3,1,4,2],3),'y':np.arange(12,dtype=float),
        'first':np.repeat([3,0,4],4)})
    frame['treat']=(frame['id']!='unit_a').astype(int)
    frame['post']=(frame['time']>=3).astype(int)
    frame['on']=((frame['first']>0)&(frame['time']>=frame['first'])).astype(int)
    if mode=='cohort_text':frame['first']=frame['first'].map({3:'3',0:'never',4:'4'})
    if mode=='cohort_float_underscores':frame['first']=frame['first'].map({3:'3.0_0',0:'never',4:'4.0_0'})
    if mode=='cohort_unicode_digits':frame['first']=frame['first'].map({3:'３',0:'never',4:'４'})
    if mode=='cohort_arabic_digits':frame['first']=frame['first'].map({3:'٣',0:'never',4:'٤'})
    if mode=='cohort_float_newlines':frame['first']=frame['first'].map({3:'3\n',0:'never',4:'\r\n4\n'})
    if mode=='cohort_float_space_exponent':frame['first']=frame['first'].map({3:'\u0085+٣.٠_٠e+٠_٠\u3000',0:'never',4:'\u00a0+4.0_0e+0_0\u2028'})
    if mode=='cohort_invalid_float':frame['first']=frame['first'].map({3:'3__0',0:'³',4:'4'})
    if mode=='cohort_text_boolean_words':frame['first']=frame['first'].map({3:'3',0:'true',4:'4'})
    if mode=='cohort_missing_entity':frame.loc[0,'id']=None
    if mode=='cohort_existing_helpers':frame.insert(1,'_did_D',-4)
    if mode=='two_by_two_boolean':
        frame['treat']=frame['treat'].astype(bool);frame['post']=frame['post'].astype(bool)
    if mode=='cohort_as_helper':frame=frame.rename(columns={'first':'_did_cohort'})
    if mode=='two_by_two_helper_treat':frame=frame.rename(columns={'treat':'_did_D'})
    normalized_mode='cohort' if mode.startswith('cohort') else ('two_by_two' if mode.startswith('two_by_two') else mode)
    spec=dict(mode=normalized_mode,entity='id',time='time',cohort='first',treat='treat',post='post',status='on')
    if mode=='cohort_as_helper':spec['cohort']='_did_cohort'
    if mode=='two_by_two_helper_treat':spec['treat']='_did_D'
    expected=normalize_did_input(frame,y='y',**spec).frame
    spec['boolean_columns']=[name for name in spec.values() if name in frame.columns and pd.api.types.is_bool_dtype(frame[name])]
    raw=frame.to_csv(index=False).encode();(tmp_path/'input.csv').write_bytes(raw)
    step=ScriptStep('prepared','data_operation','data.estimation_input',
        {'preparation':dict(kind='absorbing_treatment_panel',version=1,**spec)},('source',),
        expected={'nrows':len(expected),'columns':list(expected.columns)})
    plan=ScriptPlan('p','r',(ScriptSource('source','csv','input.csv',hashlib.sha256(raw).hexdigest()),),(step,),'1.8.11','0'*64)
    exported=export_script(plan,language,require_native=True)
    capture={'python':'data["prepared"].to_csv("prepared.csv", index=False)',
        'r':'write.csv(data[["prepared"]], "prepared.csv", row.names=FALSE, na="")',
        'stata':'frame change wb1\nexport delimited using "prepared.csv", quote replace'}[language]
    marker=('*' if language=='stata' else '#')+' Closing self-checks'
    exported=replace(exported,text=exported.text.replace(marker,capture+'\n'+marker))
    code,output=execute(exported,tmp_path)
    assert code==0,output[-3000:]
    actual=pd.read_csv(tmp_path/'prepared.csv',na_values=['.'])
    assert list(actual.columns)==list(expected.columns)
    assert actual['id'].tolist()==expected['id'].tolist()
    for name in ['_did_cohort','_did_D','_did_event_time']:
        np.testing.assert_allclose(actual[name],expected[name],atol=0,rtol=0,equal_nan=True)


@pytest.mark.parametrize('payload',[1,0,None,[],{},['kind','version','mode','entity','time','cohort','treat','post','status']])
def test_unknown_preparation_is_explicitly_refused(payload):
    from workbench.script_export.absorbing_panel import configuration
    from workbench.script_export.plan import ScriptExportRefusal,ScriptStep
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':payload},('source',))
    with pytest.raises(ScriptExportRefusal):configuration(step)


@pytest.mark.parametrize('text',['1e308','9e307','1e-300','2.2250738585072014e-308'])
def test_r_cohort_parser_preserves_extreme_float_bits(text,tmp_path):
    from workbench.script_export.absorbing_panel import prepare
    from workbench.script_export.runtime import RenderContext
    from workbench.script_export.plan import ScriptStep
    import subprocess
    ctx=RenderContext('r');ctx.datasets={'source':'source','prepared':'prepared'}
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':{'kind':'absorbing_treatment_panel','version':1,'mode':'cohort','entity':'id','time':'time','cohort':'first','treat':None,'post':None,'status':None}},('source',))
    code='data <- list(source=data.frame(id=c("a","b"),time=c(2,4),first=c('+repr(text).replace("'",'"')+',"never")))\n'+'\n'.join(prepare(step,ctx))+'\nwriteLines(sprintf("%a",data[["prepared"]][["_did_cohort"]][1]),"number.txt")\n'
    path=tmp_path/'parser.R';path.write_text(code)
    result=subprocess.run(['Rscript',str(path)],cwd=tmp_path,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert float.fromhex((tmp_path/'number.txt').read_text().strip())==float(text)


@pytest.mark.parametrize('text',['1e308','9e307'])
def test_declared_stata_unrepresentable_cohort_refuses_at_generation(text,tmp_path):
    from workbench.script_export.absorbing_panel import prepare
    from workbench.script_export.runtime import RenderContext
    from workbench.script_export.plan import ScriptExportRefusal,ScriptStep
    ctx=RenderContext('stata');ctx.datasets={'source':'source','prepared':'prepared'}
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':{'kind':'absorbing_treatment_panel','version':1,'mode':'cohort','entity':'id','time':'time','cohort':'first','treat':None,'post':None,'status':None,'cohort_range':[float(text),float(text)]}},('source',))
    with pytest.raises(ScriptExportRefusal,match="representable") as issue:prepare(step,ctx)
    assert issue.value.code=='UNREPRESENTABLE_COHORT_PERIOD'


@pytest.fixture(scope='module')
def finite_extreme_owner(tmp_path_factory):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    from workbench.graph_store import GraphStore
    directory=tmp_path_factory.mktemp('did-finite-extreme-owner')
    frame=pd.read_csv(ROOT/'tests/fixtures/panel_cluster/staggered.csv')
    first=min(value for value in frame['first_treat'].unique() if value>0)
    frame['first_treat']=frame['first_treat'].map(lambda value:'1e308' if value==first else str(float(value))+'_0')
    source=directory/'input.csv';frame.to_csv(source,index=False)
    project=create_project(directory,'public').root
    outcome=run_workflow(project,[source],mode='auto',model_type='did',y='y',x=['x1'],entity_col='g',time_col='time',did_mode='cohort',did_cohort_col='first_treat',covariance='clustered')
    assert outcome['status']=='completed',outcome
    run_id=outcome['run_id'];graph=GraphStore(project/'runs').read(run_id)
    node=next(node for node in graph.nodes.values() if node.kind.value=='model')
    return project,run_id,node.id


@pytest.mark.parametrize('require_native',[False,True])
def test_completed_finite_extreme_owner_refuses_stata(finite_extreme_owner,require_native):
    from workbench.script_export.plan import ScriptExportRefusal
    project,run_id,target=finite_extreme_owner
    with pytest.raises(ScriptExportRefusal) as issue:_prepare(project,run_id,target,'stata',require_native)
    assert issue.value.code=='UNREPRESENTABLE_COHORT_PERIOD'


@pytest.mark.parametrize('language',['python','r'])
def test_completed_finite_extreme_owner_native_r_and_python(finite_extreme_owner,language,tmp_path):
    project,run_id,target=finite_extreme_owner
    files,summary,_=_prepare(project,run_id,target,language,True)
    assert all(row['status']!='snapshot' for row in summary['coverage'])
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    filename={'python':'analysis.py','r':'analysis.R'}[language]
    code,output=execute(Executable(language,filename,files[filename].decode()),tmp_path)
    assert code==0,output[-3000:]

@pytest.mark.parametrize('text',['1e308','9e307','1e-300','2.2250738585072014e-308','3.0000000000000004','1.7976931348623157e308'])
def test_r_numeric_csv_cohort_preserves_original_float(text,tmp_path):
    from workbench.engine.did_spec import normalize_did_input
    from workbench.script_export.plan import ScriptPlan,ScriptSource,ScriptStep
    from workbench.script_export.render import export_script
    frame=pd.DataFrame({'id':['a','a','b','b'],'time':[3.,4.,3.,4.],'y':[1.,2.,3.,4.],'first':[float(text),float(text),0.,0.]})
    raw=frame.to_csv(index=False).encode();(tmp_path/'input.csv').write_bytes(raw)
    from workbench.ingestion import _read_frame
    from workbench.config import WorkbenchConfig
    ingested=_read_frame(tmp_path/'input.csv',WorkbenchConfig(),transpose=False)
    expected=normalize_did_input(ingested,y='y',mode='cohort',entity='id',time='time',cohort='first').frame
    spec=dict(kind='absorbing_treatment_panel',version=1,mode='cohort',entity='id',time='time',cohort='first',treat=None,post=None,status=None)
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':spec},('source',),expected={'nrows':4,'columns':list(expected.columns)})
    plan=ScriptPlan('p','r',(ScriptSource('source','csv','input.csv',hashlib.sha256(raw).hexdigest()),),(step,),'1.8.11','0'*64)
    exported=export_script(plan,'r',require_native=True)
    trace='writeLines(sprintf("%a",data[["prepared"]][["_did_cohort"]][1]),"number.txt")\nwriteLines(as.character(data[["prepared"]][["_did_D"]]),"status.txt")\n'
    exported=replace(exported,text=exported.text.replace('# Closing self-checks',trace+'# Closing self-checks'))
    code,output=execute(exported,tmp_path)
    assert code==0,output[-3000:]
    assert float.fromhex((tmp_path/'number.txt').read_text().strip())==expected['_did_cohort'].iloc[0]
    assert [int(value) for value in (tmp_path/'status.txt').read_text().splitlines()]==expected['_did_D'].tolist()


@pytest.mark.parametrize('time,cohort',[(3.,np.nextafter(3.,np.inf)),(np.nextafter(3.,np.inf),np.nextafter(3.,np.inf))])
def test_r_numeric_primitive_preserves_treatment_threshold(time,cohort,tmp_path):
    from workbench.script_export.absorbing_panel import prepare
    from workbench.script_export.runtime import RenderContext
    from workbench.script_export.plan import ScriptStep
    import subprocess,json
    ctx=RenderContext('r');ctx.datasets={'source':'source','prepared':'prepared'}
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':{'kind':'absorbing_treatment_panel','version':1,'mode':'cohort','entity':'id','time':'time','cohort':'first','treat':None,'post':None,'status':None}},('source',))
    frame={'id':['a','a','b','b'],'time':[time,4.,time,4.],'first':[cohort,cohort,0.,0.]}
    path=tmp_path/'input.json';path.write_text(json.dumps(frame))
    code='data <- list(source=as.data.frame(jsonlite::fromJSON("input.json")))\n'+'\n'.join(prepare(step,ctx))+'\nwriteLines(as.character(data[["prepared"]][["_did_D"]]),"status.txt")\n'
    script=tmp_path/'threshold.R';script.write_text(code)
    result=subprocess.run(['Rscript',str(script)],cwd=tmp_path,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert [int(value) for value in (tmp_path/'status.txt').read_text().splitlines()]==[int(time>=cohort),1,0,0]


def test_unbounded_integer_cohort_range_is_explicitly_refused():
    from workbench.script_export.absorbing_panel import configuration
    from workbench.script_export.plan import ScriptExportRefusal,ScriptStep
    step=ScriptStep('prepared','data_operation','data.estimation_input',{'preparation':{'kind':'absorbing_treatment_panel','version':1,'mode':'cohort','entity':'id','time':'time','cohort':'first','treat':None,'post':None,'status':None,'cohort_range':[10**1000,10**1000]}},('source',))
    with pytest.raises(ScriptExportRefusal):configuration(step)
