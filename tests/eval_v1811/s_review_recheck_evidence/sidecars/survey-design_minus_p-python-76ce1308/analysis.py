# Workbench 1.8.11
# project: survey
# run: native
# lineage_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
# Coverage
# model | model.ols | native_with_equivalence_note | Full no-FPC linearization design and the executed coefficient t df; Python uses the Workbench survey engine.
# post | postestimation.wald | native | 
import hashlib
import math
from pathlib import Path
import numpy as np
import pandas as pd

data = {}
results = {}
checks = []
base = Path(__file__).resolve().parent

def wb_read(name, digest, fmt, options=None):
    path = base / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise AssertionError('SHA256 mismatch: ' + name)
    readers = {'csv': pd.read_csv, 'dta': pd.read_stata, 'sav': pd.read_spss,
               'xlsx': pd.read_excel, 'parquet': pd.read_parquet}
    return readers[fmt](path, **(options or {}))

def wb_check(actual, expected, absolute, relative, label):
    if not math.isfinite(float(actual)) or abs(actual-expected) > absolute + relative*abs(expected):
        raise AssertionError(f'{label}: {actual!r} != {expected!r}')

data['source'] = wb_read('data.csv', '5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
import statsmodels.formula.api as smf
from scipy import stats

def wb_public(name):
    if name.startswith("Q('") and name.endswith("')"):
        return name[3:-2]
    return name

def wb_model(fit, names=None, df=None, distribution=None, link="identity"):
    names = names or list(fit.model.exog_names)
    beta = np.asarray(fit.params)
    covariance = np.asarray(fit.cov_params())
    names = [wb_public(str(n)) for n in names]
    df = getattr(fit, 'df_resid_inference', fit.df_resid) if df is None else df
    distribution = distribution or ('t' if getattr(fit, 'use_t',False) else 'z')
    se = np.sqrt(np.diag(covariance))
    statistic = beta/se
    p = 2*(stats.t.sf(np.abs(statistic),df) if distribution=='t' else stats.norm.sf(np.abs(statistic)))
    return dict(beta=dict(zip(names,beta)), se=dict(zip(names,se)), statistic=dict(zip(names,statistic)),
                p=dict(zip(names,p)), covariance=covariance, names=names, df=df if distribution=='t' else None,
                distribution=distribution, nobs=float(fit.nobs), fit=fit, loglik=getattr(fit,'llf',None), link=link, design=fit.model.exog, sample=list(fit.model.data.row_labels))

def wb_array_model(params,covariance,nobs,df,distribution,design=None,loglik=None,sample=None):
    names=list(params.index);beta=np.asarray(params);covariance=np.asarray(covariance)
    se=np.sqrt(np.diag(covariance));statistic=beta/se
    p=2*(stats.t.sf(np.abs(statistic),df) if distribution=='t' else stats.norm.sf(np.abs(statistic)))
    return dict(beta=dict(zip(names,beta)),se=dict(zip(names,se)),statistic=dict(zip(names,statistic)),
      p=dict(zip(names,p)),covariance=covariance,names=names,df=df if distribution=='t' else None,
      distribution=distribution,nobs=float(nobs),loglik=loglik,link='identity',design=design,sample=sample)

from workbench.survey.adapters import build_design_from_artifacts, glm_estimator_spec
from workbench.survey.engine import estimate_with_design
wb_frame = data['source'].dropna(subset=['y', 'x1', 'x2']).copy()
wb_design = build_design_from_artifacts(wb_frame, {'_sampling_weight': 'weight', '_survey_strata_col': 'stratum', '_survey_psu_col': 'psu', '_survey_df': 'design_minus_p'})
wb_estimator = glm_estimator_spec(family="ols", glm_family="gaussian", y='y', x=['x1', 'x2'])
wb_survey = estimate_with_design(wb_design,wb_estimator,method="linearization",df_convention='design_minus_p')
wb_params = pd.Series(wb_survey.estimates).rename(index={"(Intercept)":"Intercept"})
wb_mask = wb_design.subpop_mask()
wb_X = np.column_stack([np.ones(int(wb_mask.sum())),*([wb_frame.loc[wb_mask,c].to_numpy() for c in ['x1', 'x2']])])
results['model'] = wb_array_model(wb_params,wb_survey.covariance,len(wb_frame),wb_survey.inference_degf,"t",design=wb_X,sample=list(wb_frame.index[wb_mask]))
results['model']["df_method"] = 'design_minus_p'
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']['x1']))
checks.append(float(results['model']['beta']['x2']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']['x1']))
checks.append(float(results['model']['se']['x2']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x1']))
checks.append(float(results['model']['p']['x1']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x2']))
checks.append(float(results['model']['p']['x2']))
checks.append(float(results['model']['df']))
def wb_single(model, estimate, se):
    statistic = estimate/se
    distribution = model['distribution']
    df = model['df']
    p = 2*(stats.t.sf(abs(statistic),df) if distribution=='t' else stats.norm.sf(abs(statistic)))
    return dict(value=statistic, p_value=p, df=df, df_denominator=None, distribution=distribution)

def wb_wald(model, constraints):
    names=model['names']
    if any(not set(item['terms'])<=set(names) for item in constraints):raise AssertionError('Unknown Wald coefficient')
    R=np.asarray([[item['terms'].get(n,0) for n in names] for item in constraints],dtype=float)
    target=np.asarray([item.get('value',0) for item in constraints],dtype=float)
    if np.linalg.matrix_rank(R)!=len(constraints): raise AssertionError('Dependent Wald restrictions')
    beta=np.asarray([model['beta'][n] for n in names])
    gap=R@beta-target
    W=float(gap@np.linalg.solve(R@model['covariance']@R.T,gap))
    q=len(constraints)
    finite=model['distribution']=='t'
    value=W/q if finite else W
    denominator=model['df'] if finite else None
    if finite and model.get('df_method')=='design' and q>1:
        denominator=model['df']-q+1
        if denominator<=0:raise AssertionError('Too few survey design degrees of freedom')
        value=W*denominator/(model['df']*q)
    p=stats.f.sf(value,q,denominator) if finite else stats.chi2.sf(value,q)
    return dict(beta={},se={},statistics={'test':dict(value=value,p_value=p,df=q,df_denominator=denominator,distribution='F' if finite else 'chi2')})

def wb_lincom(model, terms, constant):
    vector=np.asarray([terms.get(n,0) for n in model['names']],dtype=float)
    if not set(terms)<=set(model['names']):raise AssertionError('Unknown lincom coefficient')
    estimate=float(vector@np.asarray(list(model['beta'].values()))+constant)
    se=float(np.sqrt(vector@model['covariance']@vector))
    return dict(beta={'estimate':estimate},se={'estimate':se},statistics={'test':wb_single(model,estimate,se)})

def wb_nlcom(model, function):
    point=dict(model['beta']);names=model['names'];estimate=float(function(point));gradient=[]
    for name in names:
        h=6e-6*max(1,abs(point[name]))
        gradient.append((function({**point,name:point[name]+h})-function({**point,name:point[name]-h}))/(2*h))
    gradient=np.asarray(gradient)
    se=float(np.sqrt(gradient@model['covariance']@gradient))
    return dict(beta={'estimate':estimate},se={'estimate':se},statistics={'test':wb_single(model,estimate,se)})

def wb_lr(full,restricted):
    if full['loglik'] is None or restricted['loglik'] is None:raise AssertionError('Likelihood is unavailable')
    if full['sample']!=restricted['sample']:raise AssertionError('LR estimation samples differ')
    if not set(restricted['names'])<set(full['names']):raise AssertionError('Models are not nested')
    value=max(0,2*(full['loglik']-restricted['loglik']));df=len(full['names'])-len(restricted['names'])
    return dict(beta={},se={},statistics={'test':dict(value=value,p_value=stats.chi2.sf(value,df),df=df,df_denominator=None,distribution='chi2')})

WB_LINK_DERIVATIVES={
 'identity':lambda eta:(np.ones_like(eta),np.zeros_like(eta)),
 'logit':lambda eta:((1/(1+np.exp(-eta)))*(1-1/(1+np.exp(-eta))), (1/(1+np.exp(-eta)))*(1-1/(1+np.exp(-eta)))*(1-2/(1+np.exp(-eta)))),
 'probit':lambda eta:(stats.norm.pdf(eta),-eta*stats.norm.pdf(eta)),
 'log':lambda eta:(np.exp(eta),np.exp(eta)),
}

def wb_margins(model, variables, at):
    X=model['design']
    if at=='means':X=X.mean(axis=0,keepdims=True)
    beta=np.asarray(list(model['beta'].values()));first,second=WB_LINK_DERIVATIVES[model['link']](X@beta)
    curvature=(second[:,None]*X).mean(axis=0);mean_first=first.mean()
    estimates={};errors={};statistics={}
    for name in variables:
        j=model['names'].index(name);estimate=float(mean_first*beta[j]);gradient=curvature*beta[j];gradient[j]+=mean_first
        se=float(np.sqrt(gradient@model['covariance']@gradient));estimates[name]=estimate;errors[name]=se
        statistics[name]=wb_single(model,estimate,se)
    return dict(beta=estimates,se=errors,statistics=statistics,nobs=model['nobs'])

results['post'] = wb_wald(results['model'], [{'terms': {'x1': 1}, 'value': 0.2}, {'terms': {'x2': 1}, 'value': 0}])
checks.append(float(results['post']["statistics"]['test']['value']))
checks.append(float(results['post']["statistics"]['test']['p_value']))
checks.append(float(results['post']["statistics"]['test']['df']))
checks.append(float(results['post']["statistics"]['test']['df_denominator']))
assert results['post']["statistics"]['test']["distribution"] == 'F'
# Closing self-checks
wb_check(checks[0], 4.652711573943123, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 1.475820771771979, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], -0.40404481777033774, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 1.5955241455226616, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[4], 0.17732404110690134, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.08888234469730581, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 80, 0.0, 0.0, 'model:nobs')
wb_check(checks[7], 2.9161022645752492, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[8], 0.026766795825847126, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[9], 6, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[10], 8.322733694537604, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[11], 0.00016326932451573436, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[12], 6, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[13], -4.545838874371921, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[14], 0.003909008379856854, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[15], 6, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[16], 101.3403708088648, 1e-08, 1e-05, 'post:statistics.value')
wb_check(checks[17], 2.3768766090400888e-05, 1e-06, 0.0, 'post:statistics.p_value')
wb_check(checks[18], 2, 0.0, 0.0, 'post:statistics.df')
wb_check(checks[19], 6.0, 0.0, 0.0, 'post:statistics.df_denominator')
