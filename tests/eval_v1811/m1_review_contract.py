"""Independent fail-closed and legacy invariance checks for M1."""
from pathlib import Path
from types import ModuleType
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.estimation import fit_joint_ar_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

ROOT=Path(__file__).resolve().parents[1]/"fixtures"/"arma_garch_joint"

def arguments():
    return dict(values=pd.read_csv(ROOT/"oracle_v1"/"data_garch11_constant.csv")["y"].to_numpy(),mean_p=1,mean_q=1,include_constant=True,variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"),time_index_semantics="observation_order")

def test_complex_input_is_rejected_without_discarding_imaginary_values():
    args=arguments()
    args["values"]=args["values"].astype(complex)+1j
    with pytest.raises(ArmaGarchInputError):
        fit_joint_arma_garch(**args)

@pytest.mark.parametrize("p,q",[(None,1),(1,None),("bad",1),(1,"bad")])
def test_malformed_variance_orders_raise_structured_errors(p,q):
    args=arguments()
    args["variance_spec"]=VarianceCandidateSpec("invalid","garch",p,q,"normal","invalid")
    with pytest.raises(ArmaGarchInputError):
        fit_joint_arma_garch(**args)

@pytest.mark.parametrize("override",[
    {"mean_p":True},{"mean_q":-1},{"mean_q":1.5},{"max_iterations":0},
    {"include_constant":1},{"values":np.ones(100)},
    {"values":np.r_[np.inf,np.ones(100)]},
    {"start":{"omega":np.nan}},{"start":{"arch1":-.1}},
    {"start":{"ar1":1.2}},{"start":{"ma1":1.2}},
    {"start":{"arch1":.5,"garch1":.5}},{"max_iterations":1},
])
def test_invalid_or_nonconverged_request_never_returns_a_result(override):
    with pytest.raises(ArmaGarchInputError):
        fit_joint_arma_garch(**{**arguments(),**override})

def test_q0_result_is_identical_to_independently_loaded_baseline():
    module=ModuleType("m1_review_baseline_estimation")
    sys.modules[module.__name__]=module
    source=subprocess.check_output(["git","show","6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3:backend/workbench/engine/packs/arma_garch/estimation.py"],text=True)
    exec(compile(source,"baseline_estimation.py","exec"),module.__dict__)
    args=arguments()
    kwargs=dict(mean_p=1,include_constant=True,variance_spec=args["variance_spec"],hold_back=2,time_index_semantics="observation_order")
    values=args["values"][:220]
    encode=lambda result:json.dumps(result.to_dict(),sort_keys=True,separators=(",",":"),allow_nan=False)
    assert encode(fit_joint_ar_garch(values,**kwargs))==encode(module.fit_joint_ar_garch(values,**kwargs))
