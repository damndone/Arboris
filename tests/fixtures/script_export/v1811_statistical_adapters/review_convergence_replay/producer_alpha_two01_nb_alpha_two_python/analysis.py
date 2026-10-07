# Workbench 1.8.11
# project: independent
# run: alpha_two
# lineage_hash: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
# Coverage
# model | model.glm:negative_binomial | native | 
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

data['source'] = wb_read('data.csv', '9707e4d6dc11d72fc6240b79a8ba79c8fd884b4edfa237905c086cddded60101', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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
wb_fit = smf.glm("Q('y') ~ Q('x1') + Q('x2')", data=data['source'], family=families.NegativeBinomial(alpha=2.0)).fit(maxiter=1000,tol=1e-12,tol_criterion="params",scale=1)
assert wb_fit.converged, "Fixed-alpha GLM did not converge"
wb_fit._results.normalized_cov_params = np.linalg.inv(-wb_fit.model.hessian(wb_fit.params,observed=False))
wb_fit._results._cache.clear()
assert np.isfinite(wb_fit.params).all() and np.isfinite(np.asarray(wb_fit.cov_params())).all()
results['model'] = wb_model(wb_fit,distribution="z",link="log")
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']['x1']))
checks.append(float(results['model']['beta']['x2']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']['x1']))
checks.append(float(results['model']['se']['x2']))
checks.append(float(results['model']["nobs"]))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 0.431862033963731, 1e-08, 0, 'model:coefficients')
wb_check(checks[1], 0.499237797659053, 1e-08, 0, 'model:coefficients')
wb_check(checks[2], -0.319131636821243, 1e-08, 0, 'model:coefficients')
wb_check(checks[3], 0.108234874866925, 1e-06, 0, 'model:std_errors')
wb_check(checks[4], 0.11295797337987, 1e-06, 0, 'model:std_errors')
wb_check(checks[5], 0.0991705432200099, 1e-06, 0, 'model:std_errors')
wb_check(checks[6], 240, 0.0, 0.0, 'model:nobs')

np.savetxt("cov.tsv",results["model"]["covariance"].reshape(-1)); open("ll.txt","w").write(str(results["model"]["loglik"]))
