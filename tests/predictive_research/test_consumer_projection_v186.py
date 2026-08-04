from __future__ import annotations

from pathlib import Path

import pytest

from workbench.artifacts import sha256_file, write_json
from workbench.http import runs_routes
from workbench.predictive_research.consumer_projection import (
    project_prediction_evidence,
    read_prediction_evidence_from_run_root,
)
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
            "cv": [{"fold": 1}, {"fold": 2}],
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
    assert len(projection["development"]["cv"]) == 2


def test_projection_rejects_unknown_version_before_exposing_values() -> None:
    bad = list(packets())
    bad[2] = {**bad[2], "schema_version": 99}

    with pytest.raises(PayloadContractError) as error:
        project_prediction_evidence(tuple(bad), consumer="report")

    assert error.value.code == "ARTIFACT_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED"


def test_reader_marks_missing_payload_contract_as_legacy_without_fabricating_split(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    prediction_dir = run_root / "prediction_results"
    prediction_dir.mkdir(parents=True)
    result_path = prediction_dir / "prediction_ridge_1.json"
    write_json(
        result_path,
        {
            "schema_version": 1,
            "model_id": "prediction_ridge_1",
            "model_type": "prediction_ridge",
            "status": "completed",
            "nobs": 20,
            "metrics": {"test_r2": 0.31, "test_rmse": 1.4},
            "cv_folds": 5,
            "sampling_method": None,
        },
    )
    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": "prediction_ridge_1",
                    "path": "prediction_results/prediction_ridge_1.json",
                    "artifact_type": "prediction_result",
                    "sha256": sha256_file(result_path),
                }
            ],
        },
    )

    projection = read_prediction_evidence_from_run_root(run_root, consumer="table")

    assert projection["status"] == "legacy"
    assert projection["protocol"] == "legacy_random_split_v0"
    assert projection["validation"] == "payload_not_evaluated"
    assert projection["comparability"] == "legacy_only"
    assert projection["model_id"] == "prediction_ridge_1"
    assert projection["message"] == (
        "Legacy evaluation — split protocol was not persisted. The result remains "
        "readable but is not comparable with v1.8.6 predictive-research results."
    )
    assert "split_plan_hash" not in projection


def test_run_detail_route_exposes_legacy_projection_to_table_consumer(
    monkeypatch, tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-legacy"
    prediction_dir = run_root / "prediction_results"
    prediction_dir.mkdir(parents=True)
    result_path = prediction_dir / "prediction_ridge_1.json"
    write_json(result_path, {"model_id": "prediction_ridge_1", "status": "completed", "metrics": {"test_r2": 0.2}})
    write_json(
        run_root / "run_manifest.json",
        {"run_id": "run-legacy", "status": "completed", "mode": "auto", "lineage": []},
    )
    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [{
                "artifact_id": "prediction_ridge_1",
                "path": "prediction_results/prediction_ridge_1.json",
                "artifact_type": "prediction_result",
                "sha256": sha256_file(result_path),
            }],
        },
    )
    monkeypatch.setattr(runs_routes, "_model_results", lambda _run_root: [])
    monkeypatch.setattr(runs_routes, "build_diagnostic_summary_preview", lambda *args: {})
    monkeypatch.setattr(runs_routes, "collect_post_estimation_results", lambda *args: [])

    detail = runs_routes.get_run_endpoint("run-legacy", str(project_root))

    assert detail["prediction_evidence"]["status"] == "legacy"
    assert detail["prediction_evidence"]["comparability"] == "legacy_only"
