# Workbench 1.8.11
# project: script
# run: 20261005_091811_675151_95c6f12b
# lineage_hash: 44cdd1794406cf58e7845d729b4a21bf1c8ddacba382ef059f60da06f836b26d
# Coverage
# step_76b2427e32344554a37924aa | data.cleaning | native | 
# step_eca26cfbad39adff69c00721 | data.subset | native | 
# step_226b4b10776b3612293e8e34 | data.feature_recipe | native | 
# step_5bb28f6498e4698e7347d1d5 | data.cleaning | native | 
# step_59722572b3c11a55aa32ba09 | model.ols | native | 
# step_522468aadb113d7b603dca9b | postestimation.wald | native | 
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
    if fmt in {'dta', 'sav'}:
        import pyreadstat
        reader = pyreadstat.read_dta if fmt == 'dta' else pyreadstat.read_sav
        kwargs = {'apply_value_formats': False, **(options or {})}
        if fmt == 'sav': kwargs['user_missing'] = True
        frame, _metadata = reader(str(path), **kwargs)
        for column in frame.columns:
            values = frame[column].dropna()
            if frame[column].dtype == object and len(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                frame[column] = pd.to_numeric(frame[column])
        return frame
    readers = {'csv': pd.read_csv,
               'xlsx': pd.read_excel, 'parquet': pd.read_parquet}
    return readers[fmt](path, **(options or {}))

def wb_check(actual, expected, absolute, relative, label):
    if not math.isfinite(float(actual)) or abs(actual-expected) > absolute + relative*abs(expected):
        raise AssertionError(f'{label}: {actual!r} != {expected!r}')

data['source_82b3c8c1d9e8aa2c806987d4'] = wb_read('source_1ce21051b81091ccc6d9f8b2.dta', '1ce21051b81091ccc6d9f8b22102b1560bc1b11924f2076b1e94db0b3b002e2f', 'dta', {})
data['step_76b2427e32344554a37924aa'] = data['source_82b3c8c1d9e8aa2c806987d4'].copy()
checks.append(float(len(data['step_76b2427e32344554a37924aa'])))
assert list(data['step_76b2427e32344554a37924aa'].columns) == ['g', 'x', 'z', 'keep', 'y']
data['step_eca26cfbad39adff69c00721'] = data['step_76b2427e32344554a37924aa'].copy()
data['step_eca26cfbad39adff69c00721'] = data['step_eca26cfbad39adff69c00721'].loc[(data['step_eca26cfbad39adff69c00721']['keep'].notna() & (data['step_eca26cfbad39adff69c00721']['keep'] == 1))].copy()
data['step_eca26cfbad39adff69c00721'] = data['step_eca26cfbad39adff69c00721'].loc[:, ['g', 'x', 'z', 'keep', 'y']]
data['step_eca26cfbad39adff69c00721'] = data['step_eca26cfbad39adff69c00721'].reset_index(drop=True)
checks.append(float(len(data['step_eca26cfbad39adff69c00721'])))
assert list(data['step_eca26cfbad39adff69c00721'].columns) == ['g', 'x', 'z', 'keep', 'y']
data['step_226b4b10776b3612293e8e34'] = data['step_eca26cfbad39adff69c00721'].copy()
assert pd.api.types.is_numeric_dtype(data['step_226b4b10776b3612293e8e34']['x'])
assert pd.api.types.is_numeric_dtype(data['step_226b4b10776b3612293e8e34']['z'])
data['step_226b4b10776b3612293e8e34']['xz'] = (data['step_226b4b10776b3612293e8e34']['x'] * data['step_226b4b10776b3612293e8e34']['z'])
checks.append(float(len(data['step_226b4b10776b3612293e8e34'])))
assert list(data['step_226b4b10776b3612293e8e34'].columns) == ['g', 'x', 'z', 'keep', 'y', 'xz']
data['step_5bb28f6498e4698e7347d1d5'] = data['step_226b4b10776b3612293e8e34'].copy()
checks.append(float(len(data['step_5bb28f6498e4698e7347d1d5'])))
assert list(data['step_5bb28f6498e4698e7347d1d5'].columns) == ['g', 'x', 'z', 'keep', 'y', 'xz']
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

wb_frame = data['step_5bb28f6498e4698e7347d1d5'].copy()
wb_fit = smf.ols("Q('y') ~ Q('x') + Q('z') + Q('xz')", data=wb_frame).fit()
wb_groups = wb_frame.loc[wb_fit.model.data.row_labels, 'g']
wb_fit = wb_fit.get_robustcov_results(cov_type="cluster", groups=wb_groups, use_correction=True, df_correction=True, use_t=True)
results['step_59722572b3c11a55aa32ba09'] = wb_model(wb_fit)
checks.append(float(results['step_59722572b3c11a55aa32ba09']['beta']['Intercept']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['beta']['x']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['beta']['z']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['beta']['xz']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['se']['Intercept']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['se']['x']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['se']['z']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['se']['xz']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']["nobs"]))
assert results['step_59722572b3c11a55aa32ba09']['distribution'] == 't'
checks.append(float(results['step_59722572b3c11a55aa32ba09']['statistic']['Intercept']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['p']['Intercept']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['df']))
assert results['step_59722572b3c11a55aa32ba09']['distribution'] == 't'
checks.append(float(results['step_59722572b3c11a55aa32ba09']['statistic']['x']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['p']['x']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['df']))
assert results['step_59722572b3c11a55aa32ba09']['distribution'] == 't'
checks.append(float(results['step_59722572b3c11a55aa32ba09']['statistic']['z']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['p']['z']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['df']))
assert results['step_59722572b3c11a55aa32ba09']['distribution'] == 't'
checks.append(float(results['step_59722572b3c11a55aa32ba09']['statistic']['xz']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['p']['xz']))
checks.append(float(results['step_59722572b3c11a55aa32ba09']['df']))
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

results['step_522468aadb113d7b603dca9b'] = wb_wald(results['step_59722572b3c11a55aa32ba09'], [{'terms': {'x': 1.0}, 'value': 0.0}, {'terms': {'xz': 1.0}, 'value': 0.0}])
results['step_522468aadb113d7b603dca9b']["nobs"] = results['step_59722572b3c11a55aa32ba09']["nobs"]
checks.append(float(results['step_522468aadb113d7b603dca9b']["nobs"]))
checks.append(float(results['step_522468aadb113d7b603dca9b']["statistics"]['test']['value']))
checks.append(float(results['step_522468aadb113d7b603dca9b']["statistics"]['test']['p_value']))
checks.append(float(results['step_522468aadb113d7b603dca9b']["statistics"]['test']['df']))
checks.append(float(results['step_522468aadb113d7b603dca9b']["statistics"]['test']['df_denominator']))
assert results['step_522468aadb113d7b603dca9b']["statistics"]['test']["distribution"] == 'F'
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 640, 0.0, 0.0, 'step_76b2427e32344554a37924aa:nrows')
wb_check(checks[1], 320, 0.0, 0.0, 'step_eca26cfbad39adff69c00721:nrows')
wb_check(checks[2], 320, 0.0, 0.0, 'step_226b4b10776b3612293e8e34:nrows')
wb_check(checks[3], 320, 0.0, 0.0, 'step_5bb28f6498e4698e7347d1d5:nrows')
wb_check(checks[4], 0.9675178036793878, 1e-08, 1e-06, 'step_59722572b3c11a55aa32ba09:coefficients')
wb_check(checks[5], 0.587233907457428, 1e-08, 1e-06, 'step_59722572b3c11a55aa32ba09:coefficients')
wb_check(checks[6], -0.1324647468019746, 1e-08, 1e-06, 'step_59722572b3c11a55aa32ba09:coefficients')
wb_check(checks[7], 0.2877185211968429, 1e-08, 1e-06, 'step_59722572b3c11a55aa32ba09:coefficients')
wb_check(checks[8], 0.06938744595036184, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:std_errors')
wb_check(checks[9], 0.05939583283342683, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:std_errors')
wb_check(checks[10], 0.05576371929506281, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:std_errors')
wb_check(checks[11], 0.060837730532374686, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:std_errors')
wb_check(checks[12], 320, 0.0, 0.0, 'step_59722572b3c11a55aa32ba09:nobs')
wb_check(checks[13], 13.943701060441503, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:statistics.value')
wb_check(checks[14], 1.974202786152289e-11, 1e-06, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.p_value')
wb_check(checks[15], 19.0, 0.0, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.df')
wb_check(checks[16], 9.886786318903908, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:statistics.value')
wb_check(checks[17], 6.320519792921724e-09, 1e-06, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.p_value')
wb_check(checks[18], 19.0, 0.0, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.df')
wb_check(checks[19], -2.375464701360096, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:statistics.value')
wb_check(checks[20], 0.028205935498091514, 1e-06, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.p_value')
wb_check(checks[21], 19.0, 0.0, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.df')
wb_check(checks[22], 4.729277681450231, 1e-08, 1e-05, 'step_59722572b3c11a55aa32ba09:statistics.value')
wb_check(checks[23], 0.00014595711024510102, 1e-06, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.p_value')
wb_check(checks[24], 19.0, 0.0, 0.0, 'step_59722572b3c11a55aa32ba09:statistics.df')
wb_check(checks[25], 320, 0.0, 0.0, 'step_522468aadb113d7b603dca9b:nobs')
wb_check(checks[26], 69.64771978987594, 1e-08, 1e-05, 'step_522468aadb113d7b603dca9b:statistics.value')
wb_check(checks[27], 1.7914693344639517e-09, 1e-06, 0.0, 'step_522468aadb113d7b603dca9b:statistics.p_value')
wb_check(checks[28], 2, 0.0, 0.0, 'step_522468aadb113d7b603dca9b:statistics.df')
wb_check(checks[29], 19.0, 0.0, 0.0, 'step_522468aadb113d7b603dca9b:statistics.df_denominator')
