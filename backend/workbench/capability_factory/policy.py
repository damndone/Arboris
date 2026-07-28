"""Trusted, immutable comparison protocol snapshots used by the resolver."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import ContractError, _content_digest, _sequence, _text


COMPARISON_OUTCOMES = frozenset({"left_dominates", "right_dominates", "tie", "incomparable"})


@dataclass(frozen=True, slots=True)
class ComparisonRelation:
    left_candidate_id: str
    right_candidate_id: str
    outcome: str

    def __post_init__(self) -> None:
        left = _text(self.left_candidate_id, "left_candidate_id")
        right = _text(self.right_candidate_id, "right_candidate_id")
        if left == right:
            raise ContractError("comparison relation requires two distinct candidates")
        if self.outcome not in COMPARISON_OUTCOMES:
            raise ContractError("unsupported comparison outcome")
        object.__setattr__(self, "left_candidate_id", left)
        object.__setattr__(self, "right_candidate_id", right)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ComparisonProtocolSnapshot:
    protocol_id: str
    revision: int
    relations: tuple[ComparisonRelation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_id", _text(self.protocol_id, "protocol_id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ContractError("comparison protocol revision must be positive")
        relations = tuple(self.relations)
        if len(relations) > 256 or any(not isinstance(item, ComparisonRelation) for item in relations):
            raise ContractError("relations must be a bounded sequence of ComparisonRelation values")
        keys: set[frozenset[str]] = set()
        for relation in relations:
            key = frozenset((relation.left_candidate_id, relation.right_candidate_id))
            if key in keys:
                raise ContractError("comparison relations must be unique per candidate pair")
            keys.add(key)
        object.__setattr__(self, "relations", relations)

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    def compare(self, left_candidate_id: str, right_candidate_id: str) -> str | None:
        for relation in self.relations:
            if relation.left_candidate_id == left_candidate_id and relation.right_candidate_id == right_candidate_id:
                return relation.outcome
            if relation.left_candidate_id == right_candidate_id and relation.right_candidate_id == left_candidate_id:
                inverse = {
                    "left_dominates": "right_dominates",
                    "right_dominates": "left_dominates",
                    "tie": "tie",
                    "incomparable": "incomparable",
                }
                return inverse[relation.outcome]
        return None


__all__ = ["COMPARISON_OUTCOMES", "ComparisonProtocolSnapshot", "ComparisonRelation"]
