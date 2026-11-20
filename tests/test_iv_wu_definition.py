"""Owned homoskedastic Wu T2, independently pinned by a hand-solvable design."""
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from linearmodels.iv import IV2SLS

from workbench.econometrics.panel_iv import run_iv_2sls
from workbench.engine.iv_diagnostics import build_iv_diagnostics
from workbench.estimation_engine import iv, native


def hand_frame(shift=0):
    a=np.array([1,1,1,1,-1,-1,-1,-1.])
    b=np.array([1,1,-1,-1,1,1,-1,-1.])
    c=np.array([1,-1,1,-1,1,-1,1,-1.])
    return pd.DataFrame({'y':a+2*c+b+a*b,'d':a+c,'z1':a,'z2':b+shift,'w':a*b})


@pytest.mark.parametrize('engine',['reference','fast'])
def test_real_runtime_wu_is_invariant_to_instrument_translation(engine):
    if engine=='fast' and not native.available():
        pytest.skip('native engine is not built')
    assert Fraction(20-16)/Fraction(16,5)==Fraction(5,4)
    for shift in (0,1):
        _,fitted=run_iv_2sls(hand_frame(shift),'y',[],['d'],['z1','z2'],'iv_hand',
                             covariance='unadjusted',estimation_engine=engine)
        result=build_iv_diagnostics(fitted,1,2)['endogeneity']
        assert result['test']=='wu_hausman'
        assert result['reference_distribution']=='F(1,5)'
        assert result['statistic']==pytest.approx(5/4,rel=1e-12,abs=0)
        assert result['pvalue']==pytest.approx(0.31437263764701706,rel=1e-12,abs=0)


def test_real_fast_selfcheck_uses_the_same_full_instrument_definition(monkeypatch):
    if not native.available():
        pytest.skip('native engine is not built')
    observed=[]
    original=iv.disagreements
    def compare(mine,reference,nobs):
        if 'wu_hausman' in mine:
            observed.append((mine['wu_hausman'],reference['wu_hausman']))
        return original(mine,reference,nobs)
    monkeypatch.setattr(iv,'disagreements',compare)
    base=iv._self_check_fixture()
    x=np.column_stack([np.ones(len(base)),base[['w','d']]])
    z=np.column_stack([np.ones(len(base)),base[['w','z1','z2']]])
    residual=base.d.to_numpy()-z@np.linalg.lstsq(z,base.d,rcond=None)[0]
    ordinary=base.y.to_numpy()-x@np.linalg.lstsq(x,base.y,rcond=None)[0]
    augmented=np.column_stack([x,residual])
    control=base.y.to_numpy()-augmented@np.linalg.lstsq(augmented,base.y,rcond=None)[0]
    expected=(ordinary@ordinary-control@control)/(control@control/(len(base)-4))
    try:
        for shift in (0,3):
            frame=base.copy();frame['z1']+=shift*(1+frame.w)
            monkeypatch.setattr(iv,'_self_check_fixture',lambda: frame)
            iv._self_check.cache_clear()
            assert iv._self_check() is None
        for mine,reference in observed:
            assert mine==pytest.approx(expected,rel=1e-9,abs=1e-12)
            assert reference==pytest.approx(expected,rel=1e-9,abs=1e-12)
        assert len(observed)==2
    finally:
        iv._self_check.cache_clear()


def test_selfcheck_does_not_recompute_or_hide_a_corrupt_native_wu_slot(monkeypatch):
    if not native.available():
        pytest.skip('native engine is not built')
    original=iv._fit
    def corrupt(*args,**kwargs):
        result=original(*args,**kwargs)
        if result is not None and result.cov_type=='unadjusted':
            result.wu_hausman_test=iv.TestStatistic(result.wu_hausman().stat+1,1,396)
        return result
    monkeypatch.setattr(iv,'_fit',corrupt)
    iv._self_check.cache_clear()
    try:
        assert iv._self_check() is not None
    finally:
        iv._self_check.cache_clear()


@pytest.mark.parametrize('case',['df','augmented_rank','zero_variance','weights','partial'])
def test_unsupported_owned_wu_has_a_named_reason(case):
    from workbench.engine.iv_diagnostics import wu_hausman_statistic
    frame=hand_frame(1)
    weights=None; variables=None
    if case=='df':frame=frame.iloc[[0,2,4]]
    elif case=='augmented_rank':frame['d']=frame.z1
    elif case=='zero_variance':frame['y']=1+frame.d
    elif case=='weights':weights=np.arange(1,len(frame)+1.)
    elif case=='partial':variables=['d']
    fitted=IV2SLS(frame.y,np.ones((len(frame),1)),frame[['d']],frame[['z1','z2']],weights=weights).fit(cov_type='unadjusted')
    with pytest.raises(ValueError,match='IV_WU_HAUSMAN_UNAVAILABLE:'):
        wu_hausman_statistic(fitted,variables=variables)


