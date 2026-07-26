"""Content-addressed registration of exact implementation revisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .contracts import (
    CandidateSet,
    CapabilityRequirementRevision,
    ImplementationCandidate,
    ImplementationRevision,
    _digest,
    _text,
)
from .store import ContentAddressedStore


class RegistryError(ValueError):
    """Raised when registration would replace an immutable implementation."""


@dataclass(frozen=True, slots=True)
class RegistrationReceipt:
    implementation_ref: str


@dataclass(frozen=True, slots=True)
class _RegisteredImplementation:
    implementation: ImplementationRevision
    validity_refs: Mapping[str, str]

    @property
    def content_digest(self) -> str:
        return self.implementation.content_digest


class CapabilityRegistry:
    """Registry with one immutable record per implementation id/revision."""

    def __init__(self) -> None:
        self._store: ContentAddressedStore[_RegisteredImplementation] = ContentAddressedStore()
        self._by_identity: dict[tuple[str, int], str] = {}

    def register(
        self,
        implementation: ImplementationRevision,
        *,
        validity_refs: Mapping[str, str],
    ) -> RegistrationReceipt:
        if not isinstance(implementation, ImplementationRevision):
            raise RegistryError("only an ImplementationRevision can be registered")
        if implementation.source_kind == "native_pack":
            raise RegistryError("trusted native projections must use the native registration path")
        if implementation.trust_tier != "registered_third_party":
            raise RegistryError("this registration path assigns only registered_third_party trust")
        if not isinstance(validity_refs, Mapping):
            raise RegistryError("validity_refs must be an object")
        normalized = MappingProxyType({
            _text(key, "validity domain"): _digest(value, "validity reference")
            for key, value in validity_refs.items()
        })
        identity = (implementation.implementation_id, implementation.revision)
        previous_ref = self._by_identity.get(identity)
        if previous_ref is not None:
            previous = self._store.get(previous_ref)
            if previous.implementation != implementation or dict(previous.validity_refs) != dict(normalized):
                raise RegistryError("implementation revision identity is immutable")
            return RegistrationReceipt(previous_ref)
        record = _RegisteredImplementation(implementation, normalized)
        reference = self._store.put(record)
        self._by_identity[identity] = reference
        return RegistrationReceipt(reference)

    def get(self, implementation_ref: str) -> ImplementationRevision:
        return self._store.get(implementation_ref).implementation

    def candidate_set(self, requirement: CapabilityRequirementRevision) -> CandidateSet:
        candidates = []
        for record in sorted(
            (self._store.get(reference) for reference in self._by_identity.values()),
            key=lambda item: (item.implementation.implementation_id, item.implementation.revision),
        ):
            implementation = record.implementation
            candidates.append(
                ImplementationCandidate(
                    candidate_id=f"{implementation.implementation_id}@{implementation.revision}",
                    implementation=implementation,
                    feasible=True,
                    available=True,
                    validity_refs=record.validity_refs,
                )
            )
        return CandidateSet(requirement.content_digest, tuple(candidates))


__all__ = ["CapabilityRegistry", "RegistryError", "RegistrationReceipt"]
