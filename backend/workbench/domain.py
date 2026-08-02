from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


class RunMode(str, Enum):
    AUTO = "auto"
    STEPPED = "stepped"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    CAUTION = "CAUTION"
    INFO = "INFO"


class DatasetKind(str, Enum):
    CROSS_SECTION = "cross_section"
    TIME_SERIES = "time_series"
    PANEL = "panel"
    REPEATED_CROSS_SECTION = "repeated_cross_section"
    UNKNOWN_MIXED = "unknown_mixed"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    path: str
    artifact_type: str
    step: str
    sha256: str
    inputs: tuple[str, ...] = field(default_factory=tuple)
    config_hash: str = ""
    code_version: str = "0.1.0"
    payload_contract: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "payload_contract", _freeze_value(self.payload_contract))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "artifact_type": self.artifact_type,
            "step": self.step,
            "sha256": self.sha256,
            "inputs": list(self.inputs),
            "config_hash": self.config_hash,
            "code_version": self.code_version,
        }
        if self.payload_contract:
            result["payload_contract"] = _to_plain(self.payload_contract)
        return result


@dataclass(frozen=True)
class GuardrailIssue:
    severity: Severity
    code: str
    message: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    issue_id: str = ""
    affected_stage: str = ""
    variables: list[str] = field(default_factory=list)
    metric: str = ""
    value: float | None = None
    threshold: float | None = None
    template_key: str = ""
    template_params: dict[str, Any] = field(default_factory=dict)
    recommended_action_key: str = ""
    is_user_action_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze_value(self.evidence))
        object.__setattr__(self, "variables", tuple(self.variables))
        object.__setattr__(self, "template_params", _freeze_value(self.template_params))

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "evidence": _to_plain(self.evidence),
            "issue_id": self.issue_id,
            "affected_stage": self.affected_stage,
            "variables": list(self.variables),
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "template_key": self.template_key,
            "template_params": _to_plain(self.template_params),
            "recommended_action_key": self.recommended_action_key,
            "is_user_action_required": self.is_user_action_required,
        }


@dataclass(frozen=True)
class DecisionRecord:
    step: str
    suggestion: str
    confidence: float
    evidence: tuple[str, ...]
    user_action: str
    final_decision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "user_action": self.user_action,
            "final_decision": self.final_decision,
        }


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    dtype: str
    semantic_role: str
    confidence: float
    source_file: str
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "semantic_role": self.semantic_role,
            "confidence": self.confidence,
            "source_file": self.source_file,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DatasetSchema:
    dataset_id: str
    source_files: tuple[str, ...]
    columns: tuple[ColumnMetadata, ...]
    primary_key_candidates: tuple[str, ...]
    time_candidates: tuple[str, ...]
    id_candidates: tuple[str, ...]
    transformations: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_files", tuple(self.source_files))
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(
            self,
            "primary_key_candidates",
            tuple(self.primary_key_candidates),
        )
        object.__setattr__(self, "time_candidates", tuple(self.time_candidates))
        object.__setattr__(self, "id_candidates", tuple(self.id_candidates))
        object.__setattr__(self, "transformations", _freeze_value(self.transformations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_files": list(self.source_files),
            "columns": [column.to_dict() for column in self.columns],
            "primary_key_candidates": list(self.primary_key_candidates),
            "time_candidates": list(self.time_candidates),
            "id_candidates": list(self.id_candidates),
            "transformations": _to_plain(self.transformations),
        }
