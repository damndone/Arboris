"""A declared regression subspace must retain covariance without ancillary rows."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
from workbench.contracts.model.inference_kernel import kernel_from_fitted


def test_declared_parameter_positions_preserve_real_regressor_named_alpha():
    covariance = np.array([[4.,.2,.3],[.2,9.,.4],[.3,.4,16.]])
    fitted = SimpleNamespace(params=pd.Series([1.,2.,.5],index=['Intercept','alpha','alpha']),
        cov_params=lambda: covariance,nobs=40,use_t=False,llf=-100.,df_resid=38)
    kernel=kernel_from_fitted(fitted,model_id='regression',model_type='declared',nobs=40,
        param_positions=(0,1))
    assert kernel['param_names']==['Intercept','alpha']
    assert kernel['params']==[1.,2.]
    assert kernel['vcov']==[[4.,.2],[.2,9.]]
    assert kernel['loglik']==-100.


def test_fixed_effect_projection_excludes_variance_parameter_interior_position():
    fitted=SimpleNamespace(params=pd.Series([1.,.8,2.],index=['Intercept','Group Var','x']),
        cov_params=lambda:np.diag([.1,.2,.3]),nobs=40,use_t=False,llf=-100.,df_resid=38)
    kernel=kernel_from_fitted(fitted,model_id='regression',model_type='declared',nobs=40,
        param_positions=(0,2))
    assert kernel['param_names']==['Intercept','x']
    assert kernel['params']==[1.,2.]
    assert kernel['vcov']==[[.1,0.],[0.,.3]]


def test_pack_records_declared_fixed_effects_for_generic_stage():
    from workbench.engine.packs.linear_mixed_effects.runner import _record_fixed_effects_kernel
    from workbench.engine.inference_kernels import recorded_inference_kernel
    fitted=SimpleNamespace(params=pd.Series([1.,2.,.5],index=['Intercept','x','Group Var']),
        fe_params=pd.Series([1.,2.],index=['Intercept','x']),cov_params=lambda:np.diag([.1,.3,.2]),
        nobs=40,use_t=False,llf=-100.,df_resid=38)
    ctx=SimpleNamespace(artifacts={})
    _record_fixed_effects_kernel(ctx,fitted)
    kernel=recorded_inference_kernel(ctx,'linear_mixed_effects_1')
    assert kernel['param_names']==['Intercept','x']
    assert kernel['vcov']==[[.1,0.],[0.,.3]]


def test_pack_refuses_ambiguous_fixed_effect_names_in_full_parameter_vector():
    from workbench.engine.packs.linear_mixed_effects.runner import _record_fixed_effects_kernel
    from workbench.engine.inference_kernels import recorded_inference_kernel
    fitted=SimpleNamespace(params=pd.Series([1.,.8,2.],index=['Intercept','x','x']),
        fe_params=pd.Series([1.,2.],index=['Intercept','x']),cov_params=lambda:np.diag([.1,9.,.3]),
        nobs=40,use_t=False,llf=-100.,df_resid=38)
    ctx=SimpleNamespace(artifacts={})
    _record_fixed_effects_kernel(ctx,fitted)
    kernel=recorded_inference_kernel(ctx,'linear_mixed_effects_1')
    assert not kernel['params']
    assert kernel['unavailable']
