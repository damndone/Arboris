"""Survey exports compared with the actual OLS estimation-stage covariance."""
from types import SimpleNamespace
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from scipy import stats
from workbench.econometrics.runner import run_ols
from workbench.engine.stages.estimation import _apply_survey_design_variance
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep, ScriptExportRefusal
from test_script_export_data_oracles import fresh_directory, source, execute
from test_script_export_render import renderer

BACKEND=Path(__file__).resolve().parents[1]/'backend'
FIXTURES=Path(__file__).parent/'fixtures/survey'


def executed_oracle(frame,design):
    primary,_=run_ols(frame,'y',['x1','x2'],False,'model',weights={'kind':'sampling','column':'weight'})
    artifacts={'_normalized_y':'y','_normalized_x':['x1','x2'],**{'_'+k:v for k,v in design.items()}}
    ctx=SimpleNamespace(data=SimpleNamespace(frame=frame),artifacts=artifacts)
    _apply_survey_design_variance(ctx,'ols',primary)
    df=primary['survey_design']['inference_degf']
    expected={'nobs':primary['nobs'],'coefficients':{},'std_errors':{},'statistics':{}}
    for term,item in primary['coefficients'].items():
        value=item['estimate']/item['std_error']
        expected['coefficients'][term]=item['estimate'];expected['std_errors'][term]=item['std_error']
        expected['statistics'][term]={'value':value,'p_value':item['p_value'],'df':df,'distribution':'t'}
    return expected,ctx.artifacts['_inference_kernels']['model'],primary


def survey_plan(directory,frame,design):
    expected,kernel,primary=executed_oracle(frame,design)
    (directory/'workbench_oracle.json').write_text(json.dumps({'primary':primary,'kernel':kernel},indent=2))
    params={'model_type':'ols','y':'y','x':['x1','x2'],'categorical_x':[],
            'covariance':'survey_design','weights':{'kind':'sampling','column':'weight'},
            'model_options':{'survey_design':design}}
    step=ScriptStep('model','model','model.ols',params,('source',),expected=expected)
    return ScriptPlan('survey','native',(source(directory,frame,'data.csv','source'),),(step,),'1.8.11','d'*64)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('convention',('design','design_minus_p'))
@pytest.mark.parametrize('structure',('strata_psu','psu_only','strata_only','subpopulation','lonely_remove','lonely_certainty','lonely_adjust','lonely_average'))
def test_complete_no_fpc_sampling_ols_true_stage_oracle(language,convention,structure,monkeypatch):
    directory=fresh_directory()
    frame=pd.read_csv(FIXTURES/('subpop.csv' if structure=='subpopulation' else 'design.csv'))
    design={'sampling_weight':'weight','survey_method':'linearization','survey_df':convention,'survey_lonely_psu':'fail'}
    if structure!='psu_only':design['survey_strata_col']='stratum'
    if structure!='strata_only':design['survey_psu_col']='psu'
    if structure=='subpopulation':design['survey_subpop']='subpop == 1'
    if structure.startswith('lonely_'):
        frame=frame.loc[~((frame.stratum=='h01') & (frame.psu=='s01_p2'))].copy()
        assert len(frame)==75
        design['survey_lonely_psu']=structure.removeprefix('lonely_')
    plan=survey_plan(directory,frame,design)
    # The generated Python program declares Workbench as a dependency; bind the
    # controlled test environment to this exact worktree rather than old editable installs.
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(renderer()(plan,language,require_native=True),directory,plan)
    assert code==0,output
    if language=='r':assert 'logLik.svyglm' not in output


@pytest.mark.parametrize('language',LANGUAGES)
def test_supplied_fpc_cannot_be_silently_dropped(language,monkeypatch):
    directory=fresh_directory();frame=pd.read_csv(FIXTURES/'design.csv')
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_fpc_col':'fpc'}
    plan=survey_plan(directory,frame,design)
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(renderer()(plan,language,require_native=True),directory,plan)
    assert code==0,output


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('convention',('design','design_minus_p'))
@pytest.mark.parametrize('operation',('wald','lincom','nlcom','margins'))
def test_sampling_postestimation_uses_executed_covariance_and_df(language,convention,operation,monkeypatch):
    from workbench.postestimation.registry import run_operation
    from test_script_export_postestimation_oracles import expected_from
    directory=fresh_directory();frame=pd.read_csv(FIXTURES/'design.csv')
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_df':convention}
    plan=survey_plan(directory,frame,design)
    _,kernel,_=executed_oracle(frame,design)
    spec={'wald':{'constraints':[{'terms':{'x1':1},'value':.2},{'terms':{'x2':1},'value':0}]},
          'lincom':{'terms':{'x1':1,'x2':2},'constant':-.5},
          'nlcom':{'expression':'exp(x1) / (1 + x2 ** 2)'},
          'margins':{'variables':['x1','x2'],'at':'average'}}[operation]
    context={'design':{'Intercept':np.ones(len(frame)),'x1':frame.x1.to_numpy(),'x2':frame.x2.to_numpy()},'inverse_link':'identity'}
    expected=expected_from(run_operation(operation,[kernel],spec,context))
    post=ScriptStep('post','postestimation','postestimation.'+operation,{**spec,'models':['model']},('model',),expected=expected)
    from dataclasses import replace
    plan=replace(plan,steps=(*plan.steps,post))
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(renderer()(plan,language,require_native=True),directory,plan)
    assert code==0,output


