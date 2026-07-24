"""Integration-owned ETS registry and capability wiring."""

from __future__ import annotations

from workbench.engine.capabilities import build_capabilities
from workbench.engine.packs import bootstrap_builtin_packs
from workbench.engine.registry import MODEL_REGISTRY


def test_builtin_ets_pack_is_registered_and_exposed_as_a_capability() -> None:
    bootstrap_builtin_packs()

    assert "time_series.ets" in MODEL_REGISTRY
    capability = next(
        item
        for item in build_capabilities()["model_types"]
        if item["key"] == "time_series.ets"
    )
    assert capability["schema_id"] == "time_series.ets@v1"
    assert capability["group"] == "Time Series"
    assert capability["requires"] == ["time", "value"]

