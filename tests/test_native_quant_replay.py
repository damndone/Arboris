"""Verified native replay, independent accounting, and the local preview contract."""
from __future__ import annotations

from fractions import Fraction
from itertools import product
import json
import math
from pathlib import Path
import random
import shutil

import numpy as np
import pandas as pd
import pytest

from workbench import native_build, native_quant_replay as replay


MODULE = Path(__file__).resolve().parents[1] / "native" / "quant_replay"
OPTIONS = {
    "signal_time_col": "signal", "execution_time_col": "execute", "end_time_col": "end",
    "return_columns": ["return_a", "return_b"], "weight_columns": ["weight_a", "weight_b"],
    "transaction_cost_bps": 156.25, "initial_equity": 100.0,
}


def _frame(n=4):
    return pd.DataFrame({
        "signal": range(n), "execute": range(1, n + 1), "end": range(2, n + 2),
        "return_a": [0.125] * n, "return_b": [-0.0625] * n,
        "weight_a": [0.5] * n, "weight_b": [0.25] * n,
    })


def _run(frame, **changes):
    return replay.run_replay(frame, **(OPTIONS | changes))


@pytest.fixture(autouse=True)
def _isolated_loader(monkeypatch, tmp_path):
    replay._load_once.cache_clear()
    monkeypatch.setattr(replay, "_output_directory", lambda: tmp_path)
    yield
    replay._load_once.cache_clear()


@pytest.fixture(scope="module")
def native_build_dir(tmp_path_factory):
    if shutil.which("cargo") is None or shutil.which("rustc") is None:
        pytest.skip("Rust compiler unavailable for explicit offline native integration test")
    directory = tmp_path_factory.mktemp("verified-quant-native")
    return directory, native_build.build(MODULE, directory)


@pytest.fixture
def verified_native(native_build_dir, monkeypatch):
    directory, manifest = native_build_dir
    monkeypatch.setattr(replay, "_output_directory", lambda: directory)
    return manifest


@pytest.mark.parametrize("changes", [
    {"return_columns": ["return_a"]}, {"signal_time_col": "execute"},
    {"weight_columns": ["weight_a", "weight_a"]}, {"return_columns": ["return_a", "missing"]},
    {"transaction_cost_bps": True}, {"transaction_cost_bps": 10_000}, {"initial_equity": 0.0},
])
def test_invalid_options_fail_before_native_lookup(changes):
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(_frame(), **changes)
    assert caught.value.code == "QUANT_REPLAY_INVALID_INPUT"


def test_missing_native_build_does_not_fallback():
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(_frame())
    assert caught.value.code == "QUANT_REPLAY_NATIVE_UNAVAILABLE"


def test_unproven_binary_never_reaches_loader(tmp_path, monkeypatch):
    (tmp_path / native_build.artifact_names(MODULE)[0]).write_bytes(b"unproven")
    monkeypatch.setattr(replay, "_open", lambda _: pytest.fail("unverified image loaded"))
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(_frame())
    assert caught.value.code == "QUANT_REPLAY_NATIVE_INVALID"


def _exact_replay(frame, rate):
    """Piecewise linear Fraction oracle independent of the Rust bisection."""
    assets = [Fraction(), Fraction()]
    cash = Fraction(100)
    path = []
    for r_a, r_b, w_a, w_b in frame[["return_a", "return_b", "weight_a", "weight_b"]].itertuples(index=False, name=None):
        r = tuple(map(Fraction, (r_a, r_b)))
        w = tuple(map(Fraction, (w_a, w_b)))
        initial = sum(assets) + cash
        roots = set()
        for signs in product((-1, 1), repeat=2):
            post = (initial + rate * sum(s * h for s, h in zip(signs, assets))) / (
                1 + rate * sum(s * weight for s, weight in zip(signs, w))
            )
            if all(s * (post * weight - h) >= 0 for s, weight, h in zip(signs, w, assets)):
                roots.add(post)
        post, = roots
        targets = [post * weight for weight in w]
        notional = sum(abs(target - old) for target, old in zip(targets, assets))
        fees = rate * notional
        assert post + fees == initial
        cash = post * (1 - sum(w))
        pnl = sum(target * ret for target, ret in zip(targets, r))
        assets = [target * (1 + ret) for target, ret in zip(targets, r)]
        end = sum(assets) + cash
        assert end == initial + pnl - fees
        path.append({
            "starting_equity": initial, "post_trade_equity": post, "ending_equity": end,
            "fees": fees, "traded_notional": notional, "holding_pnl": pnl,
            "net_pnl": pnl - fees, "net_return": (end - initial) / initial,
            "gross_exposure": sum(w), "net_exposure": sum(w),
        })
    return path


