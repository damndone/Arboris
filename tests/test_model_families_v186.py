from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.agent.context_tools import _bounded_model_family_evidence
from workbench.services.results_service import read_model_results
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path: Path, frame: pd.DataFrame, *, model_type: str, y: str, x: list[str], model_options: dict | None = None) -> Path:
    source = tmp_path / f"{model_type}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, model_type)
    result = run_workflow(project.root, [source], mode="auto", y=y, x=x, model_type=model_type, model_options=model_options)
    assert result["status"] == "completed", result
    return project.root / "runs" / result["run_id"]


def test_ordinal_logit_run_persists_probabilities_effects_and_parallel_lines(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "rating": [1, 2, 3, 1, 2, 3, 2, 3, 1, 2, 3, 2] * 5,
        "x": [float(i) / 5 for i in range(60)],
    })
    run_root = _run(tmp_path, frame, model_type="ordinal_logit", y="rating", x=["x"])
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")
    assert result["model_type"] == "ordinal_logit"
    assert len(result["predicted_probabilities"]) == len(frame)
    assert result["odds_ratios"]
    assert result["marginal_effects"]
    diagnostics = read_json(run_root / "model_results" / "diagnostics_ordinal_logit_1.json")
    assert diagnostics["parallel_lines"]["status"] in {"computed", "insufficient_support"}


def test_multinomial_logit_run_persists_probabilities_rrr_and_marginal_effects(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(tmp_path, frame, model_type="multinomial_logit", y="choice", x=["x"])
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")
    assert result["model_type"] == "multinomial_logit"
    assert set(result["predicted_probabilities"]) == {"a", "b", "c"}
    assert result["relative_risk_ratios"]
    assert result["marginal_effects"]


def test_multinomial_logit_honors_explicit_base_category(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="multinomial_logit",
        y="choice",
        x=["x"],
        model_options={"base_category": "a"},
    )
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")
    assert result["base_category"] == "a"


def test_survival_cox_run_persists_km_logrank_risk_and_schoenfeld_evidence(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
        "group": [0, 0, 1, 1, 0, 1, 0, 1] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="survival_cox",
        y="duration",
        x=["x"],
        model_options={"event_column": "event", "group_column": "group"},
    )
    evidence = read_json(run_root / "survival" / "evidence.json")
    assert evidence["contract"] == "workbench.survival.v1"
    assert evidence["kaplan_meier"]
    assert "log_rank" in evidence
    assert evidence["risk_set"]
    assert evidence["censoring"]["censored"] > 0
    assert evidence["schoenfeld"]


def test_quantile_regression_run_persists_multiple_quantiles_bootstrap_and_comparison(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "y": [float(i) + float(i % 4) * 0.3 for i in range(48)],
        "x": [float(i) for i in range(48)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="quantile_regression",
        y="y",
        x=["x"],
        model_options={"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 12, "random_state": 7},
    )
    result = read_json(run_root / "model_results" / "quantile_regression_1.json")
    assert result["quantiles"] == [0.25, 0.5, 0.75]
    assert set(result["fits"]) == {"0.25", "0.5", "0.75"}
    assert result["bootstrap"]["repetitions"] == 12
    assert result["cross_quantile_comparisons"]
    projected = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    assert projected["contract"] == "workbench.quantile_regression.result.v1"
    assert projected["cross_quantile_comparisons"]


def test_survival_cox_fails_closed_when_event_column_is_missing(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    source = tmp_path / "survival.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "survival-missing-event")
    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="duration",
        x=["x"],
        model_type="survival_cox",
    )
    assert result["status"] == "failed"
    issues = read_json(project.root / "runs" / result["run_id"] / "errors.json")["issues"]
    assert issues[0]["code"] == "SURVIVAL_EVENT_REQUIRED"


def test_ordinal_logit_thresholds_are_named_by_the_declared_outcome_levels(tmp_path: Path) -> None:
    """Cutpoints must be labelled with the levels a reader can actually see.

    Naming them from the internal 0-based codes points users at an outcome
    level that does not exist in their data.
    """
    frame = pd.DataFrame({
        "rating": [1, 2, 3, 1, 2, 3, 2, 3, 1, 2, 3, 2] * 5,
        "x": [float(i) / 5 for i in range(60)],
    })
    run_root = _run(tmp_path, frame, model_type="ordinal_logit", y="rating", x=["x"])
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")

    assert result["outcome_levels"] == ["1", "2", "3"]
    threshold_names = [name for name in result["coefficients"] if "/" in name]
    assert threshold_names == ["1/2", "2/3"], threshold_names
    assert "0/1" not in result["coefficients"]
