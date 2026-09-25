"""Executable, loss-explicit interchange contracts for data consumers.

The supported tabular formats are intentionally small.  Every advertised
format is exercised by a real write/read pair; optional statistical formats
remain typed unavailable when their dependency is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from importlib.util import find_spec
import math
from numbers import Real
import os
from pathlib import Path
import tempfile
from typing import Any, Literal, Mapping

import pandas as pd

from .metadata import (
    MetadataLossItemV1,
    MetadataLossManifestV1,
    build_metadata_loss_manifest,
)


InterchangeStatus = Literal["available", "unavailable"]
WriteStatus = Literal["written", "unavailable"]
RoundTripStatus = Literal[
    "verified",
    "unavailable",
    "schema_mismatch",
    "metadata_loss",
    "value_mismatch",
]
SUPPORTED_INTERCHANGE_FORMATS = ("csv", "xlsx", "parquet", "sav", "zsav", "dta")


class InterchangeUnavailableError(RuntimeError):
    """Raised only when a caller explicitly requires an unavailable format."""

    def __init__(self, capability: "InterchangeCapabilityV1") -> None:
        self.capability = capability
        super().__init__(f"{capability.reason_code}: {capability.message}")


class InterchangeMetadataError(ValueError):
    """Raised when declared interchange metadata cannot be represented safely."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True)
class InterchangeCapabilityV1:
    target_format: str
    status: InterchangeStatus
    reason_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_format": self.target_format,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class InterchangeWriteResultV1:
    target_format: str
    status: WriteStatus
    path: str | None
    capability: InterchangeCapabilityV1

    def to_dict(self) -> dict[str, object]:
        return {
            "target_format": self.target_format,
            "status": self.status,
            "path": self.path,
            "capability": self.capability.to_dict(),
        }


@dataclass(frozen=True)
class RoundTripResultV1:
    target_format: str
    status: RoundTripStatus
    frame_equal: bool
    dtype_equal: bool
    schema_equal: bool
    path: str | None
    metadata_loss: MetadataLossManifestV1
    capability: InterchangeCapabilityV1
    restored_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "target_format": self.target_format,
            "status": self.status,
            "frame_equal": self.frame_equal,
            "dtype_equal": self.dtype_equal,
            "schema_equal": self.schema_equal,
            "path": self.path,
            "metadata_loss": self.metadata_loss.to_dict(),
            "capability": self.capability.to_dict(),
            "restored_metadata": dict(self.restored_metadata),
        }


@dataclass(frozen=True)
class InterchangeReadResultV1:
    """A typed read result that never hides native metadata loss."""

    target_format: str
    status: Literal["read", "unavailable"]
    path: str | None
    frame: pd.DataFrame | None
    metadata: Mapping[str, Any]
    capability: InterchangeCapabilityV1

    def to_dict(self) -> dict[str, object]:
        frame = self.frame
        return {
            "target_format": self.target_format,
            "status": self.status,
            "path": self.path,
            "frame_shape": None if frame is None else [int(frame.shape[0]), int(frame.shape[1])],
            "metadata": dict(self.metadata),
            "capability": self.capability.to_dict(),
        }


