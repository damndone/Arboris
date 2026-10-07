"""E1: new ARMA orders, near-unit AR and small GARCH beta against real Stata."""
import numpy as np
import pandas as pd
import pytest
from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
from support import OUT, emit, native_stata, save


def series(ar, ma, beta, seed, n=2500):
    rng = np.random.default_rng(seed)
    e = np.zeros(n + 600); u = np.zeros_like(e); h = np.ones_like(e)
    for t in range(4, len(e)):
        h[t] = .25 + .22 * e[t-1]**2 + beta * h[t-1]
        e[t] = rng.normal() * np.sqrt(h[t])
        u[t] = sum(a*u[t-i-1] for i,a in enumerate(ar)) + sum(a*e[t-i-1] for i,a in enumerate(ma)) + e[t]
    return 1.25 + u[600:]


@pytest.mark.parametrize('name,ar,ma,beta,seed', [
    ('arma22', [.6,-.2], [.45,.15], .55, 18112051),
    ('near_unit', [.98], [.25], .55, 18112052),
    ('small_beta', [.55], [.4], .025, 18112053),
])
def test_new_orders_report_final_parameters_se_ll_ic(name,ar,ma,beta,seed,tmp_path):
    y=series(ar,ma,beta,seed)
    data=OUT/(name+'.csv'); pd.DataFrame({'t':np.arange(1,len(y)+1),'y':y}).to_csv(data,index=False,float_format='%.17g')
    options=f'ar(1/{len(ar)}) ma(1/{len(ma)}) arch(1) garch(1)'
    boundary = name == 'small_beta'
    constraints=' constraints(1)' if boundary else ''
    define='constraint define 1 [ARCH]L.garch=0\n' if boundary else ''
    body=f'import delimited "{data}", asdouble clear case(preserve)\ntsset t\n{define}quietly arch y, {options}{constraints} vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)\n'
    names=['mu']+[f'ar{i}' for i in range(1,len(ar)+1)]+[f'ma{i}' for i in range(1,len(ma)+1)]+['arch1','garch1','omega']
    body+='matrix b=e(b)\nmatrix V=e(V)\n'
    for i,key in enumerate(names,1):
        body+=emit('b_'+key,f'b[1,{i}]')+'\n'+emit('se_'+key,f'sqrt(V[{i},{i}])')+'\n'
    for key,expression in [('ll','e(ll)'),('n','e(N)'),('converged','e(converged)')]:body+=emit(key,expression)+'\n'
    body+='quietly estat ic\nmatrix IC=r(S)\n'+emit('aic','IC[1,5]')+'\n'+emit('bic','IC[1,6]')+'\n'
    oracle=native_stata(body,'e01-'+name,tmp_path)
    actual=fit_joint_arma_garch(y,mean_p=len(ar),mean_q=len(ma),include_constant=True,
        variance_spec=VarianceCandidateSpec.create(model='garch',p=1,q=1,distribution='normal'),time_index_semantics='observation_order')
    save('e01-'+name,{'oracle':oracle,'actual':actual.to_dict()})
    assert oracle['converged']==1 and actual.converged and oracle['n']==actual.nobs==len(y)
    for key in actual.parameter_names:
        assert actual.parameters[key]==pytest.approx(oracle['b_'+key],abs=1e-4,rel=0),(name,key)
        if boundary:
            continue  # Fixed-boundary Stata covariance is not full-parameter OPG inference.
        assert actual.standard_errors[key]==pytest.approx(oracle['se_'+key],rel=1e-3,abs=0),(name,key)
    assert actual.log_likelihood==pytest.approx(oracle['ll'],rel=1e-6,abs=0)
    if boundary:
        assert actual.parameters['garch1']==0 and oracle['b_garch1']==0
        assert actual.aic==pytest.approx(-2*oracle['ll']+2*len(actual.parameter_names),rel=1e-6,abs=0)
        assert actual.bic==pytest.approx(-2*oracle['ll']+len(actual.parameter_names)*np.log(len(y)),rel=1e-6,abs=0)
    else:
        for key, value in [('aic',actual.aic),('bic',actual.bic)]:assert value==pytest.approx(oracle[key],rel=1e-6,abs=0)


def test_failure_has_no_partial_numbers_or_strategy_fallback():
    with pytest.raises(ArmaGarchInputError) as caught:
        fit_joint_arma_garch(series([.55],[.4],.55,18112054),mean_p=1,mean_q=1,include_constant=True,
            variance_spec=VarianceCandidateSpec.create(model='garch',p=1,q=1,distribution='normal'),time_index_semantics='observation_order',max_iterations=1)
    payload=caught.value.to_dict();save('e01-failure',payload)
    assert caught.value.code=='JOINT_ARMA_GARCH_NOT_CONVERGED'
    assert payload['severity']=='blocking'
    assert not {'parameters','standard_errors','log_likelihood'} & set(payload)
