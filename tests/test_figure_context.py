from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.app import app
from workbench.artifacts import read_json, write_json


def _run_with_figures(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "project"
    run_id = "run_fig"
    run_root = project / "runs" / run_id
    (run_root / "figures").mkdir(parents=True)
    (run_root / "model_results").mkdir(parents=True)
    (run_root / "staged").mkdir(parents=True)

    (run_root / "figures" / "coef_plot.png").write_bytes(b"\x89PNG stub")
    (run_root / "figures" / "histograms.png").write_bytes(b"\x89PNG stub2")
    write_json(
        run_root / "model_results" / "ols_1.json",
        {"coefficients": {"education": 1.23, "experience": 0.45}, "r_squared": 0.7},
    )
    write_json(
        run_root / "staged" / "data_profile.json",
        {"columns": {"wage": {"mean": 20.0, "std": 5.0}}},
    )
    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {"artifact_id": "coef_plot", "path": "figures/coef_plot.png", "artifact_type": "figure", "step": "visualization", "sha256": "a", "inputs": []},
                {"artifact_id": "histograms", "path": "figures/histograms.png", "artifact_type": "figure", "step": "visualization", "sha256": "b", "inputs": []},
                {"artifact_id": "ols_1", "path": "model_results/ols_1.json", "artifact_type": "model_result", "step": "estimation", "sha256": "c", "inputs": []},
                {"artifact_id": "data_profile", "path": "staged/data_profile.json", "artifact_type": "profile", "step": "staging", "sha256": "d", "inputs": []},
            ],
        },
    )
    return project, run_id


def test_figure_context_resolves_model_source_for_coef_plot(tmp_path: Path) -> None:
    from workbench.figure_context import resolve_figure_ai_context

    project, run_id = _run_with_figures(tmp_path)
    ctx = resolve_figure_ai_context(project, run_id=run_id, artifact_id="coef_plot")

    assert ctx["figure"]["chart_type"].startswith("coefficient")
    assert ctx["source"]["artifact_id"] == "ols_1"
    assert ctx["source"]["kind"] == "model"
    assert "education" in ctx["source"]["preview_json"]
    assert ctx["context_visibility_notice"]["image_pixels_included"] is False
    assert ctx["response_guardrails"]["must_interpret_from_numeric_source"] is True


def test_figure_context_resolves_profile_source_for_histograms(tmp_path: Path) -> None:
    from workbench.figure_context import resolve_figure_ai_context

    project, run_id = _run_with_figures(tmp_path)
    ctx = resolve_figure_ai_context(project, run_id=run_id, artifact_id="histograms")
    assert ctx["source"]["artifact_id"] == "data_profile"
    assert ctx["source"]["kind"] == "profile"


def test_figure_context_resolves_event_study_dynamic_source(tmp_path: Path) -> None:
    from workbench.figure_context import resolve_figure_ai_context

    project, run_id = _run_with_figures(tmp_path)
    run_root = project / "runs" / run_id
    (run_root / "figures" / "event_study.png").write_bytes(b"\x89PNG event")
    write_json(
        run_root / "cs_did.json",
        {
            "aggregations": {
                "dynamic": {
                    "label_kind": "event_time",
                    "event_time": [-1, 0, 1],
                    "estimate": [0.0, 2.001, 2.4],
                    "se": [0.2, 0.3, 0.4],
                    "pointwise_ci": [[-0.4, 0.4], [1.4, 2.6], [1.6, 3.2]],
                    "uniform_band": [[-0.5, 0.5], [1.2, 2.8], [1.3, 3.5]],
                }
            }
        },
    )
    index = read_json(run_root / "artifacts_index.json")
    index["artifacts"].extend([
        {"artifact_id": "event_study", "path": "figures/event_study.png", "artifact_type": "figure", "step": "visualization", "sha256": "e", "inputs": []},
        {"artifact_id": "cs_did", "path": "cs_did.json", "artifact_type": "model_diagnostic", "step": "econometrics", "sha256": "f", "inputs": []},
    ])
    write_json(run_root / "artifacts_index.json", index)

    ctx = resolve_figure_ai_context(project, run_id=run_id, artifact_id="event_study")
    assert ctx["source"]["artifact_id"] == "cs_did"
    assert "2.001" in ctx["source"]["preview_json"]
    assert "uniform_band" in ctx["source"]["preview_json"]


def test_figure_context_resolves_time_trend_from_cleaned_data(tmp_path: Path) -> None:
    import pandas as pd

    from workbench.figure_context import resolve_figure_ai_context

    project, run_id = _run_with_figures(tmp_path)
    run_root = project / "runs" / run_id
    (run_root / "figures" / "time_trend.png").write_bytes(b"\x89PNG trend")
    (run_root / "processed").mkdir(parents=True)
    pd.DataFrame({"year": [2, 1], "outcome": [20.0, 10.0]}).to_parquet(
        run_root / "processed" / "cleaned_dataset.parquet", index=False
    )
    write_json(run_root / "run_inputs.json", {"form": {"time_col": "year"}})
    index = read_json(run_root / "artifacts_index.json")
    index["artifacts"].extend([
        {"artifact_id": "time_trend", "path": "figures/time_trend.png", "artifact_type": "figure", "step": "visualization", "sha256": "g", "inputs": []},
        {"artifact_id": "cleaned_dataset", "path": "processed/cleaned_dataset.parquet", "artifact_type": "dataset", "step": "cleaning", "sha256": "h", "inputs": []},
    ])
    write_json(run_root / "artifacts_index.json", index)

    ctx = resolve_figure_ai_context(project, run_id=run_id, artifact_id="time_trend")
    assert ctx["source"]["kind"] == "time_trend"
    assert '"year": 1' in ctx["source"]["preview_json"]
    assert '"outcome": 10.0' in ctx["source"]["preview_json"]


def test_figure_context_rejects_non_figure_and_missing(tmp_path: Path) -> None:
    from workbench.figure_context import FigureContextError, resolve_figure_ai_context

    project, run_id = _run_with_figures(tmp_path)
    try:
        resolve_figure_ai_context(project, run_id=run_id, artifact_id="ols_1")
    except FigureContextError as exc:
        assert "not a figure" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FigureContextError for non-figure")


def test_figure_ai_context_route_and_404(tmp_path: Path) -> None:
    project, run_id = _run_with_figures(tmp_path)
    with TestClient(app) as client:
        ok = client.get(
            "/figures/ai-context",
            params={"project_root": str(project), "run_id": run_id, "artifact_id": "coef_plot"},
        )
        assert ok.status_code == 200
        assert ok.json()["source"]["artifact_id"] == "ols_1"

        missing = client.get(
            "/figures/ai-context",
            params={"project_root": str(project), "run_id": run_id, "artifact_id": "nope"},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "FIGURE_CONTEXT_NOT_FOUND"


def test_llm_chat_accepts_figure_mode(tmp_path: Path) -> None:
    # unconfigured LLM → 503, but the figure MODE must be accepted (not 422).
    with TestClient(app) as client:
        resp = client.post(
            "/llm/chat",
            json={
                "mode": "workbench_figure_context_v1",
                "question": "What does this coefficient plot show?",
                "packet": {"figure_context_version": "figure-ai-context/v1", "figure": {"chart_type": "coefficient plot"}},
            },
        )
    assert resp.status_code != 422
    if resp.status_code not in (200, 503, 502):  # pragma: no cover
        raise AssertionError(f"unexpected status {resp.status_code}: {resp.text}")
