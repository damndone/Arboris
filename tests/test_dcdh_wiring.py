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


# --- T9: end-to-end run_workflow -> dcdh.json artifact ------------------------
def test_dcdh_end_to_end_writes_artifact(tmp_path):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    from workbench.artifacts import read_json

    src = tmp_path / "data.csv"
    pd.read_csv(_FIX / "panel_nonabsorbing.csv").to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [src], mode="explicit", model_type="dcdh",
                          y="y", x=[], entity_col="id", time_col="year",
                          did_treatment_path="d")
    run_root = project.root / "runs" / result["run_id"]
    art = read_json(run_root / "dcdh.json")
    assert art["estimator"] == "dcdh"
    assert art["event_study"]["label_kind"] == "event_time"
    assert art["honest_did_supported"] is False
    assert art["available"] is True
