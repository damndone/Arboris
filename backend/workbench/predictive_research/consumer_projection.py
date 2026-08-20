"""One validated evidence projection shared by Table, Report, Compare, and Agent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any

from ..artifacts import read_json
from ..canonical import sha256_canonical
from ..repository import file_integrity
from workbench.contracts.evidence.envelope import (
    ConsumerProjectionV1,
    EvidenceEnvelopeV1,
)
from .schema import PayloadContractError, default_v1_prediction_registry
from .contracts import ContractError
from .persistence import (
    _CLASSIFICATION_RECEIPT_PATH,
    _CLASSIFICATION_RECEIPT_SCHEMA,
    classification_artifact_id,
    validate_classification_server_identity,
    validate_classification_server_identity_shape,
)


_REQUIRED = {
    "workbench.prediction.sample-spec",
    "workbench.prediction.split-plan",
    "workbench.prediction.prediction-packet",
    "workbench.prediction.evaluation-packet",
    "workbench.prediction.negative-control-packet",
}
_CONSUMERS = frozenset({"agent", "report", "table", "compare"})
_CLASSIFICATION_CONSUMERS = frozenset({"agent", "notebook", "report"})
_CLASSIFICATION_UNAVAILABLE_SCHEMA = "workbench.prediction.classification-evidence.unavailable"
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
        payload = _read_indexed_json_file(
            run_root,
            raw_record.get("path"),
            raw_record.get("sha256"),
            hash_error_code="ARTIFACT_PAYLOAD_HASH_MISMATCH",
            hash_error_message="prediction evidence hash does not match index",
        )
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
            consumer=consumer,
        )
    return project_prediction_evidence(payloads, consumer=consumer)


def read_classification_artifacts_wrapper_from_run_root(run_root: Path) -> dict[str, Any]:
    """Reload raw classification bytes only inside a server-owned wrapper."""

    index = _read_classification_artifacts_index(run_root)
    records = [
        record
        for record in index["artifacts"]
        if isinstance(record, Mapping) and record.get("artifact_type") == "classification_artifacts"
    ]
    if len(records) != 1:
        raise ContractError("CLASSIFICATION_PERSISTED_ARTIFACT_REQUIRED", "exactly one indexed classification artifact is required")
    record = records[0]
    contract = record.get("payload_contract")
    if contract != {"payload_schema": _PERSISTED_CLASSIFICATION_SCHEMA, "schema_version": 1}:
        raise ContractError("CLASSIFICATION_PERSISTED_ARTIFACT_CONTRACT_INVALID", "indexed classification artifact contract is invalid")
    payload = _read_indexed_json_file(
        run_root,
        record.get("path"),
        record.get("sha256"),
        hash_error_code="ARTIFACT_PAYLOAD_HASH_MISMATCH",
        hash_error_message="classification evidence hash does not match index",
    )
    if not isinstance(payload, Mapping) or payload.get("artifact_id") != record.get("artifact_id"):
        raise ContractError("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "indexed classification artifact identity is stale")
    expected_server_identity = validate_classification_server_identity(record.get("server_identity"), Path(run_root))
    if index.get("classification_server_identity") != expected_server_identity:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_MISMATCH", "classification index server identity is stale")
    if payload.get("server_identity") != expected_server_identity:
        raise ContractError("CLASSIFICATION_SERVER_IDENTITY_MISMATCH", "classification artifact server identity is stale")
    receipt_path = record.get("receipt_path")
    receipt_sha256 = record.get("receipt_sha256")
    if receipt_path != _CLASSIFICATION_RECEIPT_PATH or type(receipt_sha256) is not str:
        raise ContractError("CLASSIFICATION_PERSISTED_RECEIPT_REQUIRED", "classification artifact has no server-owned indexed receipt")
    receipt = _read_indexed_json_file(
        run_root,
        receipt_path,
        receipt_sha256,
        hash_error_code="CLASSIFICATION_PERSISTED_RECEIPT_INVALID",
        hash_error_message="classification server receipt hash does not match the index",
    )
    _validate_classification_receipt(
        receipt,
        payload=payload,
        record=record,
        run_root=Path(run_root),
        artifact_sha256=str(record.get("sha256")),
        server_identity=expected_server_identity,
    )
    # The route-facing wrapper is a typed evidence boundary, not a raw file
    # envelope.  Run the same status, identity, fold, and C0 projection
    # validation before any consumer can receive it.
    _project_classification_evidence(payload, consumer="report")
    return {
        "payload_schema": _CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA,
        "schema_version": 1,
        "artifact_id": record["artifact_id"],
        "artifact_path": record["path"],
        "artifact_sha256": record["sha256"],
        "index": dict(record),
        "artifact": dict(payload),
        "receipt_path": _CLASSIFICATION_RECEIPT_PATH,
        "receipt_sha256": receipt_sha256,
        "receipt": dict(receipt),
        "receipt_digest": receipt["receipt_digest"],
        "content_digests": dict(receipt["content_digests"]),
        "server_identity": dict(expected_server_identity),
    }


def read_classification_evidence_from_run_root(
    run_root: Path,
    *,
    consumer: str,
) -> dict[str, Any]:
    """Project evidence only after loading and validating the shared wrapper."""

    try:
        wrapper = read_classification_artifacts_wrapper_from_run_root(run_root)
    except PayloadContractError as exc:
        if consumer in _CLASSIFICATION_CONSUMERS and exc.code in {
            "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE",
            "CLASSIFICATION_ARTIFACTS_INDEX_INVALID",
        }:
            return _classification_unavailable_projection(consumer=consumer, code=exc.code)
        raise
    return _project_classification_evidence(wrapper["artifact"], consumer=consumer)


def _read_classification_artifacts_index(run_root: Path) -> dict[str, Any]:
    """Read only the server-owned classification index with stable index errors."""

    try:
        index = read_json(run_root / "artifacts_index.json")
    except FileNotFoundError as exc:
        raise PayloadContractError(
            "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE",
            "classification artifacts_index.json is unavailable",
        ) from exc
    except OSError as exc:
        raise PayloadContractError(
            "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE",
            "classification artifacts_index.json is unavailable",
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadContractError(
            "CLASSIFICATION_ARTIFACTS_INDEX_INVALID",
            "classification artifacts_index.json is malformed",
        ) from exc
    if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
        raise PayloadContractError(
            "CLASSIFICATION_ARTIFACTS_INDEX_INVALID",
            "classification artifacts_index.json has no artifact list",
        )
    return index


def _read_indexed_json_file(
    run_root: Path,
    relative_path: object,
    expected_sha256: object,
    *,
    hash_error_code: str,
    hash_error_message: str,
) -> Any:
    try:
        with file_integrity.open_run_relative_file(run_root, relative_path) as opened:
            raw, actual_sha256 = opened.read_bytes_and_sha256()
    except (OSError, ValueError) as exc:
        raise PayloadContractError(
            "ARTIFACT_PATH_INVALID",
            "indexed evidence path could not be safely opened",
        ) from exc
    if actual_sha256 != expected_sha256:
        raise PayloadContractError(hash_error_code, hash_error_message)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadContractError(
            "ARTIFACT_PAYLOAD_VALIDATION_FAILED",
            "indexed evidence JSON is unreadable",
        ) from exc


def _classification_unavailable_projection(*, consumer: str, code: str) -> dict[str, Any]:
    """Return the one typed unavailable shape for classification index failures."""

    return {
        "payload_schema": _CLASSIFICATION_UNAVAILABLE_SCHEMA,
        "schema_version": 1,
        "status": "unavailable",
        "consumer": consumer,
        "code": code,
    }


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
    consumer: str,
) -> dict[str, Any]:
    if consumer not in _CONSUMERS:
        raise PayloadContractError("ARTIFACT_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    legacy_results: list[dict[str, Any]] = []
    for raw_record in records:
        record = dict(raw_record)
        payload = _read_indexed_json_file(
            run_root,
            record.get("path"),
            record.get("sha256"),
            hash_error_code="ARTIFACT_PAYLOAD_HASH_MISMATCH",
            hash_error_message="legacy prediction hash does not match index",
        )
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


_CLASSIFICATION_REQUIRED = frozenset(
    {
        "status",
        "task",
        "split",
        "metrics",
        "calibration",
        "baselines",
        "controls",
        "comparison",
        "explanations",
        "stability",
        "shift",
        "decision_policy",
        "blocked_reasons",
        "evidence_refs",
        "holdout",
    }
)
_CLASSIFICATION_C0_REQUIRED = frozenset(
    {
        "c0_evidence_envelope",
        "c0_consumer_projection",
        "foundation_status",
    }
)
_CLASSIFICATION_C0_CONSUMERS = frozenset({"agent", "notebook", "report"})
_CLASSIFICATION_C0_BASE_FACETS = frozenset({"classification", "task", "split", "holdout", "release_plan"})
_CLASSIFICATION_C0_STATUS = {
    "validated": ("completed", "available", "complete", "available", True),
    "degraded": ("completed", "available", "degraded", "available", False),
    "unavailable": ("blocked", "not_available", "insufficient", "blocked", False),
}
_CLASSIFICATION_FAMILY_ISSUER = "workbench.server"
_CLASSIFICATION_FAMILY_PRODUCER = "workbench.prediction.run_classification_model_v189"
_CLASSIFICATION_FAMILY_METHOD = {"id": "classification-production-v1", "version": "1.0"}
_PERSISTED_CLASSIFICATION_SCHEMA = "workbench.prediction.classification-artifacts"
_CLASSIFICATION_ARTIFACTS_WRAPPER_SCHEMA = "workbench.prediction.classification-artifacts-wrapper"
_PERSISTED_CLASSIFICATION_IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "parts",
        "task_hash",
        "split_hash",
        "model_id",
        "model_hash",
        "holdout_hash",
        "release_plan_hash",
        "fit_digest",
        "evaluation_digest",
        "server_identity",
    }
)


def _persisted_classification_error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _classification_content_digests(payload: Mapping[str, Any], *, artifact_sha256: str) -> dict[str, str]:
    evidence = payload.get("evidence")
    evaluation = payload.get("evaluation")
    models = payload.get("models")
    fit = payload.get("fit")
    if not isinstance(evidence, Mapping) or not isinstance(evaluation, Mapping) or not isinstance(models, Mapping) or not isinstance(fit, Mapping):
        raise _persisted_classification_error(
            "CLASSIFICATION_PERSISTED_RECEIPT_INVALID",
            "classification receipt cannot bind an incomplete artifact",
        )
    model_metadata = {
        str(model_id): model.get("metadata")
        for model_id, model in models.items()
        if isinstance(model_id, str) and isinstance(model, Mapping)
    }
    model_warnings = {
        model_id: metadata.get("warnings")
        for model_id, metadata in model_metadata.items()
        if isinstance(metadata, Mapping)
    }
    return {
        "artifact": artifact_sha256,
        "evidence": sha256_canonical(evidence),
        "evidence.metrics": sha256_canonical(evidence.get("metrics")),
        "evaluation": sha256_canonical(evaluation),
        "evaluation.metrics": sha256_canonical(evaluation.get("metrics")),
        "models": sha256_canonical(models),
        "models.metadata": sha256_canonical(model_metadata),
        "models.warnings": sha256_canonical(model_warnings),
        "fit": sha256_canonical(fit),
        "fold_receipts": sha256_canonical(
            {
                str(model_id): model.get("fold_receipts")
                for model_id, model in fit.get("models", {}).items()
                if isinstance(model_id, str) and isinstance(model, Mapping)
            }
        ),
    }


def _validate_classification_receipt(
    receipt: Any,
    *,
    payload: Mapping[str, Any],
    record: Mapping[str, Any],
    run_root: Path,
    artifact_sha256: str,
    server_identity: Mapping[str, Any],
) -> None:
    if not isinstance(receipt, Mapping):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_RECEIPT_INVALID", "classification server receipt must be an object")
    required = {
        "payload_schema", "schema_version", "receipt_id", "artifact_path", "artifact_id",
        "artifact_sha256", "payload_contract", "server_identity", "content_digests", "issuer", "receipt_digest",
    }
    if set(receipt) != required or receipt.get("payload_schema") != _CLASSIFICATION_RECEIPT_SCHEMA or receipt.get("schema_version") != 1:
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_RECEIPT_INVALID", "classification server receipt schema is invalid")
    if (
        type(receipt.get("receipt_id")) is not str
        or not receipt["receipt_id"]
        or receipt.get("artifact_path") != record.get("path")
        or receipt.get("artifact_id") != payload.get("artifact_id")
        or receipt.get("artifact_id") != record.get("artifact_id")
        or receipt.get("artifact_sha256") != artifact_sha256
        or receipt.get("payload_contract") != record.get("payload_contract")
        or receipt.get("server_identity") != dict(server_identity)
        or receipt.get("issuer") != "workbench.server.classification-persistence"
    ):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_RECEIPT_INVALID", "classification server receipt identity is stale")
    base = {key: receipt[key] for key in required if key != "receipt_digest"}
    if receipt.get("receipt_digest") != sha256_canonical(base):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_RECEIPT_INVALID", "classification server receipt digest is invalid")
    if receipt.get("content_digests") != _classification_content_digests(payload, artifact_sha256=artifact_sha256):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_RECEIPT_INVALID", "classification content receipt is stale")


def _validate_persisted_fold_receipts(
    artifact: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    split_hash: str,
) -> None:
    fit = artifact.get("fit")
    models = artifact.get("models")
    task = evidence.get("task")
    if not isinstance(fit, Mapping) or not isinstance(models, Mapping) or not isinstance(task, Mapping):
        raise _persisted_classification_error(
            "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
            "persisted classification fit and model structures are required",
        )
    fit_models = fit.get("models")
    overall_support = task.get("class_support")
    if fit.get("schema_version") != 1 or not isinstance(fit_models, Mapping) or not isinstance(overall_support, Mapping):
        raise _persisted_classification_error(
            "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
            "persisted classification fit schema and task support are required",
        )
    labels = list(overall_support)
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise _persisted_classification_error(
            "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
            "persisted task class support must contain unique class labels",
        )
    for label, count in overall_support.items():
        if type(label) is not str or type(count) is not int or count <= 0:
            raise _persisted_classification_error(
                "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                "persisted task class support counts must be non-negative integers",
            )
    if set(fit_models) != set(models):
        raise _persisted_classification_error(
            "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
            "persisted fit models must match persisted model candidates",
        )
    for model_id, fit_model in fit_models.items():
        model = models.get(model_id)
        if not isinstance(model_id, str) or not isinstance(fit_model, Mapping) or not isinstance(model, Mapping):
            raise _persisted_classification_error(
                "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                "persisted model fit records must be objects",
            )
        preprocessing = model.get("preprocessing")
        fold_receipts = fit_model.get("fold_receipts")
        if (
            not isinstance(preprocessing, Mapping)
            or preprocessing.get("folds") != fold_receipts
            or not isinstance(fold_receipts, list)
            or not fold_receipts
        ):
            raise _persisted_classification_error(
                "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                f"persisted model {model_id!r} has no complete fold receipts",
            )
        seen_folds: set[int] = set()
        for fold in fold_receipts:
            if not isinstance(fold, Mapping):
                raise _persisted_classification_error(
                    "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                    "persisted fold receipt must be an object",
                )
            fold_number = fold.get("fold")
            training_refs = fold.get("training_row_refs")
            validation_refs = fold.get("validation_row_refs")
            receipt = fold.get("receipt")
            support = receipt.get("class_support") if isinstance(receipt, Mapping) else None
            if (
                type(fold_number) is not int
                or fold_number < 0
                or fold_number in seen_folds
                or not isinstance(training_refs, list)
                or not isinstance(validation_refs, list)
                or not training_refs
                or not validation_refs
                or not isinstance(receipt, Mapping)
                or receipt.get("schema_version") != 1
                or receipt.get("split_hash") != split_hash
                or receipt.get("fit_row_refs") != training_refs
                or not isinstance(support, Mapping)
            ):
                raise _persisted_classification_error(
                    "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                    f"persisted fold receipt {fold_number!r} is incomplete or stale",
                )
            seen_folds.add(fold_number)
            class_labels = support.get("class_labels")
            if (
                not isinstance(class_labels, list)
                or any(type(label) is not str for label in class_labels)
                or class_labels != labels
                or len(set(class_labels)) != len(class_labels)
            ):
                raise _persisted_classification_error(
                    "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                    "persisted fold receipt class labels are incomplete or reordered",
                )
            for scope, refs in (("training", training_refs), ("validation", validation_refs)):
                counts = support.get(scope)
                if not isinstance(counts, Mapping) or set(counts) != set(labels):
                    raise _persisted_classification_error(
                        "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                        f"persisted {scope} class support is incomplete",
                    )
                if any(type(counts[label]) is not int or counts[label] <= 0 or counts[label] > overall_support[label] for label in labels):
                    raise _persisted_classification_error(
                        "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                        f"persisted {scope} class support exceeds task bounds",
                    )
                if (
                    any(type(ref) is not str for ref in refs)
                    or sum(counts.values()) != len(refs)
                    or len(set(refs)) != len(refs)
                ):
                    raise _persisted_classification_error(
                        "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID",
                        f"persisted {scope} class support does not cover its row refs",
                    )


def _unwrap_persisted_classification_artifact(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("payload_schema") != _PERSISTED_CLASSIFICATION_SCHEMA:
        return payload
    if payload.get("schema_version") != 1:
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_CONTRACT_INVALID", "persisted classification artifact schema is unsupported")
    evidence = payload.get("evidence")
    identity = payload.get("identity")
    fit = payload.get("fit")
    evaluation = payload.get("evaluation")
    models = payload.get("models")
    if (
        not isinstance(evidence, Mapping)
        or not isinstance(identity, Mapping)
        or not isinstance(fit, Mapping)
        or not isinstance(evaluation, Mapping)
        or not isinstance(models, Mapping)
    ):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_CONTRACT_INVALID", "persisted classification artifact is incomplete")
    evidence_task = evidence.get("task")
    evidence_split = evidence.get("split")
    evidence_holdout = evidence.get("holdout")
    comparison = evidence.get("comparison")
    release_plan = evidence_holdout.get("release_plan") if isinstance(evidence_holdout, Mapping) else None
    task_hash = evidence_task.get("task_hash") if isinstance(evidence_task, Mapping) else None
    split_hash = evidence_split.get("split_hash") if isinstance(evidence_split, Mapping) else None
    selected_model = comparison.get("selected_model") if isinstance(comparison, Mapping) else None
    release_plan_hash = release_plan.get("plan_hash") if isinstance(release_plan, Mapping) else None
    expected_identity = {
        "task_hash": task_hash,
        "split_hash": split_hash,
        "model_id": selected_model,
        "model_hash": release_plan.get("model_hash") if isinstance(release_plan, Mapping) else None,
        "holdout_hash": release_plan_hash,
        "release_plan_hash": release_plan_hash,
        "server_identity": payload.get("server_identity"),
    }
    try:
        server_identity = validate_classification_server_identity_shape(payload.get("server_identity"))
    except ContractError as exc:
        raise _persisted_classification_error("CLASSIFICATION_SERVER_IDENTITY_INVALID", "persisted classification server identity is invalid") from exc
    expected_identity["server_identity"] = server_identity
    _validate_persisted_fold_receipts(payload, evidence, split_hash=split_hash if isinstance(split_hash, str) else "")
    if (
        set(identity) != _PERSISTED_CLASSIFICATION_IDENTITY_FIELDS
        or identity.get("schema_version") != 1
        or identity.get("artifact_id") != payload.get("artifact_id")
        or any(identity.get(key) != value for key, value in expected_identity.items())
        or identity.get("fit_digest") != fit.get("digest")
        or identity.get("evaluation_digest") != evaluation.get("digest")
    ):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted classification identity is stale or inconsistent")
    parts = identity.get("parts")
    if not isinstance(parts, Mapping) or any(type(key) is not str or type(value) is not str for key, value in parts.items()):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted artifact identity parts are invalid")
    try:
        expected_artifact_id = classification_artifact_id(**dict(parts))
    except ContractError as exc:
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted artifact identity parts are invalid") from exc
    if expected_artifact_id != payload.get("artifact_id"):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted artifact digest binding is stale")
    fit_identity = fit.get("identity")
    evaluation_identity = evaluation.get("identity")
    if fit.get("schema_version") != 1 or evaluation.get("schema_version") != 1 or fit_identity != expected_identity or evaluation_identity != expected_identity:
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted fit/evaluation identity is stale")
    fit_base = {"schema_version": 1, "identity": dict(expected_identity), "models": fit.get("models")}
    evaluation_base = {
        "schema_version": 1,
        "identity": dict(expected_identity),
        "comparison": evaluation.get("comparison"),
        "metrics": evaluation.get("metrics"),
        "holdout": evaluation.get("holdout"),
        "decision_policy": evaluation.get("decision_policy"),
    }
    selected_model_payload = models.get(selected_model) if isinstance(selected_model, str) else None
    expected_metrics = (
        {"oof": selected_model_payload.get("oof_metrics"), "holdout": selected_model_payload.get("holdout")}
        if isinstance(selected_model_payload, Mapping)
        else None
    )
    if (
        fit.get("digest") != sha256_canonical(fit_base)
        or evaluation.get("digest") != sha256_canonical(evaluation_base)
        or evaluation.get("comparison") != evidence.get("comparison")
        or expected_metrics is None
        or evaluation.get("metrics") != expected_metrics
    ):
        raise _persisted_classification_error("CLASSIFICATION_PERSISTED_ARTIFACT_IDENTITY_INVALID", "persisted fit/evaluation digest binding is stale")
    return evidence


def project_classification_evidence(run_root: Path, *, consumer: str) -> dict[str, Any]:
    """Project only a server-owned run root with an indexed receipt.

    Raw packets and even apparently complete persisted mappings are not an
    authority boundary.  The mapping validator remains private and is reached
    only after the indexed payload and server-owned receipt have been loaded.
    """

    if not isinstance(run_root, Path):
        raise ContractError(
            "CLASSIFICATION_PERSISTED_RECEIPT_REQUIRED",
            "classification consumers require a server-owned run root or capability",
        )
    return read_classification_evidence_from_run_root(run_root, consumer=consumer)


def _project_classification_evidence(payload: Mapping[str, Any], *, consumer: str) -> dict[str, Any]:
    """Project a classification packet without recomputing or inventing facts."""

    if consumer not in _CLASSIFICATION_CONSUMERS:
        raise ContractError("CLASSIFICATION_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    if not isinstance(payload, Mapping):
        raise ContractError("CLASSIFICATION_EVIDENCE_CONTRACT_INVALID", "classification evidence contract is invalid")
    persisted_server_identity = payload.get("server_identity")
    payload = _unwrap_persisted_classification_artifact(payload)
    if not isinstance(payload, Mapping) or payload.get("payload_schema") != "workbench.prediction.classification-evidence" or payload.get("schema_version") != 1:
        raise ContractError("CLASSIFICATION_EVIDENCE_CONTRACT_INVALID", "classification evidence contract is invalid")
    missing = _CLASSIFICATION_REQUIRED - set(payload)
    if missing:
        raise ContractError("CLASSIFICATION_EVIDENCE_INCOMPLETE", f"missing classification evidence: {sorted(missing)}")
    if not isinstance(payload["blocked_reasons"], list):
        raise ContractError("CLASSIFICATION_EVIDENCE_CONTRACT_INVALID", "blocked_reasons must be a list")
    status = payload["status"]
    if type(status) is not str or status not in _CLASSIFICATION_C0_STATUS:
        raise ContractError("CLASSIFICATION_EVIDENCE_STATUS_INVALID", "producer status is not a classification evidence status")
    task = payload["task"]
    split = payload["split"]
    holdout = payload["holdout"]
    refs = payload["evidence_refs"]
    comparison = payload["comparison"]
    if (
        not isinstance(task, Mapping)
        or not isinstance(split, Mapping)
        or not isinstance(holdout, Mapping)
        or not isinstance(refs, Mapping)
        or not isinstance(comparison, Mapping)
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_IDENTITY_INVALID", "task, split, holdout and evidence_refs must be mappings")
    task_hash = task.get("task_hash")
    split_hash = split.get("split_hash")
    release_plan = holdout.get("release_plan")
    selected_model = comparison.get("selected_model")
    if (
        type(task_hash) is not str
        or type(split_hash) is not str
        or not isinstance(release_plan, Mapping)
        or type(release_plan.get("plan_hash")) is not str
        or type(release_plan.get("model_id")) is not str
        or type(release_plan.get("model_hash")) is not str
        or type(holdout.get("model_id")) is not str
        or type(selected_model) is not str
        or release_plan.get("task_hash") != task_hash
        or release_plan.get("split_hash") != split_hash
        or release_plan.get("model_id") != selected_model
        or holdout.get("model_id") != selected_model
        or holdout.get("release_plan_hash") != release_plan.get("plan_hash")
        or set(refs) != {"task", "split", "model", "holdout", "release_plan"}
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_IDENTITY_INVALID", "task/split/holdout/release-plan identities are incomplete or inconsistent")
    release_plan_hash = release_plan["plan_hash"]
    expected_refs = {
        "task": f"classification-task:{task_hash}",
        "split": f"classification-split:{split_hash}",
        "model": f"classification-model:{selected_model}:{release_plan['model_hash']}",
        "holdout": f"classification-holdout:{release_plan_hash}",
        "release_plan": f"classification-release-plan:{release_plan_hash}",
    }
    if any(type(refs.get(key)) is not str or refs[key] != expected for key, expected in expected_refs.items()):
        raise ContractError("CLASSIFICATION_EVIDENCE_IDENTITY_INVALID", "evidence_refs do not match the task, split, model, holdout and release-plan identities")
    if not isinstance(payload["metrics"], Mapping):
        raise ContractError("CLASSIFICATION_EVIDENCE_INCOMPLETE", "metrics must be a mapping")
    envelope, projection = _classification_c0_contracts(
        payload,
        status=status,
        task_hash=task_hash,
        split_hash=split_hash,
        release_plan_hash=release_plan_hash,
    )
    return {
        "status": status,
        "consumer": consumer,
        "task": dict(task),
        "task_hash": task_hash,
        "split": dict(split),
        "split_hash": split_hash,
        "metrics": dict(payload["metrics"]),
        "calibration": payload["calibration"],
        "baselines": payload["baselines"],
        "controls": payload["controls"],
        "comparison": payload["comparison"],
        "explanations": payload["explanations"],
        "stability": payload["stability"],
        "shift": payload["shift"],
        "decision_policy": payload["decision_policy"],
        "blocked_reasons": list(payload["blocked_reasons"]),
        "evidence_refs": dict(refs),
        "server_identity": dict(persisted_server_identity or {}),
        "holdout": dict(holdout),
        "release_plan_identity": dict(release_plan),
        "c0_evidence_envelope": envelope.to_dict(),
        "c0_consumer_projection": projection.to_dict(),
        "foundation_status": dict(payload.get("foundation_status", {
            "execution_status": envelope.execution_status.value,
            "availability": envelope.availability.value,
            "completeness_status": envelope.completeness_status.value,
            "producer_status": status,
        })),
    }


def _classification_c0_contracts(
    payload: Mapping[str, Any],
    *,
    status: str,
    task_hash: str,
    split_hash: str,
    release_plan_hash: str,
) -> tuple[EvidenceEnvelopeV1, ConsumerProjectionV1]:
    """Validate the producer-owned C0 envelope and consumer projection."""

    raw_envelope = payload.get("c0_evidence_envelope")
    raw_projection = payload.get("c0_consumer_projection")
    raw_foundation = payload.get("foundation_status")
    if (
        not isinstance(raw_envelope, dict)
        or not isinstance(raw_projection, dict)
        or not isinstance(raw_foundation, Mapping)
    ):
        missing = sorted(_CLASSIFICATION_C0_REQUIRED - set(payload))
        raise ContractError(
            "CLASSIFICATION_EVIDENCE_C0_REQUIRED",
            f"classification evidence requires explicit C0 envelope, projection and foundation status: {missing}",
        )
    try:
        envelope = EvidenceEnvelopeV1.from_dict(raw_envelope)
        projection = ConsumerProjectionV1.from_dict(raw_projection)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_INVALID", "C0 envelope or projection is not a valid typed contract") from exc

    expected_execution, expected_availability, expected_completeness, expected_projection, expected_eligible = _CLASSIFICATION_C0_STATUS[status]
    expected_result_ref = f"classification-evidence:{task_hash}:{split_hash}:{release_plan_hash}"
    identity = envelope.result_identity
    if (
        identity.get("result_ref") != expected_result_ref
        or identity.get("task_hash") != task_hash
        or identity.get("split_hash") != split_hash
        or identity.get("holdout_hash") != release_plan_hash
        or identity.get("release_plan_hash") != release_plan_hash
        or envelope.input_provenance.get("task_hash") != task_hash
        or envelope.input_provenance.get("split_hash") != split_hash
        or envelope.input_provenance.get("holdout_hash") != release_plan_hash
        or envelope.input_provenance.get("release_plan_hash") != release_plan_hash
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_IDENTITY_INVALID", "C0 evidence envelope identity does not match producer identity")
    if (
        envelope.execution_status.value != expected_execution
        or envelope.availability.value != expected_availability
        or envelope.completeness_status.value != expected_completeness
        or projection.payload.projection_status != expected_projection
        or projection.payload.projection_id != expected_result_ref
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID", "producer status is not monotone with C0 envelope and projection status")
    if (
        set(raw_foundation) != {"execution_status", "availability", "completeness_status", "producer_status"}
        or any(
            raw_foundation.get(key) != expected
            for key, expected in {
                "execution_status": expected_execution,
                "availability": expected_availability,
                "completeness_status": expected_completeness,
                "producer_status": status,
            }.items()
        )
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID", "foundation status does not match producer status")
    classification_family = envelope.family_evidence.get("classification")
    if not isinstance(classification_family, Mapping):
        raise ContractError("CLASSIFICATION_EVIDENCE_FAMILY_INVALID", "classification family evidence is required")
    family_method = classification_family.get("method")
    family_identity = classification_family.get("identity")
    expected_identity = {
        "result_ref": expected_result_ref,
        "task_hash": task_hash,
        "split_hash": split_hash,
        "model_id": _classification_release_plan_model_id(payload),
        "model_hash": _classification_release_plan_model_hash(payload),
        "holdout_hash": release_plan_hash,
        "release_plan_hash": release_plan_hash,
    }
    if (
        set(classification_family) != {"status", "issuer", "producer", "method", "identity"}
        or classification_family.get("status") != status
        or classification_family.get("issuer") != _CLASSIFICATION_FAMILY_ISSUER
        or classification_family.get("producer") != _CLASSIFICATION_FAMILY_PRODUCER
        or family_method != _CLASSIFICATION_FAMILY_METHOD
        or not isinstance(family_identity, Mapping)
        or set(family_identity) != set(expected_identity)
        or any(family_identity.get(key) != value for key, value in expected_identity.items())
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_FAMILY_INVALID", "classification family issuer, producer, method or identity is invalid")
    if projection.contract != "consumer-projection" or projection.contract_version != "1.0" or projection.producer_version != "1.8.9":
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_PROJECTION_INVALID", "C0 projection contract identity is invalid")
    if {slot.consumer for slot in projection.payload.slots} != _CLASSIFICATION_C0_CONSUMERS:
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_PROJECTION_INVALID", "C0 projection must contain exactly Agent, Notebook and Report slots")
    expected_facets = _CLASSIFICATION_C0_BASE_FACETS | ({"degraded"} if not expected_eligible else set())
    for slot in projection.payload.slots:
        if (
            slot.payload_schema_ref != "workbench.prediction.classification-evidence"
            or slot.source_eligible is not expected_eligible
            or set(slot.artifact_facets) != expected_facets
        ):
            raise ContractError("CLASSIFICATION_EVIDENCE_C0_PROJECTION_INVALID", "C0 consumer slot is not monotone with producer status")
    return envelope, projection


def _classification_release_plan_model_id(payload: Mapping[str, Any]) -> Any:
    holdout = payload.get("holdout")
    release_plan = holdout.get("release_plan") if isinstance(holdout, Mapping) else None
    return release_plan.get("model_id") if isinstance(release_plan, Mapping) else None


def _classification_release_plan_model_hash(payload: Mapping[str, Any]) -> Any:
    holdout = payload.get("holdout")
    release_plan = holdout.get("release_plan") if isinstance(holdout, Mapping) else None
    return release_plan.get("model_hash") if isinstance(release_plan, Mapping) else None
