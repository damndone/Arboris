"""E4: available operations consume real persisted owner kernels; unavailable reject."""
import json
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from workbench.projects import create_project
from workbench.agent.postestimation_steps import execute_postestimation_step
from workbench.postestimation.registry import require_validated,validated_operations
from workbench.postestimation.core import PostestimationRefusal
from support import OUT,fit,native_r,save


@pytest.fixture(scope='module')
def cases(tmp_path_factory):
    temp=tmp_path_factory.mktemp('e04-native');project=create_project(temp,'public-post').root
    rng=np.random.default_rng(18112080);n=850;x,z=rng.normal(size=(2,n));eta=.2+.35*x-.25*z;mu=np.exp(eta)
    frame=pd.DataFrame({'x1':x,'x2':z,'yb':rng.binomial(1,1/(1+np.exp(-eta))),'yp':rng.poisson(mu),'ynb':rng.negative_binomial(1/1.3,1/(1+1.3*mu))})
    data=OUT/'e04-public-data.csv';frame.to_csv(data,index=False,float_format='%.17g')
    native=native_r(__import__('pathlib').Path(__file__).with_name('native_glm.R').read_text(),data,'e04-glm',temp)['results']
    roots={}
    for kind,y in [('binomial','yb'),('poisson','yp'),('negative_binomial','ynb')]:
        for role,xcols in [('full',['x1','x2']),('restricted',['x1'])]:
            roots[kind,role]=fit(project,data,'glm:'+kind,y,xcols,model_options={'alpha':1.3} if kind=='negative_binomial' else {})[0]
    return project,roots,native


@pytest.mark.parametrize('kind',['binomial','poisson','negative_binomial'])
@pytest.mark.parametrize('case',['wald','lincom','nlcom','lr','margins_average','margins_means'])
def test_final_registered_public_post_values_match_real_r(cases,kind,case):
    project,roots,native=cases;root=roots[kind,'full']
    operation='margins' if case.startswith('margins_') else case
    specs={'wald':{'constraints':[{'terms':{'x1':1},'value':0},{'terms':{'x2':1},'value':0}]},
        'lincom':{'terms':{'x1':1,'x2':-.4},'constant':.1},'nlcom':{'expression':'exp(x1)'},
        'lr':{'restricted_model_ref':'model:glm_1','restricted_model_run_id':roots[kind,'restricted'].name},
        'margins_average':{'variables':['x1'],'at':'average'},'margins_means':{'variables':['x1'],'at':'means'}}
    step=SimpleNamespace(operation_id='postestimation.'+operation,spec={'model_ref':'model:glm_1',**specs[case]},depends_on=())
    actual=execute_postestimation_step(project,root.name,step)[0]
    numeric=actual['effects'][0] if operation=='margins' else actual
    expected=native[kind]['margins'][case.split('_')[1]] if operation=='margins' else native[kind][operation]
    save('e04-'+kind+'-'+case,{'owner':root,'expected':expected,'actual':actual})
    for key,value in expected.items():
        assert numeric[key]==pytest.approx(value,rel=1e-5 if key=='p_value' or (operation=='margins' and key=='std_error') else 1e-6,abs=0),(kind,case,key)
    assert operation in validated_operations('glm:'+kind)


@pytest.mark.parametrize('operation',['wald','lincom','nlcom','lr','margins'])
def test_lmm_post_does_not_gain_validation_from_successful_fit(operation):
    with pytest.raises(PostestimationRefusal) as caught:require_validated('linear_mixed_effects',operation)
    assert caught.value.code=='NOT_YET_VALIDATED'


def test_iv_lr_refuses_no_likelihood_and_panel_margins_remain_unvalidated():
    from workbench.postestimation.registry import run_operation
    kernel={'interfaces':[],'model_type':'iv_2sls'}
    with pytest.raises(PostestimationRefusal) as caught:run_operation('lr',[kernel,kernel],{})
    assert caught.value.code=='INTERFACE_UNAVAILABLE'
    with pytest.raises(PostestimationRefusal,match='not yet been checked'):require_validated('panel_ols','margins')


def test_public_two_endogenous_iv_wald_lincom_nlcom_match_fresh_stata(tmp_path):
    from support import REPO,emit,native_stata
    from workbench.postestimation.registry import run_operation
    data=REPO/'tests/fixtures/postestimation/iv_two_endogenous_v1811/data.csv'
    root,packet,kernel=fit(create_project(tmp_path,'iv').root,data,'iv_2sls','y',['x1'],iv_endog=['xe1','xe2'],iv_instruments=['z1','z2'])
    body=f'import delimited "{data}", asdouble clear case(preserve)\nquietly ivregress 2sls y x1 (xe1 xe2=z1 z2), vce(robust)\nquietly test xe1 xe2\n'
    body+=emit('wald','r(chi2)')+'\n'+emit('wald_df','r(df)')+'\n'+emit('wald_p','r(p)')+'\n'
    body+='quietly lincom x1-.4*xe1+.1\n'+emit('lincom','r(estimate)')+'\n'+emit('lincom_se','r(se)')+'\n'+emit('lincom_p','r(p)')+'\n'
    body+='quietly nlcom exp(_b[xe2]), post\n'+emit('nlcom','_b[_nl_1]')+'\n'+emit('nlcom_se','_se[_nl_1]')+'\n'
    native=native_stata(body,'e04-iv',tmp_path)
    actual={
        'wald':run_operation('wald',[kernel],{'constraints':[{'terms':{'xe1':1},'value':0},{'terms':{'xe2':1},'value':0}]}),
        'lincom':run_operation('lincom',[kernel],{'terms':{'x1':1,'xe1':-.4},'constant':.1}),
        'nlcom':run_operation('nlcom',[kernel],{'expression':'exp(xe2)'})}
    save('e04-iv',{'owner':root,'native':native,'actual':actual})
    assert actual['wald']['statistic']==pytest.approx(native['wald'],rel=1e-6,abs=0)
    assert actual['wald']['df_num']==native['wald_df']
    assert actual['wald']['p_value']==pytest.approx(native['wald_p'],rel=1e-5,abs=0)
    for key in ['lincom','nlcom']:
        assert actual[key]['estimate']==pytest.approx(native[key],rel=1e-6,abs=0)
        assert actual[key]['std_error']==pytest.approx(native[key+'_se'],rel=1e-6,abs=0)
    assert actual['lincom']['p_value']==pytest.approx(native['lincom_p'],rel=1e-5,abs=0)
