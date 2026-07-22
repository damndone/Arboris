"""Do-file parity gaps 5 and 6.

Gap 5: `twoway (line abs_y t) (line sd t, yaxis(2))` - the |y_t| vs conditional
volatility overlay that ties volatility bursts to large moves.
Gap 6: full-history in-sample 95% PI bands for ARMA-only vs ARMA-GARCH, the
interval-width difference, and in-sample coverage for both.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from workbench.engine.context import DataHandle, ModelingContext, RunEnv


class _Recorder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, object]] = []

    def record_stage(self, node_id, display_label, **kwargs) -> None:
        self.nodes.append({"node_id": node_id})

    def record_edge(self, *args, **kwargs) -> None:
        pass


def _source(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(4242)
    values = np.zeros(n)
    errors = np.zeros(n)
    variances = np.ones(n)
    for index in range(1, n):
        variances[index] = 0.1 + 0.12 * errors[index - 1] ** 2 + 0.80 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
        values[index] = 0.2 + 0.4 * values[index - 1] + errors[index]
    return pd.DataFrame({"when": pd.bdate_range("2020-01-01", periods=n), "value": values})


def _run(tmp_path: Path):
    from workbench.engine.packs.arma_garch.runner import fit_from_context

    source = _source()
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    ctx = ModelingContext(
        data=DataHandle.of(source.copy(deep=True), artifact_id="cleaned", provenance=("raw.csv",)),
        y_col="value",
        x_cols=[],
        y_type="continuous",
        requested_model_type="time_series.arma_garch",
    )
    ctx.artifacts.update(
        {
            "_model_options": {
                "dataset_ref": "dataset:t:1",
                "time_column": "when",
                "value_column": "value",
                "time_index_semantics": "business_or_trading_observations",
                "transform": "level",
                "transform_confirmed": True,
                "selection_mode": "manual",
                "arma": {"p": 1, "q": 0, "constant_mode": "include"},
                "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
                "estimation_strategy": "joint",
                "innovation_distribution": "normal",
                "validation": {"validation_n": 5, "refit_every": 1},
                "random_seed": 1,
            },
            "_frames": {"input.csv": source},
            "_upload_hash": "d" * 64,
            "_raw_inputs": ["raw.csv"],
        }
    )
    _, result, _ = fit_from_context(
        ctx, RunEnv(run_root=run_root, run_id="run", recorder=_Recorder())
    )
    index = json.loads((run_root / "artifacts_index.json").read_text())
    records = {item["artifact_id"]: item for item in index["artifacts"]}

    def payload(artifact_id: str):
        return json.loads((run_root / records[artifact_id]["path"]).read_text())["payload"]

    return result, records, payload


def test_abs_return_vs_volatility_overlay_is_emitted(tmp_path: Path) -> None:
    _result, records, payload = _run(tmp_path)

    assert "ts.chart.abs_return_vs_volatility" in records
    chart = payload("ts.chart.abs_return_vs_volatility")
    assert chart["dual_axis"] is True
    rows = chart["rows"]
    assert rows
    for row in rows[:5]:
        assert row["abs_value"] >= 0.0
        assert row["conditional_volatility"] > 0.0
        assert row["row_id"]


def test_in_sample_interval_comparison_chart_is_emitted(tmp_path: Path) -> None:
    _result, records, payload = _run(tmp_path)

    assert "ts.chart.in_sample_interval_comparison" in records
    rows = payload("ts.chart.in_sample_interval_comparison")["rows"]
    assert rows
    for row in rows[:5]:
        assert row["garch_lower"] < row["conditional_mean"] < row["garch_upper"]
        assert row["arma_lower"] < row["conditional_mean"] < row["arma_upper"]


def test_comparison_reports_in_sample_coverage_and_width_difference(tmp_path: Path) -> None:
    _result, _records, payload = _run(tmp_path)

    in_sample = payload("ts.arma_vs_garch_comparison")["in_sample"]
    for model in ("arma_garch", "arma_only"):
        assert 0.0 <= in_sample[model]["coverage"] <= 1.0
        assert in_sample[model]["average_width"] > 0.0
        assert in_sample[model]["n"] > 0
    difference = in_sample["width_difference"]
    expected = (
        in_sample["arma_garch"]["average_width"] - in_sample["arma_only"]["average_width"]
    )
    assert difference["mean"] == expected
    assert difference["max"] >= difference["mean"] >= difference["min"]


def test_new_charts_are_required_artifacts(tmp_path: Path) -> None:
    from workbench.engine.packs.arma_garch.runner import _REQUIRED_LOGICAL_ARTIFACTS

    assert "ts.chart.abs_return_vs_volatility" in _REQUIRED_LOGICAL_ARTIFACTS
    assert "ts.chart.in_sample_interval_comparison" in _REQUIRED_LOGICAL_ARTIFACTS
