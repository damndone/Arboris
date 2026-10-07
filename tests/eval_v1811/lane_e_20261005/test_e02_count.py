"""E2: independent simulated NB2/NB1/fixed alpha and honest boundaries."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2
from workbench.econometrics.runner import run_negative_binomial, run_glm
from support import OUT, emit, native_stata, native_r, save


def sample(kind):
    rng=np.random.default_rng(18112060+(kind=='nb1'));n=1800
    x,z=rng.normal(size=(2,n));mu=np.exp(.25+.3*x-.18*z)
    y=rng.negative_binomial(mu/.7,1/1.7) if kind=='nb1' else rng.negative_binomial(1/.8,1/(1+.8*mu))
    return pd.DataFrame({'y':y,'x1':x,'x2':z})


@pytest.mark.parametrize('kind,dispersion,ancillary',[('nb2','mean','lnalpha'),('nb1','constant','lndelta'),('fixed','mean',None)])
def test_new_count_data_final_outputs_match_native_stata(kind,dispersion,ancillary,tmp_path):
    frame=sample('nb1' if kind=='nb1' else 'nb2');data=OUT/(kind+'.csv');frame.to_csv(data,index=False,float_format='%.17g')
    command=('glm y x1 x2, family(nbinomial 0.7) link(log) ml' if kind=='fixed' else
        'nbreg y x1 x2'+(', dispersion(constant)' if kind=='nb1' else ','))
    command+=('' if kind=='fixed' else ' difficult')+' iterate(1000) tolerance(1e-12) ltolerance(1e-12)'
    body=f'import delimited "{data}", asdouble clear case(preserve)\nquietly {command}\n'
    for term in ['_cons','x1','x2']:
        body+=emit('b_'+term,f'_b[{term}]')+'\n'+emit('se_'+term,f'_se[{term}]')+'\n'
    body+=emit('ll','e(ll)')+'\n'+emit('n','e(N)')+'\n'
    if ancillary:
        body+=emit('loganc',f'_b[/{ancillary}]')+'\n'+emit('se_loganc',f'_se[/{ancillary}]')+'\n'+emit('lr','e(chi2_c)')+'\n'
    oracle=native_stata(body,'e02-'+kind,tmp_path)
    actual,_=run_negative_binomial(frame,'y',['x1','x2'],'nb',dispersion=dispersion,alpha=.7 if kind=='fixed' else None)
    save('e02-'+kind,{'native':oracle,'actual':actual})
    for key,term in [('Intercept','_cons'),('x1','x1'),('x2','x2')]:
        assert actual['coefficients'][key]['estimate']==pytest.approx(oracle['b_'+term],abs=1e-6,rel=0)
        assert actual['coefficients'][key]['std_error']==pytest.approx(oracle['se_'+term],rel=1e-4,abs=0)
    assert actual['information_matrix']=='observed'
    if ancillary:
        rows={r['name']:r for r in actual['ancillary_parameters']}
        assert rows[ancillary]['estimate']==pytest.approx(oracle['loganc'],abs=1e-4,rel=0)
        assert rows[ancillary]['std_error']==pytest.approx(oracle['se_loganc'],rel=1e-4,abs=0)
        assert actual['overdispersion_test']['statistic']==pytest.approx(oracle['lr'],rel=1e-5,abs=0)
        assert actual['overdispersion_test']['p_value']==pytest.approx(.5*chi2.sf(oracle['lr'],1),rel=1e-5,abs=0)
        assert actual['overdispersion_test']['distribution']=='chibar2(01)'
    else:
        assert actual['alpha_fixed_value']==.7 and not actual['alpha_estimated']
        assert actual['overdispersion_test'] is None and actual['ancillary_parameters']==[]


def test_fixed_glm_expected_information_matches_fresh_r(tmp_path):
    frame=sample('nb2');data=OUT/'glm-fixed.csv';frame.to_csv(data,index=False,float_format='%.17g')
    script='''args<-commandArgs(TRUE);d<-read.csv(args[1]);m<-glm(y~x1+x2,data=d,family=MASS::negative.binomial(theta=1/.7),control=glm.control(epsilon=1e-16,maxit=1000));X<-model.matrix(m);mu<-exp(drop(X%*%coef(m)));V<-solve(crossprod(X,X*(mu/(1+.7*mu))));jsonlite::write_json(list(beta=coef(m),se=sqrt(diag(V)),n=nobs(m),score=max(abs(crossprod(X,(m$y-mu)/(1+.7*mu))))/nobs(m)),args[2],digits=17,auto_unbox=TRUE)'''
    native=native_r(script,data,'e02-fixed-glm',tmp_path);actual,_=run_glm(frame,'y',['x1','x2'],'g','negative_binomial',alpha=.7)
    save('e02-fixed-glm',{'actual':actual,'native':native})
    assert native['score']<1e-8
    np.testing.assert_allclose([actual['coefficients'][k]['estimate'] for k in ['Intercept','x1','x2']],native['beta'],rtol=0,atol=1e-8)
    np.testing.assert_allclose([actual['coefficients'][k]['std_error'] for k in ['Intercept','x1','x2']],native['se'],rtol=1e-6,atol=0)
    assert actual['information_matrix']=='expected' and actual['overdispersion_test'] is None


def test_alpha_zero_boundary_is_explicit_not_uncertified_numbers():
    frame=sample('nb2');frame['y']=1
    try:
        actual,_=run_negative_binomial(frame,'y',['x1','x2'],'boundary')
    except ValueError as error:
        save('e02-boundary',{'error':str(error)})
        assert 'NB_INFERENCE_UNCERTIFIED' in str(error)
    else:
        save('e02-boundary',{'actual':actual})
        lr=actual['overdispersion_test'];assert lr['statistic']<=0 and lr['p_value']==1


def test_missing_glm_alpha_and_fixed_nb1_refuse_without_defaults():
    with pytest.raises(ValueError,match='GLM_NB_ALPHA_REQUIRED'):run_glm(sample('nb2'),'y',['x1','x2'],'g','negative_binomial')
    with pytest.raises(ValueError,match='NB_FIXED_DISPERSION_UNSUPPORTED'):run_negative_binomial(sample('nb1'),'y',['x1','x2'],'n',dispersion='constant',alpha=.7)
