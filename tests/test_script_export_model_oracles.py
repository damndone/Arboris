"""Direct engine oracle plans executed by all three target programs."""
from dataclasses import replace
import json
import numpy as np
import pandas as pd
import pytest
from workbench.econometrics import runner
from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep
from test_script_export_render import renderer
from test_script_export_data_oracles import execute, fresh_directory, source

CASES = ('ols_unadjusted','ols_robust','ols_clustered','ols_hac','ols_frequency','ols_analysis','logit','probit','poisson','glm_binomial','glm_poisson','negative_binomial')


def frame():
    rng=np.random.default_rng(58111)
    n=350
    x=rng.normal(size=n);z=rng.normal(size=n)
    d=pd.DataFrame({'x':x,'z':z,'y':1.1+0.5*x-0.3*z+rng.normal(size=n),'group':np.repeat(np.arange(35),10),
                    'time':np.arange(n), 'fw':rng.integers(1,4,size=n), 'aw':rng.uniform(.5,2,size=n)})
    d['binary']=rng.binomial(1,1/(1+np.exp(-(.1+.4*x-.3*z))))
    d['count']=rng.poisson(np.exp(.2+.3*x-.2*z))
    d['nb']=rng.negative_binomial(1.4,1.4/(1.4+np.exp(.2+.3*x-.2*z)))
    return d


def oracle(case,d):
    params={'model_type':'ols', 'y':'y','x':['x','z'],'categorical_x':[], 'covariance':'unadjusted', 'cluster':None,
            'hac_lags':None, 'weights':None, 'entity':None,'time':None,'model_options':{}}
    sink=[]
    if case.startswith('ols_'):
        mode=case.removeprefix('ols_')
        if mode in {'frequency','analysis'}: params['weights']={'kind':mode,'column':'fw' if mode=='frequency' else 'aw'}
        else:params['covariance']=mode
        if mode=='clustered':params['cluster']='group'
        if mode=='hac':params['hac_lags']=2;params['model_options']={'time_order':'time'}
        result,fitted=runner.run_ols(d,'y',['x','z'],False,'model',covariance=params['covariance'], cluster_col=params['cluster'],weights=params['weights'],hac_time_order='time' if mode=='hac' else None,hac_lags=params['hac_lags'],fitted_sink=sink.append)
        fitted=sink[0]
    elif case.startswith('glm_'):
        family=case.removeprefix('glm_');params.update(model_type='glm',y='binary' if family=='binomial' else 'count',model_options={'family':family})
        result,fitted=runner.run_glm(d,params['y'],['x','z'],'model',family)
    else:
        params.update(model_type=case,y={'logit':'binary','probit':'binary','poisson':'count','negative_binomial':'nb'}[case])
        result,fitted=getattr(runner,'run_'+case)(d,params['y'],['x','z'],'model')
    coeffs={k:v['estimate'] for k,v in result['coefficients'].items() if k!='alpha'}
    ses={k:v['std_error'] for k,v in result['coefficients'].items() if k!='alpha'}
    expected={'nobs':result['nobs'],'coefficients':coeffs,'std_errors':ses}
    # Final inference must preserve the actual model reference distribution.
    names=list(fitted.model.exog_names)
    distribution='t' if getattr(fitted,'use_t',False) else 'z'
    df=float(getattr(fitted,'df_resid_inference',fitted.df_resid)) if distribution=='t' else None
    expected['statistics']={k:{'value':float(np.asarray(fitted.tvalues)[i]),'df':df,'p_value':float(np.asarray(fitted.pvalues)[i]),'distribution':distribution} for i,k in enumerate(coeffs)}
    return params,expected


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_native_model_engine_oracle(case,language):
    directory=fresh_directory();d=frame();params,expected=oracle(case,d)
    s=source(directory,d,'data.csv','source')
    step=ScriptStep('model','model','model.'+params['model_type'],params,('source',),expected=expected)
    plan=ScriptPlan('model-oracle',case,(s,),(step,),'1.8.11','1'*64)
    export=renderer()(plan,language,require_native=True)
    code,output=execute(export,directory,plan)
    assert code==0,output
    (directory/'plan.json').write_text(json.dumps(plan.to_dict(),indent=2))


@pytest.mark.parametrize('language',LANGUAGES)
def test_categorical_reference_and_weighted_branch_preservation(language):
    directory=fresh_directory();d=frame();d['region']=np.resize(['west','east','south'],len(d))
    sources=(source(directory,d,'data.csv','source'),)
    steps=[]
    for name,weights in [('weighted',{'kind':'frequency','column':'fw'}),('plain',None)]:
        params={'model_type':'ols','y':'y','x':['x','region'],'categorical_x':['region'],'covariance':'unadjusted','weights':weights,'model_options':{}}
        result,fit=runner.run_ols(d,'y',['x','region'],False,name,categorical_x={'region'},weights=weights)
        expected={'nobs':result['nobs'],'coefficients':{k:v['estimate'] for k,v in result['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in result['coefficients'].items()}}
        steps.append(ScriptStep(name,'model','model.ols',params,('source',),expected=expected))
    plan=ScriptPlan('categories','branches',sources,tuple(steps),'1.8.11','3'*64)
    code,output=execute(renderer()(plan,language),directory,plan)
    assert code==0,output


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('kind',('frequency','analysis'))
@pytest.mark.parametrize('covariance',('robust','clustered'))
def test_supported_weighted_covariance_oracle(language,kind,covariance):
    directory=fresh_directory();d=frame();params,_=oracle('ols_'+kind,d)
    params.update(covariance=covariance,cluster='group' if covariance=='clustered' else None)
    sink=[]
    result,fit=runner.run_ols(d,'y',['x','z'],False,'weighted',weights=params['weights'],covariance=covariance,cluster_col=params['cluster'],fitted_sink=sink.append)
    fit=sink[0]
    expected={'nobs':result['nobs'],'coefficients':{k:v['estimate'] for k,v in result['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in result['coefficients'].items()},'statistics':{k:{'value':float(np.asarray(fit.tvalues)[i]),'p_value':float(np.asarray(fit.pvalues)[i]),'df':float(getattr(fit,'df_resid_inference',fit.df_resid)),'distribution':'t'} for i,k in enumerate(result['coefficients'])}}
    step=ScriptStep('weighted','model','model.ols',params,('source',),expected=expected)
    plan=ScriptPlan('weighted',kind+'_'+covariance,(source(directory,d,'data.csv','source'),),(step,),'1.8.11','b'*64)
    code,output=execute(renderer()(plan,language),directory,plan)
    assert code==0,output
