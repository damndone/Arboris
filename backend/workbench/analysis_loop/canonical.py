"""Canonical JSON and numeric comparison primitives for analysis packets."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any


class CanonicalJSONError(ValueError):
    """Raised when a value cannot be represented by canonical JSON v1."""


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJSONError("canonical JSON does not allow NaN or Infinity")
        return 0 if value == 0.0 else value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError("canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise CanonicalJSONError(
                    "Unicode normalization produced duplicate object keys"
                )
            normalized[normalized_key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    raise CanonicalJSONError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def canonical_json_v1(value: Any) -> str:
    """Return deterministic UTF-8-compatible canonical JSON text.

    Callers retain the distinction between omitted, null, and explicit default
    values before calling this function; canonicalization does not fill or
    remove schema fields.
    """

    normalized = _normalize(value)
    return _encode_json(normalized)


def _encode_json(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return _canonical_int(value)
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_encode_json(item) for item in value) + "]"
    if isinstance(value, dict):
        items = (
            json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            + ":"
            + _encode_json(item)
            for key, item in sorted(value.items())
        )
        return "{" + ",".join(items) + "}"
    raise CanonicalJSONError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def _canonical_float(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalJSONError("canonical JSON does not allow NaN or Infinity")
    if value == 0.0:
        return "0"

    magnitude = abs(value)
    decimal_value = Decimal(repr(value))
    if 1e-6 <= magnitude < 1e21:
        rendered = format(decimal_value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return "0" if rendered in {"", "-0"} else rendered

    return _canonical_scientific(decimal_value)


def _canonical_int(value: int) -> str:
    if abs(value) < 10**21:
        return str(value)
    return _canonical_scientific(Decimal(value))


def _canonical_scientific(value: Decimal) -> str:
    rendered = format(value.normalize(), "e")
    mantissa, exponent = rendered.split("e")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    return f"{mantissa}e{int(exponent):+d}"


def sha256_canonical(value: Any) -> str:
    """Hash canonical JSON using SHA-256 and return lowercase hexadecimal."""

    return hashlib.sha256(canonical_json_v1(value).encode("utf-8")).hexdigest()


def numbers_equal(
    left: float | int,
    right: float | int,
    *,
    atol: float = 0.0,
    rtol: float = 0.0,
) -> bool:
    """Compare numbers using ``atol + rtol * max(abs(a), abs(b))``.

    NaN is never equal. Infinities are compared by exact identity rather than
    by the finite-number tolerance rule. Signed zeroes compare equal.
    """

    if atol < 0 or rtol < 0 or not math.isfinite(atol) or not math.isfinite(rtol):
        raise ValueError("atol and rtol must be finite and non-negative")
    if math.isnan(left) or math.isnan(right):
        return False
    if math.isinf(left) or math.isinf(right):
        return left == right
    return abs(left - right) <= atol + rtol * max(abs(left), abs(right))


canonical_number_equal = numbers_equal
numeric_equal = numbers_equal
