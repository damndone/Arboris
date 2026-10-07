# Workbench 1.8.11
# project: review
# run: branch-isolation
# lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
# Coverage
# categorical | model.ols | native | 
# continuous | model.ols | native | 
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

data['source'] = wb_read('data.csv', '0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f', 'csv', {})
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
results['categorical'] = wb_model(wb_fit)
checks.append(float(results['categorical']['beta']['Intercept']))
checks.append(float(results['categorical']['beta']["C(Q('category'))[T.2]"]))
checks.append(float(results['categorical']['beta']["C(Q('category'))[T.3]"]))
checks.append(float(results['categorical']['beta']['x']))
checks.append(float(results['categorical']['se']['Intercept']))
checks.append(float(results['categorical']['se']["C(Q('category'))[T.2]"]))
checks.append(float(results['categorical']['se']["C(Q('category'))[T.3]"]))
checks.append(float(results['categorical']['se']['x']))
checks.append(float(results['categorical']["nobs"]))
assert results['categorical']['distribution'] == 't'
checks.append(float(results['categorical']['statistic']['Intercept']))
checks.append(float(results['categorical']['p']['Intercept']))
checks.append(float(results['categorical']['df']))
assert results['categorical']['distribution'] == 't'
checks.append(float(results['categorical']['statistic']["C(Q('category'))[T.2]"]))
checks.append(float(results['categorical']['p']["C(Q('category'))[T.2]"]))
checks.append(float(results['categorical']['df']))
assert results['categorical']['distribution'] == 't'
checks.append(float(results['categorical']['statistic']["C(Q('category'))[T.3]"]))
checks.append(float(results['categorical']['p']["C(Q('category'))[T.3]"]))
checks.append(float(results['categorical']['df']))
assert results['categorical']['distribution'] == 't'
checks.append(float(results['categorical']['statistic']['x']))
checks.append(float(results['categorical']['p']['x']))
checks.append(float(results['categorical']['df']))
wb_frame = data['source'].copy()
wb_fit = smf.ols("Q('y') ~ Q('x') + Q('category')", data=wb_frame).fit()
results['continuous'] = wb_model(wb_fit)
checks.append(float(results['continuous']['beta']['Intercept']))
checks.append(float(results['continuous']['beta']['x']))
checks.append(float(results['continuous']['beta']['category']))
checks.append(float(results['continuous']['se']['Intercept']))
checks.append(float(results['continuous']['se']['x']))
checks.append(float(results['continuous']['se']['category']))
checks.append(float(results['continuous']["nobs"]))
assert results['continuous']['distribution'] == 't'
checks.append(float(results['continuous']['statistic']['Intercept']))
checks.append(float(results['continuous']['p']['Intercept']))
checks.append(float(results['continuous']['df']))
assert results['continuous']['distribution'] == 't'
checks.append(float(results['continuous']['statistic']['x']))
checks.append(float(results['continuous']['p']['x']))
checks.append(float(results['continuous']['df']))
assert results['continuous']['distribution'] == 't'
checks.append(float(results['continuous']['statistic']['category']))
checks.append(float(results['continuous']['p']['category']))
checks.append(float(results['continuous']['df']))
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 1.2708994017897324, 1e-08, 1e-06, 'categorical:coefficients')
wb_check(checks[1], 0.7035527108942035, 1e-08, 1e-06, 'categorical:coefficients')
wb_check(checks[2], 1.5708783411633434, 1e-08, 1e-06, 'categorical:coefficients')
wb_check(checks[3], 0.3286601725683639, 1e-08, 1e-06, 'categorical:coefficients')
wb_check(checks[4], 0.10937400678256705, 1e-08, 1e-05, 'categorical:std_errors')
wb_check(checks[5], 0.1563678541895355, 1e-08, 1e-05, 'categorical:std_errors')
wb_check(checks[6], 0.1535480729297494, 1e-08, 1e-05, 'categorical:std_errors')
wb_check(checks[7], 0.0642479068074436, 1e-08, 1e-05, 'categorical:std_errors')
wb_check(checks[8], 240, 0.0, 0.0, 'categorical:nobs')
wb_check(checks[9], 11.619757190721288, 1e-08, 1e-05, 'categorical:statistics.value')
wb_check(checks[10], 5.575649993018833e-25, 1e-06, 0.0, 'categorical:statistics.p_value')
wb_check(checks[11], 236.0, 0.0, 0.0, 'categorical:statistics.df')
wb_check(checks[12], 4.499343644131729, 1e-08, 1e-05, 'categorical:statistics.value')
wb_check(checks[13], 1.070297878290555e-05, 1e-06, 0.0, 'categorical:statistics.p_value')
wb_check(checks[14], 236.0, 0.0, 0.0, 'categorical:statistics.df')
wb_check(checks[15], 10.230531137190138, 1e-08, 1e-05, 'categorical:statistics.value')
wb_check(checks[16], 1.4335782806912002e-20, 1e-06, 0.0, 'categorical:statistics.p_value')
wb_check(checks[17], 236.0, 0.0, 0.0, 'categorical:statistics.df')
wb_check(checks[18], 5.115500082413364, 1e-08, 1e-05, 'categorical:statistics.value')
wb_check(checks[19], 6.477886934670725e-07, 1e-06, 0.0, 'categorical:statistics.p_value')
wb_check(checks[20], 236.0, 0.0, 0.0, 'categorical:statistics.df')
wb_check(checks[21], 0.4566572648686139, 1e-08, 1e-06, 'continuous:coefficients')
wb_check(checks[22], 0.33613214971634603, 1e-08, 1e-06, 'continuous:coefficients')
wb_check(checks[23], 0.7861311171736707, 1e-08, 1e-06, 'continuous:coefficients')
wb_check(checks[24], 0.1656192709774661, 1e-08, 1e-05, 'continuous:std_errors')
wb_check(checks[25], 0.06297017907816094, 1e-08, 1e-05, 'continuous:std_errors')
wb_check(checks[26], 0.07666303913940116, 1e-08, 1e-05, 'continuous:std_errors')
wb_check(checks[27], 240, 0.0, 0.0, 'continuous:nobs')
wb_check(checks[28], 2.757271313739486, 1e-08, 1e-05, 'continuous:statistics.value')
wb_check(checks[29], 0.006282536599842314, 1e-06, 0.0, 'continuous:statistics.p_value')
wb_check(checks[30], 237.0, 0.0, 0.0, 'continuous:statistics.df')
wb_check(checks[31], 5.337957659277517, 1e-08, 1e-05, 'continuous:statistics.value')
wb_check(checks[32], 2.1978864882588204e-07, 1e-06, 0.0, 'continuous:statistics.p_value')
wb_check(checks[33], 237.0, 0.0, 0.0, 'continuous:statistics.df')
wb_check(checks[34], 10.254369328408696, 1e-08, 1e-05, 'continuous:statistics.value')
wb_check(checks[35], 1.1722180535591328e-20, 1e-06, 0.0, 'continuous:statistics.p_value')
wb_check(checks[36], 237.0, 0.0, 0.0, 'continuous:statistics.df')


