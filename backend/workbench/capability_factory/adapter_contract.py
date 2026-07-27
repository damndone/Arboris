"""Profile-bound adapter metadata for CF3.

This module describes an adapter; it never loads, imports, or executes the
referenced implementation.  The entrypoint is a content reference only.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..custom_capability.canonical import domain_digest
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
from .candidate_store import CapabilityCandidate
from .validation_contract import ValidationBundle, ValidationCase


ADAPTER_CONTRACT_SCHEMA_VERSION = "workbench_capability_factory_adapter_v1"
MAX_GENERATED_SOURCE_BYTES = 256 * 1024


class AdapterContractError(ContractError):
    """Raised when an adapter is not bound to a compatible CF1 revision."""


class AdapterSourceGenerationError(AdapterContractError):
    """Raised when generated source cannot enter the immutable source store."""


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


@dataclass(frozen=True, slots=True)
class AdapterSourceArtifact:
    source_ref: str
    entrypoint_ref: str
    language: str
    size_bytes: int
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", _digest(self.source_ref, "source_ref"))
        object.__setattr__(self, "entrypoint_ref", _digest(self.entrypoint_ref, "entrypoint_ref"))
        if self.language != "python":
            raise AdapterSourceGenerationError("only the versioned Python adapter ABI is supported")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 1 or self.size_bytes > MAX_GENERATED_SOURCE_BYTES:
            raise AdapterSourceGenerationError("generated source size is outside the bound")
        path = Path(self.path)
        if not path.is_absolute() or path.name != f"{self.source_ref}.py":
            raise AdapterSourceGenerationError("generated source path is not content-addressed")
        object.__setattr__(self, "path", path)


class AdapterSourceGenerator:
    """Store Agent-produced source as an untrusted, content-addressed artifact."""

    def generate(
        self,
        *,
        implementation: ImplementationRevision,
        provider: Callable[[Mapping[str, object]], str | bytes],
        output_root: Path | str,
    ) -> AdapterSourceArtifact:
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterSourceGenerationError("implementation must be an ImplementationRevision")
        if not callable(provider):
            raise AdapterSourceGenerationError("source provider must be callable")
        context = {
            "profile_ref": implementation.profile_digest,
            "input_schema_ref": implementation.input_schema_digest,
            "operations": list(implementation.operations),
            "implementation_ref": implementation.content_digest,
        }
        try:
            generated = provider(context)
        except Exception as error:
            raise AdapterSourceGenerationError("source provider failed") from error
        if isinstance(generated, str):
            raw = generated.encode("utf-8")
        elif isinstance(generated, bytes):
            raw = generated
        else:
            raise AdapterSourceGenerationError("source provider must return UTF-8 text or bytes")
        if not raw or len(raw) > MAX_GENERATED_SOURCE_BYTES or b"\x00" in raw:
            raise AdapterSourceGenerationError("generated source is empty, oversized, or contains NUL")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AdapterSourceGenerationError("generated source is not valid UTF-8") from error
        root = Path(output_root)
        if not root.is_absolute() or root.exists() and root.is_symlink():
            raise AdapterSourceGenerationError("source output root must be absolute and not a symlink")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AdapterSourceGenerationError("source output root is not a directory")
        source_ref = hashlib.sha256(raw).hexdigest()
        entrypoint_ref = domain_digest(
            "workbench.capability_factory.adapter_entrypoint/v1",
            {"source_ref": source_ref, "symbol": "adapter"},
        )
        destination = root / f"{source_ref}.py"
        if destination.is_symlink():
            raise AdapterSourceGenerationError("source destination must not be a symlink")
        if destination.exists():
            if destination.read_bytes() != raw:
                raise AdapterSourceGenerationError("source reference is already bound to other bytes")
            return AdapterSourceArtifact(source_ref, entrypoint_ref, "python", len(raw), destination)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".adapter-", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o444)
            os.replace(temporary, destination)
            os.chmod(destination, 0o444)
        except OSError as error:
            raise AdapterSourceGenerationError("generated source write failed") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return AdapterSourceArtifact(source_ref, entrypoint_ref, "python", len(raw), destination)


@dataclass(frozen=True, slots=True)
class GeneratedAdapterCandidate:
    """The untrusted, not-yet-validated output of adapter generation."""

    candidate: CapabilityCandidate
    adapter: AdapterContract
    validation_bundle: ValidationBundle

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def source_eligible(self) -> bool:
        return False


class AdapterCandidateFactory:
    """Turn a typed generation request into metadata-only CF3 candidates.

    The caller supplies content references for generated code and its
    entrypoint.  This factory never receives source text, imports a module, or
    calls the entrypoint.  The resulting ValidationBundle intentionally has no
    evidence; only the later B1/CF3 validation path can append server-assessed
    evidence.
    """

    def generate(
        self,
        *,
        implementation: ImplementationRevision,
        adapter_id: str,
        adapter_revision: int,
        entrypoint_ref: str,
        operations: tuple[str, ...],
        consumer_support: Mapping[str, str | None],
        candidate_id: str,
        capability_kind: str,
        source_ref: str,
        author_lineage_ref: str,
        validation_bundle_id: str,
        validation_cases: tuple[ValidationCase, ...],
        source_artifact: AdapterSourceArtifact | None = None,
    ) -> GeneratedAdapterCandidate:
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        if implementation.source_kind != "generated_adapter":
            raise AdapterContractError("adapter generation requires generated_adapter trust tier")
        if not isinstance(validation_cases, (tuple, list)) or not validation_cases:
            raise AdapterContractError("adapter generation requires bounded validation cases")
        if any(not isinstance(item, ValidationCase) for item in validation_cases):
            raise AdapterContractError("validation_cases must contain ValidationCase values")
        if source_artifact is not None:
            if not isinstance(source_artifact, AdapterSourceArtifact):
                raise AdapterContractError("source_artifact must be an AdapterSourceArtifact")
            if source_ref != source_artifact.source_ref:
                raise AdapterContractError("candidate source_ref does not match generated source")
            if entrypoint_ref != source_artifact.entrypoint_ref:
                raise AdapterContractError("candidate entrypoint_ref does not match generated source")
        adapter = AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id=adapter_id,
            revision=adapter_revision,
            entrypoint_ref=entrypoint_ref,
            operations=operations,
            consumer_support=consumer_support,
        )
        candidate = CapabilityCandidate(
            candidate_id=candidate_id,
            capability_kind=capability_kind,
            source_kind="generated_adapter",
            implementation_ref=implementation.content_digest,
            source_ref=source_ref,
            author_lineage_ref=author_lineage_ref,
            risk_level="high",
        )
        validation_bundle = ValidationBundle(
            bundle_id=validation_bundle_id,
            revision=1,
            adapter_ref=adapter.content_digest,
            cases=tuple(validation_cases),
        )
        return GeneratedAdapterCandidate(
            candidate=candidate,
            adapter=adapter,
            validation_bundle=validation_bundle,
        )


__all__ = [
    "ADAPTER_CONTRACT_SCHEMA_VERSION",
    "AdapterCandidateFactory",
    "AdapterContract",
    "AdapterContractError",
    "AdapterSourceArtifact",
    "AdapterSourceGenerationError",
    "AdapterSourceGenerator",
    "GeneratedAdapterCandidate",
]
