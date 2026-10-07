"""Public q>0 integration preserves joint estimation through forecasting."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from tests.models.arma_garch.test_classical_replication import _Recorder
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract, ArmaGarchContractError
from workbench.engine.packs.arma_garch.estimation import resolve_estimation_strategy

FIXTURE = Path(__file__).parents[2] / "fixtures/arma_garch_joint/oracle_v1"


def options(*, distribution="normal", refit=1, mode="classical_replication"):
    return {"dataset_ref":"dataset:joint-oracle", "time_column":"when", "value_column":"value",
        "time_index_semantics":"business_or_trading_observations", "transform":"level",
        "transform_confirmed":True, "selection_mode":"manual",
        "arma":{"p":1,"q":1,"constant_mode":"include"},
        "variance":{"model":"garch","garch_p":1,"garch_q":1},
        "estimation_strategy":"joint", "innovation_distribution":distribution,
        "validation":{"validation_n":2,"refit_every":refit,"evaluation_mode":mode}}


def test_public_contract_accepts_joint_ma_without_changing_auto_default():
    contract=ArmaGarchAnalysisContract.from_dict(options())
    assert contract.arma.q==1
    assert resolve_estimation_strategy("auto",mean_q=1)=="sequential_arma_garch"


def test_public_contract_refuses_unsupported_joint_ma_distribution():
    with pytest.raises(ArmaGarchContractError) as error:
        ArmaGarchAnalysisContract.from_dict(options(distribution="student_t"))
    assert error.value.code == "UNSUPPORTED_JOINT_DISTRIBUTION"


def test_public_runner_retains_joint_ma_oracle_and_forecast_state(tmp_path):
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.packs.arma_garch.runner import fit_from_context
    values=pd.read_csv(FIXTURE/"data_garch11_constant.csv")["y"].to_numpy()
    source=pd.DataFrame({"when":pd.bdate_range("2000-01-03",periods=len(values)),"value":values})
    ctx=ModelingContext(data=DataHandle.of(source.copy(),artifact_id="cleaned_dataset",provenance=("source.csv",)),
        y_col="value",x_cols=[],y_type="continuous",requested_model_type="time_series.arma_garch")
    ctx.artifacts.update({"_model_options":options(),"_frames":{"source.csv":source}})
    (tmp_path/"artifacts_index.json").write_text('{"artifacts":[]}')
    _, result, _=fit_from_context(ctx,RunEnv(run_root=tmp_path,run_id="joint-public",recorder=_Recorder()))
    oracle=json.loads((FIXTURE/"stata_garch11_constant_opg.json").read_text())
    final=json.loads((tmp_path/"artifacts/time_series/ts.final_model.json").read_text())["payload"]["in_sample_fit"]
    assert result["resolved_strategy"]=="joint_arma_garch"
    assert final["hold_back"]==0 and final["nobs"]==len(values)
    for name, reference in oracle["parameters"].items():
        assert final["parameters"][name]==pytest.approx(reference,abs=1e-4)
    assert result["validation"]["metrics"]["successful_forecast_n"]==2
    child=result["production_child"]
    assert child["refit_summary"]["effective_sample"]==len(values)
    assert "ma1" in child["refit_summary"]["parameters"]
    assert np.isfinite(child["next_forecast"]["conditional_mean"])


@pytest.mark.parametrize("case,mean,variance",[
    ("garch11_constant",2.4437119359601374,0.7061920556345433),
    ("garch11_zero",-1.7014004359436898,1.006885180685678),
    ("garch21_constant",1.9475860992065872,0.8719947404230552),
    ("arch2_constant",3.3052173999772654,0.835705512739725),
])
def test_joint_next_prediction_matches_existing_stata_series(case,mean,variance):
    # References are one-step algebra using persisted Stata parameters and
    # its predicted residual/variance series, not fresh out-of-sample predict.
    from workbench.engine.packs.arma_garch.forecast import _JointArmaState, _joint_arma_point_forecast
    from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate
    from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
    oracle=json.loads((FIXTURE/f"stata_{case}_opg.json").read_text())
    values=pd.read_csv(FIXTURE/f"data_{case}.csv")["y"].to_numpy()
    p=2 if case=="garch21_constant" else 1
    candidate=fit_arma_candidate(values,ArmaCandidateSpec(candidate_id="forecast-oracle",p=p,q=1,constant=case!="garch11_zero"),selection_mode="manual")
    spec=VarianceCandidateSpec.create(model="arch" if case=="arch2_constant" else "garch",p=2 if case=="arch2_constant" else 1,q=0 if case=="arch2_constant" else 1,distribution="normal")
    result=_joint_arma_point_forecast(values,mean_candidate=candidate,variance_spec=spec,
        state=_JointArmaState(),refit=True,time_index_semantics="observation_order")
    assert result.mean==pytest.approx(mean,abs=1e-4)
    assert result.variance==pytest.approx(variance,abs=1e-4)
    assert set(result.refit_summary["parameters"])==set(oracle["parameters"])

@pytest.mark.parametrize('strategy', [None, 'auto'])
def test_manual_ma_default_resolves_joint_at_every_contract_entry(strategy):
    payload = options()
    if strategy is None:
        payload.pop('estimation_strategy')
    else:
        payload['estimation_strategy'] = strategy
    contract = ArmaGarchAnalysisContract.from_dict(payload)
    assert contract.estimation_strategy == 'joint'


def test_manual_ma_can_explicitly_keep_sequential():
    payload = options()
    payload['estimation_strategy'] = 'sequential'
    assert ArmaGarchAnalysisContract.from_dict(payload).estimation_strategy == 'sequential'

@pytest.mark.parametrize('change,code', [
    ({'values': np.array([1+1j, 2],dtype=object)}, 'JOINT_ARMA_GARCH_INVALID_INPUT'),
    ({'values': ['bad', 2]}, 'JOINT_ARMA_GARCH_INVALID_INPUT'),
    ({'mean_q': True}, 'JOINT_ARMA_GARCH_INVALID_PARAMETERS'),
    ({'include_constant': 1}, 'JOINT_ARMA_GARCH_INVALID_PARAMETERS'),
    ({'parameters': {'mu': 0., 'ar1': .3, 'ma1': .2, 'omega': 1+1j, 'arch1': .1, 'garch1': .5}}, 'JOINT_ARMA_GARCH_INVALID_PARAMETERS'),
    ({'presample_variance': 'bad'}, 'JOINT_ARMA_GARCH_INVALID_PARAMETERS'),
])
def test_prediction_filter_rejects_invalid_inputs_structurally(change,code):
    from workbench.engine.packs.arma_garch.joint_mle import filter_joint_arma_garch
    from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    arguments = dict(values=np.array([1., 2., 3.]),mean_p=1,mean_q=1,include_constant=True,
        variance_spec=VarianceCandidateSpec.create(model='garch',p=1,q=1,distribution='normal'),
        parameters={'mu': 0., 'ar1': .3, 'ma1': .2, 'omega': 1., 'arch1': .1, 'garch1': .5},presample_variance=1.)
    arguments.update(change)
    with pytest.raises(ArmaGarchInputError) as error:
        filter_joint_arma_garch(**arguments)
    assert error.value.code == code


def test_rolling_joint_refit_starts_only_from_previous_prefix_fit(monkeypatch):
    from workbench.engine.packs.arma_garch import joint_mle
    from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate
    from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
    from workbench.engine.packs.arma_garch.forecast import _JointArmaState, _joint_arma_point_forecast
    values = pd.read_csv(FIXTURE/'data_garch11_constant.csv')['y'].to_numpy()[:180]
    mean = fit_arma_candidate(values[:-2],ArmaCandidateSpec('prefix',1,1,True),selection_mode='manual')
    spec = VarianceCandidateSpec.create(model='garch',p=1,q=1,distribution='normal')
    real_fit = joint_mle.fit_joint_arma_garch
    calls = []
    def capture(history,**kwargs):
        calls.append((len(history),kwargs.get('start')))
        return real_fit(history,**kwargs)
    monkeypatch.setattr(joint_mle,'fit_joint_arma_garch',capture)
    state = _JointArmaState()
    _joint_arma_point_forecast(values[:-2],mean_candidate=mean,variance_spec=spec,state=state,
        refit=True,time_index_semantics='observation_order')
    previous = dict(state.parameters)
    _joint_arma_point_forecast(values[:-1],mean_candidate=mean,variance_spec=spec,state=state,
        refit=True,time_index_semantics='observation_order')
    assert calls == [(178,None),(179,previous)]
    assert state.refit_summary['nobs'] == 179
