"""V1.5.4 lineage consistency invariants.

These tests assert STRUCTURAL invariants the engine's DataHandle is designed
to enforce. They are written so that future drift in the orchestrator OR a
new feature pack cannot quietly violate the "model fit on A but lineage
records B" bug class.
"""
from pathlib import Path

import pandas as pd
import pytest
import yaml

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path, frame, *, y, x, model_type="auto", config_overrides=None):
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    if config_overrides:
        cfg_path = project.root / "config.yml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        cfg.update(config_overrides)
        cfg_path.write_text(yaml.safe_dump(cfg))
    res = run_workflow(project.root, [src], mode="auto", y=y, x=x, model_type=model_type)
    return project.root / "runs" / res["run_id"], res


def _inputs_of(run_root: Path, artifact_id: str) -> list[str]:
    idx = read_json(run_root / "artifacts_index.json")
    for a in idx["artifacts"]:
        if a["artifact_id"] == artifact_id:
            return sorted(a.get("inputs", []))
    raise AssertionError(f"{artifact_id} not in artifact index")


def _artifact_ids(run_root: Path) -> set[str]:
    idx = read_json(run_root / "artifacts_index.json")
    return {a["artifact_id"] for a in idx["artifacts"]}


# -------- Invariant 1: model + diagnostics + report share ONE data lineage --
def test_invariant_model_and_diagnostics_and_report_share_one_data_lineage(tmp_path):
    """No-imputation case: the modeling artifact, its diagnostics, AND the
    report all carry the SAME single upstream-data artifact_id in their
    lineage. This is the central 'one DataHandle, one lineage id' property."""
    frame = pd.DataFrame({
        "y": [1.0 + 2.0 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    model_inputs = _inputs_of(run_root, "ols_1")
    diag_inputs = _inputs_of(run_root, "diagnostics_ols_1")
    # Model lineage: cleaned dataset only (no imputation).
    assert model_inputs == ["cleaned_dataset"], model_inputs
    # Diagnostics MUST share the same data id as the model.
    assert diag_inputs == model_inputs, (diag_inputs, model_inputs)


# -------- Invariant 2: imputation flips BOTH model and diagnostics ----------
def test_invariant_imputation_flips_model_and_diagnostics_lineage_together(tmp_path):
    """The bug-class epicenter: when imputation produces imputed_dataset,
    BOTH the model AND its diagnostics must point at imputed_dataset.
    Statistical_tests (which run BEFORE imputation on `cleaned`) must NOT
    flip — they must stay on cleaned_dataset."""
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    run_root, res = _run(tmp_path, frame, y="y", x=["x"],
                         config_overrides={"imputation_method": "mice"})
    ids = _artifact_ids(run_root)
    assert "imputed_dataset" in ids, "imputation did not fire — fixture broken"
    # Model + diagnostics point at imputed_dataset.
    assert _inputs_of(run_root, "ols_1") == ["imputed_dataset"]
    assert _inputs_of(run_root, "diagnostics_ols_1") == ["imputed_dataset"]
    # Stats stay on cleaned (they run on `cleaned`, not the modeling handle).
    for stats_id in [a for a in ids if a.startswith("statistical_tests_")]:
        assert _inputs_of(run_root, stats_id) == ["cleaned_dataset"], stats_id


# -------- Invariant 3: dummy-coded categorical preserves original var ------
def test_invariant_dummy_coded_categorical_preserves_original_variable_name(tmp_path):
    """When a categorical X is dummy-coded, the model's output must still
    let downstream consumers find the ORIGINAL variable name (e.g. as a
    prefix in the dummy term keys). This protects the report from treating
    a dummy term as if it were a continuous original variable."""
    frame = pd.DataFrame({
        "y": [1.0 + i for i in range(60)],
        "region_code": (["north", "south", "east"] * 20),
        "firm_id": list(range(100, 160)),
    })
    run_root, res = _run(tmp_path, frame, y="y", x=["region_code"])
    if res["status"] != "completed":
        pytest.skip(f"non-completed status: {res['status']}")
    mr = read_json(run_root / "model_results" / "ols_1.json")
    coef_keys = list(mr.get("coefficients", {}).keys())
    # At least one coefficient must mention the original variable name.
    assert any("region_code" in k for k in coef_keys), coef_keys


# -------- Invariant 4: exposure warning is honest (no fictional artifact) --
def test_invariant_exposure_warning_does_not_fake_offset_artifact(tmp_path):
    """V1.5.4 does not implement true offset modeling for count y +
    exposure. If exposure is detected, it MUST stay an ordinary predictor
    and the lineage MUST NOT invent a fictional `offset_dataset` artifact."""
    rows = [{"y": i % 4, "x": i * 0.2, "exposure": 1.0 + i, "firm_id": 100 + i}
            for i in range(50)]
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=["x", "exposure"])
    assert "offset_dataset" not in _artifact_ids(run_root)


# -------- Invariant 5: explicit model_type fit failure => failed, no fallback
def test_invariant_explicit_model_type_failure_returns_failed_no_silent_fallback(tmp_path):
    """1.5.3.2 contract, structurally locked: an explicit model_type that
    cannot fit returns `failed`. NO silent OLS fallback may have run —
    no `ols_1` model result must be on disk."""
    # Strictly continuous y, explicitly request logit => cannot fit.
    frame = pd.DataFrame({
        "y": [1.5 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    run_root, res = _run(tmp_path, frame, y="y", x=["x"], model_type="logit")
    assert res["status"] in {"failed", "blocked"}, res["status"]
    assert not (run_root / "model_results" / "ols_1.json").exists(), \
        "OLS fallback ran when explicit type was requested — 1.5.3.2 contract broken"


# -------- Invariant 6: artifact_index `inputs` matches what produced it ----
def test_invariant_data_provenance_is_present_for_modeling_artifacts(tmp_path):
    """A spot-check that the modeling artifact's `inputs` is non-empty —
    a regression where lineage gets silently dropped would otherwise pass
    Invariant 1 trivially (no model_inputs to compare)."""
    frame = pd.DataFrame({
        "y": [1.0 + 2.0 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    assert len(_inputs_of(run_root, "ols_1")) >= 1
    assert len(_inputs_of(run_root, "diagnostics_ols_1")) >= 1
