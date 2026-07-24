"""The pack declares exactly one handler and runs through the engine seam.

Central registration stays Integration-owned, so these tests declare the pack
inside a snapshot fixture and restore every shared registry afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.models.ets.known_truth import short_stable_series
from workbench.contracts.model.ets import ETS_MODEL_TYPE
from workbench.engine.context import DataHandle, ModelingContext, RunEnv
from workbench.engine.packs.ets.declaration import declare_pack
from workbench.engine.packs.ets.errors import ETSInputError
from workbench.engine.packs.ets.runner import MODEL_ID, fit_from_context


class _Recorder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, object]] = []
        self.edges: list[dict[str, object]] = []

    def record_stage(self, node_id, display_label, **kwargs) -> None:
        self.nodes.append({"node_id": node_id, "display_label": display_label, **kwargs})

    def record_edge(self, edge_id, source_id, target_id, op, **kwargs) -> None:
        self.edges.append({"edge_id": edge_id, "op": op})


@pytest.fixture
def declared_pack():
    from workbench.engine import capabilities
    from workbench.engine.pack import REGISTERED_PACKS, RERUN_ACTION_REGISTRY
    from workbench.engine.registry import DEFAULT_BY_Y_TYPE, MODEL_REGISTRY

    before = (
        dict(MODEL_REGISTRY),
        dict(DEFAULT_BY_Y_TYPE),
        list(REGISTERED_PACKS),
        list(RERUN_ACTION_REGISTRY),
        dict(capabilities._DECLARED_CAPABILITIES),
    )
    # Integration bootstraps ETS as a builtin. Keep this direct declaration
    # test focused on the pack's own contribution instead of colliding with a
    # handler/capability left by an earlier capability query.
    MODEL_REGISTRY.pop(ETS_MODEL_TYPE, None)
    REGISTERED_PACKS[:] = [
        pack for pack in REGISTERED_PACKS if pack.pack_id != ETS_MODEL_TYPE
    ]
    capabilities._DECLARED_CAPABILITIES.pop(ETS_MODEL_TYPE, None)
    declare_pack()
    try:
        yield MODEL_REGISTRY
    finally:
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(before[0])
        DEFAULT_BY_Y_TYPE.clear()
        DEFAULT_BY_Y_TYPE.update(before[1])
        REGISTERED_PACKS[:] = before[2]
        RERUN_ACTION_REGISTRY[:] = before[3]
        capabilities._DECLARED_CAPABILITIES.clear()
        capabilities._DECLARED_CAPABILITIES.update(before[4])


def _options(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "time_column": "date",
        "value_column": "y",
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
    }
    payload.update(overrides)
    return payload


def _context(options=None) -> ModelingContext:
    frame = short_stable_series().frame()
    ctx = ModelingContext(
        data=DataHandle.of(frame, artifact_id="cleaned_dataset", provenance=("raw.csv",)),
        y_col="y",
        x_cols=[],
        y_type="continuous",
        requested_model_type=ETS_MODEL_TYPE,
    )
    ctx.artifacts["_model_options"] = options if options is not None else _options()
    return ctx


def test_declaration_registers_exactly_one_handler(declared_pack) -> None:
    handler = declared_pack[ETS_MODEL_TYPE]

    assert handler.model_id == MODEL_ID
    assert handler.serves_y_types == ("continuous",)
    assert handler.model_options_contract.input_contract_version == "1.1"
    assert handler.validate_model_options(_options()).specification.canonical == "ETS(A,A,N)"


def test_declaration_exposes_one_selectable_capability(declared_pack) -> None:
    from workbench.engine.capabilities import build_capabilities

    entries = [
        entry
        for entry in build_capabilities()["model_types"]
        if entry.get("key") == ETS_MODEL_TYPE
    ]

    assert len(entries) == 1
    assert entries[0]["label"] == "ETS Exponential Smoothing"
    assert entries[0]["group"] == "Time Series"
    assert entries[0]["requires"] == ["time", "value"]


def test_fit_from_context_returns_the_public_packet(tmp_path: Path) -> None:
    ctx = _context()
    run_root = tmp_path / "ets-run"
    run_root.mkdir()

    model_id, packet, extra = fit_from_context(
        ctx, RunEnv(run_root=run_root, run_id="ets-run", recorder=_Recorder())
    )

    assert model_id == MODEL_ID
    assert extra is None
    assert packet["result"]["model_type"] == ETS_MODEL_TYPE
    assert packet["result"]["specification"]["canonical"] == "ETS(A,A,N)"
    assert packet["result"]["n_obs"] == 120
    assert packet["result"]["convergence_code"] == "converged"
    assert packet["producer_version"] == "time_series.ets@1.0"
    assert len(packet["sample_fingerprint"]) == 64
    assert ctx.artifacts["_ets_result"] is packet


def test_fit_from_context_records_a_blocking_diagnostic(tmp_path: Path) -> None:
    frame_options = _options(value_column="absent_column")
    ctx = _context(frame_options)
    run_root = tmp_path / "ets-blocked"
    run_root.mkdir()

    with pytest.raises(ETSInputError):
        fit_from_context(
            ctx, RunEnv(run_root=run_root, run_id="ets-blocked", recorder=_Recorder())
        )

    diagnostic = ctx.artifacts["_ets_diagnostic"]
    assert diagnostic["code"] == "ETS_INPUT_COLUMN_MISSING"
    assert diagnostic["severity"] == "blocking"
    assert "_ets_result" not in ctx.artifacts
