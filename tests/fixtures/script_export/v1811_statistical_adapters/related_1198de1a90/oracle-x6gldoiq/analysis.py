# Workbench 1.8.11
# project: weighted
# run: frequency_clustered
# lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
# Coverage
# weighted | model.ols | native | 
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

wb_frame = data['source'].copy()
wb_frame = wb_frame.loc[wb_frame.index.repeat(wb_frame['fw'].astype(int))].reset_index(drop=True)
wb_fit = smf.ols("Q('y') ~ Q('x') + Q('z')", data=wb_frame).fit()
wb_groups = wb_frame.loc[wb_fit.model.data.row_labels, 'group']
wb_fit = wb_fit.get_robustcov_results(cov_type="cluster", groups=wb_groups, use_correction=True, df_correction=True, use_t=True)
results['weighted'] = wb_model(wb_fit)
checks.append(float(results['weighted']['beta']['Intercept']))
checks.append(float(results['weighted']['beta']['x']))
checks.append(float(results['weighted']['beta']['z']))
checks.append(float(results['weighted']['se']['Intercept']))
checks.append(float(results['weighted']['se']['x']))
checks.append(float(results['weighted']['se']['z']))
checks.append(float(results['weighted']["nobs"]))
assert results['weighted']['distribution'] == 't'
checks.append(float(results['weighted']['statistic']['Intercept']))
checks.append(float(results['weighted']['p']['Intercept']))
checks.append(float(results['weighted']['df']))
assert results['weighted']['distribution'] == 't'
checks.append(float(results['weighted']['statistic']['x']))
checks.append(float(results['weighted']['p']['x']))
checks.append(float(results['weighted']['df']))
assert results['weighted']['distribution'] == 't'
checks.append(float(results['weighted']['statistic']['z']))
checks.append(float(results['weighted']['p']['z']))
checks.append(float(results['weighted']['df']))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 1.080826265723113, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[1], 0.5820891821643995, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[2], -0.22671969920741292, 1e-08, 1e-06, 'weighted:coefficients')
wb_check(checks[3], 0.046850225611337275, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[4], 0.05807633777815511, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[5], 0.054508754337820736, 1e-08, 1e-05, 'weighted:std_errors')
wb_check(checks[6], 692, 0.0, 0.0, 'weighted:nobs')
wb_check(checks[7], 23.06981987001497, 1e-08, 1e-05, 'weighted:statistics.value')
wb_check(checks[8], 2.399522848457571e-22, 1e-06, 0.0, 'weighted:statistics.p_value')
wb_check(checks[9], 34.0, 0.0, 0.0, 'weighted:statistics.df')
wb_check(checks[10], 10.022828649904078, 1e-08, 1e-05, 'weighted:statistics.value')
wb_check(checks[11], 1.100350365088937e-11, 1e-06, 0.0, 'weighted:statistics.p_value')
wb_check(checks[12], 34.0, 0.0, 0.0, 'weighted:statistics.df')
wb_check(checks[13], -4.159326368060188, 1e-08, 1e-05, 'weighted:statistics.value')
wb_check(checks[14], 0.000204625427640698, 1e-06, 0.0, 'weighted:statistics.p_value')
wb_check(checks[15], 34.0, 0.0, 0.0, 'weighted:statistics.df')