@pytest.mark.parametrize('language',LANGUAGES)
def test_sampling_corrupted_expected_value_exits_nonzero(language,monkeypatch):
    from dataclasses import replace
    directory=fresh_directory();frame=pd.read_csv(FIXTURES/'design.csv')
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_df':'design'}
    plan=survey_plan(directory,frame,design)
    expected=dict(plan.steps[0].expected);expected['coefficients']={**expected['coefficients'],'x1':99.}
    plan=replace(plan,steps=(replace(plan.steps[0],expected=expected),))
    monkeypatch.setenv('PYTHONPATH',str(BACKEND))
    code,output=execute(renderer()(plan,language,require_native=True),directory,plan)
    assert code!=0,output


@pytest.mark.parametrize('language',LANGUAGES)
def test_sampling_domain_code_injection_is_rejected(language):
    from dataclasses import replace
    directory=fresh_directory();frame=pd.read_csv(FIXTURES/'design.csv')
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_df':'design'}
    plan=survey_plan(directory,frame,design)
    malicious={**design,'survey_subpop':'__import__("os").system("echo injected")'}
    parameters={**plan.steps[0].parameters,'model_options':{'survey_design':malicious}}
    plan=replace(plan,steps=(replace(plan.steps[0],parameters=parameters),))
    with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,require_native=True)
    assert caught.value.code=='UNSUPPORTED_SURVEY_DESIGN'


def test_fpc_frozen_engine_difference_is_persisted():
    """Compare the approved correction with the original native R probe."""
    import subprocess
    directory=fresh_directory();frame=pd.read_csv(FIXTURES/'design.csv')
    frame.to_csv(directory/'data.csv',index=False)
    design={'sampling_weight':'weight','survey_strata_col':'stratum','survey_psu_col':'psu','survey_df':'design_minus_p'}
    plain,_,primary=executed_oracle(frame,design)
    with_fpc,_,fpc_primary=executed_oracle(frame,{**design,'survey_fpc_col':'fpc'})
    assert plain['coefficients']==with_fpc['coefficients']
    text='''d <- read.csv("data.csv")
a <- survey::svydesign(ids=~psu,strata=~stratum,weights=~weight,data=d,nest=TRUE)
b <- survey::svydesign(ids=~psu,strata=~stratum,weights=~weight,fpc=~fpc,data=d,nest=TRUE)
fa <- survey::svyglm(y~x1+x2,design=a)
fb <- survey::svyglm(y~x1+x2,design=b)
write.csv(data.frame(term=names(coef(fa)),estimate=coef(fa),without_fpc=sqrt(diag(vcov(fa))),with_fpc=sqrt(diag(vcov(fb)))),"fpc_pairs.csv",row.names=FALSE)
print(sessionInfo())
'''
    (directory/'fpc_probe.R').write_text(text)
    proc=subprocess.run(['Rscript','fpc_probe.R'],cwd=directory,capture_output=True,text=True,timeout=90)
    (directory/'command_output.txt').write_text(proc.stdout+proc.stderr)
    assert proc.returncode==0,proc.stdout+proc.stderr
    pairs=pd.read_csv(directory/'fpc_pairs.csv')
    for _,item in pairs.iterrows():
        term='Intercept' if item.term=='(Intercept)' else item.term
        assert abs(item.without_fpc-plain['std_errors'][term])<=1e-8+1e-6*abs(plain['std_errors'][term])
        assert abs(item.with_fpc-with_fpc['std_errors'][term])<=1e-8+1e-6*abs(with_fpc['std_errors'][term])
        assert with_fpc['std_errors'][term]<plain['std_errors'][term]
    (directory/'fpc_engine_gap.json').write_text(json.dumps({'workbench_without_fpc':primary,'workbench_with_fpc':fpc_primary,'native_r':pairs.to_dict(orient='records'),'absolute_tolerance':1e-8,'relative_tolerance':1e-6},indent=2))
