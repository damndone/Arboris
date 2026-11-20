"""Attested product adapter checks for the two offline walk-forward paths."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.test_native_walk_forward import sample
from workbench import native_quant_replay, native_walk_forward
from workbench.checks.ar_cancellation import cancellation_scope


@pytest.fixture
def adapter():
    if not native_quant_replay.manifest_path(native_quant_replay._output_directory()).is_file():
        pytest.skip("build with native/quant_replay/build.py to exercise walk-forward")
    return native_walk_forward


def frame():
    times, values = sample()
    return pd.DataFrame({"end": times, "a": values[:,0], "b": values[:,1]})


def run(adapter, data=None, **options):
    settings = dict(time_col="end", return_columns=["a","b"], window=3, first_period=0, end_period=0,
                    transaction_cost_bps=100, initial_equity=100.)
    return adapter.run_walk_forward(frame() if data is None else data, **(settings | options))


def test_first_decision_dates_raw_weights_and_fee_inclusive_comparison(adapter):
    result = run(adapter)
    assert result["contract_version"] == "quant_walk_forward_v1"
    assert len(result["engine"]["build_identity_sha256"]) == 64
    assert result["inputs"]["first_period"] == 5 and result["inputs"]["end_period"] == 9
    assert result["inputs"]["evaluated_periods"] == 5
    assert result["assumptions"]["embargo_periods"] == 1
    assert result["assumptions"]["benchmark_policy"] == "equal_weight_rebalanced_each_evaluation_period"
    local = result["decisions"]
    assert local["privacy"] == "local_only" and local["benchmark_target"] == {"a":.5,"b":.5}
    first = local["rows"][0]
    assert first["period"] == 5 and first["first_training_period"] == 1 and first["last_training_period"] == 3
    assert (first["as_of_time"],first["execution_time"],first["end_time"]) == ("30","40","50")
    assert first["target"] == pytest.approx({"a":.75,"b":.25})
    assert 0 <= first["normalized_kkt_residual"] <= 1e-9
    strategy = result["strategy_series"]
    benchmark = result["benchmark_series"]
    assert strategy["privacy"] == benchmark["privacy"] == "local_only"
    assert strategy["rows"][0]["ending_equity"] == pytest.approx(115/1.01)
    assert benchmark["rows"][0]["ending_equity"] == pytest.approx(110/1.01)
    for key, series in [("strategy",strategy),("benchmark",benchmark)]:
        metric = result["metrics"][key]
        assert metric["realized_net_return_volatility"] == pytest.approx(np.std([r["net_return"] for r in series["rows"]], ddof=1))
        assert metric["total_fees"] == pytest.approx(math.fsum(r["fees"] for r in series["rows"]))
        assert metric["final_equity"] == series["rows"][-1]["ending_equity"]
    assert result["metrics"]["cumulative_net_return_difference"] == pytest.approx(
        result["metrics"]["strategy"]["cumulative_net_return"] - result["metrics"]["benchmark"]["cumulative_net_return"],
    )
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_resolved_interval_and_suffix_perturbation_leave_both_ledgers_unchanged(adapter):
    data = frame()
    prior = run(adapter, data, first_period=6, end_period=8)
    assert prior["inputs"]["evaluated_periods"] == 3
    data.loc[8,["a","b"]] = [np.nan,-5.]
    data.loc[8,"end"] = -3
    assert run(adapter, data, first_period=6, end_period=8) == prior


def test_total_loss_in_last_evaluation_period_is_reported_by_both_paths(adapter):
    data = frame()
    data.loc[5, ["a", "b"]] = -1.
    result = run(adapter, data, end_period=6, shrinkage_bps=10_000)
    for name in ("strategy", "benchmark"):
        metrics = result["metrics"][name]
        assert metrics["final_equity"] == 0. and metrics["cumulative_net_return"] == -1.
        assert metrics["max_drawdown"] == 1.
        assert result[f"{name}_series"]["rows"][-1]["net_return"] == -1.
    assert result["metrics"]["cumulative_net_return_difference"] == 0.


def test_ledger_receipt_corruption_fails_closed(adapter, monkeypatch):
    library, receipt = adapter._loaded()
    genuine = library.arboris_quant_walk_forward

    def corrupt(*args):
        status = genuine(*args)
        if status == 0:
            args[11][6] += .5
        return status

    monkeypatch.setattr(adapter, "_loaded", lambda: (SimpleNamespace(arboris_quant_walk_forward=corrupt), receipt))
    with pytest.raises(native_quant_replay.QuantReplayError) as failure:
        run(adapter)
    assert failure.value.code == "QUANT_WALK_FORWARD_NATIVE_INVALID" and failure.value.row == 4


@pytest.mark.parametrize("options", [{"first_period":4},{"end_period":5},{"window":True},{"shrinkage_bps":10001},
                                     {"transaction_cost_bps":10_000},{"initial_equity":0.},{"return_columns":["a","a"]}])
def test_bad_options_fail_before_loading_native(adapter, monkeypatch, options):
    monkeypatch.setattr(adapter, "_loaded", lambda: pytest.fail("invalid input reached native loading"))
    with pytest.raises(native_quant_replay.QuantReplayError) as failure:
        run(adapter, **options)
    assert failure.value.code == "QUANT_WALK_FORWARD_INVALID_INPUT"


def test_wrong_order_and_unidentified_window_report_the_input_row(adapter):
    data = frame()
    data.loc[2,"end"] = data.loc[1,"end"]
    with pytest.raises(native_quant_replay.QuantReplayError) as failure:
        run(adapter,data)
    assert (failure.value.code,failure.value.row) == ("QUANT_WALK_FORWARD_TIME_ORDER",2)
    data = frame()
    data.loc[:2,["a","b"]] = 0.
    with pytest.raises(native_quant_replay.QuantReplayError) as failure:
        run(adapter,data)
    assert (failure.value.code,failure.value.row) == ("QUANT_WALK_FORWARD_UNIDENTIFIED",4)


def test_cancellation_exception_is_preserved(adapter):
    class Stop(Exception):
        pass

    count = 0

    def poll():
        nonlocal count
        count += 1
        if count >= 5:
            raise Stop("stop both paths")

    with cancellation_scope(poll), pytest.raises(Stop, match="stop both paths"):
        run(adapter)
