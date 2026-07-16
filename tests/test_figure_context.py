from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.app import app
from workbench.artifacts import write_json


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
