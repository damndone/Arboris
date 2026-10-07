"""Fresh Stata prefix fits and fixed-parameter prediction, without tail leakage."""
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.stata_oracle import run, emit, STATA
from workbench.engine.packs.arma_garch.arma import fit_arma_candidate, ArmaCandidateSpec
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
from workbench.engine.packs.arma_garch.forecast import _JointArmaState, _joint_arma_point_forecast

DATA = Path(__file__).parents[2]/"fixtures/arma_garch_joint/oracle_v1/data_garch11_constant.csv"


@pytest.mark.parametrize("refit_second",[False,True])
def test_joint_prefix_and_fixed_update_match_stata_predictions(tmp_path,refit_second):
    assert STATA.is_file(), "Stata is required for this release oracle"
    values=pd.read_csv(DATA)["y"].to_numpy()
    prefix=len(values)-2
    native=run(tmp_path/f"stata-refit-{int(refit_second)}", f'''
import delimited using "{DATA.resolve()}", asdouble clear case(preserve)
tsset t
quietly arch y if t<={prefix}, ar(1) ma(1) arch(1) garch(1) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
predict double m1, xb
predict double v1, variance
{emit("first_mean",f"m1[{prefix+1}]")}
{emit("first_variance",f"v1[{prefix+1}]")}
{emit("original_h0","e(archi)")}
''' + (f'''quietly arch y if t<={prefix+1}, ar(1) ma(1) arch(1) garch(1) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
predict double m2, xb
predict double v2, variance
{emit("second_mean",f"m2[{prefix+2}]")}
{emit("second_variance",f"v2[{prefix+2}]")}
''' if refit_second else f'''
{emit("second_mean",f"m1[{prefix+2}]")}
{emit("second_variance",f"v1[{prefix+2}]")}
'''),name="joint_prediction")
    candidate=fit_arma_candidate(values[:prefix],ArmaCandidateSpec(candidate_id="prefix",p=1,q=1,constant=True),selection_mode="manual")
    spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal")
    state=_JointArmaState()
    first=_joint_arma_point_forecast(values[:prefix],mean_candidate=candidate,variance_spec=spec,
        state=state,refit=True,time_index_semantics="observation_order")
    h0=state.presample_variance
    second=_joint_arma_point_forecast(values[:prefix+1],mean_candidate=candidate,variance_spec=spec,
        state=state,refit=refit_second,time_index_semantics="observation_order")
    if not refit_second:
        assert state.presample_variance==h0
    actual={"first_mean":first.mean,"first_variance":first.variance,
        "second_mean":second.mean,"second_variance":second.variance,"original_h0":h0}
    (tmp_path/"comparison.json").write_text(json.dumps({"stata":native,"workbench":actual},indent=2))
    for name, reference in native.items():
        assert actual[name]==pytest.approx(reference,abs=1e-4), (name,actual[name],reference)
