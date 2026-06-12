import pytest

from workbench.engine.pack import (
    AnalysisPack, RerunAction, register_pack, RERUN_ACTION_REGISTRY,
)
from workbench.engine.recommended_actions import actions_for_model_fit_failure


@pytest.fixture(autouse=True)
def restore_registered_packs():
    from workbench.engine.pack import REGISTERED_PACKS
    snap = list(REGISTERED_PACKS)
    yield
    REGISTERED_PACKS[:] = snap


@pytest.fixture
def restore_rerun_registry():
    snapshot = list(RERUN_ACTION_REGISTRY)
    yield
    RERUN_ACTION_REGISTRY[:] = snapshot


def test_pack_rerun_action_reaches_failure_actions(restore_rerun_registry):
    register_pack(AnalysisPack(
        pack_id="t_rerun",
        rerun_actions=[RerunAction(
            key="rerun_robust", label="Re-run robust",
            param_overrides={"covariance": "robust"},
        )],
    ))
    actions = actions_for_model_fit_failure(
        requested_model_type="panel_ols", y_type="continuous",
    )
    keys = {a["key"] for a in actions}
    assert "rerun_robust" in keys
    action = next(a for a in actions if a["key"] == "rerun_robust")
    assert action["label"] == "Re-run robust"
    assert action["form_overrides"] == {"covariance": "robust"}


def test_empty_registry_leaves_actions_unchanged(restore_rerun_registry):
    RERUN_ACTION_REGISTRY[:] = []
    actions = actions_for_model_fit_failure(
        requested_model_type="panel_ols", y_type="continuous",
    )
    assert all("rerun_robust" != a["key"] for a in actions)
