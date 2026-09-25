from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
from sklearn.metrics import log_loss

from workbench.prediction import run_classification_model_v189
from workbench.predictive_research.contracts import StructureSpecV1
from workbench.predictive_research.classification_contracts import DecisionPolicyV1
from workbench.predictive_research.classification_metrics import threshold_curve

from test_v189_classification_production import (
    _ordered_frame,
    _ordered_task,
    _production_dependencies,
)


def _run_accuracy_task(tmp_path):
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    task = replace(
        _ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        primary_metric="accuracy",
        structure=StructureSpecV1(kind="iid"),
        split_profile="iid_stratified",
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=task,
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        decision_policy=DecisionPolicyV1(
            cost_matrix={"false_positive": 1.0, "false_negative": 2.0},
            capacity=10,
            abstain_allowed=False,
            manual_review_allowed=False,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="all",
            time_validity="declared",
        ),
        **_production_dependencies(),
    )
    return frame, task, result


def test_threshold_curve_min_log_loss_uses_probabilities_not_hard_labels() -> None:
    rows = threshold_curve(
        actual=[0, 1],
        probabilities=[0.4, 0.6],
        thresholds=[0.5],
    )

    assert rows[0]["log_loss"] == log_loss([0, 1], [0.4, 0.6], labels=[0, 1])
    assert rows[0]["log_loss"] > 0.5


def test_model_selection_uses_selected_development_oof_threshold_for_thresholded_metrics(tmp_path) -> None:
    _frame, _task, result = _run_accuracy_task(tmp_path)

    model = result["models"]["logistic_regression"]
    selected_threshold = model["selection_threshold"]["threshold"]

    assert model["oof_metrics"]["threshold"] == selected_threshold
    assert result["comparison"]["selection_scores"]["logistic_regression"] == model[
        "oof_metrics"
    ]["metrics"]["accuracy"]["point_estimate"]


def test_threshold_input_scope_matches_the_development_oof_rows(tmp_path) -> None:
    _frame, _task, result = _run_accuracy_task(tmp_path)

    model = result["models"]["logistic_regression"]
    selection_threshold = model["selection_threshold"]
    operational_threshold = model["threshold"]

    assert selection_threshold["input_scope"] == "development_oof"
    assert set(selection_threshold["row_refs"]) == set(model["oof"]["oof_row_refs"])
    assert selection_threshold["probability_scale"] == "raw_model_probability"
    assert operational_threshold["input_scope"] == "development_calibration_eval"
    assert set(operational_threshold["row_refs"]) == set(model["calibration"]["evaluation_row_refs"])
    assert operational_threshold["probability_scale"] == "calibrated_probability"
    assert result["decision_policy"]["threshold_source"] == "development_calibration_eval"


def test_supported_explanations_are_bounded_typed_and_provenance_bound(tmp_path) -> None:
    _frame, task, result = _run_accuracy_task(tmp_path)

    explanations = result["evidence"]["explanations"]
    assert explanations["status"] == "computed"
    assert explanations["method"] == "permutation_importance"
    assert explanations["model_id"] == result["comparison"]["selected_model"]
    assert explanations["task_hash"] == task.content_hash
    assert explanations["split_hash"] == result["split_hash"]
    assert explanations["sample_scope"] == "outer_validation"
    assert len(explanations["importance"]) <= len(task.feature_columns)
    assert all(
        {
            "feature",
            "source_column",
            "importance",
            "stability_std",
            "folds",
            "repeats",
            "direction",
            "rank",
        }.issubset(row)
        for row in explanations["importance"]
    )
    assert "serialized_model" not in explanations
    assert "model_path" not in explanations


def test_agent_and_notebook_classification_helpers_use_central_reader_only(monkeypatch, tmp_path) -> None:
    from workbench.agent import context_tools
    from workbench.agent.notebook import evidence as notebook_evidence
    from workbench.services import classification_consumer_service, results_service
    from test_v189_classification_central_consumer import _materialize_run

    project_root = tmp_path / "project"
    run_root = _materialize_run(project_root)
    capability = classification_consumer_service._mint_classification_run_capability(run_root)

    def generic_reader_must_not_run(*_args, **_kwargs):
        raise AssertionError("classification helper bypassed the central reader")

    monkeypatch.setattr(results_service, "read_persisted_consumer_evidence_for_run", generic_reader_must_not_run)

    agent_projection = context_tools.read_classification_evidence_for_agent(capability)
    notebook_projection = notebook_evidence.read_classification_evidence_for_notebook(capability)

    assert agent_projection["consumer"] == "agent"
    assert notebook_projection["consumer"] == "notebook"
    assert agent_projection["source_artifact_id"] == notebook_projection["source_artifact_id"]
    assert agent_projection["explanations"] == notebook_projection["explanations"]
    assert run_root.name == agent_projection["server_identity"]["run_id"]
