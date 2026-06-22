import pandas as pd
from pathlib import Path

from workbench.engine.stages.estimation import CORE_PACK
from workbench.orchestrator import _model_types

_FIX = Path(__file__).parent / "fixtures" / "dcdh"


def test_dcdh_registered_explicit_only():
    handlers = {h.model_type for h in CORE_PACK.model_handlers}
    assert "dcdh" in handlers
    # explicit-only: NOT a y-type default
    for mt in CORE_PACK.defaults_by_y_type.values():
        assert mt != "dcdh"


def test_dcdh_model_type_is_continuous():
    assert _model_types._MODEL_TYPE_MAP["dcdh"] == "continuous"
    assert _model_types._MODEL_METADATA["dcdh"]["model_id"] == "dcdh_1"


def test_run_dcdh_reexported_from_orchestrator():
    from workbench import orchestrator
    assert hasattr(orchestrator, "run_dcdh")
