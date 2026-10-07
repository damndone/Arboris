# Workbench 1.8.11
# project: review
# run: numeric-category
# lineage_hash: 5555555555555555555555555555555555555555555555555555555555555555
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

data['source'] = wb_read('data.csv', 'fa0eee67f28f532930ea73da2c4061309cead39a55c6a6c25d95fd89f917b105', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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
wb_fit = smf.ols("Q('y') ~ Q('x') + C(Q('category'))", data=wb_frame).fit()
results['model'] = wb_model(wb_fit)
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']["C(Q('category'))[T.2.0]"]))
checks.append(float(results['model']['beta']["C(Q('category'))[T.3.0]"]))
checks.append(float(results['model']['beta']['x']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']["C(Q('category'))[T.2.0]"]))
checks.append(float(results['model']['se']["C(Q('category'))[T.3.0]"]))
checks.append(float(results['model']['se']['x']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']["C(Q('category'))[T.2.0]"]))
checks.append(float(results['model']['p']["C(Q('category'))[T.2.0]"]))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']["C(Q('category'))[T.3.0]"]))
checks.append(float(results['model']['p']["C(Q('category'))[T.3.0]"]))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x']))
checks.append(float(results['model']['p']['x']))
checks.append(float(results['model']['df']))
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 1.2708994017897324, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 0.7035527108942035, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], 1.5708783411633434, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 0.3286601725683639, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[4], 0.10937400678256705, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.1563678541895355, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 0.1535480729297494, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[7], 0.0642479068074436, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[8], 240, 0.0, 0.0, 'model:nobs')
wb_check(checks[9], 11.619757190721288, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[10], 5.575649993018833e-25, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[11], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[12], 4.499343644131729, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[13], 1.070297878290555e-05, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[14], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[15], 10.230531137190138, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[16], 1.4335782806912002e-20, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[17], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[18], 5.115500082413364, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[19], 6.477886934670725e-07, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[20], 236.0, 0.0, 0.0, 'model:statistics.df')


