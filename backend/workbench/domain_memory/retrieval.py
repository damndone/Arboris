"""Deterministic, bounded, fail-closed retrieval of approved domain memory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .contracts import ApplicabilityPredicate, DomainMemoryContentRevision
from .preferences import EffectiveDomainMemoryPreferences
from .scope import MemoryScope
from .store import DomainMemoryStore


class DomainMemoryRetrievalError(ValueError):
    """Retrieval input is missing or outside the bounded contract."""


@dataclass(frozen=True, slots=True)
class RetrievalOmission:
    memory_id: str
    revision: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, "revision": self.revision, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RetrievedMemoryHint:
    memory_id: str
    revision: int
    content_hash: str
    memory_kind: str
    domain_tags: tuple[str, ...]
    compact_lesson: str
    recommended_effect_kind: str
    recommended_target_refs: tuple[str, ...]
    source_summary_refs: tuple[str, ...]
    match_reason: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "content_hash": self.content_hash,
            "memory_kind": self.memory_kind,
            "domain_tags": list(self.domain_tags),
            "compact_lesson": self.compact_lesson,
            "recommended_effect_kind": self.recommended_effect_kind,
            "recommended_target_refs": list(self.recommended_target_refs),
            "source_summary_refs": list(self.source_summary_refs),
            "match_reason": list(self.match_reason),
            "memory_authority": "non_authoritative_hint",
        }


@dataclass(frozen=True, slots=True)
class DomainMemoryRetrieval:
    retrieval_ref: str
    scope_ref: str
    outcome: str
    reason: str
    entries: tuple[RetrievedMemoryHint, ...]
    omissions: tuple[RetrievalOmission, ...]
    bounded: bool
    preference_ref: str

    def to_context_projection(self) -> dict[str, Any]:
        return {
            "contract_version": "domain-memory-context-input/v1",
            "retrieval_ref": self.retrieval_ref,
            "scope_ref": self.scope_ref,
            "outcome": self.outcome,
            "reason": self.reason,
            "entries": [item.to_dict() for item in self.entries],
            "omissions": [item.to_dict() for item in self.omissions],
            "bounded": self.bounded,
            "preference_ref": self.preference_ref,
            "memory_authority": "non_authoritative",
        }


def _predicate_matches(predicate: ApplicabilityPredicate, facts: Mapping[str, Any]) -> bool:
    present = predicate.predicate_id in facts
    if predicate.operator == "exists":
        return present
    if not present:
        return False
    value = facts[predicate.predicate_id]
    if predicate.operator == "equals":
        return value == predicate.value
    if predicate.operator == "not_equals":
        return value != predicate.value
    if predicate.operator == "one_of":
        return value in (predicate.value or ())
    return False


def _valid_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise DomainMemoryRetrievalError("timestamp must be ISO-8601") from error


def retrieve_domain_memory(
    store: DomainMemoryStore,
    *,
    requester: MemoryScope,
    preferences: EffectiveDomainMemoryPreferences,
    facts: Mapping[str, Any],
    now: str,
    max_entries: int = 8,
    max_bytes: int = 8192,
) -> DomainMemoryRetrieval:
    if not isinstance(store, DomainMemoryStore) or not isinstance(requester, MemoryScope):
        raise DomainMemoryRetrievalError("store and requester are required")
    if not isinstance(preferences, EffectiveDomainMemoryPreferences):
        raise DomainMemoryRetrievalError("effective preferences are required")
    if not isinstance(facts, Mapping):
        raise DomainMemoryRetrievalError("applicability facts must be a mapping")
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 0 <= max_entries <= 32:
        raise DomainMemoryRetrievalError("max_entries budget is invalid")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 256 <= max_bytes <= 32768:
        raise DomainMemoryRetrievalError("max_bytes budget is invalid")
    _valid_timestamp(now)
    retrieval_ref = "retrieval-" + preferences.preference_ref[:40]
    if not preferences.use:
        return DomainMemoryRetrieval(retrieval_ref, requester.scope_ref, "not_used", "DOMAIN_MEMORY_DISABLED", (), (), True, preferences.preference_ref)
    if not store.scope.can_read(requester):
        return DomainMemoryRetrieval(retrieval_ref, requester.scope_ref, "blocked", "DOMAIN_MEMORY_SCOPE_MISMATCH", (), (), True, preferences.preference_ref)
    now_value = _valid_timestamp(now)
    omissions: list[RetrievalOmission] = []
    candidates: list[tuple[DomainMemoryContentRevision, tuple[str, ...]]] = []
    active = store.active_contents()
    identities = {f"{item.memory_id}@{item.revision}" for item in active}
    conflict_map = {
        f"{item.memory_id}@{item.revision}": set(item.conflicts_with)
        for item in active
    }
    bindings = {item.binding_ref: item for item in store.list_bindings()}
    for content in active:
        if content.scope.visibility_scope == "private" and content.scope.owner_id != requester.owner_id:
            omissions.append(RetrievalOmission(content.memory_id, content.revision, "scope_acl")); continue
        if any(not _predicate_matches(item, facts) for item in content.applicability_predicates):
            omissions.append(RetrievalOmission(content.memory_id, content.revision, "predicate_mismatch")); continue
        try:
            if now_value >= _valid_timestamp(content.review_after):
                raise ValueError("review_due")
            source_refs: list[str] = []
            for source in content.source_summary_refs:
                binding = bindings.get(source.source_access_binding_ref)
                validity = store.current_source_validity(source.source_access_binding_ref)
                if binding is None or validity is None or validity.state != "valid":
                    raise ValueError("source_access_unavailable")
                if not binding.scope.can_read(requester) or not binding.scope.exact_match(content.scope):
                    raise ValueError("source_scope_acl")
                if binding.summary_snapshot_ref != source.summary_snapshot_ref or binding.summary_snapshot_hash != source.summary_snapshot_hash or binding.summary_schema_version != source.summary_schema_version:
                    raise ValueError("source_snapshot_mismatch")
                if binding.source_namespace_id != content.scope.namespace_id or binding.source_profile_id != content.scope.profile_id:
                    raise ValueError("source_namespace_mismatch")
                source_refs.append(source.source_access_binding_ref)
        except ValueError as error:
            omissions.append(RetrievalOmission(content.memory_id, content.revision, str(error))); continue
        identity = f"{content.memory_id}@{content.revision}"
        conflicts = (set(content.conflicts_with) & identities) | {
            other_identity for other_identity, other_conflicts in conflict_map.items() if identity in other_conflicts
        }
        if conflicts:
            omissions.append(RetrievalOmission(content.memory_id, content.revision, "conflict")); continue
        candidates.append((content, tuple(source_refs)))
    candidates.sort(key=lambda item: (-len(item[0].applicability_predicates), item[0].memory_id, item[0].revision))
    selected: list[RetrievedMemoryHint] = []
    for content, source_refs in candidates:
        if len(selected) >= max_entries:
            omissions.append(RetrievalOmission(content.memory_id, content.revision, "entry_budget")); continue
        hint = RetrievedMemoryHint(
            memory_id=content.memory_id, revision=content.revision, content_hash=content.content_hash,
            memory_kind=content.memory_kind, domain_tags=content.domain_tags, compact_lesson=content.compact_lesson,
            recommended_effect_kind=content.recommended_effect_kind, recommended_target_refs=content.recommended_target_refs,
            source_summary_refs=source_refs, match_reason=tuple(item.predicate_id for item in content.applicability_predicates),
        )
        encoded = json.dumps(hint.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_bytes or (selected and len(json.dumps([item.to_dict() for item in selected], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) + len(encoded) > max_bytes):
            omissions.append(RetrievalOmission(content.memory_id, content.revision, "byte_budget")); continue
        selected.append(hint)
    return DomainMemoryRetrieval(
        retrieval_ref=retrieval_ref, scope_ref=requester.scope_ref, outcome="used" if selected else "empty",
        reason="retrieved" if selected else "no_eligible_memory", entries=tuple(selected), omissions=tuple(omissions),
        bounded=True, preference_ref=preferences.preference_ref,
    )


__all__ = ["DomainMemoryRetrieval", "DomainMemoryRetrievalError", "RetrievedMemoryHint", "RetrievalOmission", "retrieve_domain_memory"]
