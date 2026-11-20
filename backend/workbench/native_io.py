"""Native output encoders (native/io_writers) that write the bytes their Python references write.

Build with ``native/io_writers/build.py``. An absent build selects the references. A
build for another ABI fails. A build that disagrees with its references on the load-time
fixtures stands aside with a warning, because then this Python's float repr, json or csv
module is not the one the encoders were checked against. Every encoder returns None for a
shape it does not handle, and the caller then runs the reference.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import logging
import math
import struct
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any


_LOG = logging.getLogger(__name__)
_ABI_VERSION = 1
_NAME = "_arboris_io" + sysconfig.get_config_var("EXT_SUFFIX")
DTA_MISSING_DOUBLE = struct.pack("<Q", 0x7FE0000000000000)
DTA_MISSING_LONG = struct.pack("<I", 0x7FFFFFE5)


def _directory() -> Path:
    return Path(__file__).resolve().parents[2] / "local/native-io"


def _open(path: Path):
    spec = importlib.util.spec_from_file_location("_arboris_io", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load the native io extension")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = getattr(module, "ABI_VERSION", None)
    if type(version) is not int or version != _ABI_VERSION:
        raise RuntimeError("native io ABI mismatch; rebuild with native/io_writers/build.py")
    return module


@lru_cache(maxsize=1)
def module():
    """The loaded extension, or None for the Python references."""
    directory = _directory()
    path = directory / _NAME
    if not path.is_file():
        if any(directory.glob("_arboris_io*")):
            raise RuntimeError("native io interpreter ABI mismatch; rebuild with this interpreter")
        return None
    from .native_build import NativeBuildError, verify_build

    try:
        verify_build(Path(__file__).resolve().parents[2] / "native/io_writers", directory)
    except NativeBuildError as error:
        raise RuntimeError(f"{error}") from error
    loaded = _open(path)
    failed = _first_disagreement(loaded)
    if failed:
        _LOG.warning("native io %s differs from its Python reference; using the Python path", failed)
        return None
    return loaded


# --------------------------------------------------------------- references for the self-check

def _json_cases() -> list[Any]:
    floats = [0.1, -0.0, 1e16, 1e-7, 123456789.125, 5e-324, 1.7976931348623157e308, float("nan"),
              float("inf"), -float("inf"), 2.0**53 + 2, 1 / 3]
    return [
        {"a": floats, "b": [1, -2, 10**30, True, False, None], "c": {}, "d": [], "e": ()},
        {"text": ["plain", 'q"uote', "back\\slash", "\b\f\n\r\t\x00\x1f\x7f", "é中文", "😀", " "]},
        [{"nested": [[[]], [{}], [{"z": 1, "a": 2}]]}],
        {"z": 1, "y": {"b": 2, "a": [3, {"d": 4, "c": 5}]}, "é": 0, "E": 1},
    ]


def _json_options() -> list[dict[str, Any]]:
    return [
        {"indent": 2, "ensure_ascii": False},
        {"indent": 2, "ensure_ascii": True},
        {"indent": None, "sort_keys": True},
        {"indent": 0, "sort_keys": True, "ensure_ascii": False},
        {"indent": None, "separators": (",", ":"), "ensure_ascii": False},
    ]


def _reference_json_safe(value: Any) -> Any:
    import numpy as np  # loaded with the first conversion, so importing this module stays cheap for the CLI

    kind = type(value)
    if kind is float:
        return value if math.isfinite(value) else None
    if kind is dict:
        return {str(key): _reference_json_safe(item) for key, item in value.items()}
    if kind is list:
        return [_reference_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _reference_json_safe(value.item())
    return value


def _reference_dta_rows(columns: list[tuple], rows: int) -> bytes:
    out = bytearray()
    for row in range(rows):
        for column in columns:
            kind, values = column[0], column[1]
            if kind == "d":
                number = float(values[row])
                out += DTA_MISSING_DOUBLE if math.isnan(number) else struct.pack("<d", number)
            elif kind == "l":
                missing = column[2] is not None and bool(column[2][row])
                out += DTA_MISSING_LONG if missing else struct.pack("<i", int(values[row]))
            else:
                width = column[2]
                text = b"" if values[row] is None else values[row].encode("utf-8").split(b"\0", 1)[0]
                out += text + b"\0" * (width - len(text))
    return bytes(out)


def _csv_reference(rows: list[list[Any]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode("utf-8")


def _first_disagreement(loaded) -> str | None:
    import numpy as np

    for value in _json_cases():
        for options in _json_options():
            separators = options.get("separators") or ((",", ": ") if options.get("indent") is not None else (", ", ": "))
            indent = options.get("indent")
            native = loaded.encode_json(value, None if indent is None else " " * indent, options.get("sort_keys", False),
                                        options.get("ensure_ascii", True), True, *separators)
            if native != json.dumps(value, **options).encode("utf-8"):
                return "encode_json"
    if loaded.encode_json({"a": "\ud800"}, None, False, False, True, ", ", ": ") is not None:
        return "encode_json"
    sample = {"a": [1.5, float("nan"), {"b": np.float64(2.5), 3: [np.int64(4), float("inf")]}], "c": None, 4: True}
    if loaded.json_safe(sample, _reference_json_safe) != _reference_json_safe(sample):
        return "json_safe"
    from .canonical import _canonical_float, _encode_numbers

    rng = np.random.default_rng(20261103)
    floats = [*rng.normal(size=500).tolist(), *(10.0 ** np.arange(-30, 30)).tolist(), 1e-6, 9.99e-7, 1e21,
              9.999e20, -0.0, 0.0, 5e-324, 1.7976931348623157e308, 0.1, 100.0, 123456789012345680.0]
    integers = [0, -1, 2**63 - 1, -(2**63), *rng.integers(-10**12, 10**12, size=200).tolist()]
    if (loaded.canonical_list(floats) != "[" + ",".join(_canonical_float(item) for item in floats) + "]"
            or loaded.canonical_list(integers) != "[" + ",".join(_encode_numbers(integers)) + "]"
            or loaded.canonical_list(["a", "1 2", "~"]) != '["a","1 2","~"]'
            or loaded.canonical_list([1, 1.0]) is not None
            or loaded.canonical_list_kind(["a", 'b"']) != 0 or loaded.canonical_list_kind([1.0, float("nan")]) != 0
            or loaded.canonical_list_kind([1, 10**30]) != 0 or loaded.canonical_list_kind([True]) != 0):
        return "canonical_list"
    values = np.array([0.1, -0.0, float("nan"), 1e16, float("inf"), 2.5e-7, 3.0])
    texts = ["x", "a,b", 'q"q', "line\nbreak", "cr\r", None, "é"]
    integers = np.array([0, -5, 2**62, 7, -(2**63), 1, 2], dtype=np.int64)
    flags = np.array([True, False, True, True, False, False, True])
    expected = _csv_reference([
        ["" if math.isnan(number) else repr(number), text, int(whole), bool(flag), 1.5, None]
        for number, text, whole, flag in zip(values.tolist(), texts, integers.tolist(), flags.tolist())
    ] + [[""], [None]])
    columns = [("f", values), ("o", texts), ("i", integers), ("b", flags.view(np.uint8)), ("o", [1.5] * 7),
               ("o", [None] * 7)]
    native = loaded.csv_rows(columns, 0, 7, 7, "\n") + loaded.csv_rows([("o", ["", None])], 0, 2, 2, "\n")
    if native != expected:
        return "csv_rows"
    texts = ["ab", None, "", "a\0b", "é", "xyz"]
    columns = [("d", np.array([1.5, float("nan"), -0.0, -float("inf"), 8.988465674311579e307, 2.0])),
               ("l", np.array([1, 2, -2147483648, 2147483620, 0, 5], dtype=np.int32),
                np.array([0, 1, 0, 0, 0, 1], dtype=np.uint8)),
               ("s", texts, 3)]
    if (loaded.dta_rows(columns, 0, 6, 6) != _reference_dta_rows(columns, 6)
            or loaded.utf8_extent(texts) != (3, 3) or loaded.utf8_extent([None]) != (-1, -1)
            or loaded.utf8_extent(["a", 1]) is not None):
        return "dta_rows"
    return None


# --------------------------------------------------------------- encoders

def json_bytes(value: Any, *, indent: int | None = None, sort_keys: bool = False, ensure_ascii: bool = True,
               allow_nan: bool = True, separators: tuple[str, str] | None = None) -> bytes | None:
    """UTF-8 bytes of ``json.dumps(value, ...)``, or None for the json module to write."""
    loaded = module()
    if loaded is None or (indent is not None and type(indent) is not int):
        return None
    if separators is None:
        separators = (",", ": ") if indent is not None else (", ", ": ")
    return loaded.encode_json(value, None if indent is None else " " * indent, sort_keys, ensure_ascii,
                              allow_nan, *separators)


def json_safe(value: Any, reference) -> Any:
    """``reference(value)`` for a recursive JSON-safe conversion; exact builtins natively."""
    loaded = module()
    return reference(value) if loaded is None else loaded.json_safe(value, reference)


def canonical_list_kind(values: list | tuple) -> int:
    """1 plain strings, 2 finite exact numbers, 0 for the canonical reference checks."""
    loaded = module()
    return 0 if loaded is None else loaded.canonical_list_kind(values)


def canonical_list(values: list | tuple) -> str | None:
    """Canonical-v1 text of a homogeneous number or plain-string list, or None."""
    loaded = module()
    return None if loaded is None else loaded.canonical_list(values)


_JSON_OPTIONS = frozenset({"indent", "sort_keys", "ensure_ascii", "allow_nan", "separators"})


def dumps(value: Any, **options: Any) -> str:
    """``json.dumps(value, **options)``, encoded natively where it can be."""
    if options.keys() <= _JSON_OPTIONS:
        data = json_bytes(value, **options)
        if data is not None:
            return data.decode("utf-8")
    return json.dumps(value, **options)
