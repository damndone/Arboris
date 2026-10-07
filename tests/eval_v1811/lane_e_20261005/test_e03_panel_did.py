"""E3: actual defaults, final t/F/df/p and small-cluster legacy boundaries."""
import json
import numpy as np
import pandas as pd
import pytest
from workbench.projects import create_project
from workbench.postestimation.registry import run_operation
from support import OUT, REPO, emit, native_stata, fit, save


def frame():
    rng=np.random.default_rng(18112070);n=24*9
    g=np.repeat(np.arange(24),9);time=np.tile(np.arange(9),24)
    x1,x2=rng.normal(size=(2,n));first=np.where(g<12,4,0)
    D=(first>0)&(time>=first)
    y=.45*x1-.2*x2+1.15*D+rng.normal(size=24)[g]+.08*time+rng.normal(size=n)
    return pd.DataFrame({'g':g,'time':time,'first_treat':first,'x1':x1,'x2':x2,'y':y})


@pytest.mark.parametrize('family',['panel_ols','did'])
def test_actual_default_cluster_kernel_and_final_lincom_match_stata(family,tmp_path):
    data=OUT/(family+'.csv');frame().to_csv(data,index=False,float_format='%.17g')
    extra={'did_mode':'cohort','did_cohort_col':'first_treat'} if family=='did' else {}
    root,packet,kernel=fit(create_project(tmp_path,'public').root,data,family,'y',['x1','x2'],entity_col='g',time_col='time',**extra)
    term='_did_D' if family=='did' else 'x1'
    body=f'import delimited "{data}", asdouble clear case(preserve)\nxtset g time\n'
    if family=='did':body+='generate double D=(first_treat>0 & time>=first_treat)\n'
    body+='quietly xtreg y '+('D ' if family=='did' else '')+'x1 x2 '+'i.time '+', fe vce(robust)\n'
    native_term='D' if family=='did' else 'x1'
    body+=emit('b',f'_b[{native_term}]')+'\n'+emit('se',f'_se[{native_term}]')+'\n'+emit('t',f'_b[{native_term}]/_se[{native_term}]')+'\n'+emit('df','e(df_r)')+'\n'
    body+=emit('p',f'2*ttail(e(df_r),abs(_b[{native_term}]/_se[{native_term}]))')+'\n'
    body+='quietly lincom x1-x2\n'+emit('lc','r(estimate)')+'\n'+emit('lc_se','r(se)')+'\n'+emit('lc_p','r(p)')+'\n'
    body+='quietly test x1 x2\n'+emit('wald','r(F)')+'\n'+emit('wald_df','r(df)')+'\n'+emit('wald_den','r(df_r)')+'\n'+emit('wald_p','r(p)')+'\n'
    native=native_stata(body,'e03-'+family,tmp_path)
    lc=run_operation('lincom',[kernel],{'terms':{'x1':1,'x2':-1}})
    wald=run_operation('wald',[kernel],{'constraints':[{'terms':{'x1':1},'value':0},{'terms':{'x2':1},'value':0}]})
    save('e03-'+family,{'run':root,'packet':packet,'kernel':kernel,'native':native,'lincom':lc,'wald':wald})
    row=packet['coefficients'][term]
    for key,ref,tol in [('estimate','b',1e-9),('std_error','se',1e-8),('p_value','p',1e-6)]:assert row[key]==pytest.approx(native[ref],abs=tol,rel=0)
    assert row['estimate']/row['std_error']==pytest.approx(native['t'],abs=1e-8,rel=0)
    assert kernel['covariance_estimator']=='cluster' and kernel['reference_distribution']=='t'
    assert kernel['df_resid']==native['df']==23 and kernel['n_clusters']==24
    assert wald['statistic']==pytest.approx(native['wald'],rel=1e-8,abs=0)
    assert wald['df_num']==native['wald_df'] and wald['df_den']==native['wald_den']
    assert wald['p_value']==pytest.approx(native['wald_p'],abs=1e-6,rel=0)
    assert lc['estimate']==pytest.approx(native['lc'],abs=1e-9,rel=0)
    assert lc['std_error']==pytest.approx(native['lc_se'],abs=1e-8,rel=0)
    assert lc['p_value']==pytest.approx(native['lc_p'],abs=1e-6,rel=0)


def test_event_study_final_leads_f_df_p_match_fresh_stata(tmp_path):
    source=REPO/'tests/fixtures/panel_cluster/staggered.csv'
    project=create_project(tmp_path,'event').root
    root,packet,kernel=fit(project,source,'did','y',['x1'],entity_col='g',time_col='time',did_mode='cohort',did_cohort_col='first_treat')
    diagnostics=json.loads((root/'did_diagnostics.json').read_text());study=diagnostics['event_study']
    times=study['event_time'];names=[f'_evt_{"m" if k<0 else "p"}{abs(k)}' for k in times]
    body=f'import delimited "{source}", asdouble clear case(preserve)\nxtset g time\n'
    for k,key in zip(times,names):body+=f'generate double {key}=(first_treat>0 & time-first_treat=={k})\n'
    body+='quietly xtreg y '+' '.join(names)+' i.time, fe vce(robust)\n'
    for key in names:body+=emit('b'+key,f'_b[{key}]')+'\n'+emit('s'+key,f'_se[{key}]')+'\n'
    body+='quietly test '+' '.join(key for k,key in zip(times,names) if k<0)+'\n'+emit('F','r(F)')+'\n'+emit('df','r(df)')+'\n'+emit('den','r(df_r)')+'\n'+emit('p','r(p)')+'\n'
    native=native_stata(body,'e03-event',tmp_path);save('e03-event',{'native':native,'actual':diagnostics,'run':root})
    for key,b,se in zip(names,study['coef'],study['se']):
        assert b==pytest.approx(native['b'+key],abs=1e-9,rel=0)
        assert se==pytest.approx(native['s'+key],abs=1e-8,rel=0)
    test=diagnostics['parallel_trends']
    assert test['statistic']==pytest.approx(native['F'],rel=1e-8,abs=0)
    assert test['df_num']==native['df'] and test['df_den']==native['den']
    assert test['pvalue']==pytest.approx(native['p'],abs=1e-6,rel=0)


def test_one_threshold_and_old_result_label_preserve_legacy():
    from workbench.analysis_loop.policy import _CLUSTER_COUNT_CAUTION
    from workbench.checks.context import CheckContext
    from workbench.checks.fit_checks import CLUSTER_COUNT,cluster_count
    from workbench.agent.context_tools import _bounded_inference
    assert _CLUSTER_COUNT_CAUTION==CLUSTER_COUNT.threshold('caution_below')==30
    for g,phrase in [(8,'wild cluster bootstrap'),(24,'many clusters')]:
        result=cluster_count(CheckContext(model_id='p',model_type='panel_ols',traits=frozenset({'vce.cluster'}),nobs=200,kernel={'n_clusters':g}),CLUSTER_COUNT)
        assert result.status=='caution' and phrase in f'{result.summary} {result.remedy}'
    legacy={'entity_col':'g','covariance_evidence':{'covariance':'robust','cluster_entity':False}}
    original=json.loads(json.dumps(legacy))
    evidence=_bounded_inference(legacy)
    assert evidence['not_clustered_by_entity'] is True and 'predates v1.8.11' in evidence['inference_note']
    assert legacy==original
