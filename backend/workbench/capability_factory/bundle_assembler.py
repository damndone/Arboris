"""Offline quarantine assembly from inspected wheel bytes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import _digest, _sequence
from .dependency_contract import DependencyLock
from .wheel_inspection import WheelInspectionError, inspect_wheel_bytes


class BundleAssemblyError(ValueError):
    """Raised when a locked artifact cannot form a quarantine bundle."""


@dataclass(frozen=True, slots=True)
class BundleCandidate:
    bundle_ref: str
    lock_ref: str
    status: str
    manifest_digest: str
    artifact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_ref", _digest(self.bundle_ref, "bundle_ref"))
        object.__setattr__(self, "lock_ref", _digest(self.lock_ref, "lock_ref"))
        if self.status != "quarantined":
            raise BundleAssemblyError("bundle candidates must start in quarantine")
        object.__setattr__(self, "manifest_digest", _digest(self.manifest_digest, "manifest_digest"))
        object.__setattr__(
            self,
            "artifact_refs",
            tuple(_digest(item, "artifact_ref") for item in _sequence(self.artifact_refs, "artifact_refs")),
        )
        if self.bundle_ref != self.content_digest:
            raise BundleAssemblyError("bundle_ref does not match the bundle candidate content")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.bundle_candidate/v1",
            {"lock_ref": self.lock_ref, "manifest_digest": self.manifest_digest},
        )


class BundleAssembler:
    """Build only a content manifest; it never installs or imports artifacts."""

    def assemble(self, *, lock: DependencyLock, artifacts: Mapping[str, bytes]) -> BundleCandidate:
        if not isinstance(lock, DependencyLock) or not isinstance(artifacts, Mapping):
            raise BundleAssemblyError("lock and artifact bytes are required")
        manifest: list[dict[str, int | str]] = []
        for requirement in lock.requirements:
            raw = artifacts.get(requirement.artifact_digest)
            if not isinstance(raw, bytes):
                raise BundleAssemblyError("locked artifact bytes are missing")
            try:
                report = inspect_wheel_bytes(raw, expected_digest=requirement.artifact_digest)
            except WheelInspectionError as error:
                raise BundleAssemblyError(str(error)) from error
            if report.distribution != requirement.distribution or report.version != requirement.version:
                raise BundleAssemblyError("wheel metadata does not match the dependency lock")
            manifest.append(
                {
                    "artifact_digest": report.artifact_digest,
                    "member_count": report.member_count,
                    "distribution": report.distribution,
                    "version": report.version,
                }
            )
        manifest_digest = domain_digest(
            "workbench.capability_factory.bundle_manifest/v1",
            {"lock_ref": lock.content_digest, "artifacts": manifest},
        )
        bundle_ref = domain_digest(
            "workbench.capability_factory.bundle_candidate/v1",
            {"lock_ref": lock.content_digest, "manifest_digest": manifest_digest},
        )
        return BundleCandidate(
            bundle_ref=bundle_ref,
            lock_ref=lock.content_digest,
            status="quarantined",
            manifest_digest=manifest_digest,
            artifact_refs=tuple(item["artifact_digest"] for item in manifest),
        )


__all__ = ["BundleAssemblyError", "BundleAssembler", "BundleCandidate"]
