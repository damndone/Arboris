# Workbench 1.8.11
# project: review
# run: internal-column
# lineage_hash: 2222222222222222222222222222222222222222222222222222222222222222
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
wb_fit = smf.ols("Q('y') ~ Q('wb_cat0') + C(Q('category'))", data=wb_frame).fit()
results['model'] = wb_model(wb_fit)
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']["C(Q('category'))[T.2]"]))
checks.append(float(results['model']['beta']["C(Q('category'))[T.3]"]))
checks.append(float(results['model']['beta']['wb_cat0']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']["C(Q('category'))[T.2]"]))
checks.append(float(results['model']['se']["C(Q('category'))[T.3]"]))
checks.append(float(results['model']['se']['wb_cat0']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']["C(Q('category'))[T.2]"]))
checks.append(float(results['model']['p']["C(Q('category'))[T.2]"]))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']["C(Q('category'))[T.3]"]))
checks.append(float(results['model']['p']["C(Q('category'))[T.3]"]))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['wb_cat0']))
checks.append(float(results['model']['p']['wb_cat0']))
checks.append(float(results['model']['df']))
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 1.3535431849425417, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 0.5355131851309874, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], 1.5052757759719748, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 0.012904407887460556, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[4], 0.1148576860774841, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.16341097766868193, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 0.16317681892709418, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[7], 0.06663453232839193, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[8], 240, 0.0, 0.0, 'model:nobs')
wb_check(checks[9], 11.78452423314038, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[10], 1.6316144141067668e-25, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[11], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[12], 3.277094310131037, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[13], 0.0012067239241645097, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[14], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[15], 9.224813829987196, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[16], 1.6556596795009354e-17, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[17], 236.0, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[18], 0.19365946509332954, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[19], 0.8466091101084966, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[20], 236.0, 0.0, 0.0, 'model:statistics.df')