def test_verified_native_matches_seeded_fraction_oracle(verified_native):
    rng = random.Random(20261105)
    for _ in range(12):
        frame = _frame(7)
        weights = [sorted((rng.randrange(17), rng.randrange(17))) for _ in range(len(frame))]
        frame["weight_a"] = [first / 16 for first, _ in weights]
        frame["weight_b"] = [(second - first) / 16 for first, second in weights]
        frame["return_a"] = [rng.randrange(-8, 9) / 32 for _ in range(len(frame))]
        frame["return_b"] = [rng.randrange(-8, 9) / 32 for _ in range(len(frame))]
        actual = _run(frame)
        assert actual["contract_version"] == "quant_replay_v1"
        assert actual["engine"]["build_identity_sha256"] == verified_native["build_identity_sha256"]
        assert actual["engine"]["binary_sha256"] == verified_native["binary_sha256"]
        assert actual["series"]["privacy"] == "local_only"
        assert actual["assumptions"]["source_vintage_verified"] is False
        exact = _exact_replay(frame, Fraction(1, 64))
        peak = Fraction(100)
        drawdowns = []
        for row, (result, expected) in enumerate(zip(actual["series"]["rows"], exact, strict=True)):
            assert result["row"] == row
            for name, value in expected.items():
                assert result[name] == pytest.approx(float(value), rel=2e-13, abs=2e-13)
            peak = max(peak, expected["ending_equity"])
            drawdown = (peak - expected["ending_equity"]) / peak
            drawdowns.append(drawdown)
            assert result["drawdown"] == pytest.approx(float(drawdown), abs=2e-13)
        assert actual["metrics"]["max_drawdown"] == pytest.approx(float(max(drawdowns)), abs=2e-13)
        assert actual["metrics"]["total_fees"] == pytest.approx(float(sum(x["fees"] for x in exact)), rel=2e-13)
        json.dumps(actual, allow_nan=False)


def _tail(frame, **changes):
    return replay.run_replay_tail_risk(frame, **(OPTIONS | {"window": 4} | changes))


def _exact_tail(frame, rate, window, confidence_bps):
    losses = sorted(-row["net_return"] for row in _exact_replay(frame, rate)[-window:])
    confidence = Fraction(confidence_bps, 10_000)
    var = losses[math.ceil(window * confidence) - 1]
    weighted = sum(
        loss * max(Fraction(), Fraction(i + 1, window) - max(Fraction(i, window), confidence))
        for i, loss in enumerate(losses)
    )
    return float(var), float(weighted / (1 - confidence))


def test_tail_uses_a_single_verified_net_replay_with_prior_holdings(verified_native, monkeypatch):
    frame = _frame(6).assign(
        weight_a=[1, 1, 1, 1, 0, 0], weight_b=[0, 0, 0, 0, 1, 1],
        return_a=[.125, 0, -.5, -.25, 0, 0], return_b=[0, 0, 0, 0, -.25, .125],
    )
    original = replay._native_call
    native_calls = []

    def count_call(*args):
        native_calls.append(args[2].shape)
        return original(*args)

    monkeypatch.setattr(replay, "_native_call", count_call)
    result = _tail(frame, confidence_bps=7000)
    expected = _exact_tail(frame, Fraction(1, 64), 4, 7000)
    assert native_calls == [(6, 2)]
    assert result["contract_version"] == "quant_replay_tail_risk_v1"
    assert result["engine"]["build_identity_sha256"] == verified_native["build_identity_sha256"]
    assert result["metrics"] == pytest.approx({
        "value_at_risk": expected[0], "expected_shortfall": expected[1],
        "tail_observation_equivalent": 1.2, "window": 4, "confidence_bps": 7000,
    }, abs=2e-14)
    assert result["inputs"]["end_period"] == 6
    assert result["tail_window"] == {"privacy": "local_only", "first_period": 3, "as_of_period": 6,
                                     "first_end_time": "4", "as_of_end_time": "7"}
    assert result["assumptions"]["source_vintage_verified"] is False
    assert result["assumptions"]["annualized"] is False
    assert "series" not in result
    assert result == json.loads(json.dumps(result, allow_nan=False))
    isolated_window = _exact_tail(frame.iloc[2:], Fraction(1, 64), 4, 7000)
    gross = _exact_tail(frame, Fraction(), 4, 7000)
    assert result["metrics"]["expected_shortfall"] != pytest.approx(isolated_window[1])
    assert result["metrics"]["expected_shortfall"] != pytest.approx(gross[1])


