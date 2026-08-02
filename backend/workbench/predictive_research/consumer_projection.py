"""One validated evidence projection shared by Table, Report, Compare, and Agent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, sha256_file
from .schema import PayloadContractError, default_v1_prediction_registry


_REQUIRED = {
    "workbench.prediction.sample-spec",
    "workbench.prediction.split-plan",
    "workbench.prediction.prediction-packet",
    "workbench.prediction.evaluation-packet",
    "workbench.prediction.negative-control-packet",
}
_CONSUMERS = frozenset({"agent", "report", "table", "compare"})


def read_prediction_evidence_from_run_root(
    run_root: Path,
    *,
    consumer: str,
) -> dict[str, Any]:
    """Read indexed packets, then pass them through the shared projection."""

    index = read_json(run_root / "artifacts_index.json")
    if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
        raise PayloadContractError("ARTIFACT_INDEX_INVALID", "artifacts_index.json has no artifact list")
    expected = {
        "prediction_sample_spec": "workbench.prediction.sample-spec",
        "prediction_split_plan": "workbench.prediction.split-plan",
        "prediction_packet": "workbench.prediction.prediction-packet",
        "evaluation_packet": "workbench.prediction.evaluation-packet",
        "negative_control_packet": "workbench.prediction.negative-control-packet",
    }
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    resolved_root = run_root.resolve()
    for raw_record in index["artifacts"]:
        if not isinstance(raw_record, dict):
            continue
        payload_schema = expected.get(str(raw_record.get("artifact_type")))
        if payload_schema is None or payload_schema in seen:
            continue
        contract = raw_record.get("payload_contract")
        if not isinstance(contract, dict):
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_REQUIRED", "prediction evidence record has no payload contract")
        if contract.get("payload_schema") != payload_schema or contract.get("schema_version") != 1:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_MISMATCH", "prediction evidence record contract is inconsistent")
        relative_path = Path(str(raw_record.get("path", "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PayloadContractError("ARTIFACT_PATH_INVALID", "prediction evidence path must stay inside run root")
        path = (run_root / relative_path).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise PayloadContractError("ARTIFACT_PATH_INVALID", "prediction evidence path escapes run root") from error
        if not path.is_file() or sha256_file(path) != raw_record.get("sha256"):
            raise PayloadContractError("ARTIFACT_PAYLOAD_HASH_MISMATCH", "prediction evidence hash does not match index")
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("payload_schema") != payload_schema or payload.get("schema_version") != 1:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_MISMATCH", "prediction evidence payload is inconsistent")
        payloads.append(payload)
        seen.add(payload_schema)
    return project_prediction_evidence(payloads, consumer=consumer)


def project_prediction_evidence(
    payloads: Iterable[Mapping[str, Any]],
    *,
    consumer: str,
) -> dict[str, Any]:
    if consumer not in _CONSUMERS:
        raise PayloadContractError("ARTIFACT_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    registry = default_v1_prediction_registry()
    by_schema: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        validated = registry.validate(dict(payload))
        schema = str(validated["payload_schema"])
        if schema in by_schema:
            raise PayloadContractError("ARTIFACT_PAYLOAD_DUPLICATE_SCHEMA", f"duplicate payload schema {schema!r}")
        by_schema[schema] = validated
    missing = _REQUIRED - by_schema.keys()
    if missing:
        raise PayloadContractError("ARTIFACT_PAYLOAD_VALIDATION_FAILED", f"missing evidence packets: {sorted(missing)}")
    sample = by_schema["workbench.prediction.sample-spec"]
    split = by_schema["workbench.prediction.split-plan"]
    prediction = by_schema["workbench.prediction.prediction-packet"]
    evaluation = by_schema["workbench.prediction.evaluation-packet"]
    controls = by_schema["workbench.prediction.negative-control-packet"]
    split_hash = split.get("content_hash")
    if not isinstance(split_hash, str):
        raise PayloadContractError("PREDICTION_SPLIT_BINDING_MISMATCH", "split packet lacks content_hash")
    observed_hashes = {
        prediction.get("split_plan_hash"),
        evaluation.get("split_plan_hash"),
        controls.get("split_plan_hash"),
    }
    if observed_hashes != {split_hash}:
        raise PayloadContractError("PREDICTION_SPLIT_BINDING_MISMATCH", "consumer packets do not share one SplitPlan")
    model_id = prediction.get("model_id")
    if not isinstance(model_id, str) or evaluation.get("model_id") != model_id or controls.get("model_id") != model_id:
        raise PayloadContractError("PREDICTION_MODEL_BINDING_MISMATCH", "prediction, evaluation, and controls disagree on model_id")
    return {
        "status": "validated",
        "consumer": consumer,
        "model_id": model_id,
        "sample_spec_hash": sample.get("sample_spec_hash"),
        "structure": sample.get("structure"),
        "split_plan_hash": split_hash,
        "split_parameters": split.get("effective_parameters", {}),
        "oos": evaluation.get("oos", {}),
        "baseline": evaluation.get("baseline", {}),
        "controls": controls.get("controls", []),
        "limits": evaluation.get("limits", []),
        "payload_versions": {schema: payload["schema_version"] for schema, payload in by_schema.items()},
    }
