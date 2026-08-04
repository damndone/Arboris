from __future__ import annotations

from pathlib import Path

import pytest

from workbench.artifacts import sha256_file, write_json
from workbench.lineage.compare_nodes import CompareNodeError
from workbench.services.compare_node_service import create_compare_node


PREDICTION_NODE = "model:prediction_ridge_1"


def _typed_packets(*, split_hash: str, model_id: str) -> dict[str, dict[str, object]]:
    return {
        "prediction_sample_spec": {
            "payload_schema": "workbench.prediction.sample-spec",
            "schema_version": 1,
            "sample_spec_hash": "sha256:" + "a" * 64,
            "structure": {"kind": "iid"},
        },
        "prediction_split_plan": {
            "payload_schema": "workbench.prediction.split-plan",
            "schema_version": 1,
            "content_hash": split_hash,
            "effective_parameters": {"final_holdout_fraction": 0.2, "cv_folds": 3},
        },
        "prediction_packet": {
            "payload_schema": "workbench.prediction.prediction-packet",
            "schema_version": 1,
            "model_id": model_id,
            "split_plan_hash": split_hash,
            "row_predictions": {"row-1": 1.2},
        },
        "evaluation_packet": {
            "payload_schema": "workbench.prediction.evaluation-packet",
            "schema_version": 1,
            "model_id": model_id,
            "split_plan_hash": split_hash,
            "oos": {"n": 1, "metrics": {"r2": 0.4}},
            "baseline": {"model_id": "mean_regressor", "metrics": {"r2": 0.0}},
        },
        "negative_control_packet": {
            "payload_schema": "workbench.prediction.negative-control-packet",
            "schema_version": 1,
            "model_id": model_id,
            "split_plan_hash": split_hash,
            "controls": [{"control": "permuted_target", "seed": 7}],
        },
    }


def _write_typed_run(runs_dir: Path, run_id: str, *, split_hash: str) -> None:
    run_root = runs_dir / run_id
    (run_root / "artifacts" / "prediction").mkdir(parents=True)
    write_json(
        run_root / "run_manifest.json",
        {"run_id": run_id, "status": "completed", "model_routing": {}},
    )
    write_json(
        run_root / "node_index.json",
        {PREDICTION_NODE: {"node_hash": run_id + "0" * (64 - len(run_id))}},
    )
    write_json(
        run_root / "graph.json",
        {"schema_version": 3, "run_id": run_id, "nodes": {}, "edges": {}, "branches": {}},
    )
    packets = _typed_packets(split_hash=split_hash, model_id="prediction_ridge_1")
    artifact_types = {
        "prediction_sample_spec": "prediction_sample_spec",
        "prediction_split_plan": "prediction_split_plan",
        "prediction_packet": "prediction_packet",
        "evaluation_packet": "evaluation_packet",
        "negative_control_packet": "negative_control_packet",
    }
    records = []
    for artifact_id, payload in packets.items():
        path = run_root / "artifacts" / "prediction" / f"{artifact_id}.json"
        write_json(path, payload)
        records.append(
            {
                "artifact_id": artifact_id,
                "path": path.relative_to(run_root).as_posix(),
                "artifact_type": artifact_types[artifact_id],
                "sha256": sha256_file(path),
                "payload_contract": {
                    "payload_schema": payload["payload_schema"],
                    "schema_version": 1,
                },
            }
        )
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": records})


def _write_legacy_run(runs_dir: Path, run_id: str) -> None:
    run_root = runs_dir / run_id
    prediction_dir = run_root / "prediction_results"
    prediction_dir.mkdir(parents=True)
    write_json(
        run_root / "run_manifest.json",
        {"run_id": run_id, "status": "completed", "model_routing": {}},
    )
    write_json(
        run_root / "node_index.json",
        {PREDICTION_NODE: {"node_hash": run_id + "0" * (64 - len(run_id))}},
    )
    write_json(
        run_root / "graph.json",
        {"schema_version": 3, "run_id": run_id, "nodes": {}, "edges": {}, "branches": {}},
    )
    path = prediction_dir / "prediction_ridge_1.json"
    write_json(path, {"model_id": "prediction_ridge_1", "status": "completed", "metrics": {"test_r2": 0.2}})
    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": "prediction_ridge_1",
                    "path": path.relative_to(run_root).as_posix(),
                    "artifact_type": "prediction_result",
                    "sha256": sha256_file(path),
                }
            ],
        },
    )


def _endpoints(runs_dir: Path, left: str, right: str) -> dict[str, str]:
    return {
        "left_run_id": left,
        "left_node_id": PREDICTION_NODE,
        "right_run_id": right,
        "right_node_id": PREDICTION_NODE,
    }


def test_compare_accepts_typed_runs_only_when_split_plan_matches(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    split_hash = "sha256:" + "b" * 64
    _write_typed_run(runs_dir, "run-a", split_hash=split_hash)
    _write_typed_run(runs_dir, "run-b", split_hash=split_hash)

    record = create_compare_node(runs_dir, **_endpoints(runs_dir, "run-a", "run-b"))

    assert record.packet["compare_status"] == "complete"
    assert record.packet["comparability"] == "typed_same_split_plan"
    assert record.packet["left"]["split_plan_hash"] == split_hash


def test_compare_rejects_legacy_against_typed_prediction(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_legacy_run(runs_dir, "legacy")
    _write_typed_run(runs_dir, "typed", split_hash="sha256:" + "b" * 64)

    with pytest.raises(CompareNodeError) as error:
        create_compare_node(runs_dir, **_endpoints(runs_dir, "legacy", "typed"))

    assert error.value.code == "PREDICTION_LEGACY_RESULT_INCOMPARABLE"


def test_compare_keeps_legacy_pair_readable_without_scientific_comparability(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_legacy_run(runs_dir, "legacy-a")
    _write_legacy_run(runs_dir, "legacy-b")

    record = create_compare_node(runs_dir, **_endpoints(runs_dir, "legacy-a", "legacy-b"))

    assert record.packet["compare_status"] == "legacy_only"
    assert record.packet["comparability"] == "legacy_only"


def test_compare_rejects_typed_runs_with_different_split_plans(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_typed_run(runs_dir, "run-a", split_hash="sha256:" + "b" * 64)
    _write_typed_run(runs_dir, "run-b", split_hash="sha256:" + "c" * 64)

    with pytest.raises(CompareNodeError) as error:
        create_compare_node(runs_dir, **_endpoints(runs_dir, "run-a", "run-b"))

    assert error.value.code == "PREDICTION_SPLIT_INCOMPATIBLE"
