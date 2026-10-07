"""E6: manual warning integrity and exact prefix-only classical Stata results."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.arma import search_arma_candidates
from workbench.engine.packs.arma_garch.statistics import ljung_box_results
from support import REPO,OUT,emit,native_stata,save


def options(mode='manual'):
    return ArmaGarchAnalysisContract.from_dict({'dataset_ref':'dataset:e06','time_column':'when','value_column':'value','time_index_semantics':'business_or_trading_observations','transform':'level','transform_confirmed':True,'selection_mode':mode,'arma':{'p':0 if mode=='manual' else None,'q':0 if mode=='manual' else None,'constant_mode':'exclude','auto_max_p':0,'auto_max_q':0},'variance':{'model':'constant_variance' if mode=='manual' else 'auto'},'estimation_strategy':'sequential','validation':{'validation_n':4}})


def test_manual_failed_diagnostic_remains_visible_and_short_lags_unavailable():
    rng=np.random.default_rng(18112100);e=rng.normal(size=180);y=np.zeros(180)
    for t in range(1,len(y)):y[t]=.9*y[t-1]+e[t]
    source=pd.DataFrame({'when':pd.bdate_range('2025-01-01',periods=len(y)),'value':y})
    for mode in ['manual','auto']:
        contract=options(mode);prepared=prepare_arma_garch_input(source,contract)
        actual=search_arma_candidates(freeze_train_validation_split(prepared.transformed_view,contract),contract)
        if mode=='manual':
            assert actual.selected_candidate_id is not None and actual.blocking_diagnostic is None
            assert any('Ljung-Box' in w and 'lag' in w for w in actual.candidates[0].warnings)
        else:assert actual.selected_candidate_id is None and actual.blocking_diagnostic is not None
    rows=ljung_box_results(y,model_df=10,requested_lags=(5,10,20));save('e06-lags',rows)
    for row in rows[:2]:assert row['status']=='unavailable' and row['p_value'] is None and row['reason_code']=='LJUNG_BOX_NONPOSITIVE_DF'


def test_full_and_first_origin_match_stata_and_ignore_future_tail(tmp_path):
    spec=importlib.util.spec_from_file_location('e06_existing_runner',REPO/'tests/models/arma_garch/test_classical_replication.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rng=np.random.default_rng(18112101);source=pd.DataFrame({'when':pd.bdate_range('2025-01-01',periods=144),'value':rng.normal(size=144)})
    result,actual=module._run(tmp_path/'full',source)
    changed=source.copy();changed.loc[140:,'value']+=12
    _,mutant=module._run(tmp_path/'changed',changed)
    first=actual['ts.rolling_forecasts']['rows'][0];other=mutant['ts.rolling_forecasts']['rows'][0]
    for key in ['conditional_mean','conditional_variance','lower_bound','upper_bound']:assert first[key]==other[key]
    data=OUT/'e06-values.csv';source.assign(t=np.arange(1,145))[['t','value']].to_csv(data,index=False,float_format='%.17g')
    body=f'import delimited "{data}", asdouble clear case(preserve)\ntsset t\nquietly arima value, arima(0,0,0) noconstant\n'
    body+=emit('ll','e(ll)')+'\n'+emit('variance','_b[/sigma]^2')+'\n'
    body+='quietly arima value if t<=140, arima(0,0,0) noconstant\n'+emit('prefix_variance','_b[/sigma]^2')+'\n'
    native=native_stata(body,'e06-classic',tmp_path)
    full=actual['ts.final_model']['in_sample_fit'];save('e06-classic',{'full':full,'first':first,'native':native,'sample':actual['ts.report']['sample']})
    assert full['variance_stage']['parameters']['sigma2']==pytest.approx(native['variance'],abs=1e-8,rel=0)
    assert actual['ts.arma_candidates']['candidates'][0]['log_likelihood']==pytest.approx(native['ll'],abs=1e-7,rel=0)
    assert first['conditional_variance']==pytest.approx(native['prefix_variance'],abs=1e-8,rel=0)
    assert result['nobs']==144 and actual['ts.report']['sample']['validation_data_role']=='retrospective_tail_evaluation'
