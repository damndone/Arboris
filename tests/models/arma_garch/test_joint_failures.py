"""No partial estimates or sequential fallback for unsupported joint inputs."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError

ROOT = Path(__file__).resolve().parents[2]/"fixtures"/"arma_garch_joint"/"oracle_v1"

def _fit(**kwargs):
    args = dict(values=pd.read_csv(ROOT/"data_garch11_constant.csv")["y"].to_numpy(),
        mean_p=1, mean_q=1, include_constant=True,
        variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"),
        time_index_semantics="observation_order")
    return fit_joint_arma_garch(**{**args, **kwargs})

@pytest.mark.parametrize("kwargs,code", [
    ({"max_iterations": 1}, "JOINT_ARMA_GARCH_NOT_CONVERGED"),
    ({"mean_q":0}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"values": np.array([1.,np.nan])}, "JOINT_ARMA_GARCH_INVALID_INPUT"),
    ({"values": np.ones(100)}, "JOINT_ARMA_GARCH_INVALID_INPUT"),
    ({"presample":"zero"}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"vce":"hc1"}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"start":{"omega":-1.}}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"start":{"arch1":.6,"garch1":.5}}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"start":{"ar1":1.1}}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"start":{"ma1":1.1}}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"start":{"invented":1.}}, "JOINT_ARMA_GARCH_INVALID_PARAMETERS"),
    ({"variance_spec":VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="student_t")}, "UNSUPPORTED_JOINT_DISTRIBUTION"),
])
def test_joint_failure_is_structured(kwargs, code):
    with pytest.raises(ArmaGarchInputError) as caught:
        _fit(**kwargs)
    assert caught.value.code == code
    assert caught.value.to_dict()["severity"] == "blocking"


def test_joint_result_is_deeply_immutable_and_json_finite():
    result = _fit()
    payload = result.to_dict()
    json.dumps(payload, allow_nan=False)
    with pytest.raises(TypeError): result.parameters["mu"] = 0.
    with pytest.raises(TypeError): result.covariance["matrix"][0][0] = 0.
    with pytest.raises(TypeError): result.conditional_series["residual"][0] = 0.
    payload["parameters"]["mu"] = 0.
    assert result.parameters["mu"] != 0.

@pytest.mark.parametrize("kwargs", [
    {"values": ["invalid"]*100},
    {"start": {"omega": "invalid"}},
    {"variance_spec": VarianceCandidateSpec("bad", "arch", -1, 0, "normal", "invalid")},
    {"variance_spec": VarianceCandidateSpec("bad", "garch", 1, 0, "normal", "invalid")},
])
def test_malformed_inputs_produce_structured_errors(kwargs):
    with pytest.raises(ArmaGarchInputError) as caught:
        _fit(**kwargs)
    assert caught.value.code in {"JOINT_ARMA_GARCH_INVALID_INPUT", "JOINT_ARMA_GARCH_INVALID_PARAMETERS"}
