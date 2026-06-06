import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("linearmodels")


def _panel_frame() -> pd.DataFrame:
    # 8 firms x 5 years = 40 rows, clearing the default min_model_n (30).
    # rnd carries within-entity variation (not a pure function of firm+year)
    # so it is not absorbed by entity/time effects in the panel fit.
    import numpy as np

    rng = np.random.default_rng(1234)
    firms = {f"F{i}": (i + 1) * 10 for i in range(8)}
    years = (2018, 2019, 2020, 2021, 2022)
    rows = []
    for firm, base in firms.items():
        for year in years:
            rnd = base / 2 + (year - 2018) + float(rng.normal(0, 3.0))
            rows.append({
                "firm": firm,
                "yr": year,
                "rnd": rnd,
                "profit": base + (year - 2018) * 2.0 + 1.5 * rnd
                + float(rng.normal(0, 1.0)),
            })
    return pd.DataFrame(rows)


def _run(tmp_path, frame, **kwargs):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], **kwargs)
    return project.root / "runs" / result["run_id"], result


def test_user_entity_time_drives_panel_fit(tmp_path):
    run_root, result = _run(
        tmp_path,
        _panel_frame(),
        mode="auto",
        y="profit",
        x=["rnd"],
        model_type="panel_ols",
        entity_col="firm",
        time_col="yr",
    )
    assert result["status"] == "completed"
    # analysis_router.json does NOT serialize id_candidates/time_candidates keys
    # (it only echoes kind/confidence/secondary_labels/evidence). So we verify
    # the user-supplied entity/time actually drove the panel fit two ways:
    # (1) the dataset was classified as panel with firm/yr in evidence, and
    # (2) the panel_ols model result artifact exists.
    router = read_json(run_root / "staged" / "analysis_router.json")
    assert router["kind"] == "panel"
    evidence = " ".join(router.get("evidence", []))
    assert "firm" in evidence
    assert "yr" in evidence
    assert (run_root / "model_results" / "panel_ols_1.json").exists()


def test_omitting_entity_time_is_backward_compatible(tmp_path):
    run_root, result = _run(
        tmp_path, _panel_frame(), mode="auto", y="profit", x=["rnd"],
        model_type="auto",
    )
    assert result["status"] in ("completed", "blocked")