def _has_module(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _verified_import(name: str) -> Any | None:
    """Return an importable optional module, not just a find-spec result."""

    if not _has_module(name):
        return None
    try:
        module = importlib.import_module(name)
        # Exercise the normal import hook as well.  This matters when a
        # module is already present in sys.modules but its import boundary is
        # currently unavailable to a bounded consumer.
        __import__(name, fromlist=["*"])
        return module
    except Exception:
        return None


def _verified_pyarrow_adapter() -> tuple[Any, Any] | None:
    """Import and exercise the pyarrow adapter used by bounded readers."""

    pa = _verified_import("pyarrow")
    parquet = _verified_import("pyarrow.parquet")
    if pa is None or parquet is None:
        return None
    try:
        probe = pa.table({"__workbench_probe__": pa.array([1], type=pa.int64())})
        sink = pa.BufferOutputStream()
        parquet.write_table(probe, sink)
        reader = parquet.ParquetFile(pa.BufferReader(sink.getvalue()))
        if reader.metadata is None or reader.metadata.num_rows != 1:
            return None
    except Exception:
        return None
    return pa, parquet


def _parquet_adapter() -> tuple[Any, Any] | None:
    return _verified_pyarrow_adapter()


_PYREADSTAT_REQUIRED = ("read_sav", "write_sav", "read_dta", "write_dta")
_PYREADSTAT_UNAVAILABLE_MESSAGE = (
    "pyreadstat is unavailable or failed the bounded native statistical-file "
    "adapter probe."
)


def _pyreadstat_unavailable_capability(target_format: str) -> InterchangeCapabilityV1:
    return InterchangeCapabilityV1(
        target_format=target_format,
        status="unavailable",
        reason_code="optional_dependency",
        message=_PYREADSTAT_UNAVAILABLE_MESSAGE,
    )


def _pyreadstat_failure_capability(target_format: str) -> InterchangeCapabilityV1:
    """Return a stable unavailable result after an admitted adapter fails."""

    return InterchangeCapabilityV1(
        target_format=target_format,
        status="unavailable",
        reason_code="adapter_failure",
        message=(
            "The admitted pyreadstat adapter failed a bounded native "
            "interchange operation."
        ),
    )


def _adapter_failure_capability(target_format: str) -> InterchangeCapabilityV1:
    if target_format in _NATIVE_METADATA_FIELDS:
        return _pyreadstat_failure_capability(target_format)
    return InterchangeCapabilityV1(
        target_format=target_format,
        status="unavailable",
        reason_code="adapter_failure",
        message="The admitted interchange adapter failed a bounded operation.",
    )


_NATIVE_METADATA_FIELDS: dict[str, frozenset[str]] = {
    "sav": frozenset(
        {"variable_label", "value_labels", "measurement_level", "user_missing_values"}
    ),
    "zsav": frozenset(
        {"variable_label", "value_labels", "measurement_level", "user_missing_values"}
    ),
    "dta": frozenset({"variable_label", "value_labels", "user_missing_values"}),
}


def _pyreadstat_probe_succeeded(module: Any) -> bool:
    """Exercise the native adapter with one bounded, private data frame."""

    probe_frame = pd.DataFrame(
        {"workbench_probe": pd.Series([1], dtype="int64")}
    )
    with tempfile.TemporaryDirectory(prefix="workbench-pyreadstat-probe-") as directory:
        root = Path(directory)
        sav_path = root / "probe.sav"
        zsav_path = root / "probe.zsav"
        dta_path = root / "probe.dta"
        module.write_sav(probe_frame, str(sav_path))
        sav_restored, _sav_meta = module.read_sav(str(sav_path))
        module.write_sav(probe_frame, str(zsav_path), compress=True)
        zsav_restored, _zsav_meta = module.read_sav(str(zsav_path))
        module.write_dta(probe_frame, str(dta_path), version=15)
        dta_restored, _dta_meta = module.read_dta(str(dta_path))

    for restored in (sav_restored, zsav_restored, dta_restored):
        if not isinstance(restored, pd.DataFrame):
            return False
        if tuple(restored.columns) != tuple(probe_frame.columns):
            return False
        if len(restored) != 1 or restored.iloc[0, 0] != 1:
            return False
    return True


def _pyreadstat_module() -> Any | None:
    module = _verified_import("pyreadstat")
    if module is None:
        return None
    if not all(callable(getattr(module, name, None)) for name in _PYREADSTAT_REQUIRED):
        return None
    try:
        return module if _pyreadstat_probe_succeeded(module) else None
    except Exception:
        return None


def _parquet_engine() -> str | None:
    """Return an engine admitted by the bounded Parquet contract.

    The bounded reader relies on pyarrow's batch iterator for its explicit
    row-cap sentinel.  fastparquet is not admitted until an equivalent bounded
    adapter is implemented and verified, so capability discovery must not
    claim it is executable merely because its module is installed.
    """
    if _parquet_adapter() is not None:
        return "pyarrow"
    return None


_PARQUET_UNAVAILABLE_MESSAGE = (
    "pyarrow is required for the bounded Parquet interchange contract; "
    "fastparquet is not admitted without a verified bounded reader."
)


def _parquet_unavailable_capability() -> InterchangeCapabilityV1:
    return InterchangeCapabilityV1(
        target_format="parquet",
        status="unavailable",
        reason_code="optional_dependency",
        message=_PARQUET_UNAVAILABLE_MESSAGE,
    )


def interchange_capability(target_format: str) -> InterchangeCapabilityV1:
    normalized = str(target_format).strip().casefold()
    if normalized not in SUPPORTED_INTERCHANGE_FORMATS:
        return InterchangeCapabilityV1(
            target_format=normalized,
            status="unavailable",
            reason_code="unsupported_format",
            message=f"No Workbench reader/writer is registered for {normalized!r}.",
        )
    if normalized == "csv":
        return InterchangeCapabilityV1(normalized, "available")
    if normalized == "xlsx" and _verified_import("openpyxl") is None:
        return InterchangeCapabilityV1(
            normalized,
            "unavailable",
            "optional_dependency",
            "openpyxl is required for XLSX interchange.",
        )
    if normalized == "parquet" and _parquet_engine() is None:
        return _parquet_unavailable_capability()
    if normalized in {"sav", "zsav", "dta"} and _pyreadstat_module() is None:
        return _pyreadstat_unavailable_capability(normalized)
    return InterchangeCapabilityV1(normalized, "available")


def _loss_metadata(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, object]]:
    if not isinstance(metadata, Mapping):
        raise InterchangeMetadataError("invalid_metadata", "metadata must be a mapping")
    if "columns" not in metadata:
        # Accept the same top-level metadata vocabulary used by the confirmed
        # Workbench metadata registry.  Older callers may still provide the
        # compact ``{column: fields}`` shape, which remains supported below.
        top_level_fields = {
            "variable_labels",
            "value_labels",
            "measurement_level",
            "missing_policy",
            "roles",
            "sensitivity",
            "user_missing_values",
        }
        if top_level_fields.intersection(metadata):
            columns: set[str] = set()
            for field_name in top_level_fields:
                value = metadata.get(field_name)
                if value is not None:
                    if not isinstance(value, Mapping):
                        raise InterchangeMetadataError(
                            "invalid_metadata",
                            f"metadata.{field_name} must be a mapping",
                        )
                    columns.update(str(column) for column in value)
            result: dict[str, dict[str, object]] = {column: {} for column in columns}
            field_map = {
                "variable_labels": "variable_label",
                "value_labels": "value_labels",
                "measurement_level": "measurement_level",
                "missing_policy": "missing_policy",
                "roles": "role",
                "sensitivity": "sensitivity",
                "user_missing_values": "user_missing_values",
            }
            for source_field, column_field in field_map.items():
                value = metadata.get(source_field)
                if not isinstance(value, Mapping):
                    continue
                for column, field_value in value.items():
                    result.setdefault(str(column), {})[column_field] = field_value
            return result
        result: dict[str, Mapping[str, object]] = {}
        for column, fields in metadata.items():
            if not isinstance(fields, Mapping):
                raise InterchangeMetadataError(
                    "metadata_loss",
                    f"metadata for {column!r} must be a mapping",
                )
            result[str(column)] = fields
        return result
    columns = metadata.get("columns")
    if not isinstance(columns, Mapping):
        raise InterchangeMetadataError(
            "invalid_metadata", "metadata.columns must be a mapping"
        )
    result = {}
    for column, fields in columns.items():
        if not isinstance(fields, Mapping):
            raise InterchangeMetadataError(
                "metadata_loss",
                f"metadata for column {column!r} must be a mapping",
            )
        result[str(column)] = fields
    dataset = {
        key: value
        for key, value in metadata.items()
        if key in {"weight", "split", "group"}
    }
    if dataset:
        result["__dataset__"] = dataset
    return result