@pytest.mark.parametrize("returns,bps,expected", [
    ([-.5, -.25, -.25, .125], 5000, (.25, .375)),
    ([-.5, -.25, -.25, .125], 6250, (.25, 5 / 12)),
    ([-.5, -.25, -.25, .125], 9999, (.5, .5)),
    ([.125, .25, .5, .75], 7500, (-.25, -.125)),
    ([.125, .25, .5, .75], 1, (-.75, -1.6247 / 3.9996)),
])
def test_tail_exact_knots_ties_all_gains_and_edge_confidence(verified_native, returns, bps, expected):
    frame = _frame().assign(weight_a=1, weight_b=0, return_a=returns)
    result = _tail(frame, transaction_cost_bps=0, confidence_bps=bps)
    observed = result["metrics"]["value_at_risk"], result["metrics"]["expected_shortfall"]
    assert observed == pytest.approx(expected, abs=2e-14)
    assert observed == pytest.approx(_exact_tail(frame, Fraction(), 4, bps), abs=2e-14)


def test_tail_at_explicit_period_ignores_later_data(verified_native):
    baseline = _tail(_frame(6), end_period=6)
    full = _frame(8)
    full.loc[6:, ["signal", "end", "return_a", "weight_b"]] = [300, 500, float("nan"), -1]
    assert _tail(full, end_period=6) == baseline
    with pytest.raises(replay.QuantReplayError) as caught:
        _tail(full)
    assert (caught.value.code, caught.value.row) == ("QUANT_REPLAY_LOOKAHEAD", 6)


@pytest.mark.parametrize("changes", [
    {"window": 1}, {"window": 5}, {"window": True}, {"confidence_bps": 0}, {"confidence_bps": 10_000},
    {"confidence_bps": 9500.0}, {"end_period": 5}, {"end_period": None}, {"end_period": True}, {"end_period": 3},
])
def test_invalid_tail_options_fail_before_loading(monkeypatch, changes):
    monkeypatch.setattr(replay, "_loaded", lambda: pytest.fail("invalid risk request reached native loader"))
    with pytest.raises(replay.QuantReplayError) as caught:
        _tail(_frame(), **changes)
    assert caught.value.code == "QUANT_REPLAY_TAIL_RISK_INVALID_INPUT"


def test_tail_uses_full_window_instead_of_replay_preview(verified_native):
    frame = _frame(2050).assign(weight_a=1, weight_b=0, return_a=.0)
    frame.loc[1031, "return_a"] = -.875
    result = _tail(frame, transaction_cost_bps=0, window=2048, confidence_bps=9999)
    assert result["metrics"]["value_at_risk"] == .875
    assert result["metrics"]["expected_shortfall"] == .875
    assert result["tail_window"]["first_period"] == 3


@pytest.mark.parametrize("corrupt", [(0.2, 0.4), (0.25, 0.4)])
def test_plausible_but_wrong_tail_native_result_is_rejected(verified_native, monkeypatch, corrupt):
    frame = _frame().assign(weight_a=1, weight_b=0, return_a=[-.5, -.25, -.25, .125])
    monkeypatch.setattr(replay, "_tail_native_call", lambda *args: corrupt)
    with pytest.raises(replay.QuantReplayError) as caught:
        _tail(frame, transaction_cost_bps=0, confidence_bps=6250)
    assert caught.value.code == "QUANT_REPLAY_TAIL_RISK_NATIVE_INVALID"


