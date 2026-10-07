"""A real regressor named alpha is distinct from fixed dispersion alpha."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.agent.postestimation_steps import execute_postestimation_step
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from tests.eval_v1811.glm_nb_public_review_adversarial import DATA, NATIVE


@pytest.mark.parametrize('name',['alpha','lnalpha'])
def test_real_ancillary_named_covariate_remains_available_for_fixed_glm_post(tmp_path,name):
    # Only the CSV header changes: original numerical values remain byte-identical.
    first, body = DATA.read_bytes().split(b'\n',1)
    names = first.decode().split(','); assert names.count('x3')==1
    names[names.index('x3')]=name
    source=tmp_path/'named.csv'; source.write_bytes(','.join(names).encode()+b'\n'+body)
    assert source.read_bytes().split(b'\n',1)[1]==body
    project=create_project(tmp_path/'projects','named-glm').root
    outcome=run_workflow(project,[source],mode='auto',model_type='glm:negative_binomial',y='ynb',
        x=['x1','x2',name],model_options={'alpha':2.})
    assert outcome['status']=='completed'
    root=project/'runs'/outcome['run_id'];kernel=read_json(root/kernel_relative_path('glm_1'))
    packet=read_json(root/'model_results/glm_1.json')
    assert kernel['param_names']==['Intercept','x1','x2',name]
    assert packet['alpha_fixed_value']==2. and not packet['alpha_estimated']
    ref=read_json(NATIVE)['full_precision']['2']
    assert kernel['params'][3]==pytest.approx(float(ref['full']['beta']['x3']),rel=1e-6)
    requests={
        'wald': {'constraints':[{'terms':{'x2':1,name:1},'value':0}]},
        'lincom': {'terms':{'x2':1,name:-.3},'constant':.2},
        'nlcom': {'expression':'exp('+name+')'},
        'margins': {'variables':[name],'at':'average'},
    }
    for op,spec in requests.items():
        step=SimpleNamespace(operation_id='postestimation.'+op,depends_on=(),
            spec={'model_ref':'model:glm_1',**spec})
        value=execute_postestimation_step(project,root.name,step)[0]
        observed=value['effects'][0] if op=='margins' else value
        expected=ref['margins']['average'] if op=='margins' else ref[op]
        for key in ['estimate','std_error','statistic','p_value']:
            if key in expected:
                assert observed[key]==pytest.approx(float(expected[key]),
                    rel=1e-5 if key=='p_value' or (key=='std_error' and op=='margins') else 1e-6)
        json.dumps(value,allow_nan=False)
    print(json.dumps({'named_regressor':name,'run_root':str(root),'fixed_alpha':2.,'operations':list(requests)}))
