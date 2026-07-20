"""Compatibility re-export for the dependency-free canonical primitives."""

from ..canonical import (
    CanonicalJSONError,
    canonical_json_v1,
    numeric_equal,
    numbers_equal,
    sha256_canonical,
)

__all__ = [
    "CanonicalJSONError",
    "canonical_json_v1",
    "numeric_equal",
    "numbers_equal",
    "sha256_canonical",
]