def test_tail_native_rejects_invalid_shape_and_keeps_small_loss_at_exact_knot(verified_native):
    library, _ = replay._loaded()
    ledger = np.zeros((4, replay._OUTPUT_COLUMNS))
    ledger[:, replay._RETURN] = [8e307, 6e307, 4e307, -1e-300]
    with pytest.raises(replay.QuantReplayError) as caught:
        replay._tail_native_call(library, ledger, 5, 7500)
    assert caught.value.code == "QUANT_REPLAY_TAIL_RISK_NATIVE_INVALID"
    var, es = replay._tail_native_call(library, ledger, 4, 7500)
    assert (var, es) == (-4e307, 1e-300)
    replay._verify_tail_risk(ledger[:, replay._RETURN], 7500, var, es)


@pytest.mark.parametrize("quanta,rounded", [(1, 0), (3, 2)])
def test_tail_preserves_binary64_rounding_for_subnormal_mean(verified_native, quanta, rounded):
    quantum = math.ulp(0.0)
    frame = _frame().assign(weight_a=1, weight_b=0, return_a=[-quanta * quantum, 0, 0, 0])
    result = _tail(frame, transaction_cost_bps=0, initial_equity=1.0, confidence_bps=5000)
    assert result["metrics"]["value_at_risk"] == 0.0
    assert result["metrics"]["expected_shortfall"] == rounded * quantum


@pytest.mark.parametrize("column,value,code", [
    ("signal", 2, "QUANT_REPLAY_LOOKAHEAD"),
    ("signal", 3, "QUANT_REPLAY_LOOKAHEAD"),
    ("execute", 1, "QUANT_REPLAY_TIME_ORDER"),
    ("execute", 3, "QUANT_REPLAY_TIME_ORDER"),
    ("return_b", float("nan"), "QUANT_REPLAY_RETURN"),
    ("return_b", -1.01, "QUANT_REPLAY_RETURN"),
    ("weight_b", 0.75, "QUANT_REPLAY_WEIGHT"),
])
def test_fails_closed_at_exact_row(verified_native, column, value, code):
    frame = _frame()
    frame.loc[1, column] = value
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(frame)
    assert (caught.value.code, caught.value.row) == (code, 1)


def test_rejects_an_unmodeled_interval_gap(verified_native):
    frame = _frame(2)
    frame.loc[1, ["execute", "end"]] = [3, 4]
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(frame)
    assert (caught.value.code, caught.value.row) == ("QUANT_REPLAY_TIME_ORDER", 1)


def test_preserves_int64_ticks_and_refuses_mixed_clock_domains(verified_native):
    frame = _frame(2)
    offset = 2**63 - 4
    frame[["signal", "execute", "end"]] += offset
    actual = _run(frame)
    assert actual["series"]["rows"][-1]["end_time"] == str(2**63 - 1)
    frame["signal"] = ["2026-01-01", "2026-01-02"]
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(frame)
    assert caught.value.code == "QUANT_REPLAY_INVALID_INPUT"


def test_utc_alignment_and_future_change_preserve_earlier_path(verified_native):
    frame = _frame()
    for name in ("signal", "execute", "end"):
        frame[name] = [f"2026-01-01T{hour:02d}:00:00-05:00" for hour in frame[name]]
    initial = _run(frame)
    frame.loc[3, "return_a"] = 0.75
    updated = _run(frame)
    assert initial["inputs"]["time_format"] == "iso8601_utc"
    assert initial["series"]["rows"][0]["execution_time"] == "2026-01-01T06:00:00+00:00"
    assert initial["series"]["rows"][:3] == updated["series"]["rows"][:3]
    assert initial["metrics"]["final_equity"] != updated["metrics"]["final_equity"]