def _metadata_columns(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, object]]:
    """Return column declarations in one bounded internal shape."""

    return {
        column: fields
        for column, fields in _loss_metadata(metadata).items()
        if column != "__dataset__"
    }


def _metadata_json(value: object) -> str:
    return str(value) if isinstance(value, str) else repr(value)


def _canonical_value_key(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _coerce_native_value_key(frame: pd.DataFrame, column: str, value: object) -> object:
    """Convert canonical string metadata keys to the column's scalar type."""

    if column not in frame.columns:
        raise InterchangeMetadataError(
            "metadata_column_unknown",
            f"metadata names unknown column {column!r}",
        )
    if not isinstance(value, str):
        return value
    series = frame[column]
    if pd.api.types.is_integer_dtype(series.dtype):
        try:
            parsed = float(value)
        except ValueError as exc:
            raise InterchangeMetadataError(
                "metadata_value_label_invalid",
                f"value label {value!r} is not numeric for {column!r}",
            ) from exc
        if not parsed.is_integer():
            raise InterchangeMetadataError(
                "metadata_value_label_invalid",
                f"value label {value!r} is not integral for {column!r}",
            )
        return int(parsed)
    if pd.api.types.is_float_dtype(series.dtype):
        try:
            return float(value)
        except ValueError as exc:
            raise InterchangeMetadataError(
                "metadata_value_label_invalid",
                f"value label {value!r} is not numeric for {column!r}",
            ) from exc
    return value


def _native_write_options(
    frame: pd.DataFrame,
    target_format: str,
    metadata: Mapping[str, Any],
) -> dict[str, object]:
    """Map confirmed Workbench metadata to the admitted pyreadstat kwargs."""

    declarations = _metadata_columns(metadata)
    options: dict[str, object] = {}
    column_labels: dict[str, str] = {}
    value_labels: dict[str, dict[object, str]] = {}
    measurement: dict[str, str] = {}
    sav_missing: dict[str, list[object]] = {}
    dta_missing: dict[str, list[str]] = {}

    for column, fields in declarations.items():
        if column not in frame.columns:
            raise InterchangeMetadataError(
                "metadata_column_unknown",
                f"metadata names unknown column {column!r}",
            )
        variable_label = fields.get("variable_label")
        if variable_label is not None:
            if type(variable_label) is not str or not variable_label.strip():
                raise InterchangeMetadataError(
                    "metadata_variable_label_invalid",
                    f"variable_label for {column!r} must be a non-empty string",
                )
            column_labels[column] = variable_label

        raw_labels = fields.get("value_labels")
        if raw_labels is not None:
            if not isinstance(raw_labels, Mapping):
                raise InterchangeMetadataError(
                    "metadata_value_labels_invalid",
                    f"value_labels for {column!r} must be a mapping",
                )
            value_labels[column] = {
                _coerce_native_value_key(frame, column, raw_value): str(label)
                for raw_value, label in raw_labels.items()
            }

        raw_measure = fields.get("measurement_level")
        if raw_measure is not None and target_format in {"sav", "zsav"}:
            if raw_measure not in {"nominal", "ordinal", "scale"}:
                raise InterchangeMetadataError(
                    "metadata_measurement_level_invalid",
                    f"measurement_level for {column!r} is not supported by pyreadstat",
                )
            measurement[column] = str(raw_measure)

        raw_missing = fields.get("user_missing_values")
        if raw_missing is not None:
            if not isinstance(raw_missing, (list, tuple)):
                raise InterchangeMetadataError(
                    "metadata_user_missing_invalid",
                    f"user_missing_values for {column!r} must be a list",
                )
            if target_format in {"sav", "zsav"}:
                if len(raw_missing) > 3 or any(
                    isinstance(value, bool)
                    or not isinstance(value, Real)
                    or not math.isfinite(float(value))
                    for value in raw_missing
                ):
                    raise InterchangeMetadataError(
                        "metadata_user_missing_invalid",
                        "SAV user_missing_values must contain at most three finite numeric values",
                    )
                sav_missing[column] = list(raw_missing)
            elif all(
                type(value) is str and len(value) == 1 and value.lower() in "abcdefghijklmnopqrstuvwxyz"
                for value in raw_missing
            ):
                dta_missing[column] = [str(value) for value in raw_missing]

    if column_labels:
        options["column_labels"] = column_labels
    if value_labels:
        options["variable_value_labels"] = value_labels
    if target_format in {"sav", "zsav"}:
        if measurement:
            options["variable_measure"] = measurement
        if sav_missing:
            options["missing_ranges"] = sav_missing
    elif dta_missing:
        options["missing_user_values"] = dta_missing
    return options


def _native_metadata_from_pyreadstat(
    frame: pd.DataFrame,
    native_metadata: object,
) -> dict[str, object]:
    """Project pyreadstat metadata into the bounded Workbench vocabulary."""

    columns: dict[str, dict[str, object]] = {
        str(column): {} for column in frame.columns
    }
    names = list(getattr(native_metadata, "column_names", ()) or ())
    labels = list(getattr(native_metadata, "column_labels", ()) or ())
    for index, column in enumerate(names):
        if index < len(labels) and labels[index]:
            columns.setdefault(str(column), {})["variable_label"] = str(labels[index])

    for column, labels_by_value in (
        getattr(native_metadata, "variable_value_labels", {}) or {}
    ).items():
        if not isinstance(labels_by_value, Mapping):
            continue
        columns.setdefault(str(column), {})["value_labels"] = {
            _canonical_value_key(value): str(label)
            for value, label in labels_by_value.items()
        }

    for column, measure in (getattr(native_metadata, "variable_measure", {}) or {}).items():
        if measure and measure != "unknown":
            columns.setdefault(str(column), {})["measurement_level"] = str(measure)

    missing_user_values = getattr(native_metadata, "missing_user_values", {}) or {}
    for column, values in missing_user_values.items():
        if isinstance(values, (list, tuple)) and values:
            columns.setdefault(str(column), {})["user_missing_values"] = [str(value) for value in values]

    missing_ranges = getattr(native_metadata, "missing_ranges", {}) or {}
    for column, ranges in missing_ranges.items():
        values: list[object] = []
        for item in ranges or ():
            if isinstance(item, Mapping):
                low = item.get("lo")
                high = item.get("hi")
            else:
                low = getattr(item, "lo", None)
                high = getattr(item, "hi", None)
            if low == high:
                values.append(low)
        if values:
            columns.setdefault(str(column), {})["user_missing_values"] = values
    return {"columns": columns}


def _native_loss_manifest(
    metadata: Mapping[str, Any],
    target_format: str,
    restored_metadata: Mapping[str, Any] | None = None,
) -> MetadataLossManifestV1:
    loss_declarations = _loss_metadata(metadata)
    loss_restored = _loss_metadata(restored_metadata or {}) if restored_metadata else {}
    declarations = {
        column: fields for column, fields in loss_declarations.items() if column != "__dataset__"
    }
    restored = {
        column: fields for column, fields in loss_restored.items() if column != "__dataset__"
    }
    supported = _NATIVE_METADATA_FIELDS.get(target_format, frozenset())
    items: list[MetadataLossItemV1] = []
    for column, fields in declarations.items():
        for field_name, original in fields.items():
            field = f"{column}.{field_name}"
            status = "preserved"
            reason = "native adapter preserves this metadata field"
            target_repr = "native_metadata"
            if field_name not in supported:
                status = "not_supported"
                reason = f"target format {target_format!r} has no admitted mapping"
                target_repr = "not_supported"
            elif target_format == "dta" and field_name == "user_missing_values":
                values = original if isinstance(original, (list, tuple)) else ()
                if not all(
                    type(value) is str
                    and len(value) == 1
                    and value.lower() in "abcdefghijklmnopqrstuvwxyz"
                    for value in values
                ):
                    status = "converted"
                    reason = "Stata user missing values only admit single-letter codes"
                    target_repr = "stata_letter_missing_values"
            if restored_metadata is not None and status == "preserved":
                restored_value = restored.get(column, {}).get(field_name)
                if field_name == "value_labels":
                    original_value = {
                        _canonical_value_key(key): str(value)
                        for key, value in (original.items() if isinstance(original, Mapping) else ())
                    }
                    restored_value = {
                        _canonical_value_key(key): str(value)
                        for key, value in (restored_value.items() if isinstance(restored_value, Mapping) else ())
                    }
                elif field_name == "user_missing_values":
                    original_value = list(original) if isinstance(original, (list, tuple)) else original
                    restored_value = list(restored_value) if isinstance(restored_value, (list, tuple)) else restored_value
                else:
                    original_value = original
                if original_value != restored_value:
                    status = "converted"
                    reason = "native adapter returned a different metadata representation"
                    target_repr = "read_native_metadata"
            items.append(
                MetadataLossItemV1(
                    field=field,
                    status=status,
                    reason=reason,
                    original_representation=_metadata_json(original),
                    target_representation=target_repr,
                )
            )
    dataset_fields = loss_declarations.get("__dataset__", {})
    for field_name, original in dataset_fields.items():
        items.append(
            MetadataLossItemV1(
                field=f"__dataset__.{field_name}",
                status="not_supported",
                reason=f"target format {target_format!r} has no admitted dataset metadata mapping",
                original_representation=_metadata_json(original),
                target_representation="not_supported",
            )
        )
    return MetadataLossManifestV1(
        source_format="workbench-json",
        target_format=target_format,
        items=tuple(items),
    )


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> tuple[bool, bool, bool]:
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    dtype_equal = tuple(str(dtype) for dtype in left.dtypes) == tuple(
        str(dtype) for dtype in right.dtypes
    )
    schema_equal = tuple(left.columns) == tuple(right.columns) and dtype_equal
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)
    except (AssertionError, TypeError, ValueError):
        return False, dtype_equal, schema_equal
    return True, dtype_equal, schema_equal


