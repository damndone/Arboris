"""Wiring/registration tests for the sa_did model_type (Sun-Abraham, Task 7).

Mirrors test_cs_did_wiring.py: explicit-only registration, orchestrator
re-export, model-type map, capabilities 4-way sync, and the missing
entity/time guard.
"""
import numpy as np
import pandas as pd

from workbench.engine.stages.estimation import CORE_PACK
from workbench.orchestrator._model_types import _MODEL_TYPE_MAP
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project


def test_sa_did_registered_explicit_only():
    keys = [h.model_type for h in CORE_PACK.model_handlers]
    assert "sa_did" in keys
    assert "sa_did" not in CORE_PACK.defaults_by_y_type.values()
    assert _MODEL_TYPE_MAP["sa_did"] == "continuous"


def test_sa_did_orchestrator_reexports_run_sa_did():
    from workbench import orchestrator
    assert hasattr(orchestrator, "run_sa_did")


def test_sa_did_capabilities_sync():
    from workbench.engine.capabilities import (
        MODEL_UI_META, MODEL_UI_ORDER, build_capabilities,
    )
    assert MODEL_UI_META["sa_did"]["group"] == "DID"
    assert "sa_did" in MODEL_UI_ORDER
    caps = build_capabilities()
    keys = {m["key"] for m in caps["model_types"]}
    assert "sa_did" in keys


def test_sa_did_in_capabilities_sample():
    import json
    from pathlib import Path
    sample = json.loads(
        (Path(__file__).parent / "contracts" / "capabilities.sample.json").read_text())
    keys = {m["key"] for m in sample["model_types"]}
    assert "sa_did" in keys


def test_sa_did_missing_entity_time_fails_clearly(tmp_path):
    rng = np.random.default_rng(7)
    src = tmp_path / "flat.csv"
    pd.DataFrame({"y": rng.normal(size=60), "x1": rng.normal(size=60)}).to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    try:
        result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="sa_did",
                     did_mode="cohort", did_cohort_col="x1")
        run_id = result["run_id"]
    except Exception:
        runs = sorted((project.root / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
        run_id = runs[-1].name
    run_root = project.root / "runs" / run_id
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "failed"
    errors = read_json(run_root / "errors.json")
    codes = [i.get("code") for i in errors.get("issues", [])]
    assert "SA_DID_FIELDS_MISSING" in codes
