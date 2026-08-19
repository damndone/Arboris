from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal, TypeAlias
import re

import pandas as pd

from .artifacts import write_json
from .domain import ColumnMetadata, DatasetSchema


TIME_TOKENS = ("date", "time", "timestamp", "year", "month", "quarter")
ID_TOKENS = ("id", "code", "key", "gvkey", "permno", "firm", "user", "store")

UNKNOWN_METADATA = "unknown"

MetadataScalar: TypeAlias = str | int | float | bool | None
MAX_USER_MISSING_VALUES = 64
MAX_DECLARED_COLUMNS = 500
MAX_VALUE_LABELS = 256
MAX_METADATA_STRING_LENGTH = 256
MAX_METADATA_TOTAL_BYTES = 64 * 1024
MAX_METADATA_PROVENANCE_BYTES = 8 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
        "user_missing_values",
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
        "user_missing_values",
    }
)


def _metadata_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must be a non-empty string",
        )
    if len(value) > MAX_METADATA_STRING_LENGTH:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_BOUNDS",
            f"{field_name} exceeds {MAX_METADATA_STRING_LENGTH} characters",
        )
    return value


def _enforce_metadata_total_bytes(value: Mapping[str, object], field_name: str) -> None:
    encoded_size = len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if encoded_size > MAX_METADATA_TOTAL_BYTES:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_BOUNDS",
            f"{field_name} exceeds {MAX_METADATA_TOTAL_BYTES} bytes",
        )


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
    if len(raw) > MAX_VALUE_LABELS:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_BOUNDS",
            f"value_labels exceeds {MAX_VALUE_LABELS} entries",
        )
    normalized: dict[str, str] = {}
    for raw_value, label in raw.items():
        key = _metadata_text(raw_value, "value_labels key")
        text = _metadata_text(label, "value_labels label")
        if len(key) > MAX_METADATA_STRING_LENGTH or len(text) > MAX_METADATA_STRING_LENGTH:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_BOUNDS",
                f"value_labels keys and labels are limited to {MAX_METADATA_STRING_LENGTH} characters",
            )
        normalized[key] = text
    encoded_size = len(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if encoded_size > MAX_METADATA_PROVENANCE_BYTES:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_BOUNDS",
            "value_labels exceeds the bounded metadata byte budget",
        )
    return normalized


def _normalize_metadata_scalar(value: object, field_name: str) -> MetadataScalar:
    if value is None or type(value) is bool or type(value) is int or type(value) is str:
        if type(value) is str and ("\x00" in value or value != value.strip()):
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID",
                f"{field_name} string values must not contain whitespace padding",
            )
        return value  # type: ignore[return-value]
    if type(value) is float:
        if not math.isfinite(value):
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID",
                f"{field_name} values must be finite",
            )
        return value
    raise MetadataProvenanceError(
        "METADATA_DECLARATION_INVALID",
        f"{field_name} values must be JSON-like scalars",
    )


def _normalize_user_missing_values(value: object, field_name: str) -> list[MetadataScalar]:
    if type(value) not in {list, tuple}:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must be an explicit list",
        )
    if len(value) > MAX_USER_MISSING_VALUES:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} exceeds {MAX_USER_MISSING_VALUES} values",
        )
    normalized = [
        _normalize_metadata_scalar(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    ]
    if len({json.dumps(item, sort_keys=True) for item in normalized}) != len(normalized):
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must not contain duplicates",
        )
    return normalized


def _normalize_string_list(value: object, field_name: str) -> list[str]:
    if type(value) not in {list, tuple} or not value:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must be a non-empty list",
        )
    if len(value) > MAX_DECLARED_COLUMNS:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} contains too many columns",
        )
    normalized = [_metadata_text(item, f"{field_name}[]") for item in value]
    if len(set(normalized)) != len(normalized):
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_INVALID",
            f"{field_name} must not contain duplicates",
        )
    return normalized


