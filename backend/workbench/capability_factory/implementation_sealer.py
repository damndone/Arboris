"""Immutable implementation bundle sealing before CF3 validation."""

from __future__ import annotations

from dataclasses import dataclass

from .adapter_contract import AdapterContract
from .candidate_store import CapabilityCandidate
from .contracts import _content_digest, _digest, _positive_int, _text


class SealingError(ValueError):
    """Raised when a candidate cannot be sealed into a validated revision."""


@dataclass(frozen=True, slots=True)
class ImplementationBundleRevision:
    bundle_id: str
    revision: int
    candidate_ref: str
    adapter_ref: str
    implementation_ref: str
    dependency_bundle_ref: str
    runtime_policy_ref: str
    environment_ref: str
    source_ref: str
    code_ref: str
    manifest_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        for field in (
            "candidate_ref",
            "adapter_ref",
            "implementation_ref",
            "dependency_bundle_ref",
            "runtime_policy_ref",
            "environment_ref",
            "source_ref",
            "code_ref",
            "manifest_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))

    @property
    def bundle_ref(self) -> str:
        return self.content_digest

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class ImplementationSealer:
    """Seal metadata only; it never imports or executes the candidate."""

    def seal(
        self,
        *,
        candidate: CapabilityCandidate,
        adapter: AdapterContract,
        dependency_bundle_ref: str,
        runtime_policy_ref: str,
        environment_ref: str,
        source_ref: str,
        code_ref: str,
        manifest_ref: str,
    ) -> ImplementationBundleRevision:
        if not isinstance(candidate, CapabilityCandidate):
            raise SealingError("candidate must be a CapabilityCandidate")
        if not isinstance(adapter, AdapterContract):
            raise SealingError("adapter must be an AdapterContract")
        if candidate.implementation_ref != adapter.implementation_ref:
            raise SealingError("candidate and adapter implementation binding does not match")
        if candidate.status != "submitted":
            raise SealingError("only submitted candidates can be sealed")
        return ImplementationBundleRevision(
            bundle_id=f"bundle.{candidate.candidate_id}",
            revision=1,
            candidate_ref=candidate.content_digest,
            adapter_ref=adapter.content_digest,
            implementation_ref=adapter.implementation_ref,
            dependency_bundle_ref=dependency_bundle_ref,
            runtime_policy_ref=runtime_policy_ref,
            environment_ref=environment_ref,
            source_ref=source_ref,
            code_ref=code_ref,
            manifest_ref=manifest_ref,
        )


__all__ = ["ImplementationBundleRevision", "ImplementationSealer", "SealingError"]
