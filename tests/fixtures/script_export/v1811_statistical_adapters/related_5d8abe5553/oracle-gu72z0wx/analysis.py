# Workbench 1.8.11
# project: survey
# run: native
# lineage_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
# Coverage
# model | model.ols | native_with_equivalence_note | Full single-stage linearization design including supplied FPC and domain; Python uses the validated Workbench survey engine and executed t df.
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

def wb_array_model(params,covariance,nobs,df,distribution,design=None,loglik=None,sample=None):
    names=list(params.index);beta=np.asarray(params);covariance=np.asarray(covariance)
    se=np.sqrt(np.diag(covariance));statistic=beta/se
    p=2*(stats.t.sf(np.abs(statistic),df) if distribution=='t' else stats.norm.sf(np.abs(statistic)))
    return dict(beta=dict(zip(names,beta)),se=dict(zip(names,se)),statistic=dict(zip(names,statistic)),
      p=dict(zip(names,p)),covariance=covariance,names=names,df=df if distribution=='t' else None,
      distribution=distribution,nobs=float(nobs),loglik=loglik,link='identity',design=design,sample=sample)

from workbench.survey.adapters import build_design_from_artifacts, glm_estimator_spec
from workbench.survey.engine import estimate_with_design
wb_frame = data['source'].dropna(subset=['y', 'x1', 'x2']).copy()
wb_design = build_design_from_artifacts(wb_frame, {'_sampling_weight': 'weight', '_survey_method': 'linearization', '_survey_df': 'design', '_survey_lonely_psu': 'fail', '_survey_strata_col': 'stratum', '_survey_psu_col': 'psu'})
wb_estimator = glm_estimator_spec(family="ols", glm_family="gaussian", y='y', x=['x1', 'x2'])
wb_survey = estimate_with_design(wb_design,wb_estimator,method="linearization",df_convention='design')
wb_params = pd.Series(wb_survey.estimates).rename(index={"(Intercept)":"Intercept"})
wb_mask = wb_design.subpop_mask()
wb_X = np.column_stack([np.ones(int(wb_mask.sum())),*([wb_frame.loc[wb_mask,c].to_numpy() for c in ['x1', 'x2']])])
results['model'] = wb_array_model(wb_params,wb_survey.covariance,len(wb_frame),wb_survey.inference_degf,"t",design=wb_X,sample=list(wb_frame.index[wb_mask]))
results['model']["df_method"] = 'design'
checks.append(float(results['model']['beta']['Intercept']))
checks.append(float(results['model']['beta']['x1']))
checks.append(float(results['model']['beta']['x2']))
checks.append(float(results['model']['se']['Intercept']))
checks.append(float(results['model']['se']['x1']))
checks.append(float(results['model']['se']['x2']))
checks.append(float(results['model']["nobs"]))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['Intercept']))
checks.append(float(results['model']['p']['Intercept']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x1']))
checks.append(float(results['model']['p']['x1']))
checks.append(float(results['model']['df']))
assert results['model']['distribution'] == 't'
checks.append(float(results['model']['statistic']['x2']))
checks.append(float(results['model']['p']['x2']))
checks.append(float(results['model']['df']))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 4.652711573943123, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[1], 1.475820771771979, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[2], -0.40404481777033774, 1e-08, 1e-06, 'model:coefficients')
wb_check(checks[3], 1.5955241455226616, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[4], 0.17732404110690134, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[5], 0.08888234469730581, 1e-08, 1e-05, 'model:std_errors')
wb_check(checks[6], 80, 0.0, 0.0, 'model:nobs')
wb_check(checks[7], 2.9161022645752492, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[8], 0.019406798019796175, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[9], 8, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[10], 8.322733694537604, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[11], 3.2813378097179405e-05, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[12], 8, 0.0, 0.0, 'model:statistics.df')
wb_check(checks[13], -4.545838874371921, 1e-08, 1e-05, 'model:statistics.value')
wb_check(checks[14], 0.0018846599328036571, 1e-06, 0.0, 'model:statistics.p_value')
wb_check(checks[15], 8, 0.0, 0.0, 'model:statistics.df')