def _normalize_dataset_declarations(
    value: object,
    *,
    columns: frozenset[str],
) -> dict[str, object]:
    if value is None:
        return {}
    raw = _metadata_mapping(value, "declared_metadata.__dataset__")
    unknown = sorted(set(raw) - {"weight", "split", "group"})
    if unknown:
        raise MetadataProvenanceError(
            "METADATA_DECLARATION_FIELD_UNKNOWN",
            "declared_metadata.__dataset__ contains unknown field(s): " + ", ".join(unknown),
        )
    normalized: dict[str, object] = {}
    weight = raw.get("weight")
    if weight is not None:
        weight_map = _metadata_mapping(weight, "declared_metadata.__dataset__.weight")
        if set(weight_map) != {"column", "kind"}:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID",
                "weight must contain exactly column and kind",
            )
        column = _metadata_text(weight_map["column"], "weight.column")
        if column not in columns:
            raise MetadataProvenanceError("METADATA_COLUMN_UNKNOWN", f"weight names unknown column: {column!r}")
        kind = _metadata_text(weight_map["kind"], "weight.kind")
        if kind not in {"frequency", "analytic", "probability", "reliability"}:
            raise MetadataProvenanceError("METADATA_DECLARATION_INVALID", "weight.kind is not supported")
        normalized["weight"] = {"column": column, "kind": kind}
    for field_name in ("split", "group"):
        declaration = raw.get(field_name)
        if declaration is None:
            continue
        declaration_map = _metadata_mapping(
            declaration, f"declared_metadata.__dataset__.{field_name}"
        )
        unknown_fields = sorted(set(declaration_map) - {"columns", "mode"})
        if unknown_fields:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_FIELD_UNKNOWN",
                f"{field_name} contains unknown field(s): {', '.join(unknown_fields)}",
            )
        declared_columns = _normalize_string_list(
            declaration_map.get("columns"), f"{field_name}.columns"
        )
        unknown_columns = sorted(set(declared_columns) - columns)
        if unknown_columns:
            raise MetadataProvenanceError(
                "METADATA_COLUMN_UNKNOWN",
                f"{field_name} names unknown column(s): {', '.join(unknown_columns)}",
            )
        mode = declaration_map.get("mode", "split_file" if field_name == "split" else "group")
        mode = _metadata_text(mode, f"{field_name}.mode")
        allowed_modes = {"split_file", "group"}
        if mode not in allowed_modes:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID",
                f"{field_name}.mode is not supported",
            )
        normalized[field_name] = {"columns": declared_columns, "mode": mode}
    return normalized


@dataclass(frozen=True)
class WeightDeclarationV1:
    column: str
    kind: Literal["frequency", "analytic", "probability", "reliability"]

    def __post_init__(self) -> None:
        _metadata_text(self.column, "weight.column")
        if self.kind not in {"frequency", "analytic", "probability", "reliability"}:
            raise ValueError("weight.kind is not supported")

    def to_dict(self) -> dict[str, str]:
        return {"column": self.column, "kind": self.kind}


@dataclass(frozen=True)
class SplitDeclarationV1:
    columns: tuple[str, ...]
    mode: Literal["split_file", "group"] = "split_file"

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        if not self.columns or any(not isinstance(item, str) or not item.strip() for item in self.columns):
            raise ValueError("split.columns must be non-empty strings")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("split.columns must not contain duplicates")
        if self.mode not in {"split_file", "group"}:
            raise ValueError("split.mode is not supported")

    def to_dict(self) -> dict[str, object]:
        return {"columns": list(self.columns), "mode": self.mode}


@dataclass(frozen=True)
class GroupDeclarationV1:
    columns: tuple[str, ...]
    mode: Literal["group", "split_file"] = "group"

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        if not self.columns or any(not isinstance(item, str) or not item.strip() for item in self.columns):
            raise ValueError("group.columns must be non-empty strings")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("group.columns must not contain duplicates")
        if self.mode not in {"group", "split_file"}:
            raise ValueError("group.mode is not supported")

    def to_dict(self) -> dict[str, object]:
        return {"columns": list(self.columns), "mode": self.mode}


