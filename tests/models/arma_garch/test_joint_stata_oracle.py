"""Compare the full joint normal likelihood to independent Stata fixtures."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "arma_garch_joint" / "oracle_v1"

@pytest.mark.parametrize("case", ["garch11_constant", "garch11_zero", "garch21_constant", "arch2_constant"])
@pytest.mark.parametrize("vce", ["opg", "oim", "robust"])
def test_joint_stata_oracle(case, vce):
    oracle = json.loads((FIXTURES / f"stata_{case}_{vce}.json").read_text())
    values = pd.read_csv(FIXTURES / f"data_{case}.csv")["y"].to_numpy()
    spec = VarianceCandidateSpec.create(model="arch" if case == "arch2_constant" else "garch", p=2 if case == "arch2_constant" else 1, q=0 if case == "arch2_constant" else 1, distribution="normal")
    result = fit_joint_arma_garch(values, mean_p=2 if case == "garch21_constant" else 1, mean_q=1, include_constant=case != "garch11_zero", variance_spec=spec, time_index_semantics="observation_order", vce=vce)
    payload = result.to_dict()
    assert payload["parameter_names"] == oracle["parameter_names"]
    assert payload["nobs"] == oracle["nobs"] == len(values)
    assert payload["log_likelihood"] == pytest.approx(oracle["log_likelihood"], rel=1e-6)
    for name in oracle["parameter_names"]:
        assert payload["parameters"][name] == pytest.approx(oracle["parameters"][name], abs=1e-4)
        assert payload["standard_errors"][name] == pytest.approx(oracle["standard_errors"][name], rel=1e-3)
    np.testing.assert_allclose(payload["covariance"]["matrix"], oracle["covariance"], rtol=1e-3, atol=1e-7)
    assert payload["aic"] == pytest.approx(oracle["aic"], rel=1e-6)
    assert payload["bic"] == pytest.approx(oracle["bic"], rel=1e-6)
    series = pd.read_csv(FIXTURES / f"series_{case}.csv")
    np.testing.assert_allclose(payload["conditional_series"]["residual"], series[f"residual_{vce}"], rtol=1e-3, atol=1e-4)
    np.testing.assert_allclose(payload["conditional_series"]["variance"], series[f"variance_{vce}"], rtol=1e-3, atol=1e-4)

def test_robust_uses_stata_ml_finite_sample_multiplier():
    # [P] _robust: ML defaults to minus(1), i.e. n/(n-1), not n/(n-k).
    case = "garch11_zero"
    oracle = json.loads((FIXTURES/f"stata_{case}_robust.json").read_text())
    result = fit_joint_arma_garch(pd.read_csv(FIXTURES/f"data_{case}.csv")["y"].to_numpy(),
        mean_p=1, mean_q=1, include_constant=False, vce="robust",
        variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"),
        time_index_semantics="observation_order")
    for name in oracle["parameter_names"]:
        assert result.standard_errors[name] == pytest.approx(oracle["standard_errors"][name], rel=2e-5)
