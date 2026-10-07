# Workbench 1.8.11
# project: sidecar
# run: executed
# lineage_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
# Coverage
# completed | model.ols | snapshot | FPC is supplied, but the frozen Workbench linearization engine does not apply FPC; native FPC would change the executed covariance. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
# post | postestimation.wald | snapshot | Dependent post-estimation needs its own completed Workbench result sidecar; no fitted state is reconstructed. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
# selected | data.subset | native | 
# independent | model.ols | native | 
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

data['source'] = wb_read('data.csv', '5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
# Workbench completed this step: Sampling OLS completed in Workbench
data['completed'] = wb_read('completed.csv', '5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
checks.append(float(len(data['completed'])))
assert list(data['completed'].columns) == ['stratum', 'psu', 'y', 'x1', 'x2', 'weight', 'fpc', 'subpop']
from workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot
wb_result_values1 = read_result_snapshot(base,ResultSnapshotRef(**{'filename': 'completed_result.json', 'sha256': '2ebb9ab7faaddef3a1a1c4a3074f861e1d51a0eb8020e45584312e36b3100d54', 'schema_version': 1}),expected_binding={'project_id': 'sidecar', 'run_id': 'executed', 'lineage_hash': 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 'step_id': 'completed', 'kind': 'model', 'operation': 'model.ols', 'parameters_sha256': 'ac5d6b375ada920a0f3c2d2971f3b8e99504af07a1264115250c054847ab6fb2', 'inputs': ['source'], 'models': []})
assert wb_result_values1["statistics"]['Intercept']["distribution"] == 't'
assert wb_result_values1["statistics"]['x1']["distribution"] == 't'
assert wb_result_values1["statistics"]['x2']["distribution"] == 't'
checks.append(float(wb_result_values1['nobs']))
checks.append(float(wb_result_values1['coefficients']['Intercept']))
checks.append(float(wb_result_values1['coefficients']['x1']))
checks.append(float(wb_result_values1['coefficients']['x2']))
checks.append(float(wb_result_values1['std_errors']['Intercept']))
checks.append(float(wb_result_values1['std_errors']['x1']))
checks.append(float(wb_result_values1['std_errors']['x2']))
checks.append(float(wb_result_values1['statistics']['Intercept']['value']))
checks.append(float(wb_result_values1['statistics']['Intercept']['df']))
checks.append(float(wb_result_values1['statistics']['Intercept']['p_value']))
checks.append(float(wb_result_values1['statistics']['x1']['value']))
checks.append(float(wb_result_values1['statistics']['x1']['df']))
checks.append(float(wb_result_values1['statistics']['x1']['p_value']))
checks.append(float(wb_result_values1['statistics']['x2']['value']))
checks.append(float(wb_result_values1['statistics']['x2']['df']))
checks.append(float(wb_result_values1['statistics']['x2']['p_value']))
# Workbench completed this step: Actual persisted design Wald
data['post'] = data['completed'].copy()
wb_result_values2 = read_result_snapshot(base,ResultSnapshotRef(**{'filename': 'post_result.json', 'sha256': '8041f10d4694d95c968c1147bba04724ca9588cbf776037d37d6dee2f0b81139', 'schema_version': 1}),expected_binding={'project_id': 'sidecar', 'run_id': 'executed', 'lineage_hash': 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 'step_id': 'post', 'kind': 'postestimation', 'operation': 'postestimation.wald', 'parameters_sha256': 'eae0c2c236d26de1d6f48d962cef577e23609bfdaf6abe2c2495e30e1b72f8ce', 'inputs': ['completed'], 'models': ['completed']})
assert wb_result_values2["statistics"]['test']["distribution"] == 'F'
checks.append(float(wb_result_values2['statistics']['test']['value']))
checks.append(float(wb_result_values2['statistics']['test']['df']))
checks.append(float(wb_result_values2['statistics']['test']['df_denominator']))
checks.append(float(wb_result_values2['statistics']['test']['p_value']))
data['selected'] = data['post'].copy()
data['selected'] = data['selected'].loc[:, ['y', 'x1', 'x2']]
data['selected'] = data['selected'].reset_index(drop=True)
checks.append(float(len(data['selected'])))
assert list(data['selected'].columns) == ['y', 'x1', 'x2']
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

wb_frame = data['selected'].copy()
wb_fit = smf.ols("Q('y') ~ Q('x1') + Q('x2')", data=wb_frame).fit()
results['independent'] = wb_model(wb_fit)
checks.append(float(results['independent']['beta']['Intercept']))
checks.append(float(results['independent']['beta']['x1']))
checks.append(float(results['independent']['beta']['x2']))
checks.append(float(results['independent']['se']['Intercept']))
checks.append(float(results['independent']['se']['x1']))
checks.append(float(results['independent']['se']['x2']))
checks.append(float(results['independent']["nobs"]))
# Closing self-checks
wb_check(checks[0], 80, 0.0, 0.0, 'completed:nrows')
wb_check(checks[1], 80, 0.0, 0.0, 'completed:nobs')
wb_check(checks[2], 4.652711573943123, 1e-08, 1e-06, 'completed:coefficients')
wb_check(checks[3], 1.475820771771979, 1e-08, 1e-06, 'completed:coefficients')
wb_check(checks[4], -0.40404481777033774, 1e-08, 1e-06, 'completed:coefficients')
wb_check(checks[5], 1.5955241455226616, 1e-08, 1e-05, 'completed:std_errors')
wb_check(checks[6], 0.17732404110690134, 1e-08, 1e-05, 'completed:std_errors')
wb_check(checks[7], 0.08888234469730581, 1e-08, 1e-05, 'completed:std_errors')
wb_check(checks[8], 2.9161022645752492, 1e-08, 1e-05, 'completed:statistics.value')
wb_check(checks[9], 8, 0.0, 0.0, 'completed:statistics.df')
wb_check(checks[10], 0.019406798019796175, 1e-06, 0.0, 'completed:statistics.p_value')
wb_check(checks[11], 8.322733694537604, 1e-08, 1e-05, 'completed:statistics.value')
wb_check(checks[12], 8, 0.0, 0.0, 'completed:statistics.df')
wb_check(checks[13], 3.2813378097179405e-05, 1e-06, 0.0, 'completed:statistics.p_value')
wb_check(checks[14], -4.545838874371921, 1e-08, 1e-05, 'completed:statistics.value')
wb_check(checks[15], 8, 0.0, 0.0, 'completed:statistics.df')
wb_check(checks[16], 0.0018846599328036571, 1e-06, 0.0, 'completed:statistics.p_value')
wb_check(checks[17], 88.6728244577567, 1e-08, 1e-05, 'post:statistics.value')
wb_check(checks[18], 2, 0.0, 0.0, 'post:statistics.df')
wb_check(checks[19], 7.0, 0.0, 0.0, 'post:statistics.df_denominator')
wb_check(checks[20], 1.0669105752740756e-05, 1e-06, 0.0, 'post:statistics.p_value')
wb_check(checks[21], 80, 0.0, 0.0, 'selected:nrows')
wb_check(checks[22], 4.596321816357483, 1e-08, 1e-06, 'independent:coefficients')
wb_check(checks[23], 1.497109631010229, 1e-08, 1e-06, 'independent:coefficients')
wb_check(checks[24], -0.4181990460548318, 1e-08, 1e-06, 'independent:coefficients')
wb_check(checks[25], 0.6751924283923509, 1e-08, 1e-05, 'independent:std_errors')
wb_check(checks[26], 0.09246563897577949, 1e-08, 1e-05, 'independent:std_errors')
wb_check(checks[27], 0.08312412958648425, 1e-08, 1e-05, 'independent:std_errors')
wb_check(checks[28], 80, 0.0, 0.0, 'independent:nobs')