@dataclass(frozen=True)
class MetadataDeclarationsV1:
    weight: WeightDeclarationV1 | None = None
    split: SplitDeclarationV1 | None = None
    group: GroupDeclarationV1 | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "weight": None if self.weight is None else self.weight.to_dict(),
            "split": None if self.split is None else self.split.to_dict(),
            "group": None if self.group is None else self.group.to_dict(),
        }


def metadata_revision_digest(
    metadata: Mapping[str, object],
    *,
    schema_revision: str,
) -> str:
    """Return a content-bound metadata revision for a confirmed artifact."""

    _metadata_text(schema_revision, "schema_revision")
    if schema_revision == "v1":
        raise MetadataProvenanceError(
            "METADATA_REVISION_UNAVAILABLE",
            "schema_revision must identify a server-owned schema artifact",
        )
    payload = {
        "schema_revision": schema_revision,
        "metadata": metadata,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"metadata:{digest}"


@dataclass(frozen=True)
class MetadataRegistryV1:
    """The server-owned, confirmed metadata binding for one immutable frame."""

    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    schema_revision: str
    metadata_revision: str
    metadata: Mapping[str, object]
    source_content_sha256: str
    schema_artifact_id: str
    schema_artifact_sha256: str
    metadata_artifact_id: str
    metadata_artifact_path: str
    metadata_artifact_sha256: str
    metadata_index_entry_sha256: str
    confirmed: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
            "schema_revision",
            "metadata_revision",
            "source_content_sha256",
            "schema_artifact_id",
            "schema_artifact_sha256",
            "metadata_artifact_id",
            "metadata_artifact_path",
            "metadata_artifact_sha256",
            "metadata_index_entry_sha256",
        ):
            _metadata_text(getattr(self, field_name), field_name)
        for field_name in (
            "source_content_sha256",
            "schema_artifact_sha256",
            "metadata_artifact_sha256",
            "metadata_index_entry_sha256",
        ):
            if _SHA256_RE.fullmatch(getattr(self, field_name)) is None:
                raise MetadataProvenanceError(
                    "METADATA_PROVENANCE_INVALID",
                    f"{field_name} must be a lowercase SHA-256 digest",
                )
        if len(self.metadata_artifact_path) > MAX_METADATA_STRING_LENGTH:
            raise MetadataProvenanceError(
                "METADATA_PROVENANCE_INVALID", "metadata artifact path exceeds the server bound"
            )
        if self.schema_revision == "v1" or self.metadata_revision == "v1":
            raise MetadataProvenanceError(
                "METADATA_REVISION_UNAVAILABLE",
                "metadata registry revisions must not default to v1",
            )
        if self.confirmed is not True:
            raise MetadataProvenanceError(
                "METADATA_CONFIRMATION_REQUIRED",
                "metadata registry is not confirmed by the server",
            )
        if not isinstance(self.metadata, Mapping):
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID", "metadata registry metadata must be an object"
            )
        metadata_bytes = len(
            json.dumps(self.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if metadata_bytes > MAX_METADATA_TOTAL_BYTES:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_BOUNDS", "metadata registry exceeds the server byte bound"
            )
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        source_run_id: str,
        source_node_id: str,
        source_artifact_id: str,
        source_content_sha256: str,
        schema_artifact_id: str,
        schema_artifact_sha256: str,
        metadata_artifact_id: str,
        metadata_artifact_path: str,
        metadata_artifact_sha256: str,
        metadata_index_sha256: str,
    ) -> "MetadataRegistryV1":
        if payload.get("payload_schema") != "workbench.data-metadata":
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_INVALID", "metadata artifact payload_schema is unsupported"
            )
        if payload.get("schema_version") != 1:
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_INVALID", "metadata artifact schema_version is unsupported"
            )
        source = payload.get("source")
        if not isinstance(source, Mapping):
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_INVALID", "metadata artifact source is missing"
            )
        expected_source = {
            "run_id": source_run_id,
            "node_id": source_node_id,
            "artifact_id": source_artifact_id,
            "sha256": source_content_sha256,
        }
        for key, expected in expected_source.items():
            if source.get(key) != expected:
                raise MetadataProvenanceError(
                    "METADATA_REGISTRY_SOURCE_MISMATCH",
                    f"metadata artifact source.{key} does not match the selected dataset",
                )
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_INVALID", "metadata artifact metadata is missing"
            )
        schema_artifact = payload.get("schema_artifact")
        if not isinstance(schema_artifact, Mapping) or {
            "artifact_id": schema_artifact.get("artifact_id") if isinstance(schema_artifact, Mapping) else None,
            "sha256": schema_artifact.get("sha256") if isinstance(schema_artifact, Mapping) else None,
        } != {"artifact_id": schema_artifact_id, "sha256": schema_artifact_sha256}:
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_PROVENANCE_MISMATCH",
                "metadata schema artifact provenance does not match the server-owned schema artifact",
            )
        metadata_artifact = payload.get("metadata_artifact")
        if not isinstance(metadata_artifact, Mapping) or {
            "artifact_id": metadata_artifact.get("artifact_id") if isinstance(metadata_artifact, Mapping) else None,
            "path": metadata_artifact.get("path") if isinstance(metadata_artifact, Mapping) else None,
            "sha256": metadata_artifact.get("sha256") if isinstance(metadata_artifact, Mapping) else None,
        } != {
            "artifact_id": metadata_artifact_id,
            "path": metadata_artifact_path,
            "sha256": metadata_artifact_sha256,
        }:
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_PROVENANCE_MISMATCH",
                "metadata artifact provenance does not match the server-owned artifact index",
            )
        metadata_index = payload.get("metadata_index")
        if not isinstance(metadata_index, Mapping) or metadata_index.get("entry_sha256") != metadata_index_sha256:
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_PROVENANCE_MISMATCH",
                "metadata index provenance does not match the server-owned index entry",
            )
        schema_revision = payload.get("schema_revision")
        metadata_revision = payload.get("metadata_revision")
        normalized_schema_revision = _metadata_text(schema_revision, "schema_revision")
        normalized_metadata_revision = _metadata_text(metadata_revision, "metadata_revision")
        expected_metadata_revision = metadata_revision_digest(
            metadata,
            schema_revision=normalized_schema_revision,
        )
        if normalized_metadata_revision != expected_metadata_revision:
            raise MetadataProvenanceError(
                "METADATA_REVISION_MISMATCH",
                "metadata_revision is not bound to the immutable metadata payload",
            )
        return cls(
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            schema_revision=normalized_schema_revision,
            metadata_revision=normalized_metadata_revision,
            metadata=metadata,
            source_content_sha256=source_content_sha256,
            schema_artifact_id=schema_artifact_id,
            schema_artifact_sha256=schema_artifact_sha256,
            metadata_artifact_id=metadata_artifact_id,
            metadata_artifact_path=metadata_artifact_path,
            metadata_artifact_sha256=metadata_artifact_sha256,
            metadata_index_entry_sha256=metadata_index_sha256,
            confirmed=payload.get("confirmed") is True,
        )

    def to_profile_metadata(self, columns: tuple[str, ...]) -> dict[str, object]:
        """Project canonical registry fields into the profile declaration shape."""

        known = frozenset(columns)
        raw_columns = self.metadata.get("columns", {})
        if not isinstance(raw_columns, Mapping):
            raise MetadataProvenanceError(
                "METADATA_REGISTRY_INVALID", "metadata registry columns must be an object"
            )
        projected_columns = {
            str(column): dict(declaration)
            for column, declaration in raw_columns.items()
            if column in known and isinstance(declaration, Mapping)
        }
        result: dict[str, object] = dict(projected_columns)
        dataset = {
            key: self.metadata[key]
            for key in ("weight", "split", "group")
            if key in self.metadata
        }
        if dataset:
            result["__dataset__"] = dataset
        return result

    def user_missing_values(self, columns: tuple[str, ...]) -> dict[str, list[MetadataScalar]]:
        profile_metadata = self.to_profile_metadata(columns)
        raw_columns = {
            column: declaration
            for column, declaration in profile_metadata.items()
            if column != "__dataset__"
        }
        if not isinstance(raw_columns, Mapping):
            return {}
        return {
            str(column): list(declaration["user_missing_values"])
            for column, declaration in raw_columns.items()
            if isinstance(declaration, Mapping) and "user_missing_values" in declaration
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "payload_schema": "workbench.data-metadata",
            "schema_version": 1,
            "confirmed": True,
            "schema_revision": self.schema_revision,
            "metadata_revision": self.metadata_revision,
            "source_content_sha256": self.source_content_sha256,
            "schema_artifact": {
                "artifact_id": self.schema_artifact_id,
                "sha256": self.schema_artifact_sha256,
            },
            "metadata_artifact": {
                "artifact_id": self.metadata_artifact_id,
                "path": self.metadata_artifact_path,
                "sha256": self.metadata_artifact_sha256,
            },
            "metadata_index": {"entry_sha256": self.metadata_index_entry_sha256},
            "source": {
                "run_id": self.source_run_id,
                "node_id": self.source_node_id,
                "artifact_id": self.source_artifact_id,
            },
            "metadata": dict(self.metadata),
        }


