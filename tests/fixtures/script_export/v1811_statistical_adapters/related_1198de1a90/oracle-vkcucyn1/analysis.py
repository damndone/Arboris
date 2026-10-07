# Workbench 1.8.11
# project: model-oracle
# run: glm_binomial
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
wb_fit = smf.glm("Q('binary') ~ Q('x') + Q('z')", data=data['source'], family=families.Binomial()).fit(maxiter=100, tol=1e-12)
results['model'] = wb_model(wb_fit, distribution="z", link='logit')
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
wb_check(checks[0], 0.21223972211737696, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 0.5621638375809234, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], -0.2332565315867904, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 0.1120064519941844, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[4], 0.11722060171045612, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.1200130109187133, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 350, 0.0, 0.0, 'model:nobs')
wb_check(checks[7], 1.8948883598990967, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[8], 0.0581071936076671, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[9], 4.795776760893202, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[10], 1.6204566658066975e-06, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[11], -1.9435936970598857, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[12], 0.051944466503299425, 1e-06, 0.0, 'model:statistics.p_value')
