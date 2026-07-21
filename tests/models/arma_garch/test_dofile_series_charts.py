"""Do-file series plots that had data but no chart artifact.

The reference plots four series the pack computed and then never emitted:

    tsline ht                 // conditional VARIANCE h_t, not sqrt(h_t)
    tsline zG                 // standardized residuals z_t
    tsline z2G                // standardized squared residuals z_t^2
    tsline e2_arma            // mean-model squared residuals e_t^2

An earlier audit recorded these as covered because their *correlograms* were
emitted; the series themselves were not. Only `ts.chart.residual_series`
(e_t) and `ts.chart.conditional_volatility` (sd_t) existed.
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
    rng = np.random.default_rng(20260721)
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
            "_upload_hash": "e" * 64,
            "_raw_inputs": ["raw.csv"],
        }
    )
    _, _result, _ = fit_from_context(
        ctx, RunEnv(run_root=run_root, run_id="run", recorder=_Recorder())
    )
    index = json.loads((run_root / "artifacts_index.json").read_text())
    records = {item["artifact_id"]: item for item in index["artifacts"]}

    def payload(artifact_id: str):
        return json.loads((run_root / records[artifact_id]["path"]).read_text())["payload"]

    return records, payload


def test_conditional_variance_is_emitted_separately_from_volatility(tmp_path: Path) -> None:
    """`tsline ht` plots h_t. Squaring sd_t in the UI would be the caller
    re-deriving a quantity the model already produced."""

    records, payload = _run(tmp_path)

    assert "ts.chart.conditional_variance" in records
    rows = payload("ts.chart.conditional_variance")["rows"]
    assert rows
    volatility = {r["row_id"]: r["conditional_volatility"] for r in payload("ts.chart.conditional_volatility")["rows"]}
    for row in rows[:5]:
        assert row["conditional_variance"] > 0.0
        # h_t and sd_t are the same object seen twice; they must agree.
        assert row["conditional_variance"] == pytest.approx(volatility[row["row_id"]] ** 2)


def test_standardized_residual_series_is_emitted(tmp_path: Path) -> None:
    records, payload = _run(tmp_path)

    assert "ts.chart.standardized_residual_series" in records
    rows = payload("ts.chart.standardized_residual_series")["rows"]
    assert rows
    for row in rows[:5]:
        assert isinstance(row["standardized_residual"], float)
        assert row["row_id"]


def test_squared_standardized_residual_series_is_emitted(tmp_path: Path) -> None:
    """The Do-file plots z_t^2 to show whether GARCH removed the clustering."""

    records, payload = _run(tmp_path)

    assert "ts.chart.squared_standardized_residual_series" in records
    rows = payload("ts.chart.squared_standardized_residual_series")["rows"]
    z_rows = payload("ts.chart.standardized_residual_series")["rows"]
    assert len(rows) == len(z_rows)
    for squared, plain in zip(rows[:5], z_rows[:5]):
        assert squared["squared_standardized_residual"] == pytest.approx(
            plain["standardized_residual"] ** 2
        )


def test_squared_residual_series_is_emitted(tmp_path: Path) -> None:
    """Only the squared-residual *correlogram* existed; the series did not."""

    records, payload = _run(tmp_path)

    assert "ts.chart.squared_residual_series" in records
    rows = payload("ts.chart.squared_residual_series")["rows"]
    plain = payload("ts.chart.residual_series")["rows"]
    assert len(rows) == len(plain)
    for squared, source in zip(rows[:5], plain[:5]):
        assert squared["position"] == source["position"]
        assert squared["value"] == pytest.approx(source["value"] ** 2)


def test_the_new_series_charts_are_required_artifacts(tmp_path: Path) -> None:
    from workbench.engine.packs.arma_garch.runner import (
        _NODE_BY_ARTIFACT,
        _REQUIRED_LOGICAL_ARTIFACTS,
    )

    for artifact_id in (
        "ts.chart.conditional_variance",
        "ts.chart.standardized_residual_series",
        "ts.chart.squared_standardized_residual_series",
        "ts.chart.squared_residual_series",
    ):
        assert artifact_id in _REQUIRED_LOGICAL_ARTIFACTS
        # A required artifact with no owning node cannot be attributed on the graph.
        assert artifact_id in _NODE_BY_ARTIFACT


import pytest  # noqa: E402  (imported late so the module docstring leads)
