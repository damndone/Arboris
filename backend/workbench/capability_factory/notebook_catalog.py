"""Server-owned lookup for admitted capability bindings.

The Agent may name a capability, but it never supplies the binding that gives
that name meaning.  This catalog keeps the identity mapping outside the Agent
payload and re-verifies the immutable binding whenever a Notebook consumer
looks it up.  It is deliberately in-memory in this slice; the Capability
Factory authority remains the source that constructs and refreshes it.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .notebook_binding import CapabilityResolutionBinding
from .store import ContentAddressedStore


class CapabilityBindingCatalogError(ValueError):
    """A server-owned binding could not be registered or resolved."""


CapabilityBindingVerifier = Callable[[CapabilityResolutionBinding], None]
ScopeCandidate = tuple[str, str]


def _capability_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityBindingCatalogError(
            "capability_id must be a non-empty trimmed string"
        )
    return value


class CapabilityBindingCatalog:
    """Map registered capability ids to immutable, currently usable bindings.

    Construction and registration belong to the trusted Workbench side.  The
    verifier is also trusted and normally delegates to the Capability Factory
    admission controller plus its current validity stores.  Lookup is the
    boundary used by NotebookService, so revocation or validity drift fails
    closed before an Option revision is constructed.
    """

    def __init__(self, *, verifier: CapabilityBindingVerifier) -> None:
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        self._verifier = verifier
        self._bindings = ContentAddressedStore[CapabilityResolutionBinding]()
        self._refs: dict[str, str] = {}

    def register(
        self,
        capability_id: str,
        binding: CapabilityResolutionBinding,
    ) -> str:
        capability_id = _capability_id(capability_id)
        if not isinstance(binding, CapabilityResolutionBinding):
            raise CapabilityBindingCatalogError(
                "binding must be a CapabilityResolutionBinding"
            )
        if binding.execution_allowed:
            raise CapabilityBindingCatalogError(
                "capability binding cannot grant execution"
            )
        digest = binding.content_digest
        previous = self._refs.get(capability_id)
        if previous is not None and previous != digest:
            raise CapabilityBindingCatalogError(
                f"capability_id {capability_id!r} is already bound to another digest"
            )
        self._verify(binding)
        self._bindings.put(binding)
        self._refs[capability_id] = digest
        return digest

    def resolve(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> CapabilityResolutionBinding | None:
        """Return a current binding, or ``None`` for an unregistered native id."""

        capability_id = _capability_id(capability_id)
        digest = self._refs.get(capability_id)
        if digest is None:
            return None
        try:
            binding = self._bindings.get(digest)
        except KeyError as error:
            raise CapabilityBindingCatalogError(
                f"binding reference for {capability_id!r} is unavailable"
            ) from error
        if scope_candidates is not None and binding.scope_kind != "release_builtin":
            if (binding.scope_kind, binding.scope_ref) not in set(scope_candidates):
                raise CapabilityBindingCatalogError(
                    f"binding scope is not valid for capability {capability_id!r}"
                )
        self._verify(binding)
        return binding

    def require(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> CapabilityResolutionBinding:
        binding = self.resolve(capability_id, scope_candidates=scope_candidates)
        if binding is None:
            raise CapabilityBindingCatalogError(
                f"no server-owned binding is registered for {capability_id!r}"
            )
        return binding

    def assert_current_reference(self, reference: str) -> None:
        """Re-verify a persisted binding digest before a later consumer step."""

        try:
            binding = self._bindings.get(reference)
        except KeyError as error:
            raise CapabilityBindingCatalogError(
                "persisted capability binding reference is unavailable"
            ) from error
        self._verify(binding)

    def _verify(self, binding: CapabilityResolutionBinding) -> None:
        try:
            self._verifier(binding)
        except Exception as error:
            raise CapabilityBindingCatalogError(
                "server-owned capability binding is not currently usable"
            ) from error


__all__ = [
    "CapabilityBindingCatalog",
    "CapabilityBindingCatalogError",
    "CapabilityBindingVerifier",
    "ScopeCandidate",
]
