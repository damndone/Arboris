"""Bounded, immutable scope metadata shared by P7 extension results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from workbench.contracts.common.envelope import ContractError, require_exact_keys


P7_SCOPE_FIELDS = frozenset(
    {
        "estimand",
        "input_semantics",
        "assumptions",
        "limitations",
        "not_claimed",
        "unsupported_extensions",
    }
)
MAX_P7_SCOPE_TEXT_LENGTH = 512
MAX_P7_SCOPE_ITEM_LENGTH = 512
MAX_P7_SCOPE_ITEMS = 8

_P7_SCOPE_SEQUENCE_FIELDS = (
    "assumptions",
    "limitations",
    "not_claimed",
    "unsupported_extensions",
)
_UNSAFE_SCOPE_PATTERNS = (
    # Reject explicit relative path prefixes, but not ordinary prose such as A/B.
    re.compile(r"(?i)(?:^|[\s\"'(])\.\.?[\\/]"),
    # Common local filesystem roots are unambiguous; endpoint prose such as /api/v1 is not.
    re.compile(
        r"(?i)(?:^|[\s\"'(])/(?:users|home|private|var|tmp|etc|usr|opt|bin|sbin|"
        r"dev|proc|sys|mnt|srv|root)(?:[\\/]|$)"
    ),
    # An absolute path with a filename extension remains path-shaped even outside known roots.
    re.compile(
        r"(?i)(?:^|[\s\"'(])/(?:[A-Za-z0-9_.-]+[\\/])+"
        r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16}(?=$|[\s\"'),;])"
    ),
    re.compile(r"(?i)(?:^|[\s\"'(])(?:[A-Z]:[\\/]|\\\\)"),
    re.compile(r"(?i)(?:^|[\s\"'(])~[\\/]"),
    # A bare relative path is rejected only when the whole field is that token.
    re.compile(r"(?i)^\s*(?:[A-Za-z0-9_.-]{2,}[\\/]+)+[A-Za-z0-9_.-]+\s*$"),
    # Embedded no-extension paths need explicit path context; this preserves group/time prose.
    re.compile(
        r"(?i)\b(?:see|stored\s+in|located\s+at|read\s+from|loaded?\s+from|"
        r"path(?:\s+is)?|file)\s+(?:[A-Za-z0-9_.-]{2,}[\\/])+"
        r"[A-Za-z0-9_.-]+(?=$|[\s\"'),;])"
    ),
    # A directory-like token ending in a filename extension is path-shaped in prose too.
    re.compile(
        r"(?i)(?:^|[\s\"'(])(?:[A-Za-z0-9_.-]+[\\/]+)+"
        r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16}(?=$|[\s\"'),;])"
    ),
    # `file:` is allowed as prose unless it introduces a path or filename.
    re.compile(
        r"(?i)\bfile:(?:[\\/]|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16}"
        r"(?=$|[\s\"'),;]))"
    ),
    # Reject import statements, not ordinary prose that uses the word import.
    re.compile(
        r"(?im)^\s*(?:from\s+[A-Za-z_][A-Za-z0-9_.]*\s+)?import\s+"
        r"[A-Za-z_][A-Za-z0-9_.]*(?:\s+as\s+[A-Za-z_][A-Za-z0-9_.]*)?"
        r"(?:\s*;.*)?\s*$"
    ),
    re.compile(r"(?i)\b(?:exec|eval)\s*\("),
    re.compile(
        r"^\s*[A-Za-z_][A-Za-z0-9_.]*\s*~\s*[A-Za-z_][A-Za-z0-9_.]*"
        r"(?:\s*[+*:\-]\s*[A-Za-z_][A-Za-z0-9_.]*)*\s*$"
    ),
)


def _contains_unsafe_scope_shape(value: str) -> bool:
    """Reject path/code-shaped tokens without banning ordinary punctuation prose."""

    return any(pattern.search(value) for pattern in _UNSAFE_SCOPE_PATTERNS)


def _bounded_text(value: Any, field_name: str, *, limit: int) -> str:
    if type(value) is not str or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty string")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds the {limit}-character limit")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ContractError(f"{field_name} must be valid JSON text")
    if _contains_unsafe_scope_shape(value):
        raise ContractError(f"{field_name} must not contain a path or executable expression")
    return value


def _bounded_text_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{field_name} must be a non-empty sequence of strings")
    items = tuple(value)
    if not items:
        raise ContractError(f"{field_name} must contain at least one item")
    if len(items) > MAX_P7_SCOPE_ITEMS:
        raise ContractError(f"{field_name} exceeds the {MAX_P7_SCOPE_ITEMS}-item limit")
    return tuple(
        _bounded_text(item, f"{field_name}[{index}]", limit=MAX_P7_SCOPE_ITEM_LENGTH)
        for index, item in enumerate(items)
    )


@dataclass(frozen=True)
class P7ScopeMetadata:
    """Immutable, JSON-safe applicability and limitation metadata for P7."""

    estimand: str
    input_semantics: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    not_claimed: tuple[str, ...]
    unsupported_extensions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "estimand",
            _bounded_text(self.estimand, "estimand", limit=MAX_P7_SCOPE_TEXT_LENGTH),
        )
        object.__setattr__(
            self,
            "input_semantics",
            _bounded_text(
                self.input_semantics,
                "input_semantics",
                limit=MAX_P7_SCOPE_TEXT_LENGTH,
            ),
        )
        for field_name in _P7_SCOPE_SEQUENCE_FIELDS:
            object.__setattr__(
                self,
                field_name,
                _bounded_text_sequence(getattr(self, field_name), field_name),
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-shaped copy of this scope."""

        return {
            "estimand": self.estimand,
            "input_semantics": self.input_semantics,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "not_claimed": list(self.not_claimed),
            "unsupported_extensions": list(self.unsupported_extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "P7ScopeMetadata":
        """Parse the closed public scope shape without coercion or defaults."""

        require_exact_keys(value, set(P7_SCOPE_FIELDS), "P7 scope metadata")
        return cls(
            estimand=value["estimand"],
            input_semantics=value["input_semantics"],
            assumptions=value["assumptions"],
            limitations=value["limitations"],
            not_claimed=value["not_claimed"],
            unsupported_extensions=value["unsupported_extensions"],
        )


__all__ = [
    "MAX_P7_SCOPE_ITEM_LENGTH",
    "MAX_P7_SCOPE_ITEMS",
    "MAX_P7_SCOPE_TEXT_LENGTH",
    "P7_SCOPE_FIELDS",
    "P7ScopeMetadata",
]
