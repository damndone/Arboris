"""Acceptance + end-to-end tests for run_sa_did (Sun-Abraham, Task 7).

run_sa_did must build the SA EffectEstimateBundle then defer ENTIRELY to the
shared _finalize_did_bundle — it carries NO estimator-specific downstream.
"""
import json
import numpy as np
import pandas as pd

from workbench.orchestrator import run_workflow as _rw
from workbench.projects import create_project


def test_run_sa_did_has_no_downstream_logic():
    import inspect
    from workbench.econometrics import runner
    src = inspect.getsource(runner.run_sa_did)
    assert "_finalize_did_bundle" in src
    assert "aggregate(" not in src
    assert "honest_did_from_cs" not in src
    assert "multiplier_bootstrap" not in src


def _staggered_csv(tmp_path):
    """Small staggered panel: 3 treated cohorts + never-treated, >=2 pre periods."""
    rng = np.random.default_rng(11)
    rows = []
    cohorts = {f"u{i}": c for i, c in enumerate(
        [2019, 2019, 2019, 2020, 2020, 2020, 2021, 2021, 2021, 0, 0, 0, 0, 0, 0])}
    for ent, cohort in cohorts.items():
        fe = rng.normal()
        for year in range(2016, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2016) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "sa_panel.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_run_sa_did_end_to_end(tmp_path):
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    result = _rw(project.root, [src], mode="auto", y="y", x=[], model_type="sa_did",
                 entity_col="id", time_col="year", did_mode="cohort",
                 did_cohort_col="first_treat")
    run_root = project.root / "runs" / result["run_id"]

    from workbench.artifacts import read_json
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"

    primary = read_json(run_root / "model_results" / "sa_did_1.json")
    assert primary["model_type"] == "sa_did"
    assert "ATT" in primary["coefficients"]

    sa_path = run_root / "sa_did.json"
    assert sa_path.exists(), "sa_did artifact missing (diagnostics block removed?)"
    artifact = json.loads(sa_path.read_text())
    assert artifact.get("available") is True
    assert "dynamic" in artifact["aggregations"]
    assert artifact["metadata"]["estimator"] == "sun_abraham"

    index = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in index["artifacts"]}
    assert "sa_did" in ids


def test_sa_unbalanced_run_has_weight_warning_balanced_does_not():
    import pandas as pd
    from pathlib import Path
    from workbench.engine.did_spec import normalize_did_input
    from workbench.econometrics.runner import run_sa_did
    FIX = Path(__file__).parent / "fixtures" / "sa_did"
    def _run(panel):
        d = pd.read_csv(FIX / f"panel_{panel}.csv")
        norm = normalize_did_input(d, mode="cohort", entity="id", time="year", y="y", cohort="cohort")
        return run_sa_did(norm, cluster_var=None)
    unb = _run("unbalanced"); bal = _run("balanced")
    assert "interpretation_restrictions" in unb["aggregations"]["dynamic"]
    assert "interpretation_restrictions" not in bal["aggregations"]["dynamic"]