def _path_entry_exists(path: Path) -> bool:
    """Treat dangling symlinks as existing user-owned path entries."""

    return path.exists() or path.is_symlink()


def _write_frame(
    frame: pd.DataFrame,
    target_format: str,
    path: Path,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if target_format == "csv":
        frame.to_csv(path, index=False)
        return
    if target_format == "xlsx":
        frame.to_excel(path, index=False)
        return
    if target_format == "parquet":
        engine = _parquet_engine()
        if engine is None:
            raise InterchangeUnavailableError(interchange_capability(target_format))
        try:
            frame.to_parquet(path, index=False, engine=engine)
        except (ImportError, ModuleNotFoundError) as exc:
            raise InterchangeUnavailableError(interchange_capability(target_format)) from exc
        return
    if target_format in {"sav", "zsav", "dta"}:
        pyreadstat = _pyreadstat_module()
        if pyreadstat is None:
            raise InterchangeUnavailableError(
                _pyreadstat_unavailable_capability(target_format)
            )

        try:
            options = _native_write_options(frame, target_format, metadata or {})
            if target_format == "dta":
                pyreadstat.write_dta(frame, str(path), version=15, **options)
            else:
                pyreadstat.write_sav(
                    frame,
                    str(path),
                    compress=target_format == "zsav",
                    **options,
                )
        except InterchangeMetadataError:
            raise
        except Exception as exc:
            raise InterchangeUnavailableError(
                _pyreadstat_failure_capability(target_format)
            ) from exc
        return
    raise InterchangeUnavailableError(interchange_capability(target_format))


def _read_frame_with_metadata(
    target_format: str,
    path: Path,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    if target_format == "csv":
        return pd.read_csv(path), {}
    if target_format == "xlsx":
        return pd.read_excel(path), {}
    if target_format == "parquet":
        engine = _parquet_engine()
        if engine is None:
            raise InterchangeUnavailableError(interchange_capability(target_format))
        try:
            return pd.read_parquet(path, engine=engine), {}
        except (ImportError, ModuleNotFoundError) as exc:
            raise InterchangeUnavailableError(interchange_capability(target_format)) from exc
        except Exception as exc:
            raise InterchangeUnavailableError(
                _adapter_failure_capability(target_format)
            ) from exc
    if target_format in {"sav", "zsav", "dta"}:
        pyreadstat = _pyreadstat_module()
        if pyreadstat is None:
            raise InterchangeUnavailableError(
                _pyreadstat_unavailable_capability(target_format)
            )

        try:
            if target_format == "dta":
                restored, native_metadata = pyreadstat.read_dta(
                    str(path), user_missing=True
                )
            else:
                restored, native_metadata = pyreadstat.read_sav(
                    str(path), user_missing=True
                )
        except Exception as exc:
            raise InterchangeUnavailableError(
                _pyreadstat_failure_capability(target_format)
            ) from exc
        if not isinstance(restored, pd.DataFrame):
            raise InterchangeUnavailableError(
                _pyreadstat_failure_capability(target_format)
            )
        return restored, _native_metadata_from_pyreadstat(restored, native_metadata)
    raise InterchangeUnavailableError(interchange_capability(target_format))


def _read_frame(target_format: str, path: Path) -> pd.DataFrame:
    """Backward-compatible frame-only reader for internal bounded consumers."""

    return _read_frame_with_metadata(target_format, path)[0]


def read_interchange_frame(
    *,
    target_format: str,
    path: Path | str,
) -> InterchangeReadResultV1:
    """Read one interchange artifact with typed native metadata projection."""

    normalized = str(target_format).strip().casefold()
    capability = interchange_capability(normalized)
    if capability.status != "available":
        return InterchangeReadResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            frame=None,
            metadata={},
            capability=capability,
        )
    source_path = Path(path).expanduser()
    try:
        frame, metadata = _read_frame_with_metadata(normalized, source_path)
    except InterchangeUnavailableError as error:
        return InterchangeReadResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            frame=None,
            metadata={},
            capability=error.capability,
        )
    if not isinstance(frame, pd.DataFrame):
        capability = (
            _pyreadstat_failure_capability(normalized)
            if normalized in _NATIVE_METADATA_FIELDS
            else InterchangeCapabilityV1(
                target_format=normalized,
                status="unavailable",
                reason_code="adapter_failure",
                message="The interchange adapter returned a non-DataFrame result.",
            )
        )
        return InterchangeReadResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            frame=None,
            metadata={},
            capability=capability,
        )
    return InterchangeReadResultV1(
        target_format=normalized,
        status="read",
        path=str(source_path),
        frame=frame,
        metadata=metadata,
        capability=capability,
    )


