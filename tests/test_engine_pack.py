import pytest
import pandas as pd

from workbench.engine.context import DataHandle, ModelingContext
from workbench.engine.pack import AnalysisPack, register_pack, REGISTERED_PACKS
from workbench.engine.registry import (
    MODEL_REGISTRY, DEFAULT_BY_Y_TYPE, ModelHandler, resolve,
)
import workbench.engine.stages.estimation  # noqa: F401  — registers CORE_PACK


def _ctx(*, y_type=None, requested=None):
    h = DataHandle.of(pd.DataFrame({"y": [0, 1], "x": [1.0, 2.0]}),
                      artifact_id="cleaned_dataset", provenance=())
    return ModelingContext(data=h, y_col="y", x_cols=["x"],
                           y_type=y_type, requested_model_type=requested)


def test_core_pack_is_registered_on_estimation_import():
    """Dogfood proof: the kernel's built-in handlers reach MODEL_REGISTRY via
    register_pack(CORE_PACK), not via loose register_model calls."""
    assert any(p.pack_id == "core" for p in REGISTERED_PACKS)
    # The seven canonical handlers (+ poisson alias) are present:
    for key in ("ols", "logit", "poisson_rate", "probit", "negative_binomial",
                "glm", "panel_ols"):
        assert key in MODEL_REGISTRY


def test_core_pack_seeds_y_type_defaults():
    assert DEFAULT_BY_Y_TYPE["continuous"] == "ols"
    assert DEFAULT_BY_Y_TYPE["binary"] == "logit"
    assert DEFAULT_BY_Y_TYPE["count"] == "poisson_rate"


def test_register_pack_contributes_model_handlers():
    """A third-party pack can register a new model_handler via the SAME
    mechanism the kernel uses."""
    pack = AnalysisPack(
        pack_id="test_pack_handler",
        model_handlers=[ModelHandler(
            "packtest", "packtest_1", ("continuous",),
            lambda ctx, env: ("packtest_1", {"coefficients": {}}, None),
        )],
    )
    register_pack(pack)
    assert "packtest" in MODEL_REGISTRY
    assert any(p.pack_id == "test_pack_handler" for p in REGISTERED_PACKS)
    assert resolve(_ctx(y_type="continuous", requested="packtest")).model_id == "packtest_1"


def test_register_pack_can_override_y_type_default():
    """A pack may declare its own y_type → default routing."""
    # Snapshot then restore so we don't pollute other tests.
    before = DEFAULT_BY_Y_TYPE.get("continuous")
    pack = AnalysisPack(
        pack_id="test_pack_defaults",
        model_handlers=[ModelHandler(
            "fancy_ols", "fancy_ols_1", ("continuous",),
            lambda ctx, env: ("fancy_ols_1", {"coefficients": {}}, None),
        )],
        defaults_by_y_type={"continuous": "fancy_ols"},
    )
    try:
        register_pack(pack)
        assert DEFAULT_BY_Y_TYPE["continuous"] == "fancy_ols"
    finally:
        if before is not None:
            DEFAULT_BY_Y_TYPE["continuous"] = before


def test_pack_declares_future_fields_without_implementing_them():
    """The contract surface for V1.5.6+ is declared; V1.5.4 leaves slots empty."""
    pack = AnalysisPack(pack_id="future")
    assert pack.report_blocks == []
    assert pack.recommended_actions == []
    assert pack.interpretation_restrictions == []
    assert pack.rerun_actions == []
