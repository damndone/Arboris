"""Concrete canonical-v1 numeric kernel loader; no data enters its audit record.

Build with the current interpreter via ``native/canonical_numbers/build.py``.
The default auto mode uses that local binary if present. Only an absent binary
selects the reference encoder; a broken or incompatible binary raises.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import logging
from pathlib import Path
import sysconfig

EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
_LOGGER = logging.getLogger(__name__)
# The first accepted component boundary. The 4k cold-load encoding regression
# remains in the original evidence; smaller sizes have not earned native use.
MEASURED_MIN_ITEMS = 100_000


def _extension_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "local/native-canonical"


def _load_extension(path: Path):
    spec = importlib.util.spec_from_file_location("_canonical_numbers", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load native canonical extension")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = getattr(module, "ABI_VERSION", None)
    if type(version) is not int or version != 1:
        raise RuntimeError("native canonical ABI mismatch; rebuild with this interpreter")
    return module


@lru_cache(maxsize=1)
def _load():
    directory = _extension_directory()
    path = directory / ("_canonical_numbers" + EXT_SUFFIX)
    if path.is_file():
        result = _load_extension(path), "native", "extension_loaded"
    elif any(directory.glob("_canonical_numbers*")):
        raise RuntimeError("native canonical interpreter ABI mismatch; rebuild with this interpreter")
    else:
        result = None, "reference", "extension_not_built"
    _LOGGER.info(
        "canonical numeric engine=%s reason=%s", result[1], result[2],
        extra={"canonical_engine": result[1], "canonical_reason": result[2]},
    )
    return result


def backend_info() -> dict[str, str | int]:
    """Return an inspectable, data-free record of the selected numeric engine."""
    _, engine, reason = _load()
    return {"engine": engine, "reason": reason,
            "measured_min_items": MEASURED_MIN_ITEMS, "small_sequence_engine": "reference"}


@lru_cache(maxsize=1)
def small_sequence_reference() -> None:
    """Record the reference size policy once, without recording an input."""
    _LOGGER.info(
        "canonical numeric engine=reference reason=below_measured_minimum",
        extra={"canonical_engine": "reference", "canonical_reason": "below_measured_minimum"},
    )


def encode_numbers(values: list | tuple) -> str | None:
    """Return native canonical JSON, or None for the explicit reference path."""
    module, _, _ = _load()
    return None if module is None else module.encode_numbers(values)


def encode_analysis_sample_v1(row_set, row_order) -> bytes | None:
    """Encode exact decimal IDs for the sample fingerprint candidate.

    Only missing builds or unsupported input shapes return None. Present old,
    incompatible or broken builds and computation failures propagate. The
    public fingerprint selects this at its own 1M-member evidence cutoff;
    complete-workflow performance and bounded cancellation remain unverified.
    """
    module, _, _ = _load()
    if module is None:
        return None
    version = getattr(module, 'ANALYSIS_SAMPLE_ABI_VERSION', None)
    if type(version) is not int or version != 1:
        raise RuntimeError('native canonical sample ABI mismatch; rebuild with this interpreter')
    source = Path(__file__).resolve().parents[2] / 'native/canonical_numbers/canonical_numbers.cpp'
    if getattr(module, 'ANALYSIS_SAMPLE_SOURCE_SHA256', None) != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('native canonical sample source digest mismatch; rebuild current source')
    encode = getattr(module, 'encode_analysis_sample_v1', None)
    if not callable(encode):
        raise RuntimeError('native canonical sample entry point missing; rebuild current source')
    result = encode(row_set, row_order)
    if result is not None and type(result) is not bytes:
        raise RuntimeError('native canonical sample returned an invalid byte result')
    return result
