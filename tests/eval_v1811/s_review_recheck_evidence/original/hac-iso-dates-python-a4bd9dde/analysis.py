# Workbench 1.8.11
# project: review
# run: iso-dates
# lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
# Coverage
# model | model.ols | native | 
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

data['source'] = wb_read('data.csv', '4248a622d3d0e5c361e3721f7d0341675a5548cee1ce1c34ff0b02170a01ecb8', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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

wb_frame = data['source'].copy()
wb_frame = wb_frame.sort_values('time', kind="mergesort")
wb_fit = smf.ols("Q('y') ~ Q('x')", data=wb_frame).fit()
wb_fit = wb_fit.get_robustcov_results(cov_type="HAC", maxlags=2, kernel="bartlett", use_correction=True, use_t=True)
results['model'] = wb_model(wb_fit)
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']['x']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']['x']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x']))
checks.append(float(results['model']['p']['x']))
checks.append(float(results['model']['df']))
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 2.029731891227981, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 0.2870153773878842, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], 0.06617361483917072, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[3], 0.07147968356724231, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[4], 240, 0.0, 0.0, 'model:nobs')
wb_check(checks[5], 30.672827775255588, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[6], 1.1803518241590357e-84, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[7], 238.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[8], 4.015342025372613, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[9], 7.959985423803175e-05, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[10], 238.0, 0.0, 0.0, 'model:statistics.df')


