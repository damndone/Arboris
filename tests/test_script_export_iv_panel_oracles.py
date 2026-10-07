"""IV and fixed-effect export contracts use the actual Workbench runners."""
import numpy as np
import pandas as pd
import pytest
import json
from workbench.econometrics import runner
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep
from test_script_export_data_oracles import fresh_directory,source,execute
from test_script_export_render import renderer


def data():
    rng=np.random.default_rng(811)
    n=320
    z=rng.normal(size=n);x=rng.normal(size=n);u=rng.normal(size=n)
    endog=.8*z+.3*x+u
    return pd.DataFrame({'x':x,'z':z,'endog':endog,'y':1+.7*endog+.2*x+.5*u+rng.normal(size=n),'entity':np.repeat(np.arange(40),8),'time':np.tile(np.arange(8),40)})


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('covariance',('unadjusted','robust'))
def test_iv_native_runner_oracle(language,covariance):
    directory=fresh_directory();d=data()
    result,fit=runner.run_iv_2sls(d,'y',['x'],['endog'],['z'],'iv',covariance=covariance)
    params={'model_type':'iv_2sls','y':'y','x':['x'],'covariance':covariance,'model_options':{'endog':['endog'],'instruments':['z']}}
    expected={'nobs':result['nobs'],'coefficients':{k:v['estimate'] for k,v in result['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in result['coefficients'].items()},'statistics':{k:{'value':float(fit.tstats[k]),'p_value':float(fit.pvalues[k]),'distribution':'z'} for k in fit.params.index}}
    step=ScriptStep('iv','model','model.iv_2sls',params,('source',),expected=expected)
    plan=ScriptPlan('iv',covariance,(source(directory,d,'data.csv','source'),),(step,),'1.8.11','8'*64)
    code,output=execute(renderer()(plan,language),directory,plan)
    assert code==0,output


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('model',('panel_ols','did'))
@pytest.mark.parametrize('cluster_kind',('entity','coarse_string'))
def test_panel_clustered_runner_oracle(language,model,cluster_kind):
    directory=fresh_directory();d=data()
    d['_did_D']=((d.entity<20)&(d.time>=4)).astype(int)
    d['cluster']=('district_'+(d.entity//2).astype(str)) if cluster_kind=='coarse_string' else d.entity
    cluster_argument={'cluster_col':'cluster'} if cluster_kind=='coarse_string' else {}
    try:
        if model=='did':result,fit=runner.run_did(d,'y',['x'],'entity','time','model',covariance='clustered',**cluster_argument)
        else:result,fit=runner.run_panel_ols(d,'y',['x'],'entity','time','model',covariance='clustered',**cluster_argument)
    except TypeError as exc:
        (directory/'runner_failure.json').write_text(json.dumps({'model':model,'cluster_kind':cluster_kind,'language':language,'error':str(exc),'delta':None},indent=2))
        raise
    params={'model_type':model,'y':'y','x':['x'],'entity':'entity','time':'time','cluster':'cluster','covariance':'clustered','model_options':{}}
    expected={'nobs':result['nobs'],'coefficients':{k:v['estimate'] for k,v in result['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in result['coefficients'].items()}}
    expected['statistics']={k:{'value':float(fit.tstats[k]),'p_value':float(fit.pvalues[k]),'df':float(getattr(fit,'df_resid_inference',fit.df_resid)),'distribution':'t'} for k in fit.params.index}
    step=ScriptStep('model','model','model.'+model,params,('source',),expected=expected)
    plan=ScriptPlan('panel',model+'_'+cluster_kind,(source(directory,d,'data.csv','source'),),(step,),'1.8.11','9'*64)
    code,output=execute(renderer()(plan,language),directory,plan)
    assert code==0,output
