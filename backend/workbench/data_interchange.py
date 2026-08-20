"""Executable, loss-explicit interchange contracts for data consumers.

The supported tabular formats are intentionally small.  Every advertised
format is exercised by a real write/read pair; optional statistical formats
remain typed unavailable when their dependency is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd

from .metadata import MetadataLossManifestV1, build_metadata_loss_manifest


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


def _pyreadstat_module() -> Any | None:
    module = _verified_import("pyreadstat")
    if module is None:
        return None
    required = ("read_sav", "write_sav", "read_dta", "write_dta")
    if not all(callable(getattr(module, name, None)) for name in required):
        return None
    return module


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
        return InterchangeCapabilityV1(
            normalized,
            "unavailable",
            "optional_dependency",
            "pyreadstat is required for native statistical-file interchange.",
        )
    return InterchangeCapabilityV1(normalized, "available")


def _loss_metadata(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, object]]:
    if not isinstance(metadata, Mapping):
        raise InterchangeMetadataError("invalid_metadata", "metadata must be a mapping")
    if "columns" not in metadata:
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


def _write_frame(frame: pd.DataFrame, target_format: str, path: Path) -> None:
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
            raise InterchangeUnavailableError(interchange_capability(target_format))

        try:
            if target_format == "dta":
                pyreadstat.write_dta(frame, str(path), version=15)
            else:
                pyreadstat.write_sav(frame, str(path), compress=target_format == "zsav")
        except (ImportError, ModuleNotFoundError) as exc:
            raise InterchangeUnavailableError(interchange_capability(target_format)) from exc
        return
    raise InterchangeUnavailableError(interchange_capability(target_format))


def _read_frame(target_format: str, path: Path) -> pd.DataFrame:
    if target_format == "csv":
        return pd.read_csv(path)
    if target_format == "xlsx":
        return pd.read_excel(path)
    if target_format == "parquet":
        engine = _parquet_engine()
        if engine is None:
            raise InterchangeUnavailableError(interchange_capability(target_format))
        try:
            return pd.read_parquet(path, engine=engine)
        except (ImportError, ModuleNotFoundError) as exc:
            raise InterchangeUnavailableError(interchange_capability(target_format)) from exc
    if target_format in {"sav", "zsav", "dta"}:
        pyreadstat = _pyreadstat_module()
        if pyreadstat is None:
            raise InterchangeUnavailableError(interchange_capability(target_format))

        try:
            if target_format == "dta":
                restored, _meta = pyreadstat.read_dta(str(path))
            else:
                restored, _meta = pyreadstat.read_sav(str(path))
        except (ImportError, ModuleNotFoundError) as exc:
            raise InterchangeUnavailableError(interchange_capability(target_format)) from exc
        return restored
    raise InterchangeUnavailableError(interchange_capability(target_format))


def write_interchange_frame(
    frame: pd.DataFrame,
    *,
    target_format: str,
    path: Path | str,
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
    try:
        _write_frame(frame, normalized, target_path)
    except InterchangeUnavailableError as error:
        return InterchangeWriteResultV1(
            target_format=normalized,
            status="unavailable",
            path=None,
            capability=error.capability,
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
        )
    target_dir = Path(directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"roundtrip.{normalized}"
    write_result = write_interchange_frame(frame, target_format=normalized, path=path)
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
        )
    try:
        restored = _read_frame(normalized, path)
    except InterchangeUnavailableError as error:
        return RoundTripResultV1(
            target_format=normalized,
            status="unavailable",
            frame_equal=False,
            dtype_equal=False,
            schema_equal=False,
            path=None,
            metadata_loss=loss,
            capability=error.capability,
        )
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
    )


__all__ = [
    "InterchangeCapabilityV1",
    "InterchangeMetadataError",
    "InterchangeUnavailableError",
    "InterchangeWriteResultV1",
    "RoundTripResultV1",
    "SUPPORTED_INTERCHANGE_FORMATS",
    "interchange_capability",
    "round_trip_frame",
    "write_interchange_frame",
]
