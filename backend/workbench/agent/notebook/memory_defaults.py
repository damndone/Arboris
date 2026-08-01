"""Server-owned, provenance-bearing application of domain-memory defaults.

Memory content contains a target *reference*, never executable free text.  This
module is the only place that maps such a reference to a concrete proposal
field and value.  It is deliberately narrow: memory may fill an absent Draft
default, but it cannot override an explicit choice, alter evidence, or grant
execution authority.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ...contracts.agent.notebook_option import MemoryDefaultSource
from .proposal import TypedProposal


DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION = "notebook-memory-defaults-v1"
_CONTEXT_V1 = "domain-memory-context-input/v1"
_CONTEXT_V2 = "domain-memory-context-input/v2"


class MemoryDefaultApplicationError(ValueError):
    """A proposed memory default lacks current, exact server-owned provenance."""


@dataclass(frozen=True)
class MemoryDefaultTarget:
    """One registered default target with a literal, reviewable value."""

    target_ref: str
    operation_id: str
    model_type: str
    field_path: tuple[str, ...]
    value: str

    def matches(self, proposal: TypedProposal) -> bool:
        if proposal.operation_id != self.operation_id:
            return False
        params = proposal.changes.get("model_params")
        return isinstance(params, Mapping) and params.get("model_type") == self.model_type


# The registry, not a memory's free-text lesson, fixes both the writable field
# and value.  Additions here require a product-contract review and a test.
MEMORY_DEFAULT_TARGETS: dict[str, MemoryDefaultTarget] = {
    target.target_ref: target
    for target in (
        MemoryDefaultTarget(
            target_ref="model.genesis.ols.covariance.robust",
            operation_id="model.genesis",
            model_type="ols",
            field_path=("model_options", "covariance"),
            value="robust",
        ),
        MemoryDefaultTarget(
            target_ref="model.genesis.ols.covariance.unadjusted",
            operation_id="model.genesis",
            model_type="ols",
            field_path=("model_options", "covariance"),
            value="unadjusted",
        ),
    )
}


def _projection_entries(projection: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if projection is None:
        return ()
    if not isinstance(projection, Mapping):
        raise MemoryDefaultApplicationError("domain memory projection is invalid")
    version = projection.get("contract_version")
    if version == _CONTEXT_V1:
        # The v1 projection intentionally has no apply-mode field.  Legacy
        # records remain visible hints, but cannot become executable defaults.
        return ()
    if version != _CONTEXT_V2:
        raise MemoryDefaultApplicationError("domain memory projection version is unsupported")
    entries = projection.get("entries")
    if not isinstance(entries, list):
        raise MemoryDefaultApplicationError("domain memory projection entries are invalid")
    result: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MemoryDefaultApplicationError("domain memory entry is invalid")
        result.append(entry)
    return tuple(result)


def _entry_source(entry: Mapping[str, Any], target_ref: str) -> MemoryDefaultSource:
    memory_id = entry.get("memory_id")
    revision = entry.get("revision")
    source = entry.get("memory_source")
    if (
        not isinstance(memory_id, str)
        or not memory_id
        or type(revision) is not int
        or revision < 1
        or not isinstance(source, Mapping)
        or source.get("memory_id") != memory_id
        or source.get("revision") != revision
    ):
        raise MemoryDefaultApplicationError("memory default source is incomplete")
    return MemoryDefaultSource(memory_id=memory_id, revision=revision, target_ref=target_ref)


def _current_suggested_targets(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
) -> tuple[tuple[MemoryDefaultTarget, MemoryDefaultSource], ...]:
    candidates: list[tuple[MemoryDefaultTarget, MemoryDefaultSource]] = []
    for entry in _projection_entries(projection):
        if (
            entry.get("apply_mode") != "suggest_default"
            or entry.get("apply_mode_reason") != "verifier_current"
            or entry.get("memory_authority") != "non_authoritative_hint"
        ):
            continue
        refs = entry.get("recommended_target_refs")
        if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
            raise MemoryDefaultApplicationError("memory default target refs are invalid")
        for target_ref in refs:
            target = MEMORY_DEFAULT_TARGETS.get(target_ref)
            if target is not None and target.matches(proposal):
                candidates.append((target, _entry_source(entry, target_ref)))
    return tuple(candidates)


def _field_value(proposal: TypedProposal, path: tuple[str, ...]) -> Any:
    current: Any = proposal.changes
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _has_explicit_covariance(proposal: TypedProposal) -> bool:
    params = proposal.changes.get("model_params")
    return isinstance(params, Mapping) and "covariance" in params


def _with_field(
    proposal: TypedProposal,
    target: MemoryDefaultTarget,
    sources: tuple[MemoryDefaultSource, ...],
) -> TypedProposal:
    changes = dict(proposal.changes)
    container = changes.get(target.field_path[0])
    if container is None:
        container = {}
    if not isinstance(container, Mapping):
        raise MemoryDefaultApplicationError("memory default target container is invalid")
    patched = dict(container)
    patched[target.field_path[1]] = target.value
    changes[target.field_path[0]] = patched
    return replace(proposal, changes=changes, memory_default_sources=sources)


def apply_memory_defaults(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
) -> TypedProposal:
    """Return a new proposal only for one unambiguous, current default.

    An explicit agent/user covariance choice wins.  Competing current memories
    for the same field are deliberately ignored rather than selected by hidden
    priority.  The whole mutation and its source records are built together.
    """

    if not isinstance(proposal, TypedProposal):
        raise MemoryDefaultApplicationError("typed proposal is required")
    if proposal.memory_default_sources:
        validate_memory_default_sources(proposal, projection)
        return proposal
    candidates = _current_suggested_targets(proposal, projection)
    by_path: dict[tuple[str, ...], list[tuple[MemoryDefaultTarget, MemoryDefaultSource]]] = defaultdict(list)
    for target, source in candidates:
        by_path[target.field_path].append((target, source))
    if not by_path:
        return proposal

    # v1.8.5 currently has one concrete writable family field.  Do not add a
    # nested default beside the legacy top-level spelling: that would override
    # a user's explicit compatibility choice.
    if _has_explicit_covariance(proposal):
        return proposal
    applicable: list[tuple[MemoryDefaultTarget, tuple[MemoryDefaultSource, ...]]] = []
    for path, items in sorted(by_path.items()):
        if _field_value(proposal, path) is not None:
            continue
        values = {target.value for target, _source in items}
        if len(values) != 1:
            continue
        target = items[0][0]
        sources = tuple(sorted((source for _target, source in items), key=lambda item: (item.memory_id, item.revision, item.target_ref)))
        applicable.append((target, sources))
    if len(applicable) != 1:
        # More than one independent field would need an explicit expansion of
        # the option packet/UI semantics.  Refuse to create a partial default.
        return proposal
    target, sources = applicable[0]
    return _with_field(proposal, target, sources)


def validate_memory_default_sources(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
) -> None:
    """Prove persisted provenance still matches a current suggestion packet."""

    if not isinstance(proposal, TypedProposal):
        raise MemoryDefaultApplicationError("typed proposal is required")
    sources = proposal.memory_default_sources
    if not sources:
        return
    available = {
        (source.memory_id, source.revision, source.target_ref)
        for _target, source in _current_suggested_targets(proposal, projection)
    }
    for source in sources:
        key = (source.memory_id, source.revision, source.target_ref)
        if key not in available:
            raise MemoryDefaultApplicationError("memory default source is not current")
        target = MEMORY_DEFAULT_TARGETS[source.target_ref]
        if _field_value(proposal, target.field_path) != target.value:
            raise MemoryDefaultApplicationError("memory default source does not match the proposal")


__all__ = [
    "DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION",
    "MEMORY_DEFAULT_TARGETS",
    "MemoryDefaultApplicationError",
    "MemoryDefaultTarget",
    "apply_memory_defaults",
    "validate_memory_default_sources",
]
