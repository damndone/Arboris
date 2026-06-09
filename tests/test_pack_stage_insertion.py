import pytest

from workbench.engine.pack import AnalysisPack, StageInsertion, PackContractError, register_pack
from workbench.engine.stages import PIPELINE


class _NoopStage:
    name = "noop_test"
    def run(self, ctx, env):
        return ctx


@pytest.fixture
def restore_pipeline():
    snapshot = list(PIPELINE)
    yield
    PIPELINE[:] = snapshot


def _names():
    return [s.name for s in PIPELINE]


def test_stage_spliced_after_anchor(restore_pipeline):
    register_pack(AnalysisPack(
        pack_id="t_stage",
        stages=[StageInsertion(stage=_NoopStage(), after="estimation")],
    ))
    names = _names()
    assert "noop_test" in names
    assert names.index("noop_test") == names.index("estimation") + 1


def test_bad_anchor_raises(restore_pipeline):
    with pytest.raises(PackContractError):
        register_pack(AnalysisPack(
            pack_id="t_bad",
            stages=[StageInsertion(stage=_NoopStage(), after="no_such_stage")],
        ))
    assert "noop_test" not in _names()  # nothing spliced on failure