def write_interchange_frame(
    frame: pd.DataFrame,
    *,
    target_format: str,
    path: Path | str,
    metadata: Mapping[str, Any] | None = None,
) -> InterchangeWriteResultV1:
    """Write one real interchange artifact or return typed unavailability."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    normalized = str(target_format).strip().casefold()
    capability = interchange_capability(normalized)
    if capability.status != "available":
        return InterchangeWriteResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            capability=capability,
        )
    target_path = Path(path).expanduser()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_fd, staging_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".workbench-staging",
        dir=target_path.parent,
    )
    os.close(staging_fd)
    staging_path = Path(staging_name)
    staging_path.unlink(missing_ok=True)
    try:
        _write_frame(frame, normalized, staging_path, metadata)
        if not staging_path.is_file() or staging_path.stat().st_size <= 0:
            raise InterchangeUnavailableError(
                _adapter_failure_capability(normalized)
            )
        os.replace(staging_path, target_path)
    except InterchangeUnavailableError as error:
        staging_path.unlink(missing_ok=True)
        return InterchangeWriteResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            capability=error.capability,
        )
    except InterchangeMetadataError:
        staging_path.unlink(missing_ok=True)
        raise
    except Exception:
        staging_path.unlink(missing_ok=True)
        return InterchangeWriteResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            capability=_adapter_failure_capability(normalized),
        )
    return InterchangeWriteResultV1(
        target_format=normalized,
        status="written",
        path=str(target_path),
        capability=capability,
    )


def round_trip_frame(
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, Any],
    target_format: str,
    directory: Path | str,
) -> RoundTripResultV1:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas DataFrame")
    normalized = str(target_format).strip().casefold()
    capability = interchange_capability(normalized)
    if normalized in _NATIVE_METADATA_FIELDS:
        loss = _native_loss_manifest(metadata, normalized)
    else:
        loss = build_metadata_loss_manifest(
            source_format="workbench-json",
            target_format=normalized,
            metadata=_loss_metadata(metadata),
        )
    if capability.status != "available":
        return RoundTripResultV1(
            target_format=normalized,
            status="unavailable",
            frame_equal=False,
            dtype_equal=False,
            schema_equal=False,
            path=None,
            metadata_loss=loss,
            capability=capability,
            restored_metadata={},
        )
    target_dir = Path(directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"roundtrip.{normalized}"
    path_existed_before = _path_entry_exists(path)
    write_result = write_interchange_frame(
        frame,
        target_format=normalized,
        path=path,
        metadata=metadata,
    )
    if write_result.status != "written":
        return RoundTripResultV1(
            target_format=normalized,
            status="unavailable",
            frame_equal=False,
            dtype_equal=False,
            schema_equal=False,
            path=None,
            metadata_loss=loss,
            capability=write_result.capability,
            restored_metadata={},
        )
    try:
        restored, restored_metadata = _read_frame_with_metadata(normalized, path)
    except InterchangeUnavailableError as error:
        if not path_existed_before:
            path.unlink(missing_ok=True)
        return RoundTripResultV1(
            target_format=normalized,
            status="unavailable",
            frame_equal=False,
            dtype_equal=False,
            schema_equal=False,
            path=None,
            metadata_loss=loss,
            capability=error.capability,
            restored_metadata={},
        )
    if normalized in _NATIVE_METADATA_FIELDS:
        loss = _native_loss_manifest(metadata, normalized, restored_metadata)
    frame_equal, dtype_equal, schema_equal = _frames_equal(frame, restored)
    if not schema_equal:
        status: RoundTripStatus = "schema_mismatch"
    elif not frame_equal:
        status = "value_mismatch"
    elif loss.has_loss:
        status = "metadata_loss"
    else:
        status = "verified"
    return RoundTripResultV1(
        target_format=normalized,
        status=status,
        frame_equal=frame_equal,
        dtype_equal=dtype_equal,
        schema_equal=schema_equal,
        path=str(path),
        metadata_loss=loss,
        capability=capability,
        restored_metadata=restored_metadata,
    )


__all__ = [
    "InterchangeCapabilityV1",
    "InterchangeMetadataError",
    "InterchangeReadResultV1",
    "InterchangeUnavailableError",
    "InterchangeWriteResultV1",
    "RoundTripResultV1",
    "SUPPORTED_INTERCHANGE_FORMATS",
    "interchange_capability",
    "read_interchange_frame",
    "round_trip_frame",
    "write_interchange_frame",
]
