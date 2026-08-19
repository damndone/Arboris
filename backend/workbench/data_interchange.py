"""Executable, loss-explicit interchange contracts for data consumers.

The supported tabular formats are intentionally small.  Every advertised
format is exercised by a real write/read pair; optional statistical formats
remain typed unavailable when their dependency is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd

from .metadata import MetadataLossManifestV1, build_metadata_loss_manifest


InterchangeStatus = Literal["available", "unavailable"]
RoundTripStatus = Literal["verified", "unavailable"]
SUPPORTED_INTERCHANGE_FORMATS = ("csv", "xlsx", "parquet", "sav", "zsav", "dta")


class InterchangeUnavailableError(RuntimeError):
    """Raised only when a caller explicitly requires an unavailable format."""

    def __init__(self, capability: "InterchangeCapabilityV1") -> None:
        self.capability = capability
        super().__init__(f"{capability.reason_code}: {capability.message}")


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
class RoundTripResultV1:
    target_format: str
    status: RoundTripStatus
    frame_equal: bool
    dtype_equal: bool
    path: str | None
    metadata_loss: MetadataLossManifestV1
    capability: InterchangeCapabilityV1

    def to_dict(self) -> dict[str, object]:
        return {
            "target_format": self.target_format,
            "status": self.status,
            "frame_equal": self.frame_equal,
            "dtype_equal": self.dtype_equal,
            "path": self.path,
            "metadata_loss": self.metadata_loss.to_dict(),
            "capability": self.capability.to_dict(),
        }


def _has_module(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


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
    if normalized == "xlsx" and not _has_module("openpyxl"):
        return InterchangeCapabilityV1(
            normalized,
            "unavailable",
            "optional_dependency",
            "openpyxl is required for XLSX interchange.",
        )
    if normalized == "parquet" and not (_has_module("pyarrow") or _has_module("fastparquet")):
        return InterchangeCapabilityV1(
            normalized,
            "unavailable",
            "optional_dependency",
            "pyarrow or fastparquet is required for Parquet interchange.",
        )
    if normalized in {"sav", "zsav", "dta"} and not _has_module("pyreadstat"):
        return InterchangeCapabilityV1(
            normalized,
            "unavailable",
            "optional_dependency",
            "pyreadstat is required for native statistical-file interchange.",
        )
    return InterchangeCapabilityV1(normalized, "available")


def _loss_metadata(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, object]]:
    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")
    if "columns" not in metadata:
        return {str(column): fields for column, fields in metadata.items()}
    columns = metadata.get("columns")
    if not isinstance(columns, Mapping):
        raise TypeError("metadata.columns must be a mapping")
    result: dict[str, Mapping[str, object]] = {
        str(column): fields for column, fields in columns.items() if isinstance(fields, Mapping)
    }
    dataset = {
        key: value
        for key, value in metadata.items()
        if key in {"weight", "split", "group"}
    }
    if dataset:
        result["__dataset__"] = dataset
    return result


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> tuple[bool, bool]:
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    dtype_equal = tuple(str(dtype) for dtype in left.dtypes) == tuple(
        str(dtype) for dtype in right.dtypes
    )
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)
    except (AssertionError, TypeError, ValueError):
        return False, dtype_equal
    return True, dtype_equal


def _write_and_read(frame: pd.DataFrame, target_format: str, path: Path) -> pd.DataFrame:
    if target_format == "csv":
        frame.to_csv(path, index=False)
        return pd.read_csv(path)
    if target_format == "xlsx":
        frame.to_excel(path, index=False)
        return pd.read_excel(path)
    if target_format == "parquet":
        frame.to_parquet(path, index=False)
        return pd.read_parquet(path)
    if target_format in {"sav", "zsav", "dta"}:
        import pyreadstat

        if target_format == "dta":
            pyreadstat.write_dta(frame, str(path), version=15)
            restored, _meta = pyreadstat.read_dta(str(path))
        else:
            pyreadstat.write_sav(frame, str(path), compress=target_format == "zsav")
            restored, _meta = pyreadstat.read_sav(str(path))
        return restored
    raise InterchangeUnavailableError(interchange_capability(target_format))


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
            path=None,
            metadata_loss=loss,
            capability=capability,
        )
    target_dir = Path(directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"roundtrip.{normalized}"
    restored = _write_and_read(frame, normalized, path)
    frame_equal, dtype_equal = _frames_equal(frame, restored)
    if not frame_equal:
        raise ValueError(f"{normalized} round-trip changed values or column order")
    return RoundTripResultV1(
        target_format=normalized,
        status="verified",
        frame_equal=True,
        dtype_equal=dtype_equal,
        path=str(path),
        metadata_loss=loss,
        capability=capability,
    )


__all__ = [
    "InterchangeCapabilityV1",
    "InterchangeUnavailableError",
    "RoundTripResultV1",
    "SUPPORTED_INTERCHANGE_FORMATS",
    "interchange_capability",
    "round_trip_frame",
]
