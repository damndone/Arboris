"""Network-separated dependency preparation service for the CF2 boundary."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from ..custom_capability.canonical import domain_digest
from .bundle_admission import AdmissionError, BundleAdmissionController
from .bundle_assembler import BundleAssemblyError, BundleAssembler, BundleCandidate
from .contracts import _plain
from .dependency_contract import BundleAdmission, DependencyLock, DependencyRequirement
from .dependency_fetch import FetchPolicy, FetchWorker, FetchWorkerError
from .dependency_resolver import (
    DependencyResolutionError,
    DependencyResolutionPolicy,
    DependencyResolver,
    IndexSnapshot,
)
from .dependency_store import DependencyStore, DependencyStoreError
from .wheel_inspection import WheelInspectionError, inspect_wheel_bytes


class DependencyPreparationError(ValueError):
    """Raised when a locked dependency cannot reach quarantine."""


class SupplyChainAttestationError(DependencyPreparationError):
    """Raised when a bundle lacks server-bound license or vulnerability facts."""


class SupplyChainVerifier(Protocol):
    def verify(
        self,
        *,
        attestation: "SupplyChainAttestation",
        build: "QuarantineBuild",
    ) -> "SupplyChainVerification": ...


@dataclass(frozen=True, slots=True)
class DependencyPreparation:
    lock: DependencyLock
    bundle: BundleCandidate
    admission: BundleAdmission
    quarantine_build: "QuarantineBuild | None" = None

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.dependency_preparation/v1",
            {
                "lock": _plain(self.lock),
                "bundle": _plain(self.bundle),
                "admission": _plain(self.admission),
                "quarantine_build_ref": (
                    self.quarantine_build.content_digest
                    if self.quarantine_build is not None
                    else None
                ),
            },
        )


@dataclass(frozen=True, slots=True)
class QuarantineBuild:
    """A read-only dependency tree assembled without importing wheel code."""

    bundle_ref: str
    tree_manifest_ref: str
    sbom_ref: str
    root: Path
    license_status: str = "not_assessed"
    vulnerability_status: str = "not_assessed"

    def __post_init__(self) -> None:
        from .contracts import _digest

        object.__setattr__(self, "bundle_ref", _digest(self.bundle_ref, "bundle_ref"))
        object.__setattr__(self, "tree_manifest_ref", _digest(self.tree_manifest_ref, "tree_manifest_ref"))
        object.__setattr__(self, "sbom_ref", _digest(self.sbom_ref, "sbom_ref"))
        root = Path(self.root)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise DependencyPreparationError("quarantine build root is not a sealed directory")
        object.__setattr__(self, "root", root)
        if self.license_status != "not_assessed" or self.vulnerability_status != "not_assessed":
            raise DependencyPreparationError("untrusted quarantine checks cannot claim assessed status")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.quarantine_build/v1",
            {
                "bundle_ref": self.bundle_ref,
                "tree_manifest_ref": self.tree_manifest_ref,
                "sbom_ref": self.sbom_ref,
                "license_status": self.license_status,
                "vulnerability_status": self.vulnerability_status,
            },
        )


@dataclass(frozen=True, slots=True)
class SupplyChainAttestation:
    """External scanner result bound to one exact quarantine build.

    The Workbench does not infer license or vulnerability status from a wheel;
    a trusted scanner supplies these bounded report references.  ``passed`` is
    therefore an attestation input, never a claim emitted by the fetcher.
    """

    bundle_ref: str
    tree_manifest_ref: str
    sbom_ref: str
    license_status: str
    vulnerability_status: str
    authority_ref: str
    license_report_ref: str | None = None
    vulnerability_report_ref: str | None = None

    def __post_init__(self) -> None:
        from .contracts import _digest

        for field in ("bundle_ref", "tree_manifest_ref", "sbom_ref", "authority_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        for field in ("license_status", "vulnerability_status"):
            if getattr(self, field) not in {"passed", "blocked", "not_assessed"}:
                raise SupplyChainAttestationError(f"{field} status is unsupported")
        for field in ("license_report_ref", "vulnerability_report_ref"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _digest(value, field))
        if self.license_status == "passed" and self.license_report_ref is None:
            raise SupplyChainAttestationError("passed license status requires a report")
        if self.vulnerability_status == "passed" and self.vulnerability_report_ref is None:
            raise SupplyChainAttestationError("passed vulnerability status requires a report")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.supply_chain_attestation/v1",
            {
                "bundle_ref": self.bundle_ref,
                "tree_manifest_ref": self.tree_manifest_ref,
                "sbom_ref": self.sbom_ref,
                "license_status": self.license_status,
                "vulnerability_status": self.vulnerability_status,
                "license_report_ref": self.license_report_ref,
                "vulnerability_report_ref": self.vulnerability_report_ref,
                "authority_ref": self.authority_ref,
            },
        )


@dataclass(frozen=True, slots=True)
class SupplyChainVerification:
    """Server-owned decision from a configured scanner authority."""

    authority_ref: str
    decision_ref: str
    status: str
    attestation_ref: str
    build_ref: str

    def __post_init__(self) -> None:
        from .contracts import _digest

        for field in ("authority_ref", "decision_ref", "attestation_ref", "build_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if self.status not in {"passed", "blocked"}:
            raise SupplyChainAttestationError("supply-chain verification status is unsupported")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.supply_chain_verification/v1",
            {
                "authority_ref": self.authority_ref,
                "decision_ref": self.decision_ref,
                "status": self.status,
                "attestation_ref": self.attestation_ref,
                "build_ref": self.build_ref,
            },
        )


class OfflineRuntimeBuilder:
    """Extract locked wheels into a bounded, no-hook, read-only tree."""

    _MAX_TOTAL_BYTES = 256 * 1024 * 1024
    _MAX_COMPRESSION_RATIO = 100

    def build(
        self,
        *,
        lock: DependencyLock,
        bundle: BundleCandidate,
        artifacts: dict[str, bytes],
        root: Path | str,
    ) -> QuarantineBuild:
        if not isinstance(lock, DependencyLock) or not isinstance(bundle, BundleCandidate):
            raise DependencyPreparationError("lock and bundle are required for quarantine build")
        destination = Path(root)
        if not destination.is_absolute():
            raise DependencyPreparationError("quarantine build root must be an absolute non-symlink path")
        self._assert_no_symlink_ancestors(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or not destination.is_dir():
            raise DependencyPreparationError("quarantine build root is not a directory")
        members: list[dict[str, str | int]] = []
        total_bytes = 0
        seen: set[str] = set()
        try:
            for requirement in lock.requirements:
                raw = artifacts.get(requirement.artifact_digest)
                if not isinstance(raw, bytes):
                    raise DependencyPreparationError("locked artifact bytes are missing for quarantine build")
                report = inspect_wheel_bytes(raw, expected_digest=requirement.artifact_digest)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    for member in archive.infolist():
                        if member.is_dir():
                            continue
                        if member.filename in seen:
                            raise DependencyPreparationError("dependency tree contains duplicate file paths")
                        seen.add(member.filename)
                        mode = (member.external_attr >> 16) & 0o170000
                        if mode not in {0, 0o100000} or ".." in member.filename.split("/") or member.filename.startswith("/"):
                            raise DependencyPreparationError("dependency tree contains an unsafe member")
                        if member.compress_size == 0 and member.file_size:
                            raise DependencyPreparationError("dependency tree contains a compression bomb")
                        if member.compress_size and member.file_size / member.compress_size > self._MAX_COMPRESSION_RATIO:
                            raise DependencyPreparationError("dependency tree compression ratio exceeds the policy")
                        total_bytes += member.file_size
                        if total_bytes > self._MAX_TOTAL_BYTES:
                            raise DependencyPreparationError("dependency tree exceeds the policy size limit")
                        target = destination / member.filename
                        parent = target.parent
                        self._assert_no_symlink_ancestors(parent, stop=destination)
                        parent.mkdir(parents=True, exist_ok=True)
                        self._assert_no_symlink_ancestors(target, stop=destination)
                        payload = archive.read(member)
                        if target.exists():
                            if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
                                raise DependencyPreparationError(
                                    "dependency tree existing file does not match the locked artifact"
                                )
                        else:
                            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                            if hasattr(os, "O_NOFOLLOW"):
                                flags |= os.O_NOFOLLOW
                            try:
                                descriptor = os.open(target, flags, 0o600)
                            except OSError as error:
                                raise DependencyPreparationError("dependency tree file cannot be created safely") from error
                            with os.fdopen(descriptor, "wb") as handle:
                                handle.write(payload)
                        os.chmod(target, 0o444)
                        members.append(
                            {
                                "path": member.filename,
                                "digest": hashlib.sha256(payload).hexdigest(),
                                "size": len(payload),
                                "distribution": report.distribution,
                                "version": report.version,
                            }
                        )
            actual_files: set[str] = set()
            for item in destination.rglob("*"):
                if item.is_symlink():
                    raise DependencyPreparationError("dependency tree contains a symlink")
                if item.is_file():
                    actual_files.add(item.relative_to(destination).as_posix())
            if actual_files != seen:
                raise DependencyPreparationError("dependency tree contains undeclared files")
            manifest_ref = domain_digest(
                "workbench.capability_factory.installation_tree_manifest/v1",
                {"bundle_ref": bundle.bundle_ref, "members": members},
            )
            sbom_ref = domain_digest(
                "workbench.capability_factory.sbom/v1",
                {
                    "bundle_ref": bundle.bundle_ref,
                    "packages": [
                        {
                            "distribution": item.distribution,
                            "version": item.version,
                            "artifact_ref": item.artifact_digest,
                        }
                        for item in lock.requirements
                    ],
                    "tree_manifest_ref": manifest_ref,
                },
            )
            for directory in sorted((item for item in destination.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
                os.chmod(directory, 0o555)
            os.chmod(destination, 0o555)
            return QuarantineBuild(
                bundle_ref=bundle.bundle_ref,
                tree_manifest_ref=manifest_ref,
                sbom_ref=sbom_ref,
                root=destination,
            )
        except (OSError, zipfile.BadZipFile, WheelInspectionError) as error:
            raise DependencyPreparationError("offline quarantine assembly failed") from error

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path, *, stop: Path | None = None) -> None:
        current = path
        stop = stop.resolve() if stop is not None else None
        while True:
            if current.is_symlink():
                raise DependencyPreparationError("dependency tree contains a symlink path")
            if stop is not None and current == stop:
                return
            parent = current.parent
            if parent == current:
                return
            current = parent


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
        fetcher: FetchWorker | None = None,
        builder: OfflineRuntimeBuilder | None = None,
        supply_chain_verifier: SupplyChainVerifier | None = None,
    ) -> None:
        self.resolver = resolver or DependencyResolver()
        self.assembler = assembler or BundleAssembler()
        self.admission = admission or BundleAdmissionController()
        self.store = store or DependencyStore()
        self.fetcher = fetcher or FetchWorker()
        self.builder = builder or OfflineRuntimeBuilder()
        self.supply_chain_verifier = supply_chain_verifier

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

    def fetch_and_prepare(
        self,
        *,
        requirements: tuple[DependencyRequirement, ...],
        snapshot: IndexSnapshot,
        policy: DependencyResolutionPolicy,
        fetch_policy: FetchPolicy,
        quarantine_root: Path | str,
        authorization_receipt: object,
        authorization_root: Path | str,
    ) -> DependencyPreparation:
        """Fetch exact lock members, then hand only quarantined bytes to assembly.

        Resolution happens before any network call.  Each URL comes from the
        immutable index snapshot matched by the exact requirement; the fetcher
        independently rechecks the HTTPS origin, digest, size, and quarantine
        identity.  Assembly remains offline and does not receive a URL,
        transport, or executable installation hook.
        """

        if not isinstance(fetch_policy, FetchPolicy):
            raise DependencyPreparationError("fetch_policy must be a FetchPolicy")
        try:
            lock = self.resolver.resolve(
                requirements=requirements,
                snapshot=snapshot,
                policy=policy,
            )
            if not set(fetch_policy.allowed_origins) <= set(policy.allowed_origins):
                raise DependencyPreparationError(
                    "fetch policy is broader than the approved resolver policy"
                )
            self._consume_fetch_authorization(
                authorization_receipt=authorization_receipt,
                authorization_root=authorization_root,
                lock=lock,
                snapshot=snapshot,
            )
            artifacts: dict[str, bytes] = {}
            for requirement in lock.requirements:
                candidates = [
                    item
                    for item in snapshot.artifacts
                    if item.distribution == requirement.distribution
                    and item.version == requirement.version
                    and item.artifact_digest == requirement.artifact_digest
                    and item.python_tag == requirement.python_tag
                    and item.platform_tag == requirement.platform_tag
                    and self._origin(item.url) == self._origin(requirement.index_origin)
                ]
                if len(candidates) != 1:
                    raise DependencyPreparationError(
                        f"requirement {requirement.distribution} has no unique fetch candidate"
                    )
                artifact = self.fetcher.fetch(
                    url=candidates[0].url,
                    expected_digest=requirement.artifact_digest,
                    policy=fetch_policy,
                    quarantine_root=quarantine_root,
                )
                artifacts[requirement.artifact_digest] = artifact.path.read_bytes()
            preparation = self._assemble_locked(lock=lock, artifacts=artifacts)
            build = self.builder.build(
                lock=preparation.lock,
                bundle=preparation.bundle,
                artifacts=artifacts,
                root=Path(quarantine_root) / "tree",
            )
            return DependencyPreparation(
                lock=preparation.lock,
                bundle=preparation.bundle,
                admission=preparation.admission,
                quarantine_build=build,
            )
        except DependencyPreparationError:
            raise
        except (
            DependencyResolutionError,
            BundleAssemblyError,
            AdmissionError,
            DependencyStoreError,
            FetchWorkerError,
        ) as error:
            raise DependencyPreparationError(str(error)) from error

    @staticmethod
    def _consume_fetch_authorization(
        *,
        authorization_receipt: object,
        authorization_root: Path | str,
        lock: DependencyLock,
        snapshot: IndexSnapshot,
    ) -> None:
        """Consume the existing proposal/risk grant for this exact lock.

        The import is local to keep the capability-factory contracts usable by
        the Agent proposal layer without making that layer import the service.
        This grant authorizes quarantine acquisition only; the proposal's
        ``execution_allowed`` remains false and no executor is registered here.
        """

        from ..agent.dependency_control import (
            DEPENDENCY_ACQUISITION_OPERATION,
            DEPENDENCY_OPERATION_VERSION,
            DependencyAuthorizationReceipt,
        )
        from ..agent.risk import RiskAuthorizationStore

        if not isinstance(authorization_receipt, DependencyAuthorizationReceipt):
            raise DependencyPreparationError(
                "dependency fetch requires a confirmed authorization receipt"
            )
        proposal = authorization_receipt.proposal
        grant = authorization_receipt.risk_authorization
        if proposal.status != "confirmed" or proposal.execution_allowed:
            raise DependencyPreparationError("dependency fetch authorization is not quarantine-only")
        if proposal.lock_ref != lock.content_digest:
            raise DependencyPreparationError("dependency fetch authorization is bound to another lock")
        if proposal.policy_ref != lock.resolver_policy_digest:
            raise DependencyPreparationError("dependency fetch authorization policy is stale")
        if proposal.index_snapshot_ref != snapshot.snapshot_ref:
            raise DependencyPreparationError("dependency fetch authorization index snapshot is stale")
        expected_artifacts = tuple(item.artifact_digest for item in lock.requirements)
        if proposal.artifact_refs != expected_artifacts:
            raise DependencyPreparationError("dependency fetch authorization artifact set is stale")
        if grant.token is None:
            raise DependencyPreparationError("dependency fetch authorization token is unavailable")
        if grant.operation_id != DEPENDENCY_ACQUISITION_OPERATION:
            raise DependencyPreparationError("dependency fetch authorization operation is invalid")
        if grant.operation_version != DEPENDENCY_OPERATION_VERSION:
            raise DependencyPreparationError("dependency fetch authorization version is invalid")
        execution_key = domain_digest(
            "workbench.capability_factory.dependency_fetch_authorization/v1",
            {
                "proposal_id": proposal.proposal_id,
                "lock_ref": lock.content_digest,
                "index_snapshot_ref": snapshot.snapshot_ref,
                "artifact_refs": list(expected_artifacts),
            },
        )
        RiskAuthorizationStore(authorization_root).consume(
            grant.authorization_id,
            token=grant.token,
            operation_id=grant.operation_id,
            operation_version=grant.operation_version,
            proposal_id=grant.proposal_id,
            revision=grant.revision,
            fingerprint=grant.fingerprint,
            session_id=grant.session_id,
            chain_id=grant.chain_id,
            active_head_run_id=grant.active_head_run_id,
            execution_key=execution_key,
        )

    def _assemble_locked(
        self,
        *,
        lock: DependencyLock,
        artifacts: dict[str, bytes],
    ) -> DependencyPreparation:
        try:
            bundle = self.assembler.assemble(lock=lock, artifacts=artifacts)
            try:
                existing = self.store.get_bundle(bundle.bundle_ref)
                history = self.store.admission_history(bundle.bundle_ref)
            except DependencyStoreError:
                existing = None
                history = ()
            if existing is not None:
                if existing != bundle or not history:
                    raise DependencyPreparationError("persisted dependency bundle history is inconsistent")
                return DependencyPreparation(
                    lock=lock,
                    bundle=existing,
                    admission=history[-1],
                )
            admission = self.admission.quarantine(bundle_ref=bundle.bundle_ref)
            self.store.put_lock(lock)
            self.store.put_bundle(bundle)
            self.store.append_admission(admission)
            return DependencyPreparation(lock=lock, bundle=bundle, admission=admission)
        except (BundleAssemblyError, AdmissionError, DependencyStoreError) as error:
            raise DependencyPreparationError(str(error)) from error

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    def mark_validated(
        self,
        preparation: DependencyPreparation,
        *,
        attestation: SupplyChainAttestation,
    ) -> DependencyPreparation:
        """Advance quarantine only after exact external supply-chain checks."""

        if not isinstance(preparation, DependencyPreparation):
            raise SupplyChainAttestationError("preparation must be a DependencyPreparation")
        if not isinstance(attestation, SupplyChainAttestation):
            raise SupplyChainAttestationError("attestation must be a SupplyChainAttestation")
        build = preparation.quarantine_build
        if build is None:
            raise SupplyChainAttestationError("supply-chain validation requires an isolated build")
        if (
            attestation.bundle_ref != preparation.bundle.bundle_ref
            or attestation.tree_manifest_ref != build.tree_manifest_ref
            or attestation.sbom_ref != build.sbom_ref
        ):
            raise SupplyChainAttestationError("supply-chain attestation is bound to another build")
        if attestation.license_status != "passed" or attestation.vulnerability_status != "passed":
            raise SupplyChainAttestationError("bundle cannot be validated before supply-chain checks pass")
        verifier = self.supply_chain_verifier
        if verifier is None:
            raise SupplyChainAttestationError("trusted supply-chain verifier is unavailable")
        try:
            verification = verifier.verify(attestation=attestation, build=build)
        except Exception as error:
            raise SupplyChainAttestationError("trusted supply-chain verifier failed") from error
        if not isinstance(verification, SupplyChainVerification):
            raise SupplyChainAttestationError("trusted supply-chain verifier returned an invalid decision")
        if verification.status != "passed":
            raise SupplyChainAttestationError("trusted supply-chain verifier blocked the bundle")
        if (
            verification.authority_ref != attestation.authority_ref
            or verification.attestation_ref != attestation.content_digest
            or verification.build_ref != build.content_digest
        ):
            raise SupplyChainAttestationError("supply-chain verification is bound to another attestation or build")
        try:
            admission = self.admission.mark_validated(
                bundle_ref=preparation.bundle.bundle_ref,
                validation_ref=attestation.content_digest,
            )
            self.store.put_supply_chain_attestation(attestation)
            self.store.put_supply_chain_verification(verification)
            self.store.append_admission(admission)
        except (AdmissionError, DependencyStoreError) as error:
            raise SupplyChainAttestationError(str(error)) from error
        return DependencyPreparation(
            lock=preparation.lock,
            bundle=preparation.bundle,
            admission=admission,
            quarantine_build=build,
        )


__all__ = [
    "DependencyPreparation",
    "DependencyPreparationError",
    "DependencyService",
    "OfflineRuntimeBuilder",
    "QuarantineBuild",
    "SupplyChainAttestation",
    "SupplyChainAttestationError",
    "SupplyChainVerification",
    "SupplyChainVerifier",
]
