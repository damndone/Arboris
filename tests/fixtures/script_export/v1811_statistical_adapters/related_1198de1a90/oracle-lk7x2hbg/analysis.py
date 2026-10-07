# Workbench 1.8.11
# project: categories
# run: branches
# lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
# Coverage
# weighted | model.ols | native | 
# plain | model.ols | native | 
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

data['source'] = wb_read('data.csv', '050b189f5fcd4768e53803d4dfeed0b822fe264a03c4d5414075e42e6a313024', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
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
wb_frame = wb_frame.loc[wb_frame.index.repeat(wb_frame['fw'].astype(int))].reset_index(drop=True)
wb_fit = smf.ols("Q('y') ~ Q('x') + C(Q('region'))", data=wb_frame).fit()
results['weighted'] = wb_model(wb_fit)
checks.append(float(results['weighted']['beta']['Intercept']))
checks.append(float(results['weighted']['beta']["C(Q('region'))[T.south]"]))
checks.append(float(results['weighted']['beta']["C(Q('region'))[T.west]"]))
checks.append(float(results['weighted']['beta']['x']))
checks.append(float(results['weighted']['se']['Intercept']))
checks.append(float(results['weighted']['se']["C(Q('region'))[T.south]"]))
checks.append(float(results['weighted']['se']["C(Q('region'))[T.west]"]))
checks.append(float(results['weighted']['se']['x']))
checks.append(float(results['weighted']["nobs"]))
wb_frame = data['source'].copy()
wb_fit = smf.ols("Q('y') ~ Q('x') + C(Q('region'))", data=wb_frame).fit()
results['plain'] = wb_model(wb_fit)
checks.append(float(results['plain']['beta']['Intercept']))
checks.append(float(results['plain']['beta']["C(Q('region'))[T.south]"]))
checks.append(float(results['plain']['beta']["C(Q('region'))[T.west]"]))
checks.append(float(results['plain']['beta']['x']))
checks.append(float(results['plain']['se']['Intercept']))
checks.append(float(results['plain']['se']["C(Q('region'))[T.south]"]))
checks.append(float(results['plain']['se']["C(Q('region'))[T.west]"]))
checks.append(float(results['plain']['se']['x']))
checks.append(float(results['plain']["nobs"]))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 1.1406181831101954, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[1], -0.08780030675457805, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[2], -0.10670733571832419, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[3], 0.5668151259087681, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[4], 0.06512778819857358, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[5], 0.0938599257916859, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[6], 0.0910083263007167, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[7], 0.036096598808836394, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[8], 692, 0.0, 0.0, 'weighted:nobs')
wb_check(checks[9], 1.1525369575209923, 1e-08, 1e-06, 'plain:coefficients')
wb_check(checks[10], -0.07713734612483514, 1e-08, 1e-06, 'plain:coefficients')
wb_check(checks[11], -0.12606025144491617, 1e-08, 1e-06, 'plain:coefficients')
wb_check(checks[12], 0.5722984010583434, 1e-08, 1e-06, 'plain:coefficients')
wb_check(checks[13], 0.0907095488404284, 1e-08, 1e-05, 'plain:std_errors')
wb_check(checks[14], 0.12857751264891099, 1e-08, 1e-05, 'plain:std_errors')
wb_check(checks[15], 0.1283082512402164, 1e-08, 1e-05, 'plain:std_errors')
wb_check(checks[16], 0.051233154659256375, 1e-08, 1e-05, 'plain:std_errors')
wb_check(checks[17], 350, 0.0, 0.0, 'plain:nobs')
