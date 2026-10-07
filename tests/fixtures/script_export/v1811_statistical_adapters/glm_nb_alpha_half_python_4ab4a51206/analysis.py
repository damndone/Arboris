# Workbench 1.8.11
# project: glm_nb
# run: 0.5
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# full | model.glm:negative_binomial | native | 
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
wb_fit = smf.glm("Q('ynb') ~ Q('x1') + Q('x2') + Q('x3')", data=data['source'], family=families.NegativeBinomial(alpha=0.5)).fit(maxiter=1000,tol=1e-12,tol_criterion="params",scale=1)
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
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 0.5294190766274965, 1e-08, 0, 'full:coefficients')
wb_check(checks[1], 0.3808453229171612, 1e-08, 0, 'full:coefficients')
wb_check(checks[2], -0.29806517727677795, 1e-08, 0, 'full:coefficients')
wb_check(checks[3], -0.10833250363412572, 1e-08, 0, 'full:coefficients')
wb_check(checks[4], 0.14028025583591924, 1e-06, 0, 'full:std_errors')
wb_check(checks[5], 0.06283421954867592, 1e-06, 0, 'full:std_errors')
wb_check(checks[6], 0.05471088883162485, 1e-06, 0, 'full:std_errors')
wb_check(checks[7], 0.1217725004803211, 1e-06, 0, 'full:std_errors')
wb_check(checks[8], 300, 0.0, 0.0, 'full:nobs')