@pytest.mark.parametrize('engine',['reference','fast'])
@pytest.mark.parametrize('case,reason',[('df','insufficient_residual_df'),('augmented_rank','rank_deficient_augmented_design'),('zero_variance','undefined_residual_variance')])
def test_real_publisher_keeps_valid_point_when_wu_is_unavailable(case,reason,engine):
    if engine=='fast' and not native.available():
        pytest.skip('native engine is not built')
    frame=hand_frame(1)
    if case=='df':frame=frame.iloc[[0,2,4]]
    elif case=='augmented_rank':frame['d']=frame.z1
    else:frame['y']=1+frame.d
    primary,fitted=run_iv_2sls(frame,'y',[],['d'],['z1','z2'],'iv_boundary',covariance='unadjusted',estimation_engine=engine)
    if engine=='fast':
        assert primary['engine_selection']['requested']=='fast'
        assert primary['engine_selection']['used']=='reference'
        assert 'diagnostic' in primary['engine_selection']['reason']
    assert np.isfinite(fitted.params).all()
    before=fitted.params.to_numpy().tobytes(),fitted.cov.to_numpy().tobytes()
    strength={'evidence':{'per_endogenous':[{'endogenous':'d'}],'test':'F','first_stage_statistic':1.,'reference_distribution':'F(2,5)'},'summary':'Boundary test preserves the separate strength evidence.'}
    diagnosis=build_iv_diagnostics(fitted,1,2,strength)
    endogeneity=diagnosis['endogeneity']
    assert endogeneity['verdict']=='unavailable'
    assert endogeneity['reason']==reason
    assert endogeneity['statistic'] is None and endogeneity['pvalue'] is None
    assert reason in endogeneity['message']
    assert before==(fitted.params.to_numpy().tobytes(),fitted.cov.to_numpy().tobytes())
    assert primary['coefficients']
    from workbench.agent.completion_profiles import native_diagnostics
    diagnosis['weak_instruments']['anderson_rubin_95']={'kind':'whole_line','global_certification':{'status':'certified'}}
    diagnosis['overidentification']={'applicable':True,'test':'sargan','pvalue':.5}
    evidence={'contract':'analysis-completion.evidence.v2','diagnostics':{'iv':diagnosis}}
    assert not native_diagnostics('iv',[evidence])
    complete={**diagnosis,'endogeneity':{'test':'wu_hausman','pvalue':.5}}
    assert native_diagnostics('iv',[{**evidence,'diagnostics':{'iv':complete}}])


@pytest.mark.parametrize('case,endog,instruments',[('just',['d1'],['z1']),('over',['d1'],['z1','z2']),('two_endogenous',['d1','d2'],['z1','z2','z3'])])
def test_default_owned_statistic_matches_the_original_R_fixest_record(case,endog,instruments):
    from workbench.engine.iv_diagnostics import wu_hausman_statistic
    root=Path(__file__).parent/'fixtures/fast_engine_iv'
    data=pd.read_csv(root/'data.csv',float_precision='round_trip')
    expected=json.loads((root/'oracle.json').read_text())['cases'][case]['wu_hausman']
    _,fitted=run_iv_2sls(data,'y',['w'],endog,instruments,'iv_r',covariance='unadjusted')
    before={name:np.asarray(getattr(fitted,name)).tobytes() for name in ('params','cov','std_errors','pvalues')}
    test=wu_hausman_statistic(fitted)
    assert test.stat==pytest.approx(expected,rel=1e-10,abs=0)
    assert before=={name:np.asarray(getattr(fitted,name)).tobytes() for name in before}


def test_unexpected_publisher_errors_are_not_reclassified_as_scientific_unavailability(monkeypatch):
    from workbench.engine import iv_diagnostics
    _,fitted=run_iv_2sls(hand_frame(),'y',[],['d'],['z1','z2'],'iv_bug',covariance='unadjusted')
    def unexpected(_):
        raise RuntimeError('unexpected implementation error')
    monkeypatch.setattr(iv_diagnostics,'wu_hausman_statistic',unexpected)
    with pytest.raises(RuntimeError,match='unexpected implementation error'):
        build_iv_diagnostics(fitted,1,2)


def test_nonfinite_defined_native_wu_slot_is_not_scientific_unavailability():
    if not native.available():
        pytest.skip('native engine is not built')
    _,fitted=run_iv_2sls(hand_frame(),'y',[],['d'],['z1','z2'],'iv_bad_slot',covariance='unadjusted',estimation_engine='fast')
    fitted.wu_hausman_test=iv.TestStatistic(float('nan'),1,5)
    with pytest.raises(RuntimeError,match='IV_WU_HAUSMAN_INVALID_OUTPUT'):
        build_iv_diagnostics(fitted,1,2)


def test_a_small_but_estimable_first_stage_residual_is_not_declared_unavailable():
    from workbench.engine.iv_diagnostics import wu_hausman_statistic
    frame=hand_frame(1)
    residual=np.array([1,-1,1,-1,1,-1,1,-1.])
    epsilon=1e-6
    frame['d']=frame.z1+epsilon*residual
    _,fitted=run_iv_2sls(frame,'y',[],['d'],['z1','z2'],'iv_small_residual',covariance='unadjusted')
    result=wu_hausman_statistic(fitted)
    expected=2.5*(2-epsilon)**2/(1+epsilon**2)
    assert result.stat==pytest.approx(expected,rel=1e-9,abs=0)
