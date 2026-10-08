"""Post-estimation scripts preserve the real inference kernel's covariance."""
from dataclasses import replace
import numpy as np
from workbench.econometrics.normalize import _public_term
import pytest
from workbench.econometrics import runner
from workbench.contracts.model.inference_kernel import build_inference_kernel
from workbench.postestimation.registry import run_operation
from workbench.script_export.plan import LANGUAGES, ScriptExportRefusal, ScriptPlan, ScriptStep
from test_script_export_model_oracles import frame,oracle
from test_script_export_data_oracles import fresh_directory,source,execute
from test_script_export_render import renderer

FAMILIES=('ols_unadjusted','ols_robust','ols_clustered','ols_hac','logit','probit','poisson','negative_binomial','negative_binomial_nb1')
OPERATIONS=('wald','lincom','nlcom','lr','margins')


def fit_kernel(case,d,x):
    if case.startswith('ols_'):
        cov=case.removeprefix('ols_');sink=[]
        result,plain=runner.run_ols(d,'y',x,False,'model',covariance=cov,cluster_col='group' if cov=='clustered' else None,hac_lags=2 if cov=='hac' else None,hac_time_order='time' if cov=='hac' else None,fitted_sink=sink.append)
        fit=sink[0];model='ols';link='identity';estimator={'unadjusted':'nonrobust','robust':'HC1','clustered':'cluster','hac':'HAC'}[cov]
    elif case=='negative_binomial_nb1':
        result,fit=runner.run_negative_binomial(d,'nb',x,'model',dispersion='constant')
        model='negative_binomial';link='log';estimator='nonrobust'
    else:
        result,fit=getattr(runner,'run_'+case)(d,{'logit':'binary','probit':'binary','poisson':'count','negative_binomial':'nb'}[case],x,'model')
        model=case;link={'logit':'logit','probit':'probit','poisson':'log','negative_binomial':'log'}[case];estimator='nonrobust'
    # Every fitted parameter, named as production's kernel_from_fitted names them:
    # negative binomial's alpha is an auxiliary parameter, not a coefficient.
    names=[_public_term(str(name)) for name in fit.params.index] if hasattr(fit.params,'index') else list(result['coefficients'])
    use_t=getattr(fit,'use_t',False);df=float(getattr(fit,'df_resid_inference',fit.df_resid)) if use_t else None
    kernel=build_inference_kernel(model_id='model',model_type=model,param_names=names,params=np.asarray(fit.params),vcov=fit.cov_params(),reference_distribution='t' if use_t else 'z',df_resid=df,loglik=fit.llf,nobs=int(fit.nobs),covariance_estimator=estimator,estimation_sample_fingerprint='same',df_method='clusters_minus_one' if case=='ols_clustered' else None,n_clusters=35 if case=='ols_clustered' else None)
    design=dict(zip(names,fit.model.exog.T))
    return kernel,{'design':design,'inverse_link':link}


def expected_from(result):
    expected={}
    if 'estimate' in result:
        expected['coefficients']={'estimate':result['estimate']}
        expected['std_errors']={'estimate':result['std_error']}
    expected['statistics']={'test':{'value':result.get('statistic'),'df':result.get('df_num',result.get('df')),'df_denominator':result.get('df_den'),'p_value':result.get('p_value'),'distribution':result['distribution']}}
    if result['operation']=='margins':
        expected={'nobs':result['nobs'],'coefficients':{e['variable']:e['estimate'] for e in result['effects']},'std_errors':{e['variable']:e['std_error'] for e in result['effects']},'statistics':{e['variable']:{'value':e['statistic'],'p_value':e['p_value'],'df':result['df'],'distribution':result['distribution']} for e in result['effects']}}
    return expected


CASES=[(f,o) for f in FAMILIES for o in OPERATIONS if (o!='lr' or f in {'ols_unadjusted','logit','probit','poisson'}) and (not f.startswith('negative_binomial') or o in {'wald','lincom'})]

@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES,ids=[f'{f}-{o}' for f,o in CASES])
def test_postestimation_native_kernel_oracle(case,language):
    family,operation=case;directory=fresh_directory();d=frame();params,expected=oracle(family,d)
    kernel,context=fit_kernel(family,d,['x','z'])
    spec={'wald':{'constraints':[{'terms':{'x':1},'value':.2},{'terms':{'z':1},'value':0}]},
          'lincom':{'terms':{'x':1,'z':2},'constant':-.5}, 'nlcom':{'expression':'exp(x) / (1 + z ** 2)'},
          'lr':{},'margins':{'variables':['x','z'],'at':'average'}}[operation]
    kernels=[kernel];models=['model'];steps=[ScriptStep('model','model','model.'+params['model_type'],params,('source',),expected=expected)]
    if operation=='lr':
        restricted,_=fit_kernel(family,d,['x']);kernels.append(restricted);models.append('restricted')
        steps.append(ScriptStep('restricted','model','model.'+params['model_type'],{**params,'x':['x']},('source',)))
    result=run_operation(operation,kernels,spec,context)
    steps.append(ScriptStep('test','postestimation','postestimation.'+operation,{**spec,'models':models},tuple(models),expected=expected_from(result)))
    plan=ScriptPlan('postestimation',family,(source(directory,d,'data.csv','source'),),tuple(steps),'1.8.11','6'*64)
    if family=='negative_binomial_nb1' and language=='r':
        # R has no reference NB1 estimator: the model and the test on it stay Workbench results.
        with pytest.raises(ScriptExportRefusal) as caught:renderer()(plan,language,require_native=True)
        assert caught.value.code=='NOT_FULLY_NATIVE' and 'model' in caught.value.steps
        return
    exported=renderer()(plan,language,require_native=True)
    code,output=execute(exported,directory,plan)
    assert code==0,output
