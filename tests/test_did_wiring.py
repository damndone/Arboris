import pandas as pd


def test_did_handler_registered():
    """The did handler is registered in the model registry (explicit-only)."""
    from workbench.engine.stages import estimation  # ensures CORE_PACK registered
    from workbench.engine.registry import MODEL_REGISTRY
    assert "did" in MODEL_REGISTRY


def test_did_is_explicit_only_not_a_ytype_default():
    """An auto continuous run must NOT resolve to did (did is explicit-only)."""
    from workbench.engine.stages.estimation import CORE_PACK
    assert "did" not in CORE_PACK.defaults_by_y_type.values()


def test_orchestrator_reexports_run_did():
    """_fit_did calls _orch().run_did, so it must be reachable on the orchestrator."""
    from workbench import orchestrator
    assert hasattr(orchestrator, "run_did")


def test_did_model_type_maps_to_continuous():
    from workbench.orchestrator._model_types import _MODEL_TYPE_MAP
    assert _MODEL_TYPE_MAP.get("did") == "continuous"


def test_did_capabilities_declare_native_timing_fields_and_optional_covariates():
    """The generic Notebook form must not expose DID as an OLS-shaped model."""

    from workbench.engine.capabilities import build_capabilities

    capabilities = {
        item["key"]: item
        for item in build_capabilities()["model_types"]
        if item["key"] in {"cs_did", "sa_did", "dcdh"}
    }
    assert set(capabilities) == {"cs_did", "sa_did", "dcdh"}
    for model_type in ("cs_did", "sa_did"):
        params = {item["key"]: item for item in capabilities[model_type]["params"]}
        # `labels` (v1.8.7 A2) carries column metadata -- measurement levels and
        # variable/value labels -- and is published for every family because it
        # describes the data, not the model. Kept in the exact set rather than
        # loosening this to a subset check: the point of the assertion is that
        # no OLS-shaped field creeps in, and a subset check would not catch that.
        assert set(params) == {
            "model_type", "x", "entity_col", "time_col", "cohort_col", "labels",
        }
        assert params["x"]["required"] is False
        assert params["entity_col"]["required"] is True
        assert params["time_col"]["required"] is True
        assert params["cohort_col"]["required"] is True
    dcdh_params = {item["key"]: item for item in capabilities["dcdh"]["params"]}
    assert set(dcdh_params) == {
        "model_type",
        "x",
        "entity_col",
        "time_col",
        "treatment_path_col",
        "labels",  # column metadata, published for every family -- see above
    }
    assert dcdh_params["x"]["required"] is False
    assert "covariance" not in dcdh_params


import numpy as np
from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project


def _staggered_csv(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "did.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_did_params_thread_to_artifacts_and_run_completes(tmp_path):
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    run_root = project.root / "runs" / result["run_id"]
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"


def test_did_missing_entity_time_fails_clearly(tmp_path):
    # A flat cross-section has no detectable entity/time, so the
    # EstimationStage pre-check must raise DID_FIELDS_MISSING. (The staggered
    # panel above has id/year columns that get auto-detected as candidates, so
    # it would NOT trip the guard — we need data with no panel structure.)
    rng = np.random.default_rng(7)
    src = tmp_path / "flat.csv"
    pd.DataFrame({"y": rng.normal(size=60), "x1": rng.normal(size=60)}).to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    try:
        result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="did",
                     did_mode="cohort", did_cohort_col="x1")  # no entity/time
        run_id = result["run_id"]
    except Exception:
        # The DID_FIELDS_MISSING guard raises WorkflowValidationError, which
        # run_workflow re-raises after recording a failed manifest. Recover the
        # run_id from the most recent run dir to inspect what was recorded.
        runs = sorted((project.root / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
        run_id = runs[-1].name
    run_root = project.root / "runs" / run_id
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "failed"
    errors = read_json(run_root / "errors.json")
    codes = [i.get("code") for i in errors.get("issues", [])]
    assert "DID_FIELDS_MISSING" in codes


def test_did_diagnostics_failure_does_not_kill_successful_run(tmp_path, monkeypatch):
    # Fix 1: if build_did_diagnostics raises, the already-fit did_1 result must
    # survive; the run completes and a degraded did_diagnostics artifact is written.
    import workbench.engine.stages.diagnostics as diag_stage
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")

    def boom(*a, **k):
        raise RuntimeError("kaboom in diagnostics")

    monkeypatch.setattr(
        "workbench.engine.did_diagnostics.build_did_diagnostics", boom
    )
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    run_root = project.root / "runs" / result["run_id"]
    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"
    # the model result survived
    model_results = read_json(run_root / "model_results" / "did_1.json")
    assert model_results is not None
    # degraded diagnostics artifact written
    diag = read_json(run_root / "did_diagnostics.json")
    assert diag["available"] is False
    assert "error" in diag


def test_did_end_to_end_writes_diagnostics_and_calls_run_did(tmp_path, monkeypatch):
    from workbench import orchestrator as orch
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    captured = {}
    real = orch.run_did

    def spy(frame, **kwargs):
        captured.update(kwargs)
        captured["has_did_D"] = "_did_D" in frame.columns
        return real(frame, **kwargs)

    monkeypatch.setattr(orch, "run_did", spy)
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    # the spy proves the wiring actually called run_did with real args
    assert captured["entity"] == "id" and captured["time"] == "year"
    assert captured["has_did_D"] is True  # normalized cohort frame was passed
    run_root = project.root / "runs" / result["run_id"]
    from workbench.artifacts import read_json
    assert (run_root / "did_diagnostics.json").exists()
    diag = read_json(run_root / "did_diagnostics.json")
    assert set(diag) >= {"att", "event_study", "parallel_trends", "goodman_bacon", "spec"}
    # artifact registered in the index
    idx = read_json(run_root / "artifacts_index.json")
    assert any(a["artifact_id"] == "did_diagnostics" for a in idx["artifacts"])
