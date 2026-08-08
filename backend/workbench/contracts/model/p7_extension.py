"""Bounded, immutable scope metadata shared by P7 extension results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
_PATH_OR_CODE_MARKERS = ("/", "\\", "~", "file:", "import ", "exec(", "eval(")


def _bounded_text(value: Any, field_name: str, *, limit: int) -> str:
    if type(value) is not str or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty string")
    if len(value) > limit:
        raise ContractError(f"{field_name} exceeds the {limit}-character limit")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ContractError(f"{field_name} must be valid JSON text")
    lowered = value.lower()
    if any(marker in lowered for marker in _PATH_OR_CODE_MARKERS):
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
