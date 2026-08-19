from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from .artifacts import write_json
from .domain import ColumnMetadata, DatasetSchema


TIME_TOKENS = ("date", "time", "timestamp", "year", "month", "quarter")
ID_TOKENS = ("id", "code", "key", "gvkey", "permno", "firm", "user", "store")

UNKNOWN_METADATA = "unknown"


class MetadataProvenanceError(ValueError):
    """A declared metadata payload failed its closed profile contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


_COLUMN_METADATA_FIELDS = frozenset(
    {
        "variable_label",
        "value_labels",
        "measurement_level",
        "missing_policy",
        "role",
        "sensitivity",
    }
)
_TOP_LEVEL_METADATA_FIELDS = frozenset(
    {
        "variable_labels",
        "value_labels",
        "measurement_level",
        "missing_policy",
        "roles",
        "sensitivity",
    }
)


def _metadata_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must be a non-empty string",
        )
    return value


def _metadata_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must be an object",
        )
    if any(type(key) is not str for key in value):
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} keys must be strings",
        )
    return value


def _normalize_value_labels(value: object) -> dict[str, str]:
    raw = _metadata_mapping(value, "value_labels")
    normalized: dict[str, str] = {}
    for raw_value, label in raw.items():
        normalized[_metadata_text(raw_value, "value_labels key")] = _metadata_text(
            label, "value_labels label"
        )
    return normalized


def _normalize_column_declaration(value: object, column: str) -> dict[str, object]:
    raw = _metadata_mapping(value, f"metadata[{column!r}]")
    unknown = sorted(set(raw) - _COLUMN_METADATA_FIELDS)
    if unknown:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_FIELD_UNKNOWN",
            f"metadata[{column!r}] contains unknown field(s): {', '.join(unknown)}",
        )

    normalized: dict[str, object] = {}
    for field_name, field_value in raw.items():
        if field_name == "value_labels":
            normalized[field_name] = _normalize_value_labels(field_value)
        elif field_name in {
            "variable_label",
            "measurement_level",
            "missing_policy",
            "role",
            "sensitivity",
        }:
            normalized[field_name] = _metadata_text(field_value, field_name)
    return normalized


def _normalize_column_map(
    value: object,
    field_name: str,
    columns: frozenset[str],
    *,
    value_labels: bool = False,
) -> dict[str, object]:
    raw = _metadata_mapping(value, field_name)
    normalized: dict[str, object] = {}
    for column, declaration in raw.items():
        if not column or column not in columns:
            raise MetadataProvenanceError(
                "METADATA_COLUMN_UNKNOWN",
                f"{field_name} names unknown column: {column!r}",
            )
        normalized[column] = (
            _normalize_value_labels(declaration)
            if value_labels
            else _metadata_text(declaration, field_name)
        )
    return normalized


def normalize_declared_metadata(
    value: object,
    *,
    columns: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    """Normalize supported declared-label shapes without inferring facts.

    Existing ingestion stores labels as a top-level mapping while the profile
    contract also accepts the compact per-column shape used by data consumers.
    This helper only validates and groups declarations; it never fills missing
    metadata or derives values from the frame.
    """

    if value is None:
        return {}
    raw = _metadata_mapping(value, "declared_metadata")
    known_columns = frozenset(columns)
    if any(type(column) is not str or not column for column in columns):
        raise MetadataProvenanceError(
            "METADATA_COLUMNS_INVALID",
            "profile columns must be non-empty strings",
        )

    if set(raw) & _TOP_LEVEL_METADATA_FIELDS:
        unknown = sorted(set(raw) - _TOP_LEVEL_METADATA_FIELDS)
        if unknown:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_FIELD_UNKNOWN",
                "declared_metadata contains unknown field(s): " + ", ".join(unknown),
            )
        normalized = {column: {} for column in columns}
        for field_name, field_value in raw.items():
            if field_name == "variable_labels":
                values = _normalize_column_map(
                    field_value, field_name, known_columns
                )
                for column, item in values.items():
                    normalized[column]["variable_label"] = item
            elif field_name == "value_labels":
                values = _normalize_column_map(
                    field_value, field_name, known_columns, value_labels=True
                )
                for column, item in values.items():
                    normalized[column]["value_labels"] = item
            elif field_name in {
                "measurement_level",
                "missing_policy",
                "roles",
                "sensitivity",
            }:
                values = _normalize_column_map(field_value, field_name, known_columns)
                target_name = "role" if field_name == "roles" else field_name
                for column, item in values.items():
                    normalized[column][target_name] = item
        return {column: declaration for column, declaration in normalized.items() if declaration}

    normalized = {}
    for column, declaration in raw.items():
        if type(column) is not str or not column or column not in known_columns:
            raise MetadataProvenanceError(
                "METADATA_COLUMN_UNKNOWN",
                f"declared_metadata names unknown column: {column!r}",
            )
        normalized[column] = _normalize_column_declaration(declaration, column)
    return normalized


MetadataLossStatus = Literal["preserved", "converted", "dropped", "not_supported"]


@dataclass(frozen=True)
class MetadataLossItemV1:
    """One explicit, user-visible metadata round-trip outcome."""

    field: str
    status: MetadataLossStatus
    reason: str
    original_representation: str
    target_representation: str

    def __post_init__(self) -> None:
        if not self.field or not self.reason:
            raise ValueError("metadata loss item field and reason are required")
        if self.status not in {"preserved", "converted", "dropped", "not_supported"}:
            raise ValueError("unsupported metadata loss status")

    def to_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "status": self.status,
            "reason": self.reason,
            "original_representation": self.original_representation,
            "target_representation": self.target_representation,
        }


@dataclass(frozen=True)
class MetadataLossManifestV1:
    """A preview-only declaration of what an interchange format can retain."""

    source_format: str
    target_format: str
    items: tuple[MetadataLossItemV1, ...]
    schema_version: str = "metadata-loss-manifest/v1"

    def __post_init__(self) -> None:
        if not self.source_format or not self.target_format:
            raise ValueError("metadata loss formats are required")
        object.__setattr__(self, "items", tuple(self.items))

    @property
    def has_loss(self) -> bool:
        return any(item.status != "preserved" for item in self.items)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_format": self.source_format,
            "target_format": self.target_format,
            "has_loss": self.has_loss,
            "items": [item.to_dict() for item in self.items],
        }


# These are deliberately conservative. CSV/XLSX can carry values and order,
# but not Workbench's analytical metadata; dtype is represented by the file
# reader rather than preserved exactly. A future exporter must add a new
# explicit capability entry and tests rather than silently claiming parity.
_TARGET_FORMAT_CAPABILITIES: dict[str, frozenset[str]] = {
    "csv": frozenset({"column_order"}),
    "xlsx": frozenset({"column_order"}),
    "parquet": frozenset({"column_order", "dtype"}),
    "workbench-json": frozenset(
        {
            "dtype",
            "variable_label",
            "value_labels",
            "measurement_level",
            "missing_policy",
            "sensitivity",
            "column_order",
        }
    ),
}
_CONVERTED_DTYPE_FORMATS = frozenset({"csv", "xlsx"})


def build_metadata_loss_manifest(
    *,
    source_format: str,
    target_format: str,
    metadata: Mapping[str, Mapping[str, object]],
) -> MetadataLossManifestV1:
    """Build a deterministic loss report without writing or exporting data."""

    if type(source_format) is not str or not source_format.strip():
        raise ValueError("source_format is required")
    if type(target_format) is not str or not target_format.strip():
        raise ValueError("target_format is required")
    source_format = source_format.strip().casefold()
    target_format = target_format.strip().casefold()
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping of column to fields")
    if len(metadata) > 500:
        raise ValueError("metadata contains too many columns")

    target_capabilities = _TARGET_FORMAT_CAPABILITIES.get(target_format)
    items: list[MetadataLossItemV1] = []
    for column, fields in metadata.items():
        if (
            type(column) is not str
            or not column
            or len(column) > 256
            or any(ord(char) < 0x20 for char in column)
        ):
            raise ValueError("metadata column names must be non-empty strings")
        if not isinstance(fields, Mapping):
            raise ValueError(f"metadata for {column!r} must be a mapping")
        if len(fields) > 64:
            raise ValueError(f"metadata for {column!r} contains too many fields")
        for field_name in sorted(fields):
            if (
                type(field_name) is not str
                or not field_name
                or len(field_name) > 128
                or any(ord(char) < 0x20 for char in field_name)
            ):
                raise ValueError("metadata field names must be non-empty strings")
            field = f"{column}.{field_name}"
            if target_capabilities is None:
                status: MetadataLossStatus = "not_supported"
                reason = f"target format {target_format!r} has no declared metadata contract"
                target_repr = "not_supported"
            elif field_name == "dtype" and target_format in _CONVERTED_DTYPE_FORMATS:
                status = "converted"
                reason = f"target format {target_format!r} stores values without exact dtype metadata"
                target_repr = "reader_inferred_dtype"
            elif field_name not in target_capabilities:
                status = "dropped"
                reason = f"target format {target_format!r} cannot represent {field_name!r}"
                target_repr = "not_representable"
            else:
                status = "preserved"
                reason = f"target format {target_format!r} declares {field_name!r} support"
                target_repr = field_name
            items.append(
                MetadataLossItemV1(
                    field=field,
                    status=status,
                    reason=reason,
                    original_representation=field_name,
                    target_representation=target_repr,
                )
            )
    return MetadataLossManifestV1(
        source_format=source_format,
        target_format=target_format,
        items=tuple(items),
    )


def infer_schema(
    dataset_id: str, frames: dict[str, pd.DataFrame], run_root: Path
) -> DatasetSchema:
    columns: list[ColumnMetadata] = []
    time_candidates: dict[str, None] = {}
    id_candidates: dict[str, None] = {}
    primary_key_candidates: dict[str, None] = {}
    for source_file, frame in frames.items():
        row_count = max(len(frame), 1)
        for name in frame.columns:
            series = frame[name]
            normalized = str(name).lower()
            dtype = str(series.dtype)
            evidence: list[str] = []
            role = "categorical"
            confidence = 0.5
            if pd.api.types.is_numeric_dtype(series):
                role = "numeric_measure"
                confidence = 0.7
            if any(token in normalized for token in TIME_TOKENS):
                role = "time"
                confidence = 0.85
                time_candidates.setdefault(str(name), None)
                evidence.append("name_matches_time_token")
            if any(token in normalized for token in ID_TOKENS):
                role = "entity_id"
                confidence = 0.8
                id_candidates.setdefault(str(name), None)
                evidence.append("name_matches_id_token")
            unique_ratio = float(series.nunique(dropna=True) / row_count)
            if unique_ratio == 1.0:
                primary_key_candidates.setdefault(str(name), None)
                evidence.append("unique_column")
            columns.append(
                ColumnMetadata(str(name), dtype, role, confidence, source_file, evidence)
            )
    schema = DatasetSchema(
        dataset_id,
        list(frames.keys()),
        columns,
        list(primary_key_candidates.keys()),
        list(time_candidates.keys()),
        list(id_candidates.keys()),
    )
    write_json(run_root / "staged" / "metadata_registry.json", schema.to_dict())
    return schema
