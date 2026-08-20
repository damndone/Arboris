"""Bounded, provenance-aware profiles for one verified dataset snapshot."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

import pandas as pd

from .contracts.agent.context_egress import SensitivityClassV1
from .metadata import (
    MetadataDeclarationsV1,
    MetadataScalar,
    UNKNOWN_METADATA,
    MetadataProvenanceError,
    normalize_declared_metadata,
    parse_metadata_declarations,
)


JsonValue: TypeAlias = str | int | float | bool | None

MAX_SAMPLE_VALUES = 20
MAX_QUANTILES = 3
MAX_STRING_LENGTH = 256
MAX_TOKEN_COUNT = 64
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

_QUANTILE_LEVELS = (0.25, 0.5, 0.75)
_TIME_TOKENS = frozenset({"date", "time", "timestamp", "year", "month", "quarter"})
_ID_TOKENS = frozenset(
    {"id", "code", "key", "gvkey", "permno", "firm", "user", "store"}
)
_GROUP_TOKENS = frozenset(
    {"group", "category", "segment", "treatment", "class", "cohort", "type"}
)
_WEIGHT_TOKENS = frozenset({"weight", "weights", "wt", "probability", "prob"})
_SENSITIVE_TOKENS = frozenset(
    {
        "address",
        "api_key",
        "apikey",
        "credential",
        "email",
        "password",
        "phone",
        "secret",
        "ssn",
        "token",
    }
)


class DataProfileError(ValueError):
    """A profile input or lookup failed a stable data-profile contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise DataProfileError(
            "DATA_PROFILE_TEXT_INVALID", f"{field_name} must be a non-empty string"
        )
    return value


def _freeze_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


def _freeze_numeric_mapping(
    value: Mapping[str, float | None],
) -> Mapping[str, float | None]:
    return MappingProxyType(dict(value))


def _freeze_values(value: object) -> tuple[MetadataScalar, ...]:
    if type(value) not in {list, tuple}:
        raise DataProfileError(
            "DATA_PROFILE_METADATA_INVALID",
            "user_missing_values must be an explicit list",
        )
    return tuple(value)  # type: ignore[arg-type]


def _as_sensitivity(value: object, field_name: str) -> SensitivityClassV1:
    if isinstance(value, SensitivityClassV1):
        return value
    if type(value) is not str:
        raise DataProfileError(
            "DATA_PROFILE_SENSITIVITY_INVALID", f"{field_name} is invalid"
        )
    try:
        return SensitivityClassV1(value)
    except ValueError as exc:
        raise DataProfileError(
            "DATA_PROFILE_SENSITIVITY_INVALID", f"{field_name} is invalid"
        ) from exc


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _json_value(value: object, *, max_string_length: int) -> JsonValue:
    if _is_missing(value):
        return None
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is str:
        return value[:max_string_length]

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_value(item(), max_string_length=max_string_length)
        except (TypeError, ValueError, OverflowError):
            pass
    return str(value)[:max_string_length]


def _name_tokens(name: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", name.lower()) if token}


def _contains_token(name: str, tokens: frozenset[str]) -> bool:
    lowered = name.lower()
    parts = _name_tokens(name)
    return bool(parts & tokens) or any(token in lowered for token in tokens if len(token) > 2)


def _inferred_sensitivity(name: str) -> tuple[SensitivityClassV1, tuple[str, ...]]:
    if _contains_token(name, _SENSITIVE_TOKENS):
        return SensitivityClassV1.RESTRICTED, ("name_matches_sensitive_token",)
    return SensitivityClassV1.UNKNOWN, ("sensitivity_not_declared",)


def _role_inference(
    name: str,
    series: pd.Series,
) -> tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]]:
    roles: list[str] = []
    evidence: list[str] = []
    numeric = pd.api.types.is_numeric_dtype(series)
    datetime_like = pd.api.types.is_datetime64_any_dtype(series)

    if _contains_token(name, _TIME_TOKENS) or datetime_like:
        roles.append("time")
        evidence.append("name_or_dtype_matches_time")
    if _contains_token(name, _ID_TOKENS):
        roles.append("entity_id")
        evidence.append("name_matches_id_token")
    if _contains_token(name, _GROUP_TOKENS):
        roles.append("group")
        evidence.append("name_matches_group_token")
    if _contains_token(name, _WEIGHT_TOKENS):
        roles.append("weight")
        evidence.append("name_matches_weight_token")

    if numeric:
        roles.append("numeric_measure")
        evidence.append("dtype_is_numeric")
    elif pd.api.types.is_bool_dtype(series):
        roles.append("indicator")
        evidence.append("dtype_is_boolean")
    else:
        roles.append("categorical")
        evidence.append("dtype_is_non_numeric")

    unique_roles = tuple(dict.fromkeys(roles))
    if datetime_like or _contains_token(name, _TIME_TOKENS):
        levels = ("time",)
    elif numeric:
        levels = ("scale",)
    else:
        levels = ("nominal",)
    confidence = 0.85 if len(evidence) > 1 else 0.65
    return unique_roles, levels, confidence, tuple(evidence)


