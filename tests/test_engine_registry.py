import pytest
import pandas as pd

from workbench.engine.context import DataHandle, ModelingContext
from workbench.engine.registry import (
    MODEL_REGISTRY,
    DEFAULT_BY_Y_TYPE,
    resolve,
    register_model,
    ModelHandler,
)
import workbench.engine.stages.estimation  # noqa: F401 — registers core pack


def _ctx(*, y_type=None, requested=None):
    h = DataHandle.of(
        pd.DataFrame({"y": [0, 1], "x": [1.0, 2.0]}),
        artifact_id="cleaned_dataset",
        provenance=(),
    )
    return ModelingContext(
        data=h,
        y_col="y",
        x_cols=["x"],
        y_type=y_type,
        requested_model_type=requested,
    )


def test_resolve_auto_uses_y_type_default():
    assert resolve(_ctx(y_type="continuous")).model_type == "ols"
    assert resolve(_ctx(y_type="binary")).model_type == "logit"
    assert resolve(_ctx(y_type="count")).model_type == "poisson_rate"


def test_resolve_explicit_type_wins_over_y_type():
    assert resolve(_ctx(y_type="continuous", requested="logit")).model_type == "logit"
    assert resolve(_ctx(y_type="binary", requested="probit")).model_type == "probit"
    assert resolve(_ctx(y_type="count", requested="negative_binomial")).model_type == "negative_binomial"
    assert resolve(_ctx(y_type="continuous", requested="panel_ols")).model_type == "panel_ols"


def test_resolve_glm_family_collapses_to_glm_key():
    assert resolve(_ctx(y_type="count", requested="glm:gaussian")).model_type == "glm"
    assert resolve(_ctx(y_type="continuous", requested="glm:poisson")).model_type == "glm"


def test_resolve_unknown_explicit_type_raises_no_fallback():
    with pytest.raises(KeyError):
        resolve(_ctx(y_type="continuous", requested="does_not_exist"))


def test_register_model_extends_registry_without_touching_orchestrator():
    """Acceptance criterion: a new model can be added via register_model
    alone, without editing _run_workflow."""
    register_model(ModelHandler(
        model_type="dummy_x",
        model_id="dummy_1",
        serves_y_types=("continuous",),
        fit=lambda ctx, env: ("dummy_1", {"coefficients": {}}, None),
    ))
    assert "dummy_x" in MODEL_REGISTRY
    assert resolve(_ctx(y_type="continuous", requested="dummy_x")).model_id == "dummy_1"