def test_bounded_preview_keeps_first_last_and_metrics_use_all_rows(verified_native):
    n = replay.MAX_SERIES_POINTS + 13
    output = _run(_frame(n))
    series = output["series"]
    assert series["truncated"] is True
    assert series["total_rows"] == n
    assert len(series["rows"]) == replay.MAX_SERIES_POINTS
    assert (series["rows"][0]["row"], series["rows"][-1]["row"]) == (0, n - 1)
    assert output["metrics"]["final_equity"] == series["rows"][-1]["ending_equity"]
    assert output["metrics"]["total_fees"] > sum(row["fees"] for row in series["rows"])


def test_complete_ledger_keeps_integer_clock_precision_and_cancels_materialization():
    from workbench.checks.ar_cancellation import cancellation_scope

    rows = 513
    output = np.tile(np.array([100., 99., 101., .75, 1., 10., 2., 1., .01]), (rows, 1))
    end = np.arange(2**63 - rows, 2**63, dtype=np.int64)
    times = np.column_stack((end - 2, end - 1, end))
    ledger = replay._replay_ledger(output, times, "integer_tick")
    assert tuple(ledger.columns) == replay.REPLAY_LEDGER_COLUMNS
    assert ledger.end_time.iloc[-1] == str(2**63 - 1)
    assert ledger.signal_time.iloc[0] == str(int(times[0, 0]))
    assert ledger[list(replay._LEDGER_VALUES)].to_numpy().tobytes() == output.tobytes()
    checks = []

    class Stop(Exception):
        pass

    def cancel():
        checks.append(True)
        if len(checks) == 2:
            raise Stop("ledger materialization cancelled")

    with cancellation_scope(cancel), pytest.raises(Stop, match="materialization cancelled"):
        replay._replay_ledger(output, times, "integer_tick")
    assert len(checks) == 2


@pytest.mark.parametrize("switch_asset", [False, True])
def test_small_retained_equity_is_accurate_when_fee_rate_is_near_one(verified_native, switch_asset):
    frame = _frame(2)
    frame["weight_a"] = [1.0, 0.0]
    frame[["weight_b", "return_a", "return_b"]] = 0.0
    if switch_asset:
        frame.loc[1, "weight_b"] = 1.0
    bps = 9_999.999999999998
    rate = Fraction.from_float(bps / 10_000)
    expected = _exact_replay(frame, rate)[-1]["ending_equity"]
    actual = _run(frame, transaction_cost_bps=bps)["metrics"]["final_equity"]
    assert actual == pytest.approx(float(expected), rel=2e-13, abs=0.0)


def test_tiny_binary64_cash_residual_survives_a_nearly_total_loss(verified_native):
    frame = _frame(2)
    frame["weight_a"] = [1.0 - 2**-53, 0.0]
    frame["weight_b"] = [2**-54, 0.0]
    frame["return_a"] = [-1.0, 0.0]
    frame["return_b"] = [-1.0, 0.0]
    actual = _run(frame, transaction_cost_bps=0.0)
    assert actual["metrics"]["final_equity"] == 100 * 2**-54


def test_total_loss_is_reported_but_later_replay_is_refused(verified_native):
    frame = _frame(2)
    frame["weight_a"] = 1.0
    frame["weight_b"] = 0.0
    frame.loc[0, "return_a"] = -1.0
    one_period = _run(frame.iloc[:1])
    assert one_period["metrics"]["final_equity"] == 0.0
    assert one_period["metrics"]["max_drawdown"] == 1.0
    assert one_period["series"]["rows"][0]["net_return"] == -1.0
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(frame)
    assert (caught.value.code, caught.value.row) == ("QUANT_REPLAY_NONPOSITIVE_EQUITY", 1)


def test_bad_abi_output_length_is_rejected_before_execution(verified_native, monkeypatch):
    library, _ = replay._loaded()
    monkeypatch.setattr(library, "arboris_quant_replay_output_len", lambda _: 0)
    monkeypatch.setattr(library, "arboris_quant_replay", lambda *args: pytest.fail("called with an invalid ABI length"))
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(_frame())
    assert caught.value.code == "QUANT_REPLAY_NATIVE_INVALID"


