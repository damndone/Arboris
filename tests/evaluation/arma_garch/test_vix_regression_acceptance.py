"""VIX regression acceptance for the v1.8 ARMA-GARCH pack (section 23).

VIX is only a frozen configuration regression sample. When the repository holds
no genuine VIX CSV, the manual replication profile *skips deterministically* with
an explicit ``missing_external_acceptance_input`` reason — it must never be
reported as "VIX passed". The generic auto flow is still proven here on synthetic
VIX-like data, and the pack source is scanned to prove it contains no VIX
special-casing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.fixtures.models.arma_garch.vix_profiles import (
    MISSING_VIX_INPUT_REASON,
    REFERENCE_SEMANTICS,
    VIX_GENERIC_AUTO_PROFILE,
    VIX_REPLICATION_PROFILE,
    locate_repository_vix_csv,
)
from workbench.engine.context import DataHandle, ModelingContext, RunEnv


PACK_DIR = Path(__file__).resolve().parents[3] / (
    "backend/workbench/engine/packs/arma_garch"
)


class _Recorder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, object]] = []

    def record_stage(self, node_id, display_label, **kwargs) -> None:
        self.nodes.append({"node_id": node_id})

    def record_edge(self, *args, **kwargs) -> None:
        pass


def _vix_like_source(n: int = 320) -> pd.DataFrame:
    """A strictly-positive, trading-day GARCH-like level series (VIX-shaped)."""

    rng = np.random.default_rng(90210)
    log_level = np.zeros(n)
    log_level[0] = math.log(18.0)
    errors = np.zeros(n)
    variances = np.full(n, 0.02)
    for index in range(1, n):
        variances[index] = 0.001 + 0.10 * errors[index - 1] ** 2 + 0.85 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
        log_level[index] = 0.995 * log_level[index - 1] + 0.005 * math.log(18.0) + errors[index]
    return pd.DataFrame(
        {"date": pd.bdate_range("2018-01-02", periods=n), "vix_close": np.exp(log_level)}
    )


def _generic_options(frame: pd.DataFrame, time_col: str, value_col: str) -> dict[str, object]:
    options = dict(VIX_GENERIC_AUTO_PROFILE["contract_template"])
    options.update(
        {
            "dataset_ref": "dataset:vix-like-synthetic:1",
            "time_column": time_col,
            "value_column": value_col,
        }
    )
    return options


def test_repository_vix_input_presence_is_explicit() -> None:
    located = locate_repository_vix_csv()
    # The committed benchmark dataset must stay discoverable; losing it would
    # silently downgrade the replication test back to a skip.
    assert located is not None, "the committed VIXCLS benchmark dataset is missing"
    assert located.path.name == "VIXCLS.csv"
    assert located.time_column == "observation_date"
    assert located.value_column == "VIXCLS"
    assert located.row_count > 2000


def test_vix_replication_profile_runs_or_skips_by_contract(tmp_path: Path) -> None:
    located = locate_repository_vix_csv()
    if located is None:
        # Deterministic, contract-defined skip. NOT a pass.
        assert VIX_REPLICATION_PROFILE["reference_semantics"] == REFERENCE_SEMANTICS
        assert VIX_REPLICATION_PROFILE["contract_template"]["arma"] == {
            "p": 1,
            "q": 1,
            "constant_mode": "include",
        }
        assert VIX_REPLICATION_PROFILE["contract_template"]["estimation_strategy"] == (
            "sequential"
        )
        pytest.skip(
            f"{MISSING_VIX_INPUT_REASON}: no genuine VIX CSV in the repository; "
            "vix_replication_profile is skipped by contract, not passed."
        )

    frame = pd.read_csv(located.path)
    options = dict(VIX_REPLICATION_PROFILE["contract_template"])
    options.update(
        {
            "dataset_ref": f"dataset:vix:{located.path.name}",
            "time_column": located.time_column,
            "value_column": located.value_column,
            "validation": {"validation_n": 250, "refit_every": 1},
        }
    )
    result, records, run_root = _run_generic(tmp_path, "vix-replication", frame, options)

    manifest = json.loads(
        (run_root / records["ts.artifact_manifest"]["path"]).read_text()
    )["payload"]
    assert manifest["status"] == "complete"

    # Stata's `arch` is a joint MLE with an MA term; v1.8 estimates q>0
    # sequentially. Only directional / workflow parity is asserted.
    assert VIX_REPLICATION_PROFILE["reference_semantics"] == REFERENCE_SEMANTICS
    assert result["estimation_strategy"] == "sequential"
    assert result["joint_likelihood"] is False

    # Non-trading rows are excluded, never filled, and the source is untouched.
    audit = json.loads((run_root / records["ts.data_audit"]["path"]).read_text())["payload"]
    excluded = next(
        item for item in audit["diagnostics"] if item["code"] == "MISSING_OBSERVATIONS_EXCLUDED"
    )
    assert excluded["severity"] == "information"
    assert excluded["evidence"]["excluded_missing_count"] > 0

    # Trading-day persistence with a finite half-life reported in observation
    # periods (never silently converted to calendar days).
    final_fit = json.loads((run_root / records["ts.final_model"]["path"]).read_text())[
        "payload"
    ]["validation_fit"]
    persistence = final_fit["persistence"]
    assert 0.0 < persistence["persistence"] < 1.0
    assert persistence["half_life"] > 0.0
    assert persistence["half_life_unit"] == "business_or_trading_observation_periods"

    # Rolling one-step validation actually produced the frozen number of origins.
    metrics = json.loads((run_root / records["ts.forecast_metrics"]["path"]).read_text())[
        "payload"
    ]
    assert metrics["validation_n"] == 250
    assert metrics["successful_forecast_n"] == 250
    assert 0.0 <= metrics["interval_coverage"] <= 1.0
    assert metrics["exception_count"] >= 0


def _run_generic(tmp_path: Path, run_id: str, frame: pd.DataFrame, options: dict[str, object]):
    from workbench.engine.packs.arma_garch.runner import fit_from_context

    run_root = tmp_path / run_id
    run_root.mkdir()
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"artifacts": []}), encoding="utf-8"
    )
    ctx = ModelingContext(
        data=DataHandle.of(
            frame.copy(deep=True), artifact_id="cleaned_dataset", provenance=("raw_input.csv",)
        ),
        y_col=str(options["value_column"]),
        x_cols=[],
        y_type="continuous",
        requested_model_type="time_series.arma_garch",
    )
    ctx.artifacts.update(
        {
            "_model_options": options,
            "_frames": {"input.csv": frame},
            "_upload_hash": "c" * 64,
            "_raw_inputs": ["raw_input.csv"],
        }
    )
    _, result, _ = fit_from_context(
        ctx, RunEnv(run_root=run_root, run_id=run_id, recorder=_Recorder())
    )
    index = json.loads((run_root / "artifacts_index.json").read_text())
    records = {item["artifact_id"]: item for item in index["artifacts"]}
    return result, records, run_root


def test_vix_generic_auto_profile_runs_on_vix_like_data(tmp_path: Path) -> None:
    frame = _vix_like_source()
    before = frame.copy(deep=True)
    options = _generic_options(frame, "date", "vix_close")
    result, records, run_root = _run_generic(tmp_path, "vix-generic-auto", frame, options)

    manifest = json.loads(
        (run_root / records["ts.artifact_manifest"]["path"]).read_text()
    )["payload"]
    assert manifest["status"] == "complete"
    assert result["selected_specification"]["mean_candidate_id"]
    assert result["selected_specification"]["variance_candidate_id"]
    # A transform recommendation artifact must exist for the auto flow.
    assert "ts.transform_profile" in records
    # Source data untouched by the generic auto flow.
    pd.testing.assert_frame_equal(frame, before)


def test_pack_source_contains_no_vix_special_casing() -> None:
    offenders: list[str] = []
    for module in sorted(PACK_DIR.glob("*.py")):
        text = module.read_text(encoding="utf-8").lower()
        if "vix" in text:
            offenders.append(module.name)
    assert offenders == [], f"pack modules must not special-case VIX: {offenders}"
