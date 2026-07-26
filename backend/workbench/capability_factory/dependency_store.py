"""Append-only content-addressed storage for the CF2 preparation boundary."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from ..agent.storage import append_jsonl_atomic, read_jsonl
from .bundle_assembler import BundleCandidate
from .contracts import _digest
from .dependency_contract import BundleAdmission, DependencyLock, DependencyRequirement


class DependencyStoreError(ValueError):
    """Raised when an immutable dependency record cannot be stored or read."""


class DependencyStore:
    """Persist metadata without persisting or importing executable artifacts.

    ``root=None`` keeps the small unit-test/in-process mode. A project root
    enables append-only JSONL records, so a fresh service instance can rebuild
    the same lock, bundle, and admission history. The content digest is always
    checked when reading; disk mutation cannot silently rebind a reference.
    """

    def __init__(self, root: Path | str | None = None, *, create: bool = True) -> None:
        self.root = Path(root) if root is not None else None
        if self.root is not None and create:
            self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, DependencyLock] = {}
        self._bundles: dict[str, BundleCandidate] = {}
        self._admissions: dict[str, list[BundleAdmission]] = {}
        self._lock = RLock()

    def put_lock(self, lock: DependencyLock) -> DependencyLock:
        if not isinstance(lock, DependencyLock):
            raise DependencyStoreError("only DependencyLock records can be stored")
        with self._lock:
            reference = lock.content_digest
            if self.root is None:
                existing = self._locks.get(reference)
                if existing is not None and existing != lock:
                    raise DependencyStoreError("dependency lock reference is already bound")
                self._locks[reference] = lock
                return lock
            self._put_once(
                self._path("locks", reference),
                self._lock_record(lock),
                expected_digest=reference,
            )
            return self.get_lock(reference)

    def get_lock(self, reference: str) -> DependencyLock:
        reference = _digest(reference, "lock_ref")
        with self._lock:
            if self.root is None:
                try:
                    return self._locks[reference]
                except KeyError as error:
                    raise DependencyStoreError("dependency lock was not found") from error
            try:
                record = self._read_single(self._path("locks", reference))
                lock = self._lock_from_record(record)
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("dependency lock is missing or corrupt") from error
            if lock.content_digest != reference:
                raise DependencyStoreError("dependency lock reference does not match content")
            return lock

    def put_bundle(self, bundle: BundleCandidate) -> BundleCandidate:
        if not isinstance(bundle, BundleCandidate):
            raise DependencyStoreError("only BundleCandidate records can be stored")
        with self._lock:
            reference = bundle.bundle_ref
            if self.root is None:
                existing = self._bundles.get(reference)
                if existing is not None and existing != bundle:
                    raise DependencyStoreError("bundle reference is already bound")
                self._bundles[reference] = bundle
                return bundle
            self._put_once(
                self._path("bundles", reference),
                self._bundle_record(bundle),
                expected_digest=reference,
            )
            return self.get_bundle(reference)

    def get_bundle(self, reference: str) -> BundleCandidate:
        reference = _digest(reference, "bundle_ref")
        with self._lock:
            if self.root is None:
                try:
                    return self._bundles[reference]
                except KeyError as error:
                    raise DependencyStoreError("dependency bundle was not found") from error
            try:
                record = self._read_single(self._path("bundles", reference))
                bundle = self._bundle_from_record(record)
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("dependency bundle is missing or corrupt") from error
            if bundle.bundle_ref != reference or bundle.content_digest != reference:
                raise DependencyStoreError("dependency bundle reference does not match content")
            return bundle

    def append_admission(self, admission: BundleAdmission) -> BundleAdmission:
        if not isinstance(admission, BundleAdmission):
            raise DependencyStoreError("only BundleAdmission records can be stored")
        with self._lock:
            if self.root is None:
                self._admissions.setdefault(admission.bundle_ref, []).append(admission)
                return admission
            path = self._path("admissions", admission.bundle_ref)
            records = self._read_records(path)
            if records:
                previous = self._admission_from_record(records[-1])
                if previous.bundle_ref != admission.bundle_ref:
                    raise DependencyStoreError("admission history has a mismatched bundle")
                if previous.content_digest == admission.content_digest:
                    return previous
            append_jsonl_atomic(path, self._admission_record(admission))
            return admission

    def admission_history(self, bundle_ref: str) -> tuple[BundleAdmission, ...]:
        bundle_ref = _digest(bundle_ref, "bundle_ref")
        with self._lock:
            if self.root is None:
                return tuple(self._admissions.get(bundle_ref, ()))
            try:
                records = self._read_records(self._path("admissions", bundle_ref))
                history = tuple(self._admission_from_record(item) for item in records)
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("dependency admission history is corrupt") from error
            if any(item.bundle_ref != bundle_ref for item in history):
                raise DependencyStoreError("dependency admission history has a mismatched bundle")
            return history

    def _path(self, kind: str, reference: str) -> Path:
        if self.root is None:
            raise DependencyStoreError("persistent path is unavailable")
        return self.root / kind / f"{reference}.jsonl"

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, Any]]:
        return read_jsonl(path)

    @classmethod
    def _read_single(cls, path: Path) -> dict[str, Any]:
        records = cls._read_records(path)
        if len(records) != 1:
            raise DependencyStoreError("immutable dependency record must have one JSONL entry")
        return records[0]

    @staticmethod
    def _put_once(path: Path, record: dict[str, Any], *, expected_digest: str) -> None:
        if path.exists():
            existing = DependencyStore._read_single(path)
            if existing.get("content_digest") != expected_digest or existing != record:
                raise DependencyStoreError("content reference is already bound to different data")
            return
        append_jsonl_atomic(path, record)

    @staticmethod
    def _lock_record(lock: DependencyLock) -> dict[str, Any]:
        return {
            "record_type": "dependency_lock",
            "content_digest": lock.content_digest,
            "lock": {
                "lock_id": lock.lock_id,
                "revision": lock.revision,
                "requirements": [
                    {
                        "distribution": item.distribution,
                        "version": item.version,
                        "artifact_digest": item.artifact_digest,
                        "python_tag": item.python_tag,
                        "platform_tag": item.platform_tag,
                        "index_origin": item.index_origin,
                    }
                    for item in lock.requirements
                ],
                "resolver_policy_digest": lock.resolver_policy_digest,
                "python_version": lock.python_version,
                "operating_system": lock.operating_system,
                "architecture": lock.architecture,
            },
        }

    @staticmethod
    def _lock_from_record(record: dict[str, Any]) -> DependencyLock:
        payload = record["lock"]
        requirements = tuple(
            DependencyRequirement(**item) for item in payload["requirements"]
        )
        lock = DependencyLock(
            lock_id=payload["lock_id"],
            revision=payload["revision"],
            requirements=requirements,
            resolver_policy_digest=payload["resolver_policy_digest"],
            python_version=payload["python_version"],
            operating_system=payload["operating_system"],
            architecture=payload["architecture"],
        )
        if record.get("content_digest") != lock.content_digest:
            raise DependencyStoreError("dependency lock content digest mismatch")
        return lock

    @staticmethod
    def _bundle_record(bundle: BundleCandidate) -> dict[str, Any]:
        return {
            "record_type": "bundle_candidate",
            "content_digest": bundle.content_digest,
            "bundle": {
                "bundle_ref": bundle.bundle_ref,
                "lock_ref": bundle.lock_ref,
                "status": bundle.status,
                "manifest_digest": bundle.manifest_digest,
                "artifact_refs": list(bundle.artifact_refs),
            },
        }

    @staticmethod
    def _bundle_from_record(record: dict[str, Any]) -> BundleCandidate:
        payload = record["bundle"]
        bundle = BundleCandidate(**payload)
        if record.get("content_digest") != bundle.content_digest:
            raise DependencyStoreError("dependency bundle content digest mismatch")
        return bundle

    @staticmethod
    def _admission_record(admission: BundleAdmission) -> dict[str, Any]:
        return {
            "record_type": "bundle_admission",
            "content_digest": admission.content_digest,
            "admission": {
                "bundle_ref": admission.bundle_ref,
                "status": admission.status,
                "scope": admission.scope,
                "validity_ref": admission.validity_ref,
                "reason_code": admission.reason_code,
            },
        }

    @staticmethod
    def _admission_from_record(record: dict[str, Any]) -> BundleAdmission:
        admission = BundleAdmission(**record["admission"])
        if record.get("content_digest") != admission.content_digest:
            raise DependencyStoreError("dependency admission content digest mismatch")
        return admission


__all__ = ["DependencyStore", "DependencyStoreError"]
