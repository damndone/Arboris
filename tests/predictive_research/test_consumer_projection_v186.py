from __future__ import annotations

import pytest

from workbench.predictive_research.consumer_projection import project_prediction_evidence
from workbench.predictive_research.schema import PayloadContractError


def packets() -> tuple[dict[str, object], ...]:
    return (
        {
            "payload_schema": "workbench.prediction.sample-spec",
            "schema_version": 1,
            "sample_spec_hash": "sha256:" + "a" * 64,
            "structure": {"kind": "iid"},
        },
        {
            "payload_schema": "workbench.prediction.split-plan",
            "schema_version": 1,
            "content_hash": "sha256:" + "b" * 64,
            "effective_parameters": {"final_holdout_fraction": 0.2, "cv_folds": 3},
        },
        {
            "payload_schema": "workbench.prediction.prediction-packet",
            "schema_version": 1,
            "model_id": "prediction_ridge_1",
            "split_plan_hash": "sha256:" + "b" * 64,
            "row_predictions": {"row-1": 1.2},
            "oos_metrics": {"r2": 0.4, "rmse": 0.8},
        },
        {
            "payload_schema": "workbench.prediction.evaluation-packet",
            "schema_version": 1,
            "model_id": "prediction_ridge_1",
            "split_plan_hash": "sha256:" + "b" * 64,
            "oos": {"n": 1, "metrics": {"r2": 0.4, "rmse": 0.8}},
            "baseline": {"model_id": "mean_regressor", "metrics": {"r2": 0.0}},
        },
        {
            "payload_schema": "workbench.prediction.negative-control-packet",
            "schema_version": 1,
            "model_id": "prediction_ridge_1",
            "split_plan_hash": "sha256:" + "b" * 64,
            "controls": [{"control": "permuted_target", "seed": 7}],
        },
    )


def test_projection_reads_one_versioned_evidence_view_for_all_consumers() -> None:
    projection = project_prediction_evidence(packets(), consumer="agent")

    assert projection["status"] == "validated"
    assert projection["model_id"] == "prediction_ridge_1"
    assert projection["split_plan_hash"] == "sha256:" + "b" * 64
    assert projection["oos"]["metrics"]["r2"] == 0.4
    assert projection["baseline"]["model_id"] == "mean_regressor"
    assert projection["controls"][0]["control"] == "permuted_target"


def test_projection_rejects_unknown_version_before_exposing_values() -> None:
    bad = list(packets())
    bad[2] = {**bad[2], "schema_version": 99}

    with pytest.raises(PayloadContractError) as error:
        project_prediction_evidence(tuple(bad), consumer="report")

    assert error.value.code == "ARTIFACT_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED"
