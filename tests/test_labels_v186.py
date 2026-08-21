from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import matplotlib.pyplot as plt
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.app import app
from workbench.config import WorkbenchConfig
from workbench.ingestion import ingest_files
from workbench.orchestrator import run_workflow
from workbench.projects import create_project, create_run
from workbench import visualization


def _run(tmp_path: Path, *, labels: dict[str, object] | None = None) -> Path:
    source = tmp_path / "labels.csv"
    pd.DataFrame(
        {
            "outcome": [float(index) + 0.2 * (index % 3) for index in range(48)],
            "treatment": [float(index) for index in range(48)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "labels")
    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="outcome",
        x=["treatment"],
        model_type="ols",
        labels=labels,
    )
    assert result["status"] == "completed", result
    return project.root / "runs" / result["run_id"]


def _assert_unbound_report_is_typed_unavailable(run_root: Path) -> dict:
    assert not (run_root / "reports" / "report.html").exists()

    summary = read_json(run_root / "diagnostic_summary.json")
    assert summary["run_status"]["report_render_status"] == "failed"
    assert summary["run_status"]["report_available"] is False
    report_issue = next(
        issue
        for issue in summary["diagnostics"]["warnings"]
        if issue["code"] == "REPORT_RENDER_FAILED"
    )
    assert report_issue["evidence"] == {
        "error": "REPORT_EVIDENCE_UNAVAILABLE:EVIDENCE_OWNER_CAPABILITY_REQUIRED"
    }

    from workbench.report_view_model import build_report_view_model

    report_view = build_report_view_model(
        summary,
        run_root,
        include_legacy_presentation=True,
    )
    assert report_view["status"] == "unavailable"
    assert report_view["validationStatus"] == "unavailable"
    assert report_view["reasonCode"] == "EVIDENCE_OWNER_CAPABILITY_REQUIRED"
    assert report_view["facts"] == []
    return summary


def test_declared_labels_reach_durable_artifacts_and_unbound_export_fails_closed(
    tmp_path: Path,
) -> None:
    run_root = _run(
        tmp_path,
        labels={
            "variable_labels": {"outcome": "Outcome label", "treatment": "Treatment label"},
            "value_labels": {"treatment": {"0": "Control", "1": "Treated"}},
        },
    )

    inputs = read_json(run_root / "run_inputs.json")
    assert inputs["form"]["labels"]["variable_labels"]["outcome"] == "Outcome label"

    summary = _assert_unbound_report_is_typed_unavailable(run_root)
    rows = {row["column"]: row for row in summary["table_1"]}
    assert summary["labels"] == {
        "variable_labels": {
            "outcome": "Outcome label",
            "treatment": "Treatment label",
        },
        "value_labels": {"treatment": {"0": "Control", "1": "Treated"}},
    }
    assert rows["outcome"]["label"] == "Outcome label"
    assert rows["outcome"]["label_source"] == "declared"
    assert rows["treatment"]["label"] == "Treatment label"
    assert rows["treatment"]["value_labels"] == {"0": "Control", "1": "Treated"}

    assert not (run_root / "exports" / "tables.xlsx").exists()

    response = TestClient(app).post(
        f"/runs/{run_root.name}/report/result-table-export",
        params={"project_root": str(run_root.parent.parent)},
        json={"sections": ["table_1", "regression_table"]},
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "RESULT_TABLE_EXPORT_UNAVAILABLE"
    projection = error["details"]["projection"]
    assert projection["status"] == "unavailable"
    assert projection["reasonCode"] == "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED"
    assert projection["facts"] == []

    figure_labels = read_json(run_root / "figures" / "figure_labels.json")
    assert figure_labels["scatter_plots"]["x_label"] == "Treatment label"
    assert figure_labels["scatter_plots"]["y_label"] == "Outcome label"


def test_undeclared_labels_use_explicit_column_name_fallback(tmp_path: Path) -> None:
    run_root = _run(tmp_path)
    summary = _assert_unbound_report_is_typed_unavailable(run_root)
    rows = {row["column"]: row for row in summary["table_1"]}
    assert summary["labels"] == {"variable_labels": {}, "value_labels": {}}
    assert rows["outcome"]["label"] == "outcome"
    assert rows["outcome"]["label_source"] == "column_name_fallback"
    assert rows["treatment"]["label"] == "treatment"
    assert rows["treatment"]["label_source"] == "column_name_fallback"


def test_labels_reject_unknown_top_level_fields(tmp_path: Path) -> None:
    source = tmp_path / "invalid-labels.csv"
    pd.DataFrame({"y": [1.0, 2.0], "x": [1.0, 2.0]}).to_csv(source, index=False)
    project = create_project(tmp_path, "invalid-labels")
    with pytest.raises(ValueError, match="labels"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            labels={"unexpected": {}},
        )


def test_common_figures_use_variable_and_value_labels(monkeypatch, tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "outcome": [float(index) + 0.2 * (index % 3) for index in range(48)],
            "treatment": [float(index) for index in range(48)],
            "group": [index % 2 for index in range(48)],
            "period": pd.date_range("2024-01-01", periods=48, freq="D"),
        }
    )
    frame.attrs["variable_labels"] = {
        "outcome": "Outcome label",
        "treatment": "Treatment label",
        "group": "Group label",
        "period": "Period label",
    }
    frame.attrs["value_labels"] = {
        "group": {"0": "Control", "1": "Treated"},
    }
    captured: dict[str, list[dict[str, object]]] = {}

    def capture(fig, path, run_root, artifact_id, figures) -> None:
        panels: list[dict[str, object]] = []
        for axis in fig.axes:
            legend = axis.get_legend()
            panels.append(
                {
                    "title": axis.get_title(),
                    "xlabel": axis.get_xlabel(),
                    "ylabel": axis.get_ylabel(),
                    "xticks": [tick.get_text() for tick in axis.get_xticklabels()],
                    "yticks": [tick.get_text() for tick in axis.get_yticklabels()],
                    "legend": (
                        [text.get_text() for text in legend.get_texts()]
                        if legend is not None
                        else []
                    ),
                }
            )
        captured[artifact_id] = panels
        figures[artifact_id] = str(path)
        plt.close(fig)

    monkeypatch.setattr(visualization, "_save", capture)
    figures = visualization.create_figures(
        frame,
        tmp_path,
        numeric_columns=["outcome", "treatment", "group"],
        time_column="period",
        outcome_column="outcome",
        regressors=["treatment", "group"],
        model_type="ols",
    )

    assert set(
        (
            "histograms",
            "kde_plots",
            "boxplots",
            "correlation_heatmap",
            "category_counts",
            "scatter_plots",
            "group_boxplots",
            "time_trend",
        )
    ) <= set(figures)
    assert {panel["title"] for panel in captured["histograms"]} >= {
        "Outcome label",
        "Treatment label",
    }
    assert {panel["title"] for panel in captured["kde_plots"]} >= {
        "Outcome label",
        "Treatment label",
    }
    assert captured["boxplots"][0]["xticks"] == [
        "Outcome label",
        "Treatment label",
    ]
    assert captured["correlation_heatmap"][0]["xticks"] == [
        "Outcome label",
        "Treatment label",
    ]
    assert captured["correlation_heatmap"][0]["yticks"] == [
        "Outcome label",
        "Treatment label",
    ]
    assert captured["category_counts"][0]["title"] == "Group label"
    assert set(captured["category_counts"][0]["xticks"]) == {"Control", "Treated"}
    assert captured["scatter_plots"][0]["xlabel"] == "Treatment label"
    assert captured["scatter_plots"][0]["ylabel"] == "Outcome label"
    assert set(captured["group_boxplots"][0]["xticks"]) == {"Control", "Treated"}
    assert captured["group_boxplots"][0]["ylabel"] == "Outcome label"
    assert captured["time_trend"][0]["xlabel"] == "Period label"
    assert set(captured["time_trend"][0]["legend"]) == {
        "Outcome label",
        "Treatment label",
    }


@pytest.mark.parametrize("suffix", [".dta", ".sav"])
def test_external_label_formats_remain_explicitly_unsupported(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / f"external-labels{suffix}"
    source.write_bytes(b"not parsed by this release")
    project = create_project(tmp_path, f"unsupported{suffix[1:]}")
    run = create_run(project.root, mode="auto")

    with pytest.raises(ValueError, match="unsupported file type"):
        ingest_files([source], run.root, WorkbenchConfig())

    assert not (run.root / "raw_snapshot" / source.name).exists()
    assert read_json(run.root / "artifacts_index.json") == {
        "schema_version": 1,
        "artifacts": [],
    }
