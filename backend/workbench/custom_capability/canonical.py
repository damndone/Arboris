"""Canonical JSON and domain-separated digest helpers for B0."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


MAX_CANONICAL_BYTES = 1_048_576


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("value exceeds maximum canonical nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON requires finite numbers")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a bounded JSON value with one deterministic wire representation."""

    _validate_json_value(value)
    try:
        encoded = json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("value cannot be canonically encoded") from error
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise ValueError("canonical JSON exceeds maximum size")
    return encoded


def parse_canonical_json(raw: bytes) -> Any:
    """Parse only the exact canonical representation, rejecting duplicate keys."""

    if not isinstance(raw, bytes):
        raise ValueError("canonical JSON input must be bytes")
    if len(raw) > MAX_CANONICAL_BYTES:
        raise ValueError("canonical JSON exceeds maximum size")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid canonical JSON") from error
    except ValueError as error:
        if "duplicate JSON object key" in str(error):
            raise
        raise ValueError("invalid canonical JSON") from error
    if canonical_json_bytes(value) != raw:
        raise ValueError("JSON is not canonical")
    return value


def domain_digest(domain: str, value: Any) -> str:
    """Hash a value with an explicit namespace separator."""

    if not isinstance(domain, str) or not domain or "\x00" in domain:
        raise ValueError("digest domain must be a non-empty string without NUL")
    preimage = domain.encode("utf-8") + b"\x00" + canonical_json_bytes(value)
    return hashlib.sha256(preimage).hexdigest()


__all__ = ["MAX_CANONICAL_BYTES", "canonical_json_bytes", "domain_digest", "parse_canonical_json"]
