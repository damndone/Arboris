"""Independent Stata checks for IC, priming, persistence and diagnostics."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "arma_garch_joint" / "oracle_v1"


@pytest.mark.parametrize("case", ["garch11_constant", "garch11_zero", "garch21_constant", "arch2_constant"])
def test_stata_auxiliary_quantities_and_diagnostics(case):
    from workbench.engine.packs.arma_garch.volatility import fit_joint_variance_candidate
    auxiliary_root = FIXTURES.parent/"auxiliary_v1"
    auxiliary = {k: float(v) for k, v in (line.split("\t") for line in (auxiliary_root/f"auxiliary_{case}.tsv").read_text().splitlines())}
    values = pd.read_csv(FIXTURES/f"data_{case}.csv")["y"].to_numpy()
    p = 2 if case=="garch21_constant" else 1
    spec = VarianceCandidateSpec.create(model="arch" if case=="arch2_constant" else "garch",p=2 if case=="arch2_constant" else 1,q=0 if case=="arch2_constant" else 1,distribution="normal")
    fitted = fit_joint_arma_garch(values, mean_p=p, mean_q=1, include_constant=case!="garch11_zero",variance_spec=spec,time_index_semantics="observation_order")
    assert fitted.aic == pytest.approx(auxiliary["aic"], rel=1e-6)
    assert fitted.bic == pytest.approx(auxiliary["bic"], rel=1e-6)
    assert fitted.presample["variance"] == pytest.approx(auxiliary["prime"],rel=1e-5)
    if case != "arch2_constant":
        assert fitted.persistence["persistence"] == pytest.approx(auxiliary["persistence"],rel=1e-5)
        assert fitted.persistence["half_life"] == pytest.approx(auxiliary["half_life"],rel=1e-4)
    candidate = fit_joint_variance_candidate(values, spec, mean_p=p, include_constant=case!="garch11_zero",hold_back=0,mean_candidate_id="auxiliary",mean_order=(p,1),mean_constant=case!="garch11_zero")
    assert candidate.failure_code is None
    for prefix, diagnostics in (("standardized", candidate.standardized_residual_diagnostics),("squared_standardized", candidate.squared_standardized_residual_diagnostics)):
        for entry in diagnostics:
            lag = entry["lag"]
            assert entry["statistic"] == pytest.approx(auxiliary[f"{prefix}_q{lag}"],rel=1e-4,abs=1e-5)
            assert entry["p_value"] == pytest.approx(auxiliary[f"{prefix}_p{lag}"],rel=1e-4,abs=1e-5)