def test_bad_native_result_fails_independent_accounting(verified_native, monkeypatch):
    original = replay._native_call

    def corrupted(*args):
        result = original(*args)
        result[0, replay._FEES] += 1.0
        return result

    monkeypatch.setattr(replay, "_native_call", corrupted)
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(_frame())
    assert caught.value.code == "QUANT_REPLAY_NATIVE_INVALID"


def test_subnanosecond_iso_gap_is_rejected_before_rounding(verified_native):
    frame = _frame(2)
    frame["signal"] = ["2026-01-01T00:00:00Z", "2026-01-01T00:00:01.5Z"]
    frame["execute"] = ["2026-01-01T00:00:01Z", "2026-01-01T00:00:02.0000000002Z"]
    frame["end"] = ["2026-01-01T00:00:02.0000000001Z", "2026-01-01T00:00:03Z"]
    with pytest.raises(replay.QuantReplayError) as caught:
        _run(frame)
    assert caught.value.code == "QUANT_REPLAY_INVALID_INPUT"
    assert "nine fractional" in str(caught.value)


def _risk(frame, window=3):
    return replay.run_rolling_risk(frame, time_col="signal", return_columns=["return_a", "return_b"], window=window)


def _covariance_exact(rows):
    n = len(rows)
    columns = [tuple(map(Fraction, column)) for column in zip(*rows)]
    return [
        [float((sum(x * y for x, y in zip(left, right)) - sum(left) * sum(right) / n) / (n - 1))
         for right in columns]
        for left in columns
    ]


def test_rolling_risk_matches_fraction_and_retains_local_units(verified_native):
    rng = random.Random(20261105)
    frame = _frame(28)
    frame["signal"] = [i * 3 for i in range(len(frame))]
    frame["return_a"] = [2**44 + rng.randrange(-64, 65) / 64 for _ in range(len(frame))]
    frame["return_b"] = [-2**44 + rng.randrange(-64, 65) / 64 for _ in range(len(frame))]
    for window in (2, 3, 7, 19):
        actual = _risk(frame, window)
        assert actual["contract_version"] == "quant_rolling_risk_v1"
        assert actual["engine"]["build_identity_sha256"] == verified_native["build_identity_sha256"]
        assert actual["assumptions"]["annualized"] is False
        assert actual["assumptions"]["source_vintage_verified"] is False
        assert actual["metrics"]["warmup_rows"] == window - 1
        assert actual["metrics"]["complete_windows"] == len(frame) - window + 1
        assert actual["series"]["privacy"] == actual["latest_covariance"]["privacy"] == "local_only"
        for point in actual["series"]["rows"]:
            row = point["row"]
            rows = frame[["return_a", "return_b"]].iloc[row + 1 - window:row + 1]
            matrix = _covariance_exact(list(rows.itertuples(index=False, name=None)))
            expected = [matrix[0][0] ** 0.5, matrix[1][1] ** 0.5]
            assert point["time"] == str(frame.loc[row, "signal"])
            assert point["volatility"] == pytest.approx(expected, rel=2e-12, abs=0.0)
        latest = actual["latest_covariance"]
        assert latest["row"] == len(frame) - 1
        assert latest["columns"] == ["return_a", "return_b"]
        for candidate, expected in zip(latest["matrix"], matrix, strict=True):
            assert candidate == pytest.approx(expected, rel=2e-12, abs=2e-15)
        json.dumps(actual, allow_nan=False)


def test_risk_prefix_is_invariant_to_a_valid_future_append(verified_native):
    frame = _frame(13)
    frame["return_a"] = [2.0**20 if i == 3 else i / 64 for i in range(len(frame))]
    complete = _risk(frame, 5)
    shorter = _risk(frame.iloc[:-2], 5)
    assert complete["series"]["rows"][:-2] == shorter["series"]["rows"]
    by_row = {point["row"]: point for point in complete["series"]["rows"]}
    assert by_row[7]["volatility"][0] > 1.0
    assert by_row[8]["volatility"][0] < 1.0
    assert complete["latest_covariance"]["matrix"][1] == [0.0, 0.0]


