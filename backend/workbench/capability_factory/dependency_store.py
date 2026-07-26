"""In-memory content-addressed storage for the CF2 preparation boundary."""

from __future__ import annotations

from .bundle_assembler import BundleCandidate
from .dependency_contract import BundleAdmission, DependencyLock
from .contracts import _digest


class DependencyStoreError(ValueError):
    """Raised when an immutable dependency record cannot be stored or read."""


class DependencyStore:
    """Keep immutable CF2 records without exposing mutable references.

    Persistence and project scoping are deliberately deferred to the service
    integration slice. This store still enforces the important invariant now:
    a content reference can never be rebound to a different record.
    """

    def __init__(self) -> None:
        self._locks: dict[str, DependencyLock] = {}
        self._bundles: dict[str, BundleCandidate] = {}
        self._admissions: dict[str, list[BundleAdmission]] = {}

    def put_lock(self, lock: DependencyLock) -> DependencyLock:
        if not isinstance(lock, DependencyLock):
            raise DependencyStoreError("only DependencyLock records can be stored")
        reference = lock.content_digest
        existing = self._locks.get(reference)
        if existing is not None and existing != lock:
            raise DependencyStoreError("dependency lock reference is already bound")
        self._locks[reference] = lock
        return lock

    def get_lock(self, reference: str) -> DependencyLock:
        try:
            return self._locks[_digest(reference, "lock_ref")]
        except KeyError as error:
            raise DependencyStoreError("dependency lock was not found") from error

    def put_bundle(self, bundle: BundleCandidate) -> BundleCandidate:
        if not isinstance(bundle, BundleCandidate):
            raise DependencyStoreError("only BundleCandidate records can be stored")
        existing = self._bundles.get(bundle.bundle_ref)
        if existing is not None and existing != bundle:
            raise DependencyStoreError("bundle reference is already bound")
        self._bundles[bundle.bundle_ref] = bundle
        return bundle

    def get_bundle(self, reference: str) -> BundleCandidate:
        try:
            return self._bundles[_digest(reference, "bundle_ref")]
        except KeyError as error:
            raise DependencyStoreError("dependency bundle was not found") from error

    def append_admission(self, admission: BundleAdmission) -> BundleAdmission:
        if not isinstance(admission, BundleAdmission):
            raise DependencyStoreError("only BundleAdmission records can be stored")
        self._admissions.setdefault(admission.bundle_ref, []).append(admission)
        return admission

    def admission_history(self, bundle_ref: str) -> tuple[BundleAdmission, ...]:
        return tuple(self._admissions.get(_digest(bundle_ref, "bundle_ref"), ()))


__all__ = ["DependencyStore", "DependencyStoreError"]
