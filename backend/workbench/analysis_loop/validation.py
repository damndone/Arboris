"""Deterministic validation packets for the Agent Analysis Loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .canonical import sha256_canonical
from .contracts import SourceRunContract, _freeze, _thaw

if TYPE_CHECKING:
    from .storage import ValidationPacketStore

VALIDATION_PACKET_SCHEMA_VERSION = "validation_packet_v1"
VALIDATION_POLICY_VERSION = "validation_policy_v1"
_PACKET_STATUSES = frozenset({"pending", "complete", "blocked", "failed"})
_CHECK_STATUSES = frozenset({"pass", "warning", "fail", "unknown", "not_applicable"})


def _string(value: Any, field: str, *, non_empty: bool = True) -> str:
    if type(value) is not str or (non_empty and not value):
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field} mapping keys must be strings")
    return value


def _check_status(value: Any, field: str = "status") -> str:
    if type(value) is not str or value not in _CHECK_STATUSES:
        raise ValueError(f"{field} must be one of {sorted(_CHECK_STATUSES)}")
    return value


@dataclass(frozen=True)
class ValidationCheck:
    """One deterministic validation observation."""

    check_id: str
    status: str
    severity: str
    expected: Any
    observed: Any
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _string(self.check_id, "check_id")
        _check_status(self.status)
        _string(self.severity, "severity")
        if not isinstance(self.evidence_refs, (tuple, list)):
            raise TypeError("evidence_refs must be a tuple or list")
        if any(type(item) is not str for item in self.evidence_refs):
            raise TypeError("evidence_refs must contain strings")
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if self.reason_code is not None:
            _string(self.reason_code, "reason_code")
        object.__setattr__(self, "expected", _freeze(self.expected, "expected"))
        object.__setattr__(self, "observed", _freeze(self.observed, "observed"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "severity": self.severity,
            "expected": _thaw(self.expected),
            "observed": _thaw(self.observed),
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationCheck":
        value = _mapping(value, "validation check")
        required = {
            "check_id",
            "status",
            "severity",
            "expected",
            "observed",
            "evidence_refs",
            "reason_code",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra validation check field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing validation check field(s): " + ", ".join(sorted(missing)))
        return cls(**{key: value[key] for key in required})


@dataclass(frozen=True)
class ValidationPacket:
    """Immutable, replayable validation evidence for one child run."""

    status: str
    overall_status: str
    terminal: bool
    checks: tuple[ValidationCheck, ...]
    logical_key: str
    child_run_id: str
    source_run_id: str
    plan_hash: str
    executed_payload_hash: str
    artifact_manifest_hash: str
    validation_policy_version: str
    schema_version: str
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in _PACKET_STATUSES:
            raise ValueError(f"status must be one of {sorted(_PACKET_STATUSES)}")
        _string(self.overall_status, "overall_status")
        if type(self.terminal) is not bool:
            raise TypeError("terminal must be a bool")
        if self.terminal is not (self.status != "pending"):
            raise ValueError("terminal must match packet status")
        if not isinstance(self.checks, (tuple, list)):
            raise TypeError("checks must be a tuple or list")
        if any(not isinstance(check, ValidationCheck) for check in self.checks):
            raise TypeError("checks must contain ValidationCheck values")
        object.__setattr__(self, "checks", tuple(self.checks))
        for field in (
            "logical_key",
            "child_run_id",
            "source_run_id",
            "plan_hash",
            "executed_payload_hash",
            "artifact_manifest_hash",
            "validation_policy_version",
            "schema_version",
        ):
            _string(getattr(self, field), field)
        if self.evidence is None:
            object.__setattr__(self, "evidence", {})
        else:
            object.__setattr__(self, "evidence", _freeze(self.evidence, "evidence"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "overall_status": self.overall_status,
            "terminal": self.terminal,
            "checks": [check.to_dict() for check in self.checks],
            "logical_key": self.logical_key,
            "child_run_id": self.child_run_id,
            "source_run_id": self.source_run_id,
            "plan_hash": self.plan_hash,
            "executed_payload_hash": self.executed_payload_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "validation_policy_version": self.validation_policy_version,
            "schema_version": self.schema_version,
            "evidence": _thaw(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationPacket":
        value = _mapping(value, "validation packet")
        required = {
            "status",
            "overall_status",
            "terminal",
            "checks",
            "logical_key",
            "child_run_id",
            "source_run_id",
            "plan_hash",
            "executed_payload_hash",
            "artifact_manifest_hash",
            "validation_policy_version",
            "schema_version",
            "evidence",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra validation packet field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing validation packet field(s): " + ", ".join(sorted(missing)))
        checks = value["checks"]
        if not isinstance(checks, (list, tuple)):
            raise TypeError("checks must be a list or tuple")
        return cls(
            status=value["status"],
            overall_status=value["overall_status"],
            terminal=value["terminal"],
            checks=tuple(ValidationCheck.from_dict(item) for item in checks),
            logical_key=value["logical_key"],
            child_run_id=value["child_run_id"],
            source_run_id=value["source_run_id"],
            plan_hash=value["plan_hash"],
            executed_payload_hash=value["executed_payload_hash"],
            artifact_manifest_hash=value["artifact_manifest_hash"],
            validation_policy_version=value["validation_policy_version"],
            schema_version=value["schema_version"],
            evidence=value["evidence"],
        )


def validation_packet_logical_key(
    *,
    child_run_id: str,
    executed_payload_hash: str,
    artifact_manifest_hash: str,
    validation_policy_version: str = VALIDATION_POLICY_VERSION,
    schema_version: str = VALIDATION_PACKET_SCHEMA_VERSION,
) -> str:
    fields = {
        "child_run_id": _string(child_run_id, "child_run_id"),
        "executed_payload_hash": _string(executed_payload_hash, "executed_payload_hash"),
        "artifact_manifest_hash": _string(artifact_manifest_hash, "artifact_manifest_hash"),
        "validation_policy_version": _string(validation_policy_version, "validation_policy_version"),
        "schema_version": _string(schema_version, "schema_version"),
    }
    return "validation:" + sha256_canonical(fields)


def _check(
    check_id: str,
    status: str,
    *,
    expected: Any,
    observed: Any,
    reason_code: str | None = None,
    evidence_refs: Sequence[str] = (),
) -> ValidationCheck:
    severity = {
        "pass": "info",
        "warning": "warning",
        "fail": "error",
        "unknown": "warning",
        "not_applicable": "info",
    }[status]
    return ValidationCheck(
        check_id=check_id,
        status=status,
        severity=severity,
        expected=expected,
        observed=observed,
        evidence_refs=tuple(evidence_refs),
        reason_code=reason_code,
    )


def _equal_check(
    check_id: str,
    expected: Any,
    observed: Any,
    *,
    reason_code: str,
) -> ValidationCheck:
    equal = expected == observed
    return _check(
        check_id,
        "pass" if equal else "fail",
        expected=expected,
        observed=observed,
        reason_code=None if equal else reason_code,
    )


def _value_check(
    check_id: str,
    value: Any,
    *,
    expected: Any = "pass",
    fail_reason: str,
    unknown_reason: str,
) -> ValidationCheck:
    if value in {"pass", True, "complete", "committed"}:
        return _check(check_id, "pass", expected=expected, observed=value)
    if value in {"warning", "warn"}:
        return _check(check_id, "warning", expected=expected, observed=value)
    if value in {"fail", False, "failed"}:
        return _check(check_id, "fail", expected=expected, observed=value, reason_code=fail_reason)
    return _check(check_id, "unknown", expected=expected, observed=value, reason_code=unknown_reason)


def build_validation_packet(
    *,
    source: SourceRunContract,
    child: Mapping[str, Any],
    plan_diff: Any,
    execution_evidence: Mapping[str, Any],
    model_evidence: Mapping[str, Any],
    artifact_evidence: Mapping[str, Any],
    comparison_evidence: Mapping[str, Any],
    validation_policy_version: str = VALIDATION_POLICY_VERSION,
    schema_version: str = VALIDATION_PACKET_SCHEMA_VERSION,
) -> ValidationPacket:
    """Build deterministic validation evidence without mutating lifecycle state."""

    if not isinstance(source, SourceRunContract):
        raise TypeError("source must be a SourceRunContract")
    child = _mapping(child, "child")
    execution = _mapping(execution_evidence, "execution_evidence")
    model = _mapping(model_evidence, "model_evidence")
    artifacts = _mapping(artifact_evidence, "artifact_evidence")
    comparison = _mapping(comparison_evidence, "comparison_evidence")
    child_run_id = _string(child.get("run_id"), "child.run_id")
    source_run_id = source.run_id
    plan_hash = _string(getattr(plan_diff, "plan_hash", None), "plan_hash")
    executed_payload_hash = _string(
        execution.get("executed_payload_hash"), "executed_payload_hash"
    )
    artifact_manifest_hash = _string(
        artifacts.get("manifest_hash"), "artifact_manifest_hash"
    )

    checks: list[ValidationCheck] = []
    checks.append(
        _equal_check(
            "execution.confirmed_payload_hash",
            execution.get("confirmed_payload_hash"),
            execution.get("executed_payload_hash"),
            reason_code="CONFIRMED_EXECUTED_PAYLOAD_HASH_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "execution.plan_hash",
            plan_hash,
            execution.get("executed_plan_hash"),
            reason_code="EXECUTED_PLAN_HASH_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "execution.canonical_patch_hash",
            getattr(plan_diff, "canonical_patch_hash", None),
            execution.get("executed_canonical_patch_hash"),
            reason_code="EXECUTED_CANONICAL_PATCH_HASH_MISMATCH",
        )
    )
    checks.append(
        _value_check(
            "execution.effect_committed",
            execution.get("effect_status"),
            expected="committed",
            fail_reason="EFFECT_NOT_COMMITTED",
            unknown_reason="EFFECT_STATUS_UNKNOWN",
        )
    )
    projection_status = execution.get("projection_status")
    projection_check = _value_check(
        "execution.projection_complete",
        projection_status,
        expected="complete",
        fail_reason="PROJECTION_INCOMPLETE",
        unknown_reason="PROJECTION_STATUS_UNKNOWN",
    )
    if projection_status == "pending":
        projection_check = _check(
            "execution.projection_complete",
            "unknown",
            expected="complete",
            observed=projection_status,
            reason_code="PROJECTION_PENDING",
        )
    checks.append(projection_check)
    checks.append(
        _value_check(
            "execution.child_terminal",
            execution.get("child_terminal"),
            expected=True,
            fail_reason="CHILD_NOT_TERMINAL",
            unknown_reason="CHILD_TERMINAL_STATE_UNKNOWN",
        )
    )
    checks.append(
        _value_check(
            "artifact.complete",
            artifacts.get("complete"),
            expected=True,
            fail_reason="ARTIFACT_INCOMPLETE",
            unknown_reason="ARTIFACT_COMPLETENESS_UNKNOWN",
        )
    )
    checks.append(
        _value_check(
            "artifact.terminal_state",
            artifacts.get("terminal_state"),
            expected="complete",
            fail_reason="ARTIFACT_TERMINAL_STATE_INVALID",
            unknown_reason="ARTIFACT_TERMINAL_STATE_UNKNOWN",
        )
    )
    checks.append(
        _equal_check(
            "execution.lineage",
            {"source_run_id": source_run_id},
            {"source_run_id": child.get("source_run_id")},
            reason_code="SOURCE_CHILD_LINEAGE_MISMATCH",
        )
    )

    for name in ("fit", "convergence", "singular", "collinearity", "standard_errors", "nobs"):
        value = model.get(name)
        reason = "MODEL_FIT_FAILED" if name == "fit" else f"MODEL_{name.upper()}_FAILED"
        checks.append(
            _value_check(
                f"model.{name}",
                value,
                fail_reason=reason,
                unknown_reason=f"MODEL_{name.upper()}_UNKNOWN",
            )
        )

    checks.append(
        _equal_check(
            "comparison.analysis_sample_fingerprint",
            comparison.get("source_fingerprints", {}).get("analysis_sample"),
            comparison.get("child_fingerprints", {}).get("analysis_sample"),
            reason_code="ANALYSIS_SAMPLE_FINGERPRINT_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "comparison.dataset_snapshot_fingerprint",
            comparison.get("source_fingerprints", {}).get("dataset_snapshot"),
            comparison.get("child_fingerprints", {}).get("dataset_snapshot"),
            reason_code="DATASET_SNAPSHOT_FINGERPRINT_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "comparison.point_estimation_fingerprint",
            comparison.get("source_fingerprints", {}).get("point_estimation"),
            comparison.get("child_fingerprints", {}).get("point_estimation"),
            reason_code="POINT_ESTIMATION_FINGERPRINT_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "comparison.coefficient_schema_fingerprint",
            comparison.get("source_fingerprints", {}).get("coefficient_schema"),
            comparison.get("child_fingerprints", {}).get("coefficient_schema"),
            reason_code="COEFFICIENT_SCHEMA_FINGERPRINT_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "comparison.primary_target",
            comparison.get("primary_target_id"),
            getattr(getattr(plan_diff, "target_identity", {}), "get", lambda _key: None)("result_id"),
            reason_code="PRIMARY_TARGET_MISMATCH",
        )
    )
    checks.append(
        _equal_check(
            "comparison.inference_config",
            comparison.get("expected_inference_config"),
            comparison.get("observed_inference_config"),
            reason_code="INFERENCE_CONFIG_MISMATCH",
        )
    )

    blocked_reasons = {
        "CONFIRMED_EXECUTED_PAYLOAD_HASH_MISMATCH",
        "EXECUTED_PLAN_HASH_MISMATCH",
        "EXECUTED_CANONICAL_PATCH_HASH_MISMATCH",
        "SOURCE_CHILD_LINEAGE_MISMATCH",
    }
    blocking_failure = any(check.reason_code in blocked_reasons for check in checks)
    pending = projection_status == "pending" or execution.get("child_terminal") is False
    if blocking_failure:
        status = "blocked"
    elif pending:
        status = "pending"
    else:
        status = "complete"
    if any(check.status == "fail" for check in checks):
        overall_status = "failed"
    elif any(check.status == "unknown" for check in checks):
        overall_status = "unknown"
    elif any(check.status == "warning" for check in checks):
        overall_status = "warning"
    else:
        overall_status = "passed"
    return ValidationPacket(
        status=status,
        overall_status=overall_status,
        terminal=status != "pending",
        checks=tuple(checks),
        logical_key=validation_packet_logical_key(
            child_run_id=child_run_id,
            executed_payload_hash=executed_payload_hash,
            artifact_manifest_hash=artifact_manifest_hash,
            validation_policy_version=validation_policy_version,
            schema_version=schema_version,
        ),
        child_run_id=child_run_id,
        source_run_id=source_run_id,
        plan_hash=plan_hash,
        executed_payload_hash=executed_payload_hash,
        artifact_manifest_hash=artifact_manifest_hash,
        validation_policy_version=_string(validation_policy_version, "validation_policy_version"),
        schema_version=_string(schema_version, "schema_version"),
        evidence={
            "execution": dict(execution),
            "model": dict(model),
            "artifacts": dict(artifacts),
            "comparison": dict(comparison),
        },
    )


def build_and_store_validation_packet(
    *,
    store: "ValidationPacketStore",
    source: SourceRunContract,
    child: Mapping[str, Any],
    plan_diff: Any,
    execution_evidence: Mapping[str, Any],
    model_evidence: Mapping[str, Any],
    artifact_evidence: Mapping[str, Any],
    comparison_evidence: Mapping[str, Any],
    validation_policy_version: str = VALIDATION_POLICY_VERSION,
    schema_version: str = VALIDATION_PACKET_SCHEMA_VERSION,
) -> ValidationPacket:
    """Build one terminal observation through the immutable packet store."""

    child = _mapping(child, "child")
    execution = _mapping(execution_evidence, "execution_evidence")
    artifacts = _mapping(artifact_evidence, "artifact_evidence")
    logical_key = validation_packet_logical_key(
        child_run_id=_string(child.get("run_id"), "child.run_id"),
        executed_payload_hash=_string(
            execution.get("executed_payload_hash"), "executed_payload_hash"
        ),
        artifact_manifest_hash=_string(
            artifacts.get("manifest_hash"), "artifact_manifest_hash"
        ),
        validation_policy_version=validation_policy_version,
        schema_version=schema_version,
    )
    return store.build_packet(
        logical_key=logical_key,
        builder=lambda: build_validation_packet(
            source=source,
            child=child,
            plan_diff=plan_diff,
            execution_evidence=execution,
            model_evidence=model_evidence,
            artifact_evidence=artifacts,
            comparison_evidence=comparison_evidence,
            validation_policy_version=validation_policy_version,
            schema_version=schema_version,
        ),
    )


__all__ = [
    "VALIDATION_PACKET_SCHEMA_VERSION",
    "VALIDATION_POLICY_VERSION",
    "ValidationCheck",
    "ValidationPacket",
    "build_and_store_validation_packet",
    "build_validation_packet",
    "validation_packet_logical_key",
]
