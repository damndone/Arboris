# Workbench 1.8.11
# project: glm_nb
# run: 1.0
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# full | model.glm:negative_binomial | native | 
# restricted | model.glm:negative_binomial | native | 
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

data['source'] = wb_read('data.csv', '2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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

from statsmodels.genmod import families
wb_fit = smf.glm("Q('ynb') ~ Q('x1') + Q('x2') + Q('x3')", data=data['source'], family=families.NegativeBinomial(alpha=1.0)).fit(maxiter=1000,tol=1e-12,tol_criterion="params",scale=1)
assert wb_fit.converged, "Fixed-alpha GLM did not converge"
wb_fit._results.normalized_cov_params = np.linalg.inv(-wb_fit.model.hessian(wb_fit.params,observed=False))
wb_fit._results._cache.clear()
assert np.isfinite(wb_fit.params).all() and np.isfinite(np.asarray(wb_fit.cov_params())).all()
results['full'] = wb_model(wb_fit,distribution="z",link="log")
checks.append(float(results['full']['beta']['Intercept']))
checks.append(float(results['full']['beta']['x1']))
checks.append(float(results['full']['beta']['x2']))
checks.append(float(results['full']['beta']['x3']))
checks.append(float(results['full']['se']['Intercept']))
checks.append(float(results['full']['se']['x1']))
checks.append(float(results['full']['se']['x2']))
checks.append(float(results['full']['se']['x3']))
checks.append(float(results['full']["nobs"]))
from statsmodels.genmod import families
wb_fit = smf.glm("Q('ynb') ~ Q('x1')", data=data['source'], family=families.NegativeBinomial(alpha=1.0)).fit(maxiter=1000,tol=1e-12,tol_criterion="params",scale=1)
assert wb_fit.converged, "Fixed-alpha GLM did not converge"
wb_fit._results.normalized_cov_params = np.linalg.inv(-wb_fit.model.hessian(wb_fit.params,observed=False))
wb_fit._results._cache.clear()
assert np.isfinite(wb_fit.params).all() and np.isfinite(np.asarray(wb_fit.cov_params())).all()
results['restricted'] = wb_model(wb_fit,distribution="z",link="log")
# Standalone inference primitive probe; public postestimation admission is checked separately.
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

checks.append(float(results['full']['covariance'][0,0]))
checks.append(float(results['full']['covariance'][0,1]))
checks.append(float(results['full']['covariance'][0,2]))
checks.append(float(results['full']['covariance'][0,3]))
checks.append(float(results['full']['covariance'][1,0]))
checks.append(float(results['full']['covariance'][1,1]))
checks.append(float(results['full']['covariance'][1,2]))
checks.append(float(results['full']['covariance'][1,3]))
checks.append(float(results['full']['covariance'][2,0]))
checks.append(float(results['full']['covariance'][2,1]))
checks.append(float(results['full']['covariance'][2,2]))
checks.append(float(results['full']['covariance'][2,3]))
checks.append(float(results['full']['covariance'][3,0]))
checks.append(float(results['full']['covariance'][3,1]))
checks.append(float(results['full']['covariance'][3,2]))
checks.append(float(results['full']['covariance'][3,3]))
wb_probe = wb_wald(results['full'], [{'terms': {'x1': 1}, 'value': 0}, {'terms': {'x2': 1}, 'value': 0}])
checks.append(float(wb_probe["statistics"]['test']['value']))
checks.append(float(wb_probe["statistics"]['test']['p_value']))
checks.append(float(wb_probe["statistics"]['test']['df']))
assert wb_probe["statistics"]['test']["distribution"] == 'chi2'
wb_probe = wb_wald(results['full'], [{'terms': {'x1': 1, 'x2': -1}, 'value': 1}])
checks.append(float(wb_probe["statistics"]['test']['value']))
checks.append(float(wb_probe["statistics"]['test']['p_value']))
checks.append(float(wb_probe["statistics"]['test']['df']))
assert wb_probe["statistics"]['test']["distribution"] == 'chi2'
wb_probe = wb_lincom(results['full'], {'x1': 1, 'x2': 2}, -.5)
checks.append(float(wb_probe['beta']['estimate']))
checks.append(float(wb_probe['se']['estimate']))
checks.append(float(wb_probe["statistics"]['test']['value']))
checks.append(float(wb_probe["statistics"]['test']['p_value']))
assert wb_probe["statistics"]['test']["distribution"] == 'z'
wb_probe = wb_nlcom(results['full'], lambda b: b['x1']/b['x2'])
checks.append(float(wb_probe['beta']['estimate']))
checks.append(float(wb_probe['se']['estimate']))
checks.append(float(wb_probe["statistics"]['test']['value']))
checks.append(float(wb_probe["statistics"]['test']['p_value']))
assert wb_probe["statistics"]['test']["distribution"] == 'z'
wb_probe = wb_lr(results['full'], results['restricted'])
checks.append(float(wb_probe["statistics"]['test']['value']))
checks.append(float(wb_probe["statistics"]['test']['p_value']))
checks.append(float(wb_probe["statistics"]['test']['df']))
assert wb_probe["statistics"]['test']["distribution"] == 'chi2'
wb_probe = wb_margins(results['full'], ['x1', 'x2'], 'average')
checks.append(float(wb_probe['beta']['x1']))
checks.append(float(wb_probe['beta']['x2']))
checks.append(float(wb_probe['se']['x1']))
checks.append(float(wb_probe['se']['x2']))
checks.append(float(wb_probe["nobs"]))
wb_probe = wb_margins(results['full'], ['x1', 'x2'], 'means')
checks.append(float(wb_probe['beta']['x1']))
checks.append(float(wb_probe['beta']['x2']))
checks.append(float(wb_probe['se']['x1']))
checks.append(float(wb_probe['se']['x2']))
checks.append(float(wb_probe["nobs"]))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 0.524033398275554, 1e-08, 0, 'full:coefficients')
wb_check(checks[1], 0.37889378683709035, 1e-08, 0, 'full:coefficients')
wb_check(checks[2], -0.28894515154376593, 1e-08, 0, 'full:coefficients')
wb_check(checks[3], -0.10121807811349151, 1e-08, 0, 'full:coefficients')
wb_check(checks[4], 0.16986251046239487, 1e-06, 0, 'full:std_errors')
wb_check(checks[5], 0.07594663821229021, 1e-06, 0, 'full:std_errors')
wb_check(checks[6], 0.06578041865981685, 1e-06, 0, 'full:std_errors')
wb_check(checks[7], 0.14744903698769615, 1e-06, 0, 'full:std_errors')
wb_check(checks[8], 300, 0.0, 0.0, 'full:nobs')
wb_check(checks[9], 0.028853272460587203, 1e-06, 0, 'full:std_errors')
wb_check(checks[10], -0.0001870336902630863, 1e-06, 0, 'full:std_errors')
wb_check(checks[11], -0.0001220058983948316, 1e-06, 0, 'full:std_errors')
wb_check(checks[12], -0.022391429324453097, 1e-06, 0, 'full:std_errors')
wb_check(checks[13], -0.000187033690263085, 1e-06, 0, 'full:std_errors')
wb_check(checks[14], 0.0057678918557485, 1e-06, 0, 'full:std_errors')
wb_check(checks[15], -8.623713349002263e-05, 1e-06, 0, 'full:std_errors')
wb_check(checks[16], -0.0007567698511704407, 1e-06, 0, 'full:std_errors')
wb_check(checks[17], -0.00012200589839483038, 1e-06, 0, 'full:std_errors')
wb_check(checks[18], -8.623713349002254e-05, 1e-06, 0, 'full:std_errors')
wb_check(checks[19], 0.00432706347906078, 1e-06, 0, 'full:std_errors')
wb_check(checks[20], 0.0005314706280484755, 1e-06, 0, 'full:std_errors')
wb_check(checks[21], -0.022391429324453094, 1e-06, 0, 'full:std_errors')
wb_check(checks[22], -0.0007567698511704395, 1e-06, 0, 'full:std_errors')
wb_check(checks[23], 0.0005314706280484765, 1e-06, 0, 'full:std_errors')
wb_check(checks[24], 0.021741218508598985, 1e-06, 0, 'full:std_errors')
wb_check(checks[25], 43.44065374496691, 1e-08, 1e-06, 'wald_joint:statistics.value')
wb_check(checks[26], 3.689622161148643e-10, 0, 1e-05, 'wald_joint:statistics.p_value')
wb_check(checks[27], 2, 0.0, 0.0, 'wald_joint:statistics.df')
wb_check(checks[28], 10.745724600510435, 1e-08, 1e-06, 'wald_shifted:statistics.value')
wb_check(checks[29], 0.0010452050791167394, 0, 1e-05, 'wald_shifted:statistics.p_value')
wb_check(checks[30], 1, 0.0, 0.0, 'wald_shifted:statistics.df')
wb_check(checks[31], -0.6989965162504415, 1e-08, 0, 'lincom:coefficients')
wb_check(checks[32], 0.1507686878567016, 1e-06, 0, 'lincom:std_errors')
wb_check(checks[33], -4.636218078085312, 1e-08, 1e-06, 'lincom:statistics.value')
wb_check(checks[34], 3.548415987298015e-06, 0, 1e-05, 'lincom:statistics.p_value')
wb_check(checks[35], -1.3113000332857292, 1e-08, 0, 'nlcom:coefficients')
wb_check(checks[36], 0.3943281916651146, 1e-06, 0, 'nlcom:std_errors')
wb_check(checks[37], -3.3254027000924093, 1e-08, 1e-06, 'nlcom:statistics.value')
wb_check(checks[38], 0.0008829091096100815, 0, 1e-05, 'nlcom:statistics.p_value')
wb_check(checks[39], 20.9225036111211, 1e-08, 1e-06, 'lr_drop_x2_x3:statistics.value')
wb_check(checks[40], 2.862437857314723e-05, 0, 1e-05, 'lr_drop_x2_x3:statistics.p_value')
wb_check(checks[41], 2, 0.0, 0.0, 'lr_drop_x2_x3:statistics.df')
wb_check(checks[42], 0.6517441141230731, 1e-08, 0, 'margins_average:coefficients')
wb_check(checks[43], -0.49702135014477106, 1e-08, 0, 'margins_average:coefficients')
wb_check(checks[44], 0.1514857182227496, 1e-06, 0, 'margins_average:std_errors')
wb_check(checks[45], 0.12705412477458178, 1e-06, 0, 'margins_average:std_errors')
wb_check(checks[46], 300, 0.0, 0.0, 'margins_average:nobs')
wb_check(checks[47], 0.5730412374002157, 1e-08, 0, 'margins_means:coefficients')
wb_check(checks[48], -0.4370023807343474, 1e-08, 0, 'margins_means:coefficients')
wb_check(checks[49], 0.1167857486671616, 1e-06, 0, 'margins_means:std_errors')
wb_check(checks[50], 0.1008076409375375, 1e-06, 0, 'margins_means:std_errors')
wb_check(checks[51], 300, 0.0, 0.0, 'margins_means:nobs')