@pytest.mark.parametrize("window", [True, 1, 5, 2049])
def test_risk_requires_a_bounded_complete_window(window):
    with pytest.raises(replay.QuantReplayError) as caught:
        _risk(_frame(), window)
    assert caught.value.code == "QUANT_ROLLING_RISK_INVALID_INPUT"


@pytest.mark.parametrize("column,value,code", [
    ("signal", 0, "QUANT_ROLLING_RISK_TIME_ORDER"),
    ("signal", -1, "QUANT_ROLLING_RISK_TIME_ORDER"),
    ("return_a", float("nan"), "QUANT_ROLLING_RISK_RETURN"),
    ("return_a", float("inf"), "QUANT_ROLLING_RISK_RETURN"),
])
def test_risk_refuses_bad_rows_in_supplied_order(verified_native, column, value, code):
    frame = _frame()
    frame.loc[1, column] = value
    with pytest.raises(replay.QuantReplayError) as caught:
        _risk(frame)
    assert (caught.value.code, caught.value.row) == (code, 1)


def test_risk_bounds_preview_and_refuses_numerical_overflow(verified_native):
    frame = _frame(replay.MAX_SERIES_POINTS + 10)
    frame["return_a"] = [index % 17 / 64 for index in range(len(frame))]
    actual = _risk(frame)
    assert actual["series"]["truncated"] is True
    assert len(actual["series"]["rows"]) == replay.MAX_SERIES_POINTS
    assert (actual["series"]["rows"][0]["row"], actual["series"]["rows"][-1]["row"]) == (2, len(frame) - 1)
    frame.loc[0, "return_a"] = -1e308
    frame.loc[1, "return_a"] = 1e308
    with pytest.raises(replay.QuantReplayError) as caught:
        _risk(frame)
    assert caught.value.code == "QUANT_ROLLING_RISK_NUMERICAL"


def test_risk_uses_exact_nanosecond_clock_within_the_iso_boundary(verified_native):
    frame = _frame()
    frame["signal"] = [f"2026-01-01T00:00:00.{index:09d}Z" for index in range(1, 5)]
    actual = _risk(frame)
    assert actual["inputs"]["time_format"] == "iso8601_utc"
    assert actual["series"]["rows"][0]["time"] == "2026-01-01T00:00:00.000000003+00:00"


def test_maximum_risk_width_and_window_match_an_analytic_rank_one_panel(verified_native):
    width, window = replay.MAX_ASSETS, replay.MAX_RISK_WINDOW
    observations = 2 * window + 3
    slopes = [(index % 7 - 3) / 8 for index in range(width)]
    names = [f"r{column}" for column in range(width)]
    frame = pd.DataFrame({
        "time": range(observations),
        **{name: [index * slope / 1024 for index in range(observations)]
           for name, slope in zip(names, slopes, strict=True)},
    })
    actual = replay.run_rolling_risk(frame, time_col="time", return_columns=names, window=window)
    ramp_variance = window * (window + 1) / (12 * 1024**2)
    for row, left in zip(actual["latest_covariance"]["matrix"], slopes, strict=True):
        assert row == pytest.approx([left * right * ramp_variance for right in slopes], rel=2e-12, abs=0.0)
    assert actual["metrics"]["complete_windows"] == observations - window + 1


def test_native_risk_shape_rejects_resource_overflow(verified_native):
    library, _ = replay._loaded()
    length = library.arboris_quant_risk_output_len
    assert length(replay.MAX_PERIODS + 1, 1, 2) == 0
    assert length(4, replay.MAX_ASSETS + 1, 2) == 0
    assert length(replay.MAX_PERIODS, 1, replay.MAX_RISK_WINDOW + 1) == 0


def test_risk_corrupt_native_covariance_is_rejected(verified_native, monkeypatch):
    original = replay._risk_native_call

    def corrupted(*args):
        volatility, matrix = original(*args)
        matrix[0, 1] += 0.01
        matrix[1, 0] = matrix[0, 1]
        return volatility, matrix

    monkeypatch.setattr(replay, "_risk_native_call", corrupted)
    with pytest.raises(replay.QuantReplayError) as caught:
        _risk(_frame())
    assert caught.value.code == "QUANT_ROLLING_RISK_NATIVE_INVALID"
