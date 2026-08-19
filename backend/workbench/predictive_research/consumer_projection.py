"""One validated evidence projection shared by Table, Report, Compare, and Agent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, sha256_file
from workbench.contracts.evidence.envelope import (
    ConsumerProjectionNotApplicableV1,
    ConsumerProjectionPayloadV1,
    ConsumerProjectionSlotV1,
    ConsumerProjectionV1,
    EvidenceEnvelopeV1,
    EvidenceReasonV1,
)
from .schema import PayloadContractError, default_v1_prediction_registry
from .contracts import ContractError


_REQUIRED = {
    "workbench.prediction.sample-spec",
    "workbench.prediction.split-plan",
    "workbench.prediction.prediction-packet",
    "workbench.prediction.evaluation-packet",
    "workbench.prediction.negative-control-packet",
}
_CONSUMERS = frozenset({"agent", "report", "table", "compare"})
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


def project_classification_evidence(payload: Mapping[str, Any], *, consumer: str) -> dict[str, Any]:
    """Project a classification packet without recomputing or inventing facts."""

    if consumer not in _CONSUMERS:
        raise ContractError("CLASSIFICATION_CONSUMER_UNSUPPORTED", f"unsupported consumer {consumer!r}")
    if not isinstance(payload, Mapping) or payload.get("payload_schema") != "workbench.prediction.classification-evidence" or payload.get("schema_version") != 1:
        raise ContractError("CLASSIFICATION_EVIDENCE_CONTRACT_INVALID", "classification evidence contract is invalid")
    missing = _CLASSIFICATION_REQUIRED - set(payload)
    if missing:
        raise ContractError("CLASSIFICATION_EVIDENCE_INCOMPLETE", f"missing classification evidence: {sorted(missing)}")
    if not isinstance(payload["blocked_reasons"], list):
        raise ContractError("CLASSIFICATION_EVIDENCE_CONTRACT_INVALID", "blocked_reasons must be a list")
    status = payload["status"]
    if status not in {"validated", "degraded", "unavailable"}:
        raise ContractError("CLASSIFICATION_EVIDENCE_STATUS_INVALID", "producer status is not a classification evidence status")
    task = payload["task"]
    split = payload["split"]
    holdout = payload["holdout"]
    refs = payload["evidence_refs"]
    if not isinstance(task, Mapping) or not isinstance(split, Mapping) or not isinstance(holdout, Mapping) or not isinstance(refs, Mapping):
        raise ContractError("CLASSIFICATION_EVIDENCE_IDENTITY_INVALID", "task, split, holdout and evidence_refs must be mappings")
    task_hash = task.get("task_hash")
    split_hash = split.get("split_hash")
    release_plan = holdout.get("release_plan")
    if (
        type(task_hash) is not str
        or type(split_hash) is not str
        or not isinstance(release_plan, Mapping)
        or type(release_plan.get("plan_hash")) is not str
        or release_plan.get("task_hash") != task_hash
        or release_plan.get("split_hash") != split_hash
        or holdout.get("release_plan_hash") != release_plan.get("plan_hash")
        or any(type(refs.get(key)) is not str for key in ("task", "split", "holdout", "release_plan"))
    ):
        raise ContractError("CLASSIFICATION_EVIDENCE_IDENTITY_INVALID", "task/split/holdout/release-plan identities are incomplete or inconsistent")
    if not isinstance(payload["metrics"], Mapping):
        raise ContractError("CLASSIFICATION_EVIDENCE_INCOMPLETE", "metrics must be a mapping")
    envelope, projection = _classification_c0_contracts(payload, status=status, task_hash=task_hash, split_hash=split_hash, release_plan_hash=release_plan["plan_hash"])
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
    """Validate producer C0 contracts, with an explicit legacy packet adapter."""

    raw_envelope = payload.get("c0_evidence_envelope")
    raw_projection = payload.get("c0_consumer_projection")
    if raw_envelope is not None or raw_projection is not None:
        if not isinstance(raw_envelope, dict) or not isinstance(raw_projection, dict):
            raise ContractError("CLASSIFICATION_EVIDENCE_C0_INVALID", "C0 envelope and projection must be supplied together")
        envelope = EvidenceEnvelopeV1.from_dict(raw_envelope)
        projection = ConsumerProjectionV1.from_dict(raw_projection)
    else:
        reason = EvidenceReasonV1(
            code="CLASSIFICATION_LEGACY_PACKET_ADAPTER",
            message="classification packet was adapted into the shared C0 evidence contracts",
            source_refs=(f"classification-task:{task_hash}", f"classification-split:{split_hash}", f"classification-release-plan:{release_plan_hash}"),
        ).to_dict()
        envelope_status = {
            "validated": ("completed", "available", "complete", [], [], []),
            "degraded": ("completed", "available", "degraded", [], [], [reason]),
            "unavailable": ("blocked", "not_available", "insufficient", [reason], [reason], [reason]),
        }[status]
        envelope = EvidenceEnvelopeV1.from_dict(
            {
                "result_identity": {"result_ref": f"classification-evidence:{task_hash}:{split_hash}:{release_plan_hash}", "task_hash": task_hash, "split_hash": split_hash, "holdout_hash": release_plan_hash, "release_plan_hash": release_plan_hash},
                "execution_status": envelope_status[0],
                "availability": envelope_status[1],
                "completeness_status": envelope_status[2],
                "execution_reasons": envelope_status[3],
                "availability_reasons": envelope_status[4],
                "degradation_reasons": envelope_status[5],
                "numerical_method": "deterministic_numeric",
                "inference_basis": "descriptive",
                "evaluation_design": "nested_cross_validation",
                "validation_summary": {"levels_present": [], "minimum_required": "none", "requirement_status": "not_applicable"},
                "method": {"id": "classification-production-v1", "version": "1.0"},
                "estimand": {"id": "out_of_sample_binary_classification_performance"},
                "input_provenance": {"task_hash": task_hash, "split_hash": split_hash, "release_plan_hash": release_plan_hash},
                "assumptions": [],
                "diagnostics": [],
                "figures": [],
                "warnings": [],
                "dependencies": [],
                "numeric_facts": [],
                "family_evidence": {"classification": {"status": status}},
                "oracle": {},
                "lineage_refs": [f"classification-task:{task_hash}", f"classification-split:{split_hash}", f"classification-release-plan:{release_plan_hash}"],
            }
        )
        facets = ("classification", "task", "split", "holdout", "release_plan") if status == "validated" else ("classification", "task", "split", "holdout", "release_plan", "degraded")
        projection = ConsumerProjectionV1(
            contract="consumer-projection",
            contract_version="1.0",
            producer_version="1.8.9",
            payload=ConsumerProjectionPayloadV1(
                projection_id=f"classification-evidence:{task_hash}:{split_hash}:{release_plan_hash}",
                projection_ref=f"classification-legacy-adapter:{task_hash}:{split_hash}:{release_plan_hash}",
                projection_status="available" if status in {"validated", "degraded"} else "blocked",
                slots=tuple(ConsumerProjectionSlotV1(consumer=item, artifact_facets=facets, payload_schema_ref="workbench.prediction.classification-evidence", source_eligible=status == "validated") for item in ("agent", "notebook", "report")),
                not_applicable_projection=ConsumerProjectionNotApplicableV1("not_applicable", "classification evidence is applicable to this result"),
            ),
        )
    if envelope.result_identity.get("task_hash") != task_hash or envelope.result_identity.get("split_hash") != split_hash or envelope.result_identity.get("release_plan_hash") != release_plan_hash:
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_IDENTITY_INVALID", "C0 evidence envelope identity does not match producer identity")
    if projection.payload.projection_status == "blocked" and status == "degraded":
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID", "degraded evidence must remain an available projection")
    consumers = {slot.consumer for slot in projection.payload.slots}
    if not {"agent", "notebook", "report"}.issubset(consumers):
        raise ContractError("CLASSIFICATION_EVIDENCE_C0_PROJECTION_INVALID", "C0 projection must cover Agent, Notebook and Report")
    return envelope, projection
