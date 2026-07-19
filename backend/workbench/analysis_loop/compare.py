"""Deterministic result comparison and primary-target classification."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import numeric_equal, sha256_canonical
from .contracts import ComparisonTarget, _freeze, _thaw
from .validation import ValidationPacket

COMPARISON_ALPHA = 0.05
COMPARISON_CONFIDENCE_LEVEL = 0.95
ESTIMATE_ATOL = 1e-10
ESTIMATE_RTOL = 1e-8
CI_WIDTH_ATOL = 1e-12
CI_WIDTH_RTOL = 1e-8


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def _target_record(value: Mapping[str, Any], target_result_id: str | None) -> Mapping[str, Any] | None:
    coefficients = value.get("coefficients")
    if isinstance(coefficients, Mapping):
        result_id = target_result_id or value.get("primary_target_id")
        if result_id is None and len(coefficients) == 1:
            result_id = next(iter(coefficients))
        if type(result_id) is not str:
            return None
        candidate = coefficients.get(result_id)
        return candidate if isinstance(candidate, Mapping) else None
    result_id = value.get("result_id")
    if target_result_id is not None and result_id != target_result_id:
        return None
    return value if isinstance(result_id, str) else None


def _confidence_level(record: Mapping[str, Any]) -> float | None:
    value = record.get("confidence_level", COMPARISON_CONFIDENCE_LEVEL)
    return float(value) if _finite(value) else None


def _ci_width(record: Mapping[str, Any]) -> float | None:
    interval = record.get("confidence_interval")
    if isinstance(interval, (list, tuple)) and len(interval) == 2:
        lower, upper = interval
    else:
        lower, upper = record.get("ci_lower"), record.get("ci_upper")
    if not (_finite(lower) and _finite(upper)):
        return None
    width = float(upper) - float(lower)
    return width if math.isfinite(width) and width >= 0 else None


def _significant(p_value: float) -> bool:
    return math.isfinite(p_value) and p_value < COMPARISON_ALPHA


@dataclass(frozen=True)
class ConclusionClassification:
    """One target-level semantic label separated from integrity findings."""

    target_result_id: str
    status: str
    classification: str | None
    reason_code: str | None = None
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if type(self.target_result_id) is not str or not self.target_result_id:
            raise ValueError("target_result_id must be a non-empty string")
        if self.status not in {"complete", "blocked"}:
            raise ValueError("status must be complete or blocked")
        allowed = {
            None,
            "NO_MATERIAL_CHANGE",
            "UNCERTAINTY_INCREASED",
            "UNCERTAINTY_DECREASED",
            "SIGNIFICANCE_LOST",
            "SIGNIFICANCE_GAINED",
        }
        if self.classification not in allowed:
            raise ValueError("unsupported conclusion classification")
        if self.status == "complete" and self.classification is None:
            raise ValueError("complete classification must have a semantic label")
        if self.status == "blocked" and not self.reason_code:
            raise ValueError("blocked classification must have a reason_code")
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise ValueError("reason_code must be a non-empty string")
        object.__setattr__(self, "evidence", _freeze(self.evidence or {}, "evidence"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_result_id": self.target_result_id,
            "status": self.status,
            "classification": self.classification,
            "reason_code": self.reason_code,
            "evidence": _thaw(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConclusionClassification":
        if not isinstance(value, Mapping):
            raise TypeError("classification must be a mapping")
        return cls(
            target_result_id=value["target_result_id"],
            status=value["status"],
            classification=value.get("classification"),
            reason_code=value.get("reason_code"),
            evidence=value.get("evidence", {}),
        )


def classify_primary_target(
    source: Mapping[str, Any],
    child: Mapping[str, Any],
    *,
    target_result_id: str | None = None,
    alpha: float = COMPARISON_ALPHA,
    confidence_level: float = COMPARISON_CONFIDENCE_LEVEL,
    estimate_atol: float = ESTIMATE_ATOL,
    estimate_rtol: float = ESTIMATE_RTOL,
    ci_width_atol: float = CI_WIDTH_ATOL,
    ci_width_rtol: float = CI_WIDTH_RTOL,
) -> ConclusionClassification:
    """Classify one exact target without label or ordering inference."""

    if not isinstance(source, Mapping) or not isinstance(child, Mapping):
        raise TypeError("source and child result records must be mappings")
    source_record = _target_record(source, target_result_id)
    child_record = _target_record(child, target_result_id)
    if source_record is None or child_record is None:
        return ConclusionClassification(
            target_result_id=target_result_id or "<unknown>",
            status="blocked",
            classification=None,
            reason_code="PRIMARY_TARGET_MISSING",
        )

    source_confidence = _confidence_level(source_record)
    child_confidence = _confidence_level(child_record)
    if (
        source_confidence is None
        or child_confidence is None
        or not math.isclose(source_confidence, confidence_level, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(child_confidence, confidence_level, rel_tol=0.0, abs_tol=1e-12)
    ):
        return ConclusionClassification(
            target_result_id=target_result_id or "<unknown>",
            status="blocked",
            classification=None,
            reason_code="CONFIDENCE_LEVEL_MISMATCH",
            evidence={
                "source_confidence_level": source_confidence,
                "child_confidence_level": child_confidence,
                "expected_confidence_level": confidence_level,
            },
        )

    source_estimate = source_record.get("estimate")
    child_estimate = child_record.get("estimate")
    source_p = source_record.get("p_value")
    child_p = child_record.get("p_value")
    source_width = _ci_width(source_record)
    child_width = _ci_width(child_record)
    if not (
        _finite(source_estimate)
        and _finite(child_estimate)
        and _finite(source_p)
        and _finite(child_p)
        and source_width is not None
        and child_width is not None
    ):
        return ConclusionClassification(
            target_result_id=target_result_id or "<unknown>",
            status="blocked",
            classification=None,
            reason_code="TARGET_EVIDENCE_UNKNOWN",
        )

    if not numeric_equal(
        float(source_estimate),
        float(child_estimate),
        atol=estimate_atol,
        rtol=estimate_rtol,
    ):
        return ConclusionClassification(
            target_result_id=target_result_id or "<unknown>",
            status="blocked",
            classification=None,
            reason_code="EFFECT_ESTIMATE_MATERIALLY_CHANGED",
            evidence={"source_estimate": source_estimate, "child_estimate": child_estimate},
        )

    source_significant = float(source_p) < alpha and math.isfinite(float(source_p))
    child_significant = float(child_p) < alpha and math.isfinite(float(child_p))
    if source_significant and not child_significant:
        classification = "SIGNIFICANCE_LOST"
    elif not source_significant and child_significant:
        classification = "SIGNIFICANCE_GAINED"
    elif not numeric_equal(
        source_width,
        child_width,
        atol=ci_width_atol,
        rtol=ci_width_rtol,
    ):
        classification = (
            "UNCERTAINTY_INCREASED"
            if child_width > source_width
            else "UNCERTAINTY_DECREASED"
        )
    else:
        classification = "NO_MATERIAL_CHANGE"
    return ConclusionClassification(
        target_result_id=target_result_id or str(source_record.get("result_id")),
        status="complete",
        classification=classification,
        evidence={
            "source_estimate": source_estimate,
            "child_estimate": child_estimate,
            "source_p_value": source_p,
            "child_p_value": child_p,
            "source_ci_width": source_width,
            "child_ci_width": child_width,
            "alpha": alpha,
            "confidence_level": confidence_level,
        },
    )


COMPARE_PACKET_SCHEMA_VERSION = "compare_packet_v1"
COMPARE_STRATEGY_VERSION = "ols_clustered_v1"
_COMPARE_STATUSES = frozenset(
    {"complete", "partial", "not_comparable", "blocked_by_integrity", "restricted"}
)


def compare_logical_key(
    *,
    source_run_id: str,
    child_run_id: str,
    validation_logical_key: str,
    target_hash: str,
    strategy_version: str = COMPARE_STRATEGY_VERSION,
    schema_version: str = COMPARE_PACKET_SCHEMA_VERSION,
) -> str:
    return "compare:" + sha256_canonical(
        {
            "source_run_id": source_run_id,
            "child_run_id": child_run_id,
            "validation_logical_key": validation_logical_key,
            "target_hash": target_hash,
            "strategy_version": strategy_version,
            "schema_version": schema_version,
        }
    )


@dataclass(frozen=True)
class ComparePacket:
    """Immutable four-layer comparison evidence."""

    compare_status: str
    source_run_id: str
    child_run_id: str
    target: Mapping[str, Any]
    data_diff: Mapping[str, Any]
    parameter_diff: Mapping[str, Any]
    result_diff: Mapping[str, Any]
    conclusion_diff: Mapping[str, Any]
    validation_status: str
    integrity_findings: tuple[str, ...]
    logical_key: str
    strategy_version: str
    schema_version: str
    reason_code: str | None = None
    user_safe_message: str | None = None

    def __post_init__(self) -> None:
        if self.compare_status not in _COMPARE_STATUSES:
            raise ValueError("unsupported compare_status")
        for field in (
            "source_run_id",
            "child_run_id",
            "validation_status",
            "logical_key",
            "strategy_version",
            "schema_version",
        ):
            if type(getattr(self, field)) is not str or not getattr(self, field):
                raise ValueError(f"{field} must be a non-empty string")
        if any(type(item) is not str or not item for item in self.integrity_findings):
            raise TypeError("integrity_findings must contain strings")
        if self.compare_status == "restricted":
            if type(self.reason_code) is not str or not self.reason_code:
                raise ValueError("restricted compare packet requires a non-empty reason_code")
            if type(self.user_safe_message) is not str or not self.user_safe_message:
                raise ValueError(
                    "restricted compare packet requires a non-empty user_safe_message"
                )
        else:
            for field in ("reason_code", "user_safe_message"):
                value = getattr(self, field)
                if value is not None and (type(value) is not str or not value):
                    raise ValueError(f"{field} must be a non-empty string when provided")
        object.__setattr__(self, "integrity_findings", tuple(self.integrity_findings))
        for field in ("target", "data_diff", "parameter_diff", "result_diff", "conclusion_diff"):
            object.__setattr__(self, field, _freeze(getattr(self, field), field))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "compare_status": self.compare_status,
            "source_run_id": self.source_run_id,
            "child_run_id": self.child_run_id,
            "target": _thaw(self.target),
            "data_diff": _thaw(self.data_diff),
            "parameter_diff": _thaw(self.parameter_diff),
            "result_diff": _thaw(self.result_diff),
            "conclusion_diff": _thaw(self.conclusion_diff),
            "validation_status": self.validation_status,
            "integrity_findings": list(self.integrity_findings),
            "logical_key": self.logical_key,
            "strategy_version": self.strategy_version,
            "schema_version": self.schema_version,
        }
        # Omit absent optional fields so every existing OLS packet remains
        # byte-for-byte wire-compatible.
        if self.reason_code is not None:
            payload["reason_code"] = self.reason_code
        if self.user_safe_message is not None:
            payload["user_safe_message"] = self.user_safe_message
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComparePacket":
        if not isinstance(value, Mapping):
            raise TypeError("compare packet must be a mapping")
        required = {
            "compare_status",
            "source_run_id",
            "child_run_id",
            "target",
            "data_diff",
            "parameter_diff",
            "result_diff",
            "conclusion_diff",
            "validation_status",
            "integrity_findings",
            "logical_key",
            "strategy_version",
            "schema_version",
        }
        optional = {"reason_code", "user_safe_message"}
        extra = set(value) - required - optional
        missing = required - set(value)
        if extra:
            raise ValueError("extra compare packet field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing compare packet field(s): " + ", ".join(sorted(missing)))
        return cls(
            **{key: value[key] for key in required},
            reason_code=value.get("reason_code"),
            user_safe_message=value.get("user_safe_message"),
        )


def _run_id(run: Mapping[str, Any]) -> str:
    value = run.get("run_id")
    if type(value) is not str or not value:
        raise ValueError("run_id must be a non-empty string")
    return value


def _result_map(run: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values: Any = run.get("results")
    if values is None and isinstance(run.get("result_artifact"), Mapping):
        artifact = run["result_artifact"]
        values = artifact.get("coefficients") or artifact.get("results")
    if not isinstance(values, Mapping):
        return {}
    if isinstance(values.get("result_id"), str):
        return {values["result_id"]: values}
    result: dict[str, Mapping[str, Any]] = {}
    for key, item in values.items():
        if not isinstance(item, Mapping):
            continue
        stable_id = item.get("result_id")
        if type(stable_id) is str and stable_id:
            result[stable_id] = item
        elif type(key) is str:
            result[key] = item
    return result


def _run_field(run: Mapping[str, Any], name: str) -> Any:
    if name in run:
        return run[name]
    fingerprints = run.get("fingerprints")
    if name == "fingerprints" and isinstance(fingerprints, Mapping):
        return fingerprints
    return {}


def _layer_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        left = before.get(key)
        right = after.get(key)
        fields[key] = {"before": left, "after": right, "changed": left != right}
    return {"changed": any(item["changed"] for item in fields.values()), "fields": fields}


def _result_entry_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in ("estimate", "std_error", "p_value", "confidence_interval", "ci_lower", "ci_upper"):
        if key not in before and key not in after:
            continue
        left = before.get(key)
        right = after.get(key)
        changed = left != right
        if _finite(left) and _finite(right):
            changed = not numeric_equal(float(left), float(right), atol=ESTIMATE_ATOL, rtol=ESTIMATE_RTOL)
        fields[key] = {"before": left, "after": right, "changed": changed}
    return {
        "status": "complete",
        "changed": any(item["changed"] for item in fields.values()),
        "fields": fields,
    }


def build_compare_packet(
    *,
    source: Mapping[str, Any],
    child: Mapping[str, Any],
    validation: ValidationPacket,
    target: ComparisonTarget | Mapping[str, Any] | str,
    strategy_version: str = COMPARE_STRATEGY_VERSION,
    schema_version: str = COMPARE_PACKET_SCHEMA_VERSION,
) -> ComparePacket:
    """Build a four-layer comparison from already structured backend evidence."""

    if not isinstance(source, Mapping) or not isinstance(child, Mapping):
        raise TypeError("source and child must be mappings")
    if not isinstance(validation, ValidationPacket):
        raise TypeError("validation must be a ValidationPacket")
    source_run_id = _run_id(source)
    child_run_id = _run_id(child)
    if isinstance(target, str):
        target_obj = ComparisonTarget(
            result_id=target,
            role="primary",
            resolution_source="explicit_result_id",
        )
    elif isinstance(target, ComparisonTarget):
        target_obj = target
    else:
        target_obj = ComparisonTarget.from_dict(target)

    findings: list[str] = []
    if validation.status != "complete":
        findings.append("VALIDATION_NOT_COMPLETE")
    if validation.overall_status in {"failed", "unknown"}:
        findings.append("VALIDATION_NOT_PASS")
    if validation.source_run_id != source_run_id or validation.child_run_id != child_run_id:
        findings.append("VALIDATION_LINEAGE_MISMATCH")
    if child.get("source_run_id") != source_run_id:
        findings.append("SOURCE_CHILD_LINEAGE_MISMATCH")
    source_results = _result_map(source)
    child_results = _result_map(child)
    target_present = target_obj.result_id in source_results and target_obj.result_id in child_results
    if not target_present:
        findings.append("PRIMARY_TARGET_MISSING")

    source_fingerprints = source.get("fingerprints")
    child_fingerprints = child.get("fingerprints")
    source_fingerprints = source_fingerprints if isinstance(source_fingerprints, Mapping) else {}
    child_fingerprints = child_fingerprints if isinstance(child_fingerprints, Mapping) else {}
    fingerprint_reason_codes = {
        "dataset_snapshot": "DATASET_SNAPSHOT_FINGERPRINT_MISMATCH",
        "analysis_sample": "ANALYSIS_SAMPLE_FINGERPRINT_MISMATCH",
        "point_estimation": "POINT_ESTIMATION_FINGERPRINT_MISMATCH",
        "coefficient_schema": "COEFFICIENT_SCHEMA_FINGERPRINT_MISMATCH",
    }
    for fingerprint_name, reason_code in fingerprint_reason_codes.items():
        if source_fingerprints.get(fingerprint_name) != child_fingerprints.get(fingerprint_name):
            findings.append(reason_code)
    data_fields = {
        key: {
            "before": source_fingerprints.get(key),
            "after": child_fingerprints.get(key),
            "changed": source_fingerprints.get(key) != child_fingerprints.get(key),
        }
        for key in ("dataset_snapshot", "analysis_sample")
    }
    data_diff = {
        "changed": any(item["changed"] for item in data_fields.values()),
        **data_fields,
    }
    parameter_diff = _layer_diff(
        source.get("inference_config") if isinstance(source.get("inference_config"), Mapping) else {},
        child.get("inference_config") if isinstance(child.get("inference_config"), Mapping) else {},
    )
    result_diff: dict[str, Any] = {}
    for result_id in sorted(set(source_results) | set(child_results)):
        if result_id not in source_results:
            result_diff[result_id] = {"status": "missing_in_source"}
        elif result_id not in child_results:
            result_diff[result_id] = {"status": "missing_in_child"}
        else:
            result_diff[result_id] = _result_entry_diff(source_results[result_id], child_results[result_id])

    if findings:
        conclusion_diff = {
            "status": "blocked",
            "classification": None,
            "reason_code": findings[0],
        }
    else:
        classification = classify_primary_target(
            source_results[target_obj.result_id],
            child_results[target_obj.result_id],
            target_result_id=target_obj.result_id,
        )
        conclusion_diff = classification.to_dict()
        if classification.status == "blocked":
            findings.append(classification.reason_code or "CONCLUSION_UNKNOWN")

    if findings:
        compare_status = "not_comparable" if "PRIMARY_TARGET_MISSING" in findings else "blocked_by_integrity"
    else:
        missing_secondary = any(item.get("status") == "missing_in_child" for item in result_diff.values())
        compare_status = "partial" if missing_secondary else "complete"
    return ComparePacket(
        compare_status=compare_status,
        source_run_id=source_run_id,
        child_run_id=child_run_id,
        target=target_obj.to_dict(),
        data_diff=data_diff,
        parameter_diff={"inference_config": parameter_diff},
        result_diff=result_diff,
        conclusion_diff=conclusion_diff,
        validation_status=validation.status,
        integrity_findings=tuple(dict.fromkeys(findings)),
        logical_key=compare_logical_key(
            source_run_id=source_run_id,
            child_run_id=child_run_id,
            validation_logical_key=validation.logical_key,
            target_hash=target_obj.target_hash,
            strategy_version=strategy_version,
            schema_version=schema_version,
        ),
        strategy_version=strategy_version,
        schema_version=schema_version,
    )


__all__ = [
    "CI_WIDTH_ATOL",
    "CI_WIDTH_RTOL",
    "COMPARISON_ALPHA",
    "COMPARISON_CONFIDENCE_LEVEL",
    "ConclusionClassification",
    "COMPARE_PACKET_SCHEMA_VERSION",
    "COMPARE_STRATEGY_VERSION",
    "ComparePacket",
    "ESTIMATE_ATOL",
    "ESTIMATE_RTOL",
    "classify_primary_target",
    "build_compare_packet",
    "compare_logical_key",
]
