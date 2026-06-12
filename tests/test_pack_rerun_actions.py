import pytest

from workbench.engine.pack import (
    AnalysisPack, RerunAction, register_pack, RERUN_ACTION_REGISTRY,
    PackContractError,
)
from workbench.engine.recommended_actions import (
    actions_for_model_fit_failure, BUILTIN_ACTION_KEYS,
)


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


def test_duplicate_key_across_packs_raises(restore_rerun_registry):
    register_pack(AnalysisPack(
        pack_id="t_first",
        rerun_actions=[RerunAction(key="rerun_robust", label="Re-run robust")],
    ))
    with pytest.raises(PackContractError, match="already registered"):
        register_pack(AnalysisPack(
            pack_id="t_second",
            rerun_actions=[RerunAction(key="rerun_robust", label="Dup")],
        ))


@pytest.mark.parametrize("builtin_key", sorted(BUILTIN_ACTION_KEYS))
def test_key_clashing_with_builtin_raises(restore_rerun_registry, builtin_key):
    with pytest.raises(PackContractError, match="built-in action key"):
        register_pack(AnalysisPack(
            pack_id="t_builtin_clash",
            rerun_actions=[RerunAction(key=builtin_key, label="Clash")],
        ))


def test_duplicate_key_within_one_pack_raises(restore_rerun_registry):
    with pytest.raises(PackContractError, match="declared twice"):
        register_pack(AnalysisPack(
            pack_id="t_self_dup",
            rerun_actions=[
                RerunAction(key="rerun_robust", label="A"),
                RerunAction(key="rerun_robust", label="B"),
            ],
        ))


def test_collision_does_not_partially_register(restore_rerun_registry):
    register_pack(AnalysisPack(
        pack_id="t_existing",
        rerun_actions=[RerunAction(key="rerun_existing", label="Existing")],
    ))
    before = list(RERUN_ACTION_REGISTRY)
    # Second action collides with built-in -> whole pack must be rejected,
    # leaving the good first action unregistered (atomic registration).
    with pytest.raises(PackContractError):
        register_pack(AnalysisPack(
            pack_id="t_partial",
            rerun_actions=[
                RerunAction(key="rerun_ok", label="OK"),
                RerunAction(key="rerun_auto", label="Bad builtin clash"),
            ],
        ))
    assert RERUN_ACTION_REGISTRY == before
    assert all(ra.key != "rerun_ok" for ra in RERUN_ACTION_REGISTRY)