def _sample_values(
    series: pd.Series,
    *,
    redacted: bool,
) -> tuple[JsonValue, ...]:
    if redacted:
        return ()
    values: list[JsonValue] = []
    for value in series:
        if _is_missing(value):
            continue
        values.append(_json_value(value, max_string_length=MAX_STRING_LENGTH))
        if len(values) >= MAX_SAMPLE_VALUES:
            break
    return tuple(values)


def _quantiles(series: pd.Series, *, redacted: bool = False) -> Mapping[str, float | None]:
    if redacted:
        return MappingProxyType({})
    if not pd.api.types.is_numeric_dtype(series):
        return MappingProxyType({})
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return MappingProxyType({})
    result: dict[str, float | None] = {}
    for level in _QUANTILE_LEVELS[:MAX_QUANTILES]:
        value = numeric.quantile(level)
        result[str(level)] = (
            float(value) if pd.notna(value) and math.isfinite(float(value)) else None
        )
    return _freeze_numeric_mapping(result)


def _string_bounds(series: pd.Series) -> tuple[int | None, int | None]:
    lengths: list[int] = []
    max_tokens = 0
    for value in series:
        if _is_missing(value) or not isinstance(value, str):
            continue
        bounded = value[:MAX_STRING_LENGTH]
        lengths.append(len(bounded))
        max_tokens = max(max_tokens, min(len(bounded.split()), MAX_TOKEN_COUNT))
    if not lengths:
        return None, None
    return max(lengths), max_tokens


@dataclass(frozen=True)
class DatasetRefV1:
    run_id: str
    node_id: str
    artifact_id: str
    content_sha256: str
    schema_revision: str
    metadata_revision: str

    def __post_init__(self) -> None:
        for field_name in ("run_id", "node_id", "artifact_id", "schema_revision", "metadata_revision"):
            _text(getattr(self, field_name), field_name)
        if self.schema_revision == "v1" or self.metadata_revision == "v1":
            raise DataProfileError(
                "DATA_PROFILE_REVISION_UNAVAILABLE",
                "schema_revision and metadata_revision must come from a server-owned metadata artifact",
            )
        if type(self.content_sha256) is not str or _SHA256_RE.fullmatch(self.content_sha256) is None:
            raise DataProfileError(
                "DATA_PROFILE_DIGEST_INVALID",
                "content_sha256 must be a lowercase SHA-256 digest",
            )

    @property
    def node_ref(self) -> str:
        return self.node_id

    @property
    def sha256(self) -> str:
        return self.content_sha256

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "node_id": self.node_id,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
            "schema_revision": self.schema_revision,
            "metadata_revision": self.metadata_revision,
        }


@dataclass(frozen=True)
class ObservedColumnMetadataV1:
    dtype: str
    row_count: int
    missing_count: int
    missing_rate: float
    unique_count: int
    unique_ratio: float
    sample_values: tuple[JsonValue, ...] = field(default_factory=tuple)
    quantiles: Mapping[str, float | None] = field(default_factory=dict)
    max_string_length: int | None = None
    max_token_count: int | None = None
    samples_redacted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_values", tuple(self.sample_values))
        object.__setattr__(self, "quantiles", _freeze_numeric_mapping(self.quantiles))

    @property
    def examples(self) -> tuple[JsonValue, ...]:
        return self.sample_values

    def to_dict(self) -> dict[str, object]:
        return {
            "dtype": self.dtype,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "missing_rate": self.missing_rate,
            "unique_count": self.unique_count,
            "unique_ratio": self.unique_ratio,
            "sample_values": list(self.sample_values),
            "examples": list(self.examples),
            "quantiles": dict(self.quantiles),
            "max_string_length": self.max_string_length,
            "max_token_count": self.max_token_count,
            "samples_redacted": self.samples_redacted,
        }


