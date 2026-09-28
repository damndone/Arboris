"""One validated evidence projection shared by Table, Report, Compare, and Agent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, sha256_file
from .schema import (
    CLASSIFICATION_PACKET_SCHEMA,
    PayloadContractError,
    default_v1_prediction_registry,
    validate_classification_packet,
)
from .persistence import PredictionPersistenceAdmission


_REQUIRED = {
    "workbench.prediction.sample-spec",
    "workbench.prediction.split-plan",
    "workbench.prediction.prediction-packet",
    "workbench.prediction.evaluation-packet",
    "workbench.prediction.negative-control-packet",
}
_CONSUMERS = frozenset({"agent", "report", "table", "compare"})
_CLASSIFICATION_CONSUMERS = frozenset({"agent", "notebook", "report", "table", "compare"})
_LEGACY_MESSAGE = (
    "Legacy evaluation — split protocol was not persisted. The result remains "
    "readable but is not comparable with v1.8.6 predictive-research results."
)


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
    legacy_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    resolved_root = run_root.resolve()
    for raw_record in index["artifacts"]:
        if not isinstance(raw_record, dict):
            continue
        if (
            raw_record.get("artifact_type") == "prediction_result"
            and not _has_payload_contract(raw_record.get("payload_contract"))
        ):
            legacy_records.append(raw_record)
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
    if legacy_records and payloads:
        raise PayloadContractError(
            "ARTIFACT_PAYLOAD_MIXED_GENERATIONS",
            "legacy and v1.8.6 prediction evidence cannot share one projection",
        )
    if legacy_records:
        return _project_legacy_prediction_evidence(
            legacy_records,
            run_root=run_root,
            resolved_root=resolved_root,
            consumer=consumer,
        )
    return project_prediction_evidence(payloads, consumer=consumer)


def _has_payload_contract(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("payload_schema"), str)
        and isinstance(value.get("schema_version"), int)
    )


def _project_legacy_prediction_evidence(
    records: Iterable[Mapping[str, Any]],
    *,
    run_root: Path,
    resolved_root: Path,
    consumer: str,
) -> dict[str, Any]:
    if consumer not in _CONSUMERS:
        raise PayloadContractError("ARTIFACT_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    legacy_results: list[dict[str, Any]] = []
    for raw_record in records:
        record = dict(raw_record)
        relative_path = Path(str(record.get("path", "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PayloadContractError("ARTIFACT_PATH_INVALID", "legacy prediction path must stay inside run root")
        path = (run_root / relative_path).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as error:
            raise PayloadContractError("ARTIFACT_PATH_INVALID", "legacy prediction path escapes run root") from error
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise PayloadContractError("ARTIFACT_PAYLOAD_HASH_MISMATCH", "legacy prediction hash does not match index")
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise PayloadContractError("ARTIFACT_PAYLOAD_VALIDATION_FAILED", "legacy prediction payload must be an object")
        legacy_results.append(
            {
                "artifact_id": record.get("artifact_id"),
                "model_id": payload.get("model_id") or record.get("artifact_id"),
                "model_type": payload.get("model_type"),
                "status": payload.get("status"),
                "nobs": payload.get("nobs"),
                "cv_folds": payload.get("cv_folds"),
                "sampling_method": payload.get("sampling_method"),
                "metrics": payload.get("metrics", {}),
            }
        )
    first = legacy_results[0] if legacy_results else {}
    return {
        "status": "legacy",
        "consumer": consumer,
        "protocol": "legacy_random_split_v0",
        "validation": "payload_not_evaluated",
        "comparability": "legacy_only",
        "message": _LEGACY_MESSAGE,
        "model_id": first.get("model_id"),
        "legacy_artifacts": legacy_results,
    }


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
        "dataset_sha256": (sample.get("dataset_ref") or {}).get("dataset_sha256"),
        "structure": sample.get("structure"),
        "split_plan_hash": split_hash,
        "split_parameters": split.get("effective_parameters", {}),
        "oos": evaluation.get("oos", {}),
        "development": {"cv": evaluation.get("cv", [])},
        "baseline": evaluation.get("baseline", {}),
        "controls": controls.get("controls", []),
        "limits": evaluation.get("limits", []),
        "payload_versions": {schema: payload["schema_version"] for schema, payload in by_schema.items()},
    }


def project_classification_evidence(
    payload: Mapping[str, Any],
    *,
    consumer: str,
) -> dict[str, Any]:
    """Project one classification packet without recomputing any result.

    This is intentionally a copy-by-reference projection: the packet is the
    authority, and consumers receive the exact typed metric/calibration/
    control objects produced by the protocol.  No row data, estimator, or
    metric implementation is imported here.
    """

    if consumer not in _CLASSIFICATION_CONSUMERS:
        raise PayloadContractError("ARTIFACT_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    packet = validate_classification_packet(payload)
    ready = packet["status"] == "validated"
    # A blocked/unavailable packet may retain diagnostic fields for audit, but
    # it is not an evidence release.  Do not leak stale numeric sections to a
    # downstream Agent, Notebook, Report, or table projection.
    models = packet["models"] if ready else []
    selected_model = packet.get("selected_model") if ready else None
    model_id = selected_model.get("model_id") if isinstance(selected_model, Mapping) else None
    evaluation = packet["evaluation"] if ready else {"status": "unavailable", "metrics": {}}
    calibration = packet["calibration"] if ready else {"status": "unavailable"}
    baselines = packet["baselines"] if ready else []
    controls = packet["controls"] if ready else []
    comparison = packet["comparison"] if ready else {"status": "unavailable"}
    explanations = packet["explanations"] if ready else {"status": "unavailable"}
    decision_policy = packet["decision_policy"] if ready else {"status": "unavailable"}
    safe_task = packet["task"] if ready else {"status": "unavailable"}
    safe_split = packet["split"] if ready else {"status": "unavailable"}
    safe_availability = packet["availability"] if ready else {
        "status": packet["availability"].get("status", "unknown"),
    }
    safe_receipt = packet["evidence_receipt"] if ready else {
        "status": "unavailable",
        "validation_level": "blocked",
    }
    return {
        "status": packet["status"],
        "consumer": consumer,
        "protocol": "classification_ml_v1",
        "projection_kind": "typed_classification_evidence",
        "packet_id": packet["packet_id"],
        "packet_hash": packet.get("packet_hash"),
        "model_id": model_id,
        "task": safe_task,
        "split": safe_split,
        "models": models,
        "selected_model": selected_model,
        "evaluation": evaluation,
        "metrics": evaluation.get("metrics", {}),
        "calibration": calibration,
        "baselines": baselines,
        "controls": controls,
        "comparison": comparison,
        "explanations": explanations,
        "decision_policy": decision_policy,
        "holdout_boundary": packet["holdout_boundary"],
        "availability": safe_availability,
        "warnings": packet["warnings"],
        "blocked_reasons": packet["warnings"] if packet["status"] != "validated" else [],
        "evidence_receipt": safe_receipt,
        "artifact_refs": packet["artifact_refs"] if ready else {},
        "derived_from_raw_rows": False,
    }


def read_classification_evidence_from_run_root(
    run_root: Path,
    *,
    consumer: str,
) -> dict[str, Any]:
    """Read exactly one hash-verified classification packet from a run.

    A missing packet becomes an explicit unavailable projection.  A present
    but tampered packet raises a typed contract error; neither case exposes
    raw JSON to a consumer as if it were trustworthy evidence.
    """

    if consumer not in _CLASSIFICATION_CONSUMERS:
        raise PayloadContractError("ARTIFACT_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    with PredictionPersistenceAdmission.admit(Path(run_root)) as admission:
        index = admission._read_json(("artifacts_index.json",))
        if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
            raise PayloadContractError("ARTIFACT_INDEX_INVALID", "artifacts_index.json has no artifact list")
        records = [
            record
            for record in index["artifacts"]
            if isinstance(record, dict) and record.get("artifact_type") == "classification_evidence_packet"
        ]
        if not records:
            return {
                "status": "unavailable",
                "consumer": consumer,
                "protocol": "classification_ml_v1",
                "projection_kind": "typed_classification_evidence",
                "reason": "classification evidence packet is unavailable",
                "derived_from_raw_rows": False,
            }
        if len(records) != 1:
            raise PayloadContractError(
                "CLASSIFICATION_PACKET_DUPLICATE",
                "a run must expose exactly one classification evidence packet",
            )
        record = records[0]
        contract = record.get("payload_contract")
        if not isinstance(contract, Mapping) or contract.get("payload_schema") != CLASSIFICATION_PACKET_SCHEMA or contract.get("schema_version") != 1:
            raise PayloadContractError("ARTIFACT_PAYLOAD_CONTRACT_MISMATCH", "classification packet contract is inconsistent")
        relative_path = Path(str(record.get("path", "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise PayloadContractError("ARTIFACT_PATH_INVALID", "classification evidence path must stay inside run root")
        payload = admission.read_verified_json(tuple(relative_path.parts), str(record.get("sha256", "")))
        if not isinstance(payload, Mapping):
            raise PayloadContractError("CLASSIFICATION_PACKET_INVALID", "classification evidence payload is not an object")
    return project_classification_evidence(payload, consumer=consumer)