def parse_metadata_declarations(
    normalized: Mapping[str, Mapping[str, object]],
) -> MetadataDeclarationsV1:
    raw = normalized.get("__dataset__", {})
    if not isinstance(raw, Mapping):
        raise MetadataProvenanceError("METADATA_DECLARATION_INVALID", "dataset declarations must be an object")
    weight_raw = raw.get("weight")
    split_raw = raw.get("split")
    group_raw = raw.get("group")
    weight = None if weight_raw is None else WeightDeclarationV1(
        column=str(weight_raw["column"]), kind=str(weight_raw["kind"])
    )
    split = None if split_raw is None else SplitDeclarationV1(
        columns=tuple(split_raw["columns"]), mode=str(split_raw.get("mode", "split_file"))
    )
    group = None if group_raw is None else GroupDeclarationV1(
        columns=tuple(group_raw["columns"]), mode=str(group_raw.get("mode", "group"))
    )
    return MetadataDeclarationsV1(weight=weight, split=split, group=group)


def normalize_metadata_mutation_payload(
    metadata: Mapping[str, object],
    *,
    weight: Mapping[str, object] | None = None,
    split: Mapping[str, object] | None = None,
    group: Mapping[str, object] | None = None,
    columns: tuple[str, ...],
) -> dict[str, object]:
    """Build the canonical, server-validated metadata artifact payload."""

    if not isinstance(metadata, Mapping):
        raise MetadataProvenanceError("METADATA_DECLARATION_INVALID", "metadata must be an object")
    combined: dict[str, object] = dict(metadata)
    dataset: dict[str, object] = {}
    if weight is not None:
        dataset["weight"] = dict(weight)
    if split is not None:
        dataset["split"] = dict(split)
    if group is not None:
        dataset["group"] = dict(group)
    if "__dataset__" in combined:
        existing = combined["__dataset__"]
        if not isinstance(existing, Mapping):
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID", "metadata.__dataset__ must be an object"
            )
        if dataset:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_INVALID",
                "metadata.__dataset__ cannot be combined with top-level declarations",
            )
        dataset = dict(existing)
    if dataset:
        combined["__dataset__"] = dataset
    normalized = normalize_declared_metadata(combined, columns=columns)
    column_payload = {
        column: dict(declaration)
        for column, declaration in normalized.items()
        if column != "__dataset__"
    }
    payload: dict[str, object] = {"columns": column_payload}
    payload.update(dict(normalized.get("__dataset__", {})))
    _enforce_metadata_total_bytes(payload, "metadata")
    return payload


