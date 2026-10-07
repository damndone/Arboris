"""Execute the frozen basic intent after explicitly supplying required columns."""
from dataclasses import replace
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from workbench.data_operation_registry import get_data_operation
from workbench.econometrics import runner
from workbench.contracts.model.inference_kernel import build_inference_kernel
from workbench.contracts.common.envelope import thaw_json
from workbench.postestimation.registry import run_operation
from workbench.script_export.plan import LANGUAGES, ScriptPlan
from test_script_export_data_oracles import fresh_directory,source,execute
from test_script_export_postestimation_oracles import expected_from
from test_script_export_render import renderer


@pytest.mark.parametrize('language',LANGUAGES)
def test_validated_basic_real_registry_runner(language):
    directory=fresh_directory();root=Path(__file__).parent/'fixtures/script_export/basic'
    plan=ScriptPlan.from_dict(json.loads((root/'plan.json').read_text()))
    d=pd.read_csv(root/'data.csv');steps=[]
    for original in plan.steps[:2]:
        parameters=thaw_json(original.parameters)
        if original.operation=='data.subset':parameters['columns']=list(d.columns)
        declaration=get_data_operation(original.operation)
        declaration.validate(parameters)
        d=declaration.run(d,parameters)
        steps.append(replace(original,parameters=parameters,expected={'nrows':len(d),'columns':list(d.columns)}))
    original=plan.steps[2];p=original.parameters;sink=[]
    result,fit=runner.run_ols(d,p['y'],list(p['x']),False,'basic',categorical_x=set(p['categorical_x']),covariance=p['covariance'],cluster_col=p['cluster'],fitted_sink=sink.append)
    fit=sink[0];names=list(result['coefficients'])
    expected={'nobs':result['nobs'],'coefficients':{k:v['estimate'] for k,v in result['coefficients'].items()},'std_errors':{k:v['std_error'] for k,v in result['coefficients'].items()}}
    steps.append(replace(original,expected=expected))
    kernel=build_inference_kernel(model_id='basic',model_type='ols',param_names=names,params=np.asarray(fit.params),vcov=fit.cov_params(),reference_distribution='t',df_resid=float(fit.df_resid_inference),loglik=fit.llf,nobs=int(fit.nobs),covariance_estimator='cluster',estimation_sample_fingerprint='basic',df_method='clusters_minus_one',n_clusters=int(d.firm.nunique()))
    test=run_operation('wald',[kernel],{'constraints':[{'terms':{'educ':1},'value':0},{'terms':{'age':1},'value':0}]},{})
    steps.append(replace(plan.steps[3],expected=expected_from(test)))
    plan=replace(plan,sources=(source(directory,pd.read_csv(root/'data.csv'),'data.csv','source:1'),),steps=tuple(steps))
    code,output=execute(renderer()(plan,language,require_native=True),directory,plan)
    assert code==0,output
