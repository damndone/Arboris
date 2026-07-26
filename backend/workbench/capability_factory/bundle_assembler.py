"""Offline quarantine assembly from inspected wheel bytes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..custom_capability.canonical import domain_digest
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
