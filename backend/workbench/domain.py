from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunMode(str, Enum):
    AUTO = "auto"
    STEPPED = "stepped"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
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
    inputs: list[str] = field(default_factory=list)
    config_hash: str = ""
    code_version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardrailIssue:
    severity: Severity
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass(frozen=True)
class DecisionRecord:
    step: str
    suggestion: str
    confidence: float
    evidence: list[str]
    user_action: str
    final_decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    dtype: str
    semantic_role: str
    confidence: float
    source_file: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetSchema:
    dataset_id: str
    source_files: list[str]
    columns: list[ColumnMetadata]
    primary_key_candidates: list[str]
    time_candidates: list[str]
    id_candidates: list[str]
    transformations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
