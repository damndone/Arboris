"""Rebuildable, non-authoritative Project/RunFamily memory contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from ..custom_capability.canonical import domain_digest


PROJECT_CONTEXT_INDEX_CONTRACT_VERSION = "project-context-index/v1"
SOURCE_KINDS = frozenset({"graph", "trace", "option", "draft", "run_family", "artifact", "user_fact"})
FACT_KINDS = frozenset(
    {
        "goal",
        "constraint",
        "graph_summary",
        "run_summary",
        "option_summary",
        "decision",
        "validation",
        "warning",
        "follow_up",
    }
)
_HEX = frozenset("0123456789abcdef")
_MAX_ID = 256
_MAX_SUMMARY = 512
_MAX_SOURCE_REFS = 8
_MAX_FACTS = 128
_MAX_SOURCES = 64
_MAX_ATTRIBUTES = 8


class ProjectIndexError(ValueError):
    """A project context index or one of its bounded facts is invalid."""


def _text(value: Any, field: str, *, maximum: int = _MAX_SUMMARY) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProjectIndexError(f"{field} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise ProjectIndexError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field, maximum=_MAX_ID)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ProjectIndexError(f"{field} must be an opaque path-safe id")
    return text


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ProjectIndexError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _revision(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProjectIndexError(f"{field} must be a positive integer")
    return value


def _source_refs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value or len(value) > _MAX_SOURCE_REFS:
        raise ProjectIndexError("source_refs must contain one to eight refs")
    refs = tuple(_identifier(item, "source_ref") for item in value)
    if len(set(refs)) != len(refs):
        raise ProjectIndexError("source_refs must be unique")
    return refs


def _attributes(value: Any) -> tuple[tuple[str, str | int | bool], ...]:
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, Mapping):
        items = tuple(value.items())
    else:
        raise ProjectIndexError("attributes must be a bounded mapping")
    if len(items) > _MAX_ATTRIBUTES:
        raise ProjectIndexError("attributes exceed the bounded field limit")
    normalized: list[tuple[str, str | int | bool]] = []
    for key, item in items:
        normalized_key = _identifier(key, "attribute key")
        if type(item) not in {str, int, bool}:
            raise ProjectIndexError("attribute values must be scalar")
        if isinstance(item, str):
            item = _text(item, f"attribute[{normalized_key}]", maximum=128)
        normalized.append((normalized_key, item))
    if len({key for key, _ in normalized}) != len(normalized):
        raise ProjectIndexError("attributes keys must be unique")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class SourceManifestEntry:
    """A hash/revision pointer to a canonical fact source, never its payload."""

    kind: str
    source_ref: str
    revision: int
    content_hash: str

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_KINDS:
            raise ProjectIndexError(f"source kind is not registered: {self.kind!r}")
        object.__setattr__(self, "source_ref", _identifier(self.source_ref, "source_ref"))
        object.__setattr__(self, "revision", _revision(self.revision, "source revision"))
        object.__setattr__(self, "content_hash", _digest(self.content_hash, "source content_hash"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_ref": self.source_ref,
            "revision": self.revision,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceManifestEntry":
        if not isinstance(value, Mapping) or set(value) != {"kind", "source_ref", "revision", "content_hash"}:
            raise ProjectIndexError("source manifest entry fields are invalid")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class ProjectContextFact:
    """A bounded summary with explicit source references."""

    fact_id: str
    kind: str
    summary: str
    source_refs: tuple[str, ...]
    attributes: tuple[tuple[str, str | int | bool], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        if self.kind not in FACT_KINDS:
            raise ProjectIndexError(f"fact kind is not registered: {self.kind!r}")
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(self, "source_refs", _source_refs(self.source_refs))
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind,
            "summary": self.summary,
            "source_refs": list(self.source_refs),
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectContextFact":
        if not isinstance(value, Mapping) or set(value) != {
            "fact_id",
            "kind",
            "summary",
            "source_refs",
            "attributes",
        }:
            raise ProjectIndexError("project context fact fields are invalid")
        return cls(
            fact_id=value["fact_id"],
            kind=value["kind"],
            summary=value["summary"],
            source_refs=tuple(value["source_refs"]),
            attributes=value["attributes"],
        )


@dataclass(frozen=True, slots=True)
class ProjectContextIndex:
    """A rebuildable cache revision bound to one CORE project identity."""

    index_id: str
    profile_id: str
    project_id: str
    project_revision: int
    project_identity_hash: str
    run_family_id: str
    revision: int
    source_manifest: tuple[SourceManifestEntry, ...]
    facts: tuple[ProjectContextFact, ...]
    built_at: str
    previous_index_hash: str | None = None

    CONTRACT_VERSION: ClassVar[str] = PROJECT_CONTEXT_INDEX_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "index_id", _identifier(self.index_id, "index_id"))
        object.__setattr__(self, "profile_id", _identifier(self.profile_id, "profile_id"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id"))
        object.__setattr__(self, "project_revision", _revision(self.project_revision, "project_revision"))
        object.__setattr__(self, "project_identity_hash", _digest(self.project_identity_hash, "project_identity_hash"))
        object.__setattr__(self, "run_family_id", _identifier(self.run_family_id, "run_family_id"))
        object.__setattr__(self, "revision", _revision(self.revision, "index revision"))
        if not isinstance(self.source_manifest, tuple) or not self.source_manifest:
            raise ProjectIndexError("source_manifest must not be empty")
        if len(self.source_manifest) > _MAX_SOURCES or any(
            not isinstance(item, SourceManifestEntry) for item in self.source_manifest
        ):
            raise ProjectIndexError("source_manifest is invalid or too large")
        sources = tuple(sorted(self.source_manifest, key=lambda item: (item.kind, item.source_ref)))
        if len({item.source_ref for item in sources}) != len(sources):
            raise ProjectIndexError("source_manifest refs must be unique")
        object.__setattr__(self, "source_manifest", sources)
        if not isinstance(self.facts, tuple) or len(self.facts) > _MAX_FACTS:
            raise ProjectIndexError("facts are invalid or too large")
        if any(not isinstance(item, ProjectContextFact) for item in self.facts):
            raise ProjectIndexError("facts must contain ProjectContextFact values")
        facts = tuple(sorted(self.facts, key=lambda item: item.fact_id))
        if len({item.fact_id for item in facts}) != len(facts):
            raise ProjectIndexError("fact ids must be unique")
        known_refs = {item.source_ref for item in sources}
        if any(ref not in known_refs for item in facts for ref in item.source_refs):
            raise ProjectIndexError("fact source_refs must exist in source_manifest")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "built_at", _text(self.built_at, "built_at", maximum=64))
        if self.revision == 1:
            if self.previous_index_hash is not None:
                raise ProjectIndexError("revision one cannot have previous_index_hash")
        else:
            object.__setattr__(self, "previous_index_hash", _digest(self.previous_index_hash, "previous_index_hash"))

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.CONTRACT_VERSION,
            "index_id": self.index_id,
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "project_revision": self.project_revision,
            "project_identity_hash": self.project_identity_hash,
            "run_family_id": self.run_family_id,
            "revision": self.revision,
            "source_manifest": [item.to_dict() for item in self.source_manifest],
            "facts": [item.to_dict() for item in self.facts],
            "built_at": self.built_at,
            "previous_index_hash": self.previous_index_hash,
        }

    @property
    def content_hash(self) -> str:
        return domain_digest("workbench.domain_memory.project_context_index/v1", self._payload())

    @property
    def source_cursor_digest(self) -> str:
        return domain_digest(
            "workbench.domain_memory.project_context_index_sources/v1",
            {"source_manifest": [item.to_dict() for item in self.source_manifest]},
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectContextIndex":
        expected = {
            "contract_version",
            "index_id",
            "profile_id",
            "project_id",
            "project_revision",
            "project_identity_hash",
            "run_family_id",
            "revision",
            "source_manifest",
            "facts",
            "built_at",
            "previous_index_hash",
            "content_hash",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ProjectIndexError("project context index fields are invalid")
        if value["contract_version"] != PROJECT_CONTEXT_INDEX_CONTRACT_VERSION:
            raise ProjectIndexError("project context index contract is unsupported")
        source_manifest = tuple(SourceManifestEntry.from_dict(item) for item in value["source_manifest"])
        facts = tuple(ProjectContextFact.from_dict(item) for item in value["facts"])
        result = cls(
            index_id=value["index_id"],
            profile_id=value["profile_id"],
            project_id=value["project_id"],
            project_revision=value["project_revision"],
            project_identity_hash=value["project_identity_hash"],
            run_family_id=value["run_family_id"],
            revision=value["revision"],
            source_manifest=source_manifest,
            facts=facts,
            built_at=value["built_at"],
            previous_index_hash=value["previous_index_hash"],
        )
        if value["content_hash"] != result.content_hash:
            raise ProjectIndexError("project context index content hash mismatch")
        return result


__all__ = [
    "FACT_KINDS",
    "PROJECT_CONTEXT_INDEX_CONTRACT_VERSION",
    "ProjectContextFact",
    "ProjectContextIndex",
    "ProjectIndexError",
    "SOURCE_KINDS",
    "SourceManifestEntry",
]