@dataclass(frozen=True)
class MetadataMutationSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    metadata: Mapping[str, object] = field(default_factory=dict)
    weight: Mapping[str, object] | None = None
    split: Mapping[str, object] | None = None
    group: Mapping[str, object] | None = None
    operation_id: str = "data.metadata.update"
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "source_node_id", "source_artifact_id"):
            _metadata_text(getattr(self, field_name), field_name)
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
        object.__setattr__(self, "metadata", dict(self.metadata))
        for field_name in ("weight", "split", "group"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise ValueError(f"{field_name} must be an object")
                object.__setattr__(self, field_name, dict(value))

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "metadata": dict(self.metadata),
            "weight": None if self.weight is None else dict(self.weight),
            "split": None if self.split is None else dict(self.split),
            "group": None if self.group is None else dict(self.group),
        }


@dataclass(frozen=True)
class MetadataMutationPreviewV1:
    spec: MetadataMutationSpecV1
    source_sha256: str
    metadata_fingerprint: str
    changed_columns: tuple[str, ...]
    fingerprint: str
    canonical_metadata: Mapping[str, object] = field(default_factory=dict)
    schema_revision: str = ""
    metadata_revision: str = ""
    status: str = "ready"
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "changed_columns", tuple(self.changed_columns))
        object.__setattr__(self, "canonical_metadata", dict(self.canonical_metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            **self.spec.to_dict(),
            "source_sha256": self.source_sha256,
            "metadata_fingerprint": self.metadata_fingerprint,
            "changed_columns": list(self.changed_columns),
            "metadata": dict(self.canonical_metadata),
            "schema_revision": self.schema_revision,
            "metadata_revision": self.metadata_revision,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MetadataMutationEffectV1:
    record_id: str
    execution_key: str
    metadata_artifact_id: str
    metadata_artifact_path: str
    child_node_id: str
    schema_revision: str | None = None
    metadata_revision: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "operation_id": "data.metadata.update",
            "status": "completed",
            "execution_key": self.execution_key,
            "metadata_artifact_id": self.metadata_artifact_id,
            "metadata_artifact_path": self.metadata_artifact_path,
            "child_node_id": self.child_node_id,
            "schema_revision": self.schema_revision,
            "metadata_revision": self.metadata_revision,
        }


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
        elif field_name == "user_missing_values":
            normalized[field_name] = _normalize_user_missing_values(
                field_value, f"metadata[{column!r}].user_missing_values"
            )
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

    dataset_declarations = _normalize_dataset_declarations(
        raw.get("__dataset__"), columns=known_columns
    )
    column_raw = {key: item for key, item in raw.items() if key != "__dataset__"}

    if set(column_raw) & _TOP_LEVEL_METADATA_FIELDS:
        unknown = sorted(set(column_raw) - _TOP_LEVEL_METADATA_FIELDS)
        if unknown:
            raise MetadataProvenanceError(
                "METADATA_DECLARATION_FIELD_UNKNOWN",
                "declared_metadata contains unknown field(s): " + ", ".join(unknown),
            )
        normalized = {column: {} for column in columns}
        for field_name, field_value in column_raw.items():
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
            elif field_name == "user_missing_values":
                values = _metadata_mapping(field_value, field_name)
                for column, item in values.items():
                    if column not in known_columns:
                        raise MetadataProvenanceError(
                            "METADATA_COLUMN_UNKNOWN",
                            f"{field_name} names unknown column: {column!r}",
                        )
                    normalized[column]["user_missing_values"] = _normalize_user_missing_values(
                        item, f"{field_name}[{column!r}]"
                    )
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
        result = {
            column: declaration for column, declaration in normalized.items() if declaration
        }
        if dataset_declarations:
            result["__dataset__"] = dataset_declarations
        _enforce_metadata_total_bytes(result, "declared_metadata")
        return result

    normalized = {}
    for column, declaration in column_raw.items():
        if type(column) is not str or not column or column not in known_columns:
            raise MetadataProvenanceError(
                "METADATA_COLUMN_UNKNOWN",
                f"declared_metadata names unknown column: {column!r}",
            )
        normalized[column] = _normalize_column_declaration(declaration, column)
    if dataset_declarations:
        normalized["__dataset__"] = dataset_declarations
    _enforce_metadata_total_bytes(normalized, "declared_metadata")
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
