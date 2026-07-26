"""Immutable, generic CF1 capability and resolution contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..custom_capability.canonical import domain_digest


CAPABILITY_FACTORY_SCHEMA_VERSION = "workbench_capability_factory_v1"
NOTEBOOK_OPTION_PLANNER_CONSUMER = "notebook_option_planner"
CONSUMER_SLOTS = (
    NOTEBOOK_OPTION_PLANNER_CONSUMER,
    "report_projection",
    "diagnostic_adapter",
    "figure_provider",
    "compare_adapter",
)
TRUST_ORDER = (
    "native_pack",
    "registered_third_party",
    "generated_adapter",
    "authored_implementation",
)
SELECTION_OUTCOMES = frozenset(
    {"selected", "unavailable", "stale", "incomparable", "tied", "no_dominant_choice"}
)
_MAX_IDENTIFIER = 256
_MAX_ITEMS = 128
_MAX_SCHEMA_KEYS = 256
_DIGEST_SIZE = 64


class ContractError(ValueError):
    """Raised when a CF1 contract is malformed or incomplete."""


def _text(value: Any, field: str, *, maximum: int = _MAX_IDENTIFIER) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{field} must be a non-empty bounded string")
    if any(ord(char) < 0x20 for char in value):
        raise ContractError(f"{field} contains a control character")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=_DIGEST_SIZE)
    if len(text) != _DIGEST_SIZE or any(char not in "0123456789abcdef" for char in text):
        raise ContractError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _sequence(values: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise ContractError(f"{field} must be a sequence")
    if len(values) > _MAX_ITEMS or (not values and not allow_empty):
        raise ContractError(f"{field} must contain a bounded non-empty sequence")
    result = tuple(_text(item, f"{field} item") for item in values)
    if len(set(result)) != len(result):
        raise ContractError(f"{field} must not contain duplicates")
    return result


def _freeze(value: Any, *, depth: int = 0) -> Any:
    if depth > 16:
        raise ContractError("contract value exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ContractError("contract values must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_SCHEMA_KEYS:
            raise ContractError("contract mapping exceeds maximum keys")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[_text(key, "mapping key")] = _freeze(item, depth=depth + 1)
        return MappingProxyType(normalized)
    if isinstance(value, (tuple, list)):
        if len(value) > _MAX_ITEMS:
            raise ContractError("contract sequence exceeds maximum length")
        return tuple(_freeze(item, depth=depth + 1) for item in value)
    raise ContractError(f"unsupported contract value type: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _content_digest(value: Any) -> str:
    return domain_digest(
        f"{CAPABILITY_FACTORY_SCHEMA_VERSION}:content",
        _plain(value),
    )


def _consumer_map(value: Any, field: str) -> Mapping[str, str | None]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must declare every consumer slot")
    # A new consumer slot is backward-compatible for persisted profiles: an
    # omitted slot means explicit unsupported/null, never implicit support.
    if NOTEBOOK_OPTION_PLANNER_CONSUMER not in value:
        value = {**value, NOTEBOOK_OPTION_PLANNER_CONSUMER: None}
    keys = set(value)
    expected = set(CONSUMER_SLOTS)
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if unknown:
            detail.append(f"unknown={unknown}")
        raise ContractError(f"{field} consumer_support is incomplete ({', '.join(detail)})")
    normalized: dict[str, str | None] = {}
    for slot in CONSUMER_SLOTS:
        item = value[slot]
        normalized[slot] = None if item is None else _text(item, f"{field}.{slot}")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class SemanticProfile:
    profile_id: str
    revision: int
    input_kinds: tuple[str, ...]
    operations: tuple[str, ...]
    output_facets: tuple[str, ...]
    assumptions: tuple[str, ...]
    consumers: Mapping[str, str | None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        object.__setattr__(self, "input_kinds", _sequence(self.input_kinds, "input_kinds"))
        object.__setattr__(self, "operations", _sequence(self.operations, "operations"))
        object.__setattr__(self, "output_facets", _sequence(self.output_facets, "output_facets"))
        object.__setattr__(self, "assumptions", _sequence(self.assumptions, "assumptions", allow_empty=True))
        object.__setattr__(self, "consumers", _consumer_map(self.consumers, "consumers"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

@dataclass(frozen=True, slots=True)
class CapabilityRequirementRevision:
    requirement_id: str
    revision: int
    semantic_profile: SemanticProfile
    requested_operations: tuple[str, ...]
    requested_consumers: tuple[str, ...]
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", _text(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        if not isinstance(self.semantic_profile, SemanticProfile):
            raise ContractError("semantic_profile must be a SemanticProfile")
        operations = _sequence(self.requested_operations, "requested_operations")
        if not set(operations) <= set(self.semantic_profile.operations):
            raise ContractError("requested_operations are not declared by semantic_profile")
        consumers = _sequence(self.requested_consumers, "requested_consumers")
        if not set(consumers) <= set(CONSUMER_SLOTS):
            raise ContractError("requested_consumers contain unknown consumer slots")
        if not isinstance(self.input_schema, Mapping) or not self.input_schema:
            raise ContractError("input_schema must be a non-empty object")
        object.__setattr__(self, "requested_operations", operations)
        object.__setattr__(self, "requested_consumers", consumers)
        object.__setattr__(self, "input_schema", _freeze(self.input_schema))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    @property
    def input_schema_digest(self) -> str:
        return domain_digest(
            f"{CAPABILITY_FACTORY_SCHEMA_VERSION}:input-schema",
            _plain(self.input_schema),
        )


@dataclass(frozen=True, slots=True)
class ImplementationRevision:
    implementation_id: str
    revision: int
    profile_id: str
    profile_revision: int
    profile_digest: str
    input_schema_digest: str
    source_kind: str
    trust_tier: str
    operations: tuple[str, ...]
    consumer_support: Mapping[str, str | None]
    artifact_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementation_id", _text(self.implementation_id, "implementation_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "profile_revision", _positive_int(self.profile_revision, "profile_revision"))
        object.__setattr__(self, "profile_digest", _digest(self.profile_digest, "profile_digest"))
        object.__setattr__(self, "input_schema_digest", _digest(self.input_schema_digest, "input_schema_digest"))
        source_kind = _text(self.source_kind, "source_kind")
        if source_kind not in TRUST_ORDER:
            raise ContractError("source_kind is not a registered capability source")
        if self.trust_tier != source_kind:
            raise ContractError("trust_tier must match source_kind")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "trust_tier", _text(self.trust_tier, "trust_tier"))
        object.__setattr__(self, "operations", _sequence(self.operations, "operations"))
        object.__setattr__(self, "consumer_support", _consumer_map(self.consumer_support, "consumer_support"))
        object.__setattr__(self, "artifact_ref", _digest(self.artifact_ref, "artifact_ref"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ResolutionPolicySnapshot:
    policy_id: str
    revision: int
    trust_order: tuple[str, ...]
    required_validity_domains: tuple[str, ...]
    comparison_protocol_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        order = _sequence(self.trust_order, "trust_order")
        if order != TRUST_ORDER:
            raise ContractError("trust_order must use the fixed trust order")
        object.__setattr__(self, "trust_order", order)
        object.__setattr__(self, "required_validity_domains", _sequence(self.required_validity_domains, "required_validity_domains"))
        if self.comparison_protocol_ref is not None:
            object.__setattr__(self, "comparison_protocol_ref", _digest(self.comparison_protocol_ref, "comparison_protocol_ref"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ImplementationCandidate:
    candidate_id: str
    implementation: ImplementationRevision
    feasible: bool
    available: bool
    validity_refs: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id"))
        if not isinstance(self.implementation, ImplementationRevision):
            raise ContractError("implementation must be an ImplementationRevision")
        if not isinstance(self.feasible, bool) or not isinstance(self.available, bool):
            raise ContractError("candidate feasibility and availability must be boolean")
        if not isinstance(self.validity_refs, Mapping):
            raise ContractError("validity_refs must be an object")
        normalized = {
            _text(key, "validity domain"): _digest(value, "validity reference")
            for key, value in self.validity_refs.items()
        }
        object.__setattr__(self, "validity_refs", MappingProxyType(normalized))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class CandidateSet:
    requirement_digest: str
    candidates: tuple[ImplementationCandidate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_digest", _digest(self.requirement_digest, "requirement_digest"))
        if not isinstance(self.candidates, (tuple, list)) or len(self.candidates) > _MAX_ITEMS:
            raise ContractError("candidates must be a bounded sequence")
        items = tuple(self.candidates)
        if any(not isinstance(item, ImplementationCandidate) for item in items):
            raise ContractError("candidates must contain ImplementationCandidate values")
        if len({item.candidate_id for item in items}) != len(items):
            raise ContractError("candidate_id must be unique within a candidate set")
        object.__setattr__(self, "candidates", items)

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    outcome: str
    candidate_set_digest: str
    policy_digest: str
    selected_candidate_id: str | None
    reason_code: str
    compared_candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.outcome not in SELECTION_OUTCOMES:
            raise ContractError("unsupported selection outcome")
        object.__setattr__(self, "candidate_set_digest", _digest(self.candidate_set_digest, "candidate_set_digest"))
        object.__setattr__(self, "policy_digest", _digest(self.policy_digest, "policy_digest"))
        if self.selected_candidate_id is not None:
            object.__setattr__(self, "selected_candidate_id", _text(self.selected_candidate_id, "selected_candidate_id"))
        if self.outcome == "selected" and self.selected_candidate_id is None:
            raise ContractError("selected outcome requires selected_candidate_id")
        if self.outcome != "selected" and self.selected_candidate_id is not None:
            raise ContractError("non-selected outcome cannot bind a candidate")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "compared_candidate_ids", _sequence(self.compared_candidate_ids, "compared_candidate_ids", allow_empty=True))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ResolutionBinding:
    requirement_digest: str
    policy_digest: str
    candidate_set_digest: str
    selection_digest: str
    implementation_ref: str
    validity_cursor_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "requirement_digest",
            "policy_digest",
            "candidate_set_digest",
            "selection_digest",
            "implementation_ref",
            "validity_cursor_digest",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = [
    "CAPABILITY_FACTORY_SCHEMA_VERSION",
    "CONSUMER_SLOTS",
    "NOTEBOOK_OPTION_PLANNER_CONSUMER",
    "TRUST_ORDER",
    "CandidateSet",
    "CapabilityRequirementRevision",
    "ContractError",
    "ImplementationCandidate",
    "ImplementationRevision",
    "ResolutionBinding",
    "ResolutionPolicySnapshot",
    "SELECTION_OUTCOMES",
    "SelectionDecision",
    "SemanticProfile",
]
