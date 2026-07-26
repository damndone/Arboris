"""Profile-bound adapter metadata for CF3.

This module describes an adapter; it never loads, imports, or executes the
referenced implementation.  The entrypoint is a content reference only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import (
    CONSUMER_SLOTS,
    TRUST_ORDER,
    ContractError,
    ImplementationRevision,
    _consumer_map,
    _content_digest,
    _digest,
    _positive_int,
    _sequence,
    _text,
)


ADAPTER_CONTRACT_SCHEMA_VERSION = "workbench_capability_factory_adapter_v1"


class AdapterContractError(ContractError):
    """Raised when an adapter is not bound to a compatible CF1 revision."""


@dataclass(frozen=True, slots=True)
class AdapterContract:
    """An immutable, executable-free binding for one adapter revision."""

    adapter_id: str
    revision: int
    implementation_ref: str
    profile_id: str
    profile_revision: int
    profile_digest: str
    input_schema_digest: str
    source_kind: str
    trust_tier: str
    operations: tuple[str, ...]
    consumer_support: Mapping[str, str | None]
    entrypoint_ref: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "adapter_id", _text(self.adapter_id, "adapter_id"))
            object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
            object.__setattr__(self, "implementation_ref", _digest(self.implementation_ref, "implementation_ref"))
            object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
            object.__setattr__(self, "profile_revision", _positive_int(self.profile_revision, "profile_revision"))
            object.__setattr__(self, "profile_digest", _digest(self.profile_digest, "profile_digest"))
            object.__setattr__(self, "input_schema_digest", _digest(self.input_schema_digest, "input_schema_digest"))
            source_kind = _text(self.source_kind, "source_kind")
            if source_kind not in TRUST_ORDER:
                raise AdapterContractError("source_kind is not a registered capability source")
            if self.trust_tier != source_kind:
                raise AdapterContractError("trust_tier must match source_kind")
            object.__setattr__(self, "source_kind", source_kind)
            object.__setattr__(self, "trust_tier", _text(self.trust_tier, "trust_tier"))
            object.__setattr__(self, "operations", _sequence(self.operations, "operations"))
            object.__setattr__(self, "consumer_support", _consumer_map(self.consumer_support, "consumer_support"))
            object.__setattr__(self, "entrypoint_ref", _digest(self.entrypoint_ref, "entrypoint_ref"))
        except ContractError as error:
            if isinstance(error, AdapterContractError):
                raise
            raise AdapterContractError(str(error)) from error

    @classmethod
    def from_implementation(
        cls,
        *,
        implementation: ImplementationRevision,
        adapter_id: str,
        revision: int,
        entrypoint_ref: str,
        operations: tuple[str, ...],
        consumer_support: Mapping[str, str | None],
    ) -> "AdapterContract":
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        adapter = cls(
            adapter_id=adapter_id,
            revision=revision,
            implementation_ref=implementation.content_digest,
            profile_id=implementation.profile_id,
            profile_revision=implementation.profile_revision,
            profile_digest=implementation.profile_digest,
            input_schema_digest=implementation.input_schema_digest,
            source_kind=implementation.source_kind,
            trust_tier=implementation.trust_tier,
            operations=operations,
            consumer_support=consumer_support,
            entrypoint_ref=entrypoint_ref,
        )
        adapter.validate_against(implementation)
        return adapter

    def validate_against(self, implementation: ImplementationRevision) -> None:
        """Recheck every inherited identity before a consumer can use metadata."""

        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        if self.implementation_ref != implementation.content_digest:
            raise AdapterContractError("implementation binding does not match")
        if self.profile_id != implementation.profile_id or self.profile_revision != implementation.profile_revision:
            raise AdapterContractError("profile identity does not match implementation")
        if self.profile_digest != implementation.profile_digest:
            raise AdapterContractError("profile digest does not match implementation")
        if self.input_schema_digest != implementation.input_schema_digest:
            raise AdapterContractError("input schema digest does not match implementation")
        if self.source_kind != implementation.source_kind or self.trust_tier != implementation.trust_tier:
            raise AdapterContractError("trust binding does not match implementation")
        if not set(self.operations) <= set(implementation.operations):
            raise AdapterContractError("adapter operations are not declared by implementation")
        for slot in CONSUMER_SLOTS:
            if implementation.consumer_support[slot] is None and self.consumer_support[slot] is not None:
                raise AdapterContractError(f"{slot} is not declared by implementation")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = ["ADAPTER_CONTRACT_SCHEMA_VERSION", "AdapterContract", "AdapterContractError"]