@dataclass(frozen=True)
class DeclaredColumnMetadataV1:
    variable_label: str = UNKNOWN_METADATA
    value_labels: Mapping[str, str] | None = None
    measurement_level: str = UNKNOWN_METADATA
    missing_policy: str = UNKNOWN_METADATA
    role: str = UNKNOWN_METADATA
    sensitivity: SensitivityClassV1 = SensitivityClassV1.UNKNOWN
    user_missing_values: tuple[MetadataScalar, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.value_labels is not None:
            object.__setattr__(self, "value_labels", _freeze_mapping(self.value_labels))
        object.__setattr__(
            self,
            "user_missing_values",
            _freeze_values(self.user_missing_values),
        )
        object.__setattr__(
            self,
            "sensitivity",
            _as_sensitivity(self.sensitivity, "sensitivity"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "variable_label": self.variable_label,
            "value_labels": (
                None if self.value_labels is None else dict(self.value_labels)
            ),
            "measurement_level": self.measurement_level,
            "missing_policy": self.missing_policy,
            "role": self.role,
            "sensitivity": self.sensitivity.value,
            "user_missing_values": list(self.user_missing_values),
        }


@dataclass(frozen=True)
class InferredColumnMetadataV1:
    role_candidates: tuple[str, ...]
    measurement_level_candidates: tuple[str, ...]
    sensitivity: SensitivityClassV1
    method: str
    method_version: str
    confidence: float
    evidence: tuple[str, ...]
    confirmed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_candidates", tuple(self.role_candidates))
        object.__setattr__(
            self,
            "measurement_level_candidates",
            tuple(self.measurement_level_candidates),
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self,
            "sensitivity",
            _as_sensitivity(self.sensitivity, "sensitivity"),
        )
        if type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0:
            raise DataProfileError(
                "DATA_PROFILE_CONFIDENCE_INVALID", "inference confidence is invalid"
            )
        if type(self.confirmed) is not bool:
            raise DataProfileError(
                "DATA_PROFILE_INFERENCE_INVALID", "confirmed must be boolean"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "role_candidates": list(self.role_candidates),
            "measurement_level_candidates": list(self.measurement_level_candidates),
            "sensitivity": self.sensitivity.value,
            "method": self.method,
            "method_version": self.method_version,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "confirmed": self.confirmed,
        }


@dataclass(frozen=True)
class ColumnProfileV1:
    name: str
    observed: ObservedColumnMetadataV1
    declared: DeclaredColumnMetadataV1
    inferred: InferredColumnMetadataV1

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "observed": self.observed.to_dict(),
            "declared": self.declared.to_dict(),
            "inferred": self.inferred.to_dict(),
        }


@dataclass(frozen=True)
class DataProfileV1:
    dataset_ref: DatasetRefV1
    shape: tuple[int, int]
    columns: tuple[ColumnProfileV1, ...]
    declarations: MetadataDeclarationsV1 = field(default_factory=MetadataDeclarationsV1)

    def __post_init__(self) -> None:
        object.__setattr__(self, "shape", tuple(self.shape))
        object.__setattr__(self, "columns", tuple(self.columns))

    @property
    def row_count(self) -> int:
        return self.shape[0]

    @property
    def column_count(self) -> int:
        return self.shape[1]

    @property
    def schema_revision(self) -> str:
        return self.dataset_ref.schema_revision

    @property
    def metadata_revision(self) -> str:
        return self.dataset_ref.metadata_revision

    def column(self, name: str) -> ColumnProfileV1:
        for column in self.columns:
            if column.name == name:
                return column
        raise DataProfileError(
            "DATA_PROFILE_COLUMN_UNKNOWN", f"profile has no column: {name!r}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dataset_ref": self.dataset_ref.to_dict(),
            "schema_revision": self.schema_revision,
            "metadata_revision": self.metadata_revision,
            "shape": {"rows": self.row_count, "columns": self.column_count},
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [column.to_dict() for column in self.columns],
            "declarations": self.declarations.to_dict(),
        }


def _declared_column(value: Mapping[str, object] | None) -> DeclaredColumnMetadataV1:
    raw = {} if value is None else value
    sensitivity = raw.get("sensitivity", UNKNOWN_METADATA)
    return DeclaredColumnMetadataV1(
        variable_label=str(raw.get("variable_label", UNKNOWN_METADATA)),
        value_labels=raw.get("value_labels"),  # type: ignore[arg-type]
        measurement_level=str(raw.get("measurement_level", UNKNOWN_METADATA)),
        missing_policy=str(raw.get("missing_policy", UNKNOWN_METADATA)),
        role=str(raw.get("role", UNKNOWN_METADATA)),
        sensitivity=_as_sensitivity(sensitivity, "declared sensitivity"),
        user_missing_values=tuple(raw.get("user_missing_values", ())),  # type: ignore[arg-type]
    )


def _observed_column(
    series: pd.Series,
    *,
    redacted: bool,
) -> ObservedColumnMetadataV1:
    row_count = int(len(series))
    missing_count = int(series.isna().sum())
    unique_count = int(series.nunique(dropna=True))
    max_string_length, max_token_count = _string_bounds(series)
    return ObservedColumnMetadataV1(
        dtype=str(series.dtype),
        row_count=row_count,
        missing_count=missing_count,
        missing_rate=0.0 if row_count == 0 else missing_count / row_count,
        unique_count=unique_count,
        unique_ratio=unique_count / max(row_count, 1),
        sample_values=_sample_values(series, redacted=redacted),
        quantiles=_quantiles(series, redacted=redacted),
        max_string_length=max_string_length,
        max_token_count=max_token_count,
        samples_redacted=redacted,
    )


def build_data_profile(
    frame: pd.DataFrame,
    dataset_ref: DatasetRefV1,
    declared_metadata: Mapping[str, object] | None = None,
) -> DataProfileV1:
    """Build one immutable profile without mutating the source frame."""

    if type(frame) is not pd.DataFrame:
        raise DataProfileError("DATA_PROFILE_FRAME_INVALID", "frame must be a DataFrame")
    if type(dataset_ref) is not DatasetRefV1:
        raise DataProfileError(
            "DATA_PROFILE_DATASET_REF_INVALID",
            "dataset_ref must be DatasetRefV1",
        )

    columns = tuple(frame.columns)
    if any(type(column) is not str or not column for column in columns):
        raise DataProfileError(
            "DATA_PROFILE_COLUMNS_INVALID",
            "frame columns must be non-empty strings",
        )
    if len(set(columns)) != len(columns):
        raise DataProfileError(
            "DATA_PROFILE_COLUMNS_INVALID", "frame columns must be unique"
        )

    try:
        declarations = normalize_declared_metadata(
            declared_metadata, columns=columns
        )
    except MetadataProvenanceError as exc:
        code = (
            "DATA_PROFILE_METADATA_COLUMN_UNKNOWN"
            if exc.code == "METADATA_COLUMN_UNKNOWN"
            else "DATA_PROFILE_METADATA_INVALID"
        )
        raise DataProfileError(code, str(exc)) from exc

    profiles: list[ColumnProfileV1] = []
    for name in columns:
        series = frame[name]
        declared = _declared_column(declarations.get(name))
        roles, levels, confidence, evidence = _role_inference(name, series)
        inferred_sensitivity, sensitivity_evidence = _inferred_sensitivity(name)
        inferred = InferredColumnMetadataV1(
            role_candidates=roles,
            measurement_level_candidates=levels,
            sensitivity=inferred_sensitivity,
            method="dtype_and_name_heuristics",
            method_version="v1",
            confidence=float(confidence),
            evidence=evidence + sensitivity_evidence,
            confirmed=False,
        )
        redacted = (
            declared.sensitivity in {SensitivityClassV1.RESTRICTED, SensitivityClassV1.UNKNOWN}
            or inferred.sensitivity in {SensitivityClassV1.RESTRICTED, SensitivityClassV1.UNKNOWN}
        )
        profiles.append(
            ColumnProfileV1(
                name=name,
                observed=_observed_column(series, redacted=redacted),
                declared=declared,
                inferred=inferred,
            )
        )

    return DataProfileV1(
        dataset_ref=dataset_ref,
        shape=(int(frame.shape[0]), int(frame.shape[1])),
        columns=tuple(profiles),
        declarations=parse_metadata_declarations(declarations),
    )


ObservedMetadataV1 = ObservedColumnMetadataV1
DeclaredMetadataV1 = DeclaredColumnMetadataV1
InferredMetadataV1 = InferredColumnMetadataV1
DatasetProfileV1 = DataProfileV1


__all__ = [
    "ColumnProfileV1",
    "DataProfileError",
    "DataProfileV1",
    "DatasetProfileV1",
    "DatasetRefV1",
    "DeclaredColumnMetadataV1",
    "DeclaredMetadataV1",
    "MetadataDeclarationsV1",
    "InferredColumnMetadataV1",
    "InferredMetadataV1",
    "ObservedColumnMetadataV1",
    "ObservedMetadataV1",
    "build_data_profile",
]
