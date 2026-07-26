"""Offline dependency preparation service for the CF2 boundary."""

from __future__ import annotations

from dataclasses import dataclass

from ..custom_capability.canonical import domain_digest
from .bundle_admission import AdmissionError, BundleAdmissionController
from .bundle_assembler import BundleAssemblyError, BundleAssembler, BundleCandidate
from .contracts import _plain
from .dependency_contract import BundleAdmission, DependencyLock, DependencyRequirement
from .dependency_resolver import (
    DependencyResolutionError,
    DependencyResolutionPolicy,
    DependencyResolver,
    IndexSnapshot,
)
from .dependency_store import DependencyStore, DependencyStoreError


class DependencyPreparationError(ValueError):
    """Raised when a locked dependency cannot reach quarantine."""


@dataclass(frozen=True, slots=True)
class DependencyPreparation:
    lock: DependencyLock
    bundle: BundleCandidate
    admission: BundleAdmission

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.dependency_preparation/v1",
            {
                "lock": _plain(self.lock),
                "bundle": _plain(self.bundle),
                "admission": _plain(self.admission),
            },
        )


class DependencyService:
    """Resolve and quarantine bytes without fetching, installing, or importing.

    The caller supplies an immutable index snapshot and already-fetched bytes.
    That keeps the network boundary outside this service and makes the result
    safe to hand to an offline validation stage.
    """

    def __init__(
        self,
        *,
        resolver: DependencyResolver | None = None,
        assembler: BundleAssembler | None = None,
        admission: BundleAdmissionController | None = None,
        store: DependencyStore | None = None,
    ) -> None:
        self.resolver = resolver or DependencyResolver()
        self.assembler = assembler or BundleAssembler()
        self.admission = admission or BundleAdmissionController()
        self.store = store or DependencyStore()

    def prepare_quarantine(
        self,
        *,
        requirements: tuple[DependencyRequirement, ...],
        snapshot: IndexSnapshot,
        policy: DependencyResolutionPolicy,
        artifacts: dict[str, bytes],
    ) -> DependencyPreparation:
        try:
            lock = self.resolver.resolve(
                requirements=requirements,
                snapshot=snapshot,
                policy=policy,
            )
            bundle = self.assembler.assemble(lock=lock, artifacts=artifacts)
            admission = self.admission.quarantine(bundle_ref=bundle.bundle_ref)
            self.store.put_lock(lock)
            self.store.put_bundle(bundle)
            self.store.append_admission(admission)
            return DependencyPreparation(lock=lock, bundle=bundle, admission=admission)
        except (
            DependencyResolutionError,
            BundleAssemblyError,
            AdmissionError,
            DependencyStoreError,
        ) as error:
            raise DependencyPreparationError(str(error)) from error


__all__ = ["DependencyPreparation", "DependencyPreparationError", "DependencyService"]
