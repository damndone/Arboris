import pytest
from workbench.engine.pack import (
    AnalysisPack, RerunAction, register_pack, RERUN_ACTION_REGISTRY, PackContractError,
)


@pytest.fixture
def restore_rerun_registry():
    snap = list(RERUN_ACTION_REGISTRY)
    yield
    RERUN_ACTION_REGISTRY[:] = snap


def test_duplicate_rerun_key_raises(restore_rerun_registry):
    register_pack(AnalysisPack(pack_id="p1", rerun_actions=[
        RerunAction(key="dup", label="A", param_overrides={})]))
    with pytest.raises(PackContractError) as exc:
        register_pack(AnalysisPack(pack_id="p2", rerun_actions=[
            RerunAction(key="dup", label="B", param_overrides={})]))
    assert "dup" in str(exc.value)
