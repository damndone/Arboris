"""Versioned result sidecars without changing the frozen ScriptPlan contract.

The builder reads an actual persisted artifact through a trusted owner-supplied
projector. The integration caller verifies completed-run and artifact identity;
this low-level interface is never an untrusted projector submission API.
Renderers load these bytes at runtime and compare the loaded values to expected;
no fitted model is implied.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json
from .plan import ScriptPlan, ScriptStep

RESULT_SNAPSHOT_CONTRACT = "workbench.script_result_snapshot.v1"
MAX_RESULT_SNAPSHOT_BYTES = 16 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json")
_BINDING_FIELDS = {"project_id", "run_id", "lineage_hash", "step_id", "kind",
                   "operation", "parameters_sha256", "inputs", "models"}


def _text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ContractError(f"{field} must be a nonempty text identity")


def _sha(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ContractError(f"{field} must be a lowercase SHA-256")


def _exact(value: object, fields: set[str], field: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContractError(f"{field} must contain exactly its declared fields")
    return value


@dataclass(frozen=True)
class ResultSnapshotRef:
    filename: str
    sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.filename, str) or _FILENAME.fullmatch(self.filename) is None:
            raise ContractError("result snapshot filename must be a safe bare JSON filename")
        _sha(self.sha256, "result snapshot SHA")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("unsupported result snapshot schema version")


def _canonical(value: object) -> bytes:
    return json.dumps(thaw_json(freeze_json(value, "result_snapshot")), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def result_snapshot_binding(plan: ScriptPlan, step: ScriptStep) -> dict[str, Any]:
    if step.kind not in {"model", "postestimation"}:
        raise ContractError("result snapshots require a model or postestimation step")
    return {"project_id": plan.project_id, "run_id": plan.run_id,
        "lineage_hash": plan.lineage_hash, "step_id": step.step_id,
        "kind": step.kind, "operation": step.operation,
        "parameters_sha256": hashlib.sha256(_canonical(step.parameters)).hexdigest(),
        "inputs": list(step.inputs),
        "models": list(step.parameters.get("models", ())) if step.kind == "postestimation" else []}


def _validate_binding(value: object) -> Mapping:
    value = _exact(value, _BINDING_FIELDS, "binding")
    for key in _BINDING_FIELDS - {"inputs", "models"}:
        _text(value[key], f"binding.{key}")
    _sha(value["parameters_sha256"], "binding.parameters_sha256")
    if value["kind"] not in {"model", "postestimation"}:
        raise ContractError("unsupported result snapshot kind")
    prefix = "model." if value["kind"] == "model" else "postestimation."
    if not value["operation"].startswith(prefix):
        raise ContractError("result snapshot operation disagrees with its kind")
    for key in ("inputs", "models"):
        if not isinstance(value[key], (list, tuple)):
            raise ContractError(f"binding.{key} must be an ordered identity list")
        for item in value[key]:
            _text(item, f"binding.{key}")
    if value["kind"] == "model" and value["models"]:
        raise ContractError("model result snapshot cannot declare predecessor models")
    return value


def _number(value: object, field: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ContractError(f"{field} must be a finite number")


def validate_result_snapshot(payload: object, *, expected_binding: Mapping) -> Mapping:
    fields = {"contract", "schema_version", "binding", "source", "values"}
    if isinstance(payload, Mapping) and "documents" in payload:
        fields.add("documents")
    payload = _exact(payload, fields, "result snapshot")
    if "documents" in payload:
        documents = payload["documents"]
        if not isinstance(documents, Mapping) or not documents or len(documents) > 256:
            raise ContractError("documents must be a bounded nonempty role mapping")
        filenames = set()
        for role, document in documents.items():
            _text(role, "document role")
            document = _exact(document, {"artifact_id", "filename", "sha256"}, "document")
            _text(document["artifact_id"], "document artifact identity")
            ResultSnapshotRef(document["filename"], document["sha256"])
            if document["filename"] in filenames:
                raise ContractError("completed documents must have distinct filenames")
            filenames.add(document["filename"])
    if payload["contract"] != RESULT_SNAPSHOT_CONTRACT or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ContractError("unsupported result snapshot contract/version")
    binding = _validate_binding(payload["binding"])
    expected_binding = _validate_binding(expected_binding)
    if _canonical(binding) != _canonical(expected_binding):
        raise ContractError("result snapshot binding differs from the executed step")
    source = _exact(payload["source"], {"artifact_id", "artifact_sha256", "result_contract"}, "source")
    _text(source["artifact_id"], "source.artifact_id")
    _text(source["result_contract"], "source.result_contract")
    _sha(source["artifact_sha256"], "source.artifact_sha256")
    values = _exact(payload["values"], {"nobs", "coefficients", "std_errors", "statistics"}, "values")
    if values["nobs"] is not None and (type(values["nobs"]) is not int or not 0 <= values["nobs"] <= 2**53-1):
        raise ContractError("values.nobs must be an exactly representable nonnegative integer or null")
    for key in ("coefficients", "std_errors", "statistics"):
        if not isinstance(values[key], Mapping):
            raise ContractError(f"values.{key} must be an object")
        for name, value in values[key].items():
            _text(name, key)
            if key != "statistics":
                _number(value, f"values.{key}.{name}")
                if key == "std_errors" and value < 0:
                    raise ContractError("standard errors cannot be negative")
                continue
            entry = _exact(value, {"value", "df", "df_denominator", "p_value", "distribution"}, "statistic")
            for field in ("value", "df", "df_denominator", "p_value"):
                _number(entry[field], f"statistic.{field}", nullable=True)
            for field in ("df", "df_denominator"):
                if entry[field] is not None and entry[field] <= 0:
                    raise ContractError("statistic degrees of freedom must be positive")
            if entry["p_value"] is not None and not 0 <= entry["p_value"] <= 1:
                raise ContractError("statistic p-value must be between zero and one")
            if entry["distribution"] is not None:
                _text(entry["distribution"], "statistic.distribution")
    return freeze_json(values, "result_snapshot.values")


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("duplicate JSON object key in result snapshot")
            result[key] = value
        return result

    def constant(value):
        raise ContractError("nonfinite JSON constant in result snapshot")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContractError(f"invalid result snapshot JSON: {exc}") from exc


def _read_bytes(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_RESULT_SNAPSHOT_BYTES:
                raise ContractError("result snapshot must be a bounded regular file")
            raw = handle.read(MAX_RESULT_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_RESULT_SNAPSHOT_BYTES:
                raise ContractError("result snapshot exceeds its size limit")
            return raw
    except OSError as exc:
        raise ContractError("result snapshot cannot be read as a local regular file") from exc


def read_result_snapshot(directory: Path, ref: ResultSnapshotRef, *, expected_binding: Mapping) -> Mapping:
    if not isinstance(ref, ResultSnapshotRef):
        raise ContractError("result snapshot reference must be a declared ResultSnapshotRef")
    raw = _read_bytes(Path(directory) / ref.filename)
    if hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ContractError("result snapshot SHA-256 differs")
    payload = _strict_json(raw)
    values = validate_result_snapshot(payload, expected_binding=expected_binding)
    for document in payload.get("documents", {}).values():
        document_raw = _read_bytes(Path(directory) / document["filename"])
        if hashlib.sha256(document_raw).hexdigest() != document["sha256"]:
            raise ContractError("completed result document SHA-256 differs")
    return values


def build_result_snapshot(artifact_path: Path, *, binding: Mapping, artifact_id: str,
                          result_contract: str, projector: Callable[[Mapping], Mapping]) -> bytes:
    raw = _read_bytes(Path(artifact_path))
    artifact = _strict_json(raw)
    if not isinstance(artifact, Mapping):
        raise ContractError("persisted result artifact must be an object")
    payload = {"contract": RESULT_SNAPSHOT_CONTRACT, "schema_version": 1,
        "binding": binding, "source": {"artifact_id": artifact_id,
            "artifact_sha256": hashlib.sha256(raw).hexdigest(), "result_contract": result_contract},
        "values": projector(artifact)}
    validate_result_snapshot(payload, expected_binding=binding)
    return _canonical(payload)
