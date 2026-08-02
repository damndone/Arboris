from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import register_artifact
from workbench.predictive_research.schema import PayloadContractError


def make_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    return run_root


def test_new_packet_validates_payload_before_index_update(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)
    payload_path = run_root / "prediction.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload_schema": "workbench.prediction.prediction-packet",
                "schema_version": 1,
                "prediction_id": "p-1",
            }
        ),
        encoding="utf-8",
    )

    record = register_artifact(
        run_root,
        "prediction-1",
        payload_path,
        "prediction_packet",
        "prediction",
        [],
        payload_contract={
            "payload_schema": "workbench.prediction.prediction-packet",
            "schema_version": 1,
        },
    )

    assert record.to_dict()["payload_contract"] == {
        "payload_schema": "workbench.prediction.prediction-packet",
        "schema_version": 1,
    }
    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert index["artifacts"][0]["payload_contract"] == record.to_dict()["payload_contract"]


def test_invalid_new_packet_does_not_update_index(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)
    payload_path = run_root / "prediction.json"
    payload_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    with pytest.raises(PayloadContractError) as error:
        register_artifact(
            run_root,
            "prediction-1",
            payload_path,
            "prediction_packet",
            "prediction",
            [],
            payload_contract={
                "payload_schema": "workbench.prediction.prediction-packet",
                "schema_version": 1,
            },
        )

    assert error.value.code == "ARTIFACT_PAYLOAD_CONTRACT_REQUIRED"
    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert index["artifacts"] == []
