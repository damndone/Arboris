# Workbench 1.8.11
# project: model-oracle
# run: glm_poisson
# lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
# Coverage
# model | model.glm | native | 
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

data['source'] = wb_read('data.csv', '0f643fba418a92bc7a08befa218425056e866314340e1148775107241af4e143', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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
wb_fit = smf.glm("Q('count') ~ Q('x') + Q('z')", data=data['source'], family=families.Poisson()).fit(maxiter=100, tol=1e-12)
results['model'] = wb_model(wb_fit, distribution="z", link='log')
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']['x']))
checks.append(float(results['model']['beta']['z']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']['x']))
checks.append(float(results['model']['se']['z']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 'z'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
assert results['model']['distribution'] == 'z'
checks.append(float(results['model']['statistic']['x']))
checks.append(float(results['model']['p']['x']))
assert results['model']['distribution'] == 'z'
checks.append(float(results['model']['statistic']['z']))
checks.append(float(results['model']['p']['z']))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 0.10396571524991229, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 0.37818762298179404, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], -0.22000781353014975, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 0.05268928385125403, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[4], 0.04757957492734309, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.05226849883001865, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 350, 0.0, 0.0, 'model:nobs')
wb_check(checks[7], 1.9731852029611112, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[8], 0.04847446569865196, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[9], 7.948528829005084, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[10], 1.887394208540221e-15, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[11], -4.209185617624734, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[12], 2.5629277905377592e-05, 1e-06, 0.0, 'model:statistics.p_value')
