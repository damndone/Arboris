"""Append-only content-addressed storage for the CF2 preparation boundary."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

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
        if self.root is not None:
            if not self.root.is_absolute():
                raise DependencyStoreError("persistent dependency store root must be absolute")
            self._assert_no_symlink_ancestors(self.root)
            if create:
                self.root.mkdir(parents=True, exist_ok=True)
            elif self.root.is_symlink():
                raise DependencyStoreError("persistent dependency store root cannot be a symlink")
        self._locks: dict[str, DependencyLock] = {}
        self._bundles: dict[str, BundleCandidate] = {}
        self._admissions: dict[str, list[BundleAdmission]] = {}
        self._quarantine_builds: dict[str, Any] = {}
        self._supply_chain: dict[str, Any] = {}
        self._supply_chain_reports: dict[str, Any] = {}
        self._supply_chain_verifications: dict[str, Any] = {}
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
                "locks",
                reference,
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
                record = self._read_single("locks", reference)
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
                "bundles",
                reference,
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
                record = self._read_single("bundles", reference)
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
            previous = self._append_record(
                "admissions",
                admission.bundle_ref,
                self._admission_record(admission),
                dedupe_digest=admission.content_digest,
            )
            if previous is not None:
                previous_admission = self._admission_from_record(previous)
                if previous_admission.bundle_ref != admission.bundle_ref:
                    raise DependencyStoreError("admission history has a mismatched bundle")
                return previous_admission
            return admission

    def admission_history(self, bundle_ref: str) -> tuple[BundleAdmission, ...]:
        bundle_ref = _digest(bundle_ref, "bundle_ref")
        with self._lock:
            if self.root is None:
                return tuple(self._admissions.get(bundle_ref, ()))
            try:
                records = self._read_records("admissions", bundle_ref)
                history = tuple(self._admission_from_record(item) for item in records)
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("dependency admission history is corrupt") from error
            if any(item.bundle_ref != bundle_ref for item in history):
                raise DependencyStoreError("dependency admission history has a mismatched bundle")
            return history

    def put_quarantine_build(self, build: Any) -> Any:
        from .dependency_service import QuarantineBuild

        if not isinstance(build, QuarantineBuild):
            raise DependencyStoreError("only QuarantineBuild records can be stored")
        with self._lock:
            reference = build.bundle_ref
            if self.root is None:
                existing = self._quarantine_builds.get(reference)
                if existing is not None and existing != build:
                    raise DependencyStoreError("quarantine build reference is already bound")
                self._quarantine_builds[reference] = build
                return build
            self._put_once(
                "quarantine-builds",
                reference,
                self._quarantine_build_record_payload(build),
                expected_digest=build.content_digest,
            )
            return self.get_quarantine_build(reference, root=build.root)

    def get_quarantine_build(self, bundle_ref: str, *, root: Path | str) -> Any:
        from .dependency_service import QuarantineBuild

        bundle_ref = _digest(bundle_ref, "bundle_ref")
        with self._lock:
            if self.root is None:
                try:
                    build = self._quarantine_builds[bundle_ref]
                except KeyError as error:
                    raise DependencyStoreError("quarantine build was not found") from error
                if Path(root) == build.root:
                    return build
                return QuarantineBuild(
                    lock_ref=build.lock_ref,
                    bundle_ref=build.bundle_ref,
                    tree_manifest_ref=build.tree_manifest_ref,
                    sbom_ref=build.sbom_ref,
                    root=Path(root),
                )
            try:
                record = self._read_single("quarantine-builds", bundle_ref)
                build = QuarantineBuild(root=root, **record["build"])
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("quarantine build is missing or corrupt") from error
            if (
                build.bundle_ref != bundle_ref
                or record.get("content_digest") != build.content_digest
            ):
                raise DependencyStoreError("quarantine build reference does not match content")
            return build

    def put_supply_chain_report(self, report: Any) -> Any:
        from .dependency_service import SupplyChainReport

        if not isinstance(report, SupplyChainReport):
            raise DependencyStoreError("only SupplyChainReport records can be stored")
        with self._lock:
            reference = report.content_digest
            if self.root is None:
                existing = self._supply_chain_reports.get(reference)
                if existing is not None and existing != report:
                    raise DependencyStoreError("supply-chain report reference is already bound")
                self._supply_chain_reports[reference] = report
                return report
            self._put_once(
                "supply-chain-reports",
                reference,
                self._supply_chain_report_record(report),
                expected_digest=reference,
            )
            return self.get_supply_chain_report(reference)

    def get_supply_chain_report(self, report_ref: str) -> Any:
        from .dependency_service import SupplyChainReport

        report_ref = _digest(report_ref, "report_ref")
        with self._lock:
            if self.root is None:
                try:
                    return self._supply_chain_reports[report_ref]
                except KeyError as error:
                    raise DependencyStoreError("supply-chain report was not found") from error
            try:
                record = self._read_single("supply-chain-reports", report_ref)
                report = SupplyChainReport(**record["report"])
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("supply-chain report is missing or corrupt") from error
            if (
                report.content_digest != report_ref
                or record.get("content_digest") != report.content_digest
            ):
                raise DependencyStoreError("supply-chain report reference does not match content")
            return report

    def put_supply_chain_attestation(self, attestation: Any) -> Any:
        """Persist one exact external supply-chain attestation by bundle."""

        from .dependency_service import SupplyChainAttestation

        if not isinstance(attestation, SupplyChainAttestation):
            raise DependencyStoreError("only SupplyChainAttestation records can be stored")
        with self._lock:
            self._require_persisted_build_binding(attestation)
            for report_ref in (
                attestation.license_report_ref,
                attestation.vulnerability_report_ref,
            ):
                if report_ref is not None:
                    self.get_supply_chain_report(report_ref)
            reference = attestation.bundle_ref
            if self.root is None:
                existing = self._supply_chain.get(reference)
                if existing is not None and existing != attestation:
                    raise DependencyStoreError("supply-chain attestation is already bound")
                self._supply_chain[reference] = attestation
                return attestation
            self._put_once(
                "supply-chain",
                reference,
                self._supply_chain_record(attestation),
                expected_digest=attestation.content_digest,
            )
            return self.get_supply_chain_attestation(reference)

    def get_supply_chain_attestation(self, bundle_ref: str) -> Any:
        from .dependency_service import SupplyChainAttestation

        bundle_ref = _digest(bundle_ref, "bundle_ref")
        with self._lock:
            if self.root is None:
                try:
                    return self._supply_chain[bundle_ref]
                except KeyError as error:
                    raise DependencyStoreError("supply-chain attestation was not found") from error
            try:
                record = self._read_single("supply-chain", bundle_ref)
                attestation = SupplyChainAttestation(**record["attestation"])
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("supply-chain attestation is missing or corrupt") from error
            if attestation.bundle_ref != bundle_ref or record.get("content_digest") != attestation.content_digest:
                raise DependencyStoreError("supply-chain attestation reference does not match content")
            return attestation

    def put_supply_chain_verification(self, verification: Any) -> Any:
        """Persist the verifier's decision bound to one attestation and build."""

        from .dependency_service import SupplyChainVerification

        if not isinstance(verification, SupplyChainVerification):
            raise DependencyStoreError("only SupplyChainVerification records can be stored")
        with self._lock:
            try:
                attestation = self.get_supply_chain_attestation_by_reference(
                    verification.attestation_ref
                )
            except DependencyStoreError as error:
                raise DependencyStoreError(
                    "supply-chain verification requires a persisted attestation"
                ) from error
            if verification.authority_ref != attestation.authority_ref:
                raise DependencyStoreError("supply-chain verification authority is mismatched")
            if verification.build_ref != self._persisted_build_digest(attestation.bundle_ref):
                raise DependencyStoreError("supply-chain verification build is mismatched")
            reference = verification.attestation_ref
            if self.root is None:
                existing = self._supply_chain_verifications.get(reference)
                if existing is not None and existing != verification:
                    raise DependencyStoreError("supply-chain verification is already bound")
                self._supply_chain_verifications[reference] = verification
                return verification
            self._put_once(
                "supply-chain-verifications",
                reference,
                self._supply_chain_verification_record(verification),
                expected_digest=verification.content_digest,
            )
            return self.get_supply_chain_verification(reference)

    def get_supply_chain_verification(self, attestation_ref: str) -> Any:
        from .dependency_service import SupplyChainVerification

        attestation_ref = _digest(attestation_ref, "attestation_ref")
        with self._lock:
            if self.root is None:
                try:
                    return self._supply_chain_verifications[attestation_ref]
                except KeyError as error:
                    raise DependencyStoreError("supply-chain verification was not found") from error
            try:
                record = self._read_single("supply-chain-verifications", attestation_ref)
                verification = SupplyChainVerification(**record["verification"])
            except (KeyError, OSError, TypeError, ValueError) as error:
                raise DependencyStoreError("supply-chain verification is missing or corrupt") from error
            if (
                verification.attestation_ref != attestation_ref
                or record.get("content_digest") != verification.content_digest
            ):
                raise DependencyStoreError("supply-chain verification reference does not match content")
            return verification

    def get_supply_chain_attestation_by_reference(self, attestation_ref: str) -> Any:
        from .dependency_service import SupplyChainAttestation

        attestation_ref = _digest(attestation_ref, "attestation_ref")
        with self._lock:
            if self.root is None:
                for attestation in self._supply_chain.values():
                    if attestation.content_digest == attestation_ref:
                        return attestation
                raise DependencyStoreError("supply-chain attestation was not found")
            directory = self.root / "supply-chain"
            self._assert_no_symlink_ancestors(directory)
            if not directory.exists() or directory.is_symlink():
                raise DependencyStoreError("supply-chain attestation was not found")
            for path in directory.iterdir():
                if path.name.endswith(".jsonl") and len(path.stem) == 64:
                    try:
                        record = self._read_single("supply-chain", path.stem)
                        attestation = SupplyChainAttestation(**record["attestation"])
                    except (KeyError, OSError, TypeError, ValueError):
                        continue
                    if attestation.content_digest == attestation_ref:
                        return attestation
            raise DependencyStoreError("supply-chain attestation was not found")

    def _require_persisted_build_binding(self, attestation: Any) -> None:
        record = self._stored_quarantine_build_record(attestation.bundle_ref)
        payload = record["build"]
        if (
            payload["bundle_ref"] != attestation.bundle_ref
            or payload["tree_manifest_ref"] != attestation.tree_manifest_ref
            or payload["sbom_ref"] != attestation.sbom_ref
        ):
            raise DependencyStoreError("supply-chain attestation is not bound to a quarantine build")

    def _persisted_build_digest(self, bundle_ref: str) -> str:
        return self._stored_quarantine_build_record(bundle_ref)["content_digest"]

    def _stored_quarantine_build_record(self, bundle_ref: str) -> dict[str, Any]:
        bundle_ref = _digest(bundle_ref, "bundle_ref")
        if self.root is None:
            try:
                build = self._quarantine_builds[bundle_ref]
            except KeyError as error:
                raise DependencyStoreError("quarantine build was not found") from error
            return self._quarantine_build_record_payload(build)
        return self._read_single("quarantine-builds", bundle_ref)

    @staticmethod
    def _quarantine_build_record_payload(build: Any) -> dict[str, Any]:
        return {
            "record_type": "quarantine_build",
            "content_digest": build.content_digest,
            "build": {
                "lock_ref": build.lock_ref,
                "bundle_ref": build.bundle_ref,
                "tree_manifest_ref": build.tree_manifest_ref,
                "sbom_ref": build.sbom_ref,
                "license_status": build.license_status,
                "vulnerability_status": build.vulnerability_status,
            },
        }

    def _path(self, kind: str, reference: str) -> Path:
        if self.root is None:
            raise DependencyStoreError("persistent path is unavailable")
        return self.root / kind / f"{reference}.jsonl"

    def _read_records(self, kind: str, reference: str) -> list[dict[str, Any]]:
        directory = self._open_kind_directory(kind, create=False)
        if directory is None:
            return []
        try:
            filename = self._record_filename(reference)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(filename, flags, dir_fd=directory)
            except FileNotFoundError:
                return []
            try:
                return self._decode_jsonl(self._read_descriptor(descriptor))
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)

    def _read_single(self, kind: str, reference: str) -> dict[str, Any]:
        records = self._read_records(kind, reference)
        if len(records) != 1:
            raise DependencyStoreError("immutable dependency record must have one JSONL entry")
        return records[0]

    def _put_once(
        self,
        kind: str,
        reference: str,
        record: dict[str, Any],
        *,
        expected_digest: str,
    ) -> None:
        directory = self._open_kind_directory(kind, create=True)
        assert directory is not None
        try:
            filename = self._record_filename(reference)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(filename, flags, 0o600, dir_fd=directory)
            except FileExistsError:
                existing = self._read_single(kind, reference)
                if existing.get("content_digest") != expected_digest or existing != record:
                    raise DependencyStoreError("content reference is already bound to different data")
                return
            try:
                self._write_descriptor(descriptor, record)
            finally:
                os.close(descriptor)
        except DependencyStoreError:
            raise
        except OSError as error:
            raise DependencyStoreError("dependency store write failed closed") from error
        finally:
            os.close(directory)

    def _append_record(
        self,
        kind: str,
        reference: str,
        record: dict[str, Any],
        *,
        dedupe_digest: str,
    ) -> dict[str, Any] | None:
        directory = self._open_kind_directory(kind, create=True)
        assert directory is not None
        descriptor = -1
        try:
            filename = self._record_filename(reference)
            flags = (
                os.O_RDWR
                | os.O_CREAT
                | os.O_APPEND
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(filename, flags, 0o600, dir_fd=directory)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            records = self._decode_jsonl(self._read_descriptor(descriptor))
            if records and records[-1].get("content_digest") == dedupe_digest:
                return records[-1]
            self._write_descriptor(descriptor, record, append=True)
            return None
        except DependencyStoreError:
            raise
        except OSError as error:
            raise DependencyStoreError("dependency store append failed closed") from error
        finally:
            if descriptor != -1:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
            os.close(directory)

    @staticmethod
    def _record_filename(reference: str) -> str:
        return f"{_digest(reference, 'record_ref')}.jsonl"

    def _open_kind_directory(self, kind: str, *, create: bool) -> int | None:
        if self.root is None:
            raise DependencyStoreError("persistent path is unavailable")
        if kind not in {
            "locks",
            "bundles",
            "admissions",
            "quarantine-builds",
            "supply-chain",
            "supply-chain-reports",
            "supply-chain-verifications",
        }:
            raise DependencyStoreError("unsupported dependency store record kind")
        kind_path = self.root / kind
        self._assert_no_symlink_ancestors(kind_path)
        if create:
            kind_path.mkdir(parents=True, exist_ok=True)
        elif not kind_path.exists():
            return None
        if kind_path.is_symlink() or not kind_path.is_dir():
            raise DependencyStoreError("dependency store record directory is not safe")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            return os.open(kind_path, flags)
        except OSError as error:
            raise DependencyStoreError("dependency store record directory is unavailable") from error

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _write_descriptor(
        descriptor: int,
        record: dict[str, Any],
        *,
        append: bool = False,
    ) -> None:
        if not append:
            os.lseek(descriptor, 0, os.SEEK_SET)
        payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)

    @staticmethod
    def _decode_jsonl(raw: bytes) -> list[dict[str, Any]]:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DependencyStoreError("dependency store contains invalid UTF-8") from error
        records: list[dict[str, Any]] = []
        lines = text.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise DependencyStoreError(
                    f"dependency store contains invalid JSONL at line {index + 1}"
                ) from error
            if not isinstance(value, dict):
                raise DependencyStoreError("dependency store JSONL record is not an object")
            records.append(value)
        return records

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path) -> None:
        current = path
        while True:
            if current.is_symlink():
                raise DependencyStoreError("dependency store path cannot contain a symlink")
            if current.parent == current:
                return
            current = current.parent

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

    @staticmethod
    def _supply_chain_record(attestation: Any) -> dict[str, Any]:
        return {
            "record_type": "supply_chain_attestation",
            "content_digest": attestation.content_digest,
            "attestation": {
                "bundle_ref": attestation.bundle_ref,
                "tree_manifest_ref": attestation.tree_manifest_ref,
                "sbom_ref": attestation.sbom_ref,
                "license_status": attestation.license_status,
                "vulnerability_status": attestation.vulnerability_status,
                "authority_ref": attestation.authority_ref,
                "license_report_ref": attestation.license_report_ref,
                "vulnerability_report_ref": attestation.vulnerability_report_ref,
            },
        }

    @staticmethod
    def _supply_chain_report_record(report: Any) -> dict[str, Any]:
        return {
            "record_type": "supply_chain_report",
            "content_digest": report.content_digest,
            "report": {
                "report_kind": report.report_kind,
                "build_ref": report.build_ref,
                "sbom_ref": report.sbom_ref,
                "authority_ref": report.authority_ref,
                "status": report.status,
                "evidence_ref": report.evidence_ref,
            },
        }

    @staticmethod
    def _supply_chain_verification_record(verification: Any) -> dict[str, Any]:
        return {
            "record_type": "supply_chain_verification",
            "content_digest": verification.content_digest,
            "verification": {
                "authority_ref": verification.authority_ref,
                "decision_ref": verification.decision_ref,
                "status": verification.status,
                "attestation_ref": verification.attestation_ref,
                "build_ref": verification.build_ref,
                "issued_at": verification.issued_at,
                "valid_until": verification.valid_until,
                "advisory_snapshot_ref": verification.advisory_snapshot_ref,
            },
        }


__all__ = ["DependencyStore", "DependencyStoreError"]
