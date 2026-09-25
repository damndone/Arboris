"""Explicit local macOS bootstrap for Workbench's server-owned P0 seams.

The local host is a real deployment boundary for development, not a relaxed
test mode. It persists only stable identity/authority metadata, admits all
writable roots through FD-safe capabilities, and composes the same typed
Agent/Notebook compiler used by an external host. Linux and remote hosts use
their own adapters and remain outside this module's acceptance claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fcntl

from ..agent.cutover_runtime import EvidenceCommitReceiptV1
from ..agent.planning_contracts import (
    HostCompilationRequestV1,
    HostCompilationResultV1,
    LocalDeploymentIdentityResolverV1,
)
from ..agent.workflow_runtime import (
    WorkflowHostEndpointV1,
    bootstrap_local_workflow_host,
)
from ..canonical import canonical_json_v1, sha256_canonical
from ..contracts.agent.planning import (
    CompilationRecordV1,
    CompiledWorkflowV1,
    ServerCompilationRecordReferenceV1,
)
from ..evidence.authority import LocalHostAuthorityHandleV1
from ..evidence.persistence import EvidencePacketStoreV1
from ..evidence.registry import EvidenceRegistryV1
from .report_evidence_owner_factory import ServerOwnedReportEvidenceOwnerFactoryV1
from .workflow_post_estimation_host import WorkflowPostEstimationExecutionPortV1
from .provider_egress import ProviderEgressAuthorityV1


LOCAL_SERVER_IDENTITY_SCHEMA = "local-workbench-server-identity.v1"
LOCAL_EVIDENCE_AUTHORITY_SCHEMA = "local-evidence-authority.v1"
_SERVER_IDENTITY_FILENAME = ".server-identity.v1"
_EVIDENCE_AUTHORITY_FILENAME = ".evidence-authority.v1"
_LOCAL_BOOTSTRAP_ISSUER = object()


class LocalHostBootstrapError(RuntimeError):
    """A local host could not be admitted without weakening a trust boundary."""


def _required_ref(value: object, name: str, prefix: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(prefix)
        or any(token in value for token in ("/", "\\", "..", "\x00"))
    ):
        raise ValueError(f"{name} must be a safe {prefix} reference")
    return value


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return canonical_json_v1(dict(value)).encode("utf-8")


def _parse_canonical(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalHostBootstrapError("local bootstrap metadata is not valid JSON") from exc
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise LocalHostBootstrapError("local bootstrap metadata is not canonical")
    return value


def _write_new_relative(directory_fd: int, filename: str, raw: bytes) -> None:
    if (
        type(filename) is not str
        or not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise LocalHostBootstrapError("local bootstrap metadata filename is unsafe")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    temp_name = f".{filename}.{secrets.token_hex(8)}.tmp"
    temp_fd = -1
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | cloexec,
            0o600,
            dir_fd=directory_fd,
        )
        offset = 0
        while offset < len(raw):
            offset += os.write(temp_fd, raw[offset:])
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        try:
            os.link(
                temp_name,
                filename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing_fd = os.open(filename, os.O_RDONLY | nofollow | cloexec, dir_fd=directory_fd)
            try:
                existing = os.read(existing_fd, len(raw) + 1)
            finally:
                os.close(existing_fd)
            if existing != raw:
                raise LocalHostBootstrapError("local bootstrap metadata conflicts with the existing file")
        os.fsync(directory_fd)
    except LocalHostBootstrapError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise LocalHostBootstrapError("local bootstrap metadata could not be persisted safely") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _read_relative(directory_fd: int, filename: str) -> bytes | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    fd = -1
    try:
        fd = os.open(filename, os.O_RDONLY | nofollow | cloexec, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalHostBootstrapError("local bootstrap metadata could not be opened safely") from exc
    try:
        result = bytearray()
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > 128 * 1024:
                raise LocalHostBootstrapError("local bootstrap metadata exceeds its bound")
        return bytes(result)
    finally:
        os.close(fd)


def _load_or_create_metadata(
    directory_fd: int,
    filename: str,
    create: Any,
) -> dict[str, object]:
    lock_fd = os.dup(directory_fd)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        raw = _read_relative(directory_fd, filename)
        if raw is None:
            value = create()
            if type(value) is not dict:
                raise LocalHostBootstrapError("local bootstrap metadata factory returned invalid data")
            raw = _canonical_bytes(value)
            _write_new_relative(directory_fd, filename, raw)
        return _parse_canonical(raw)
    except LocalHostBootstrapError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise LocalHostBootstrapError("local bootstrap metadata lock failed") from exc
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _open_child_directory(parent_fd: int, name: str) -> int:
    """Open/create one local bootstrap component relative to an admitted FD."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _attempt in range(2):
        try:
            fd = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            continue
        except OSError as exc:
            raise LocalHostBootstrapError(
                "local bootstrap directory is not FD-safe"
            ) from exc
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise LocalHostBootstrapError(
                    "local bootstrap path is not a directory"
                )
            return fd
        except BaseException:
            os.close(fd)
            raise
    raise LocalHostBootstrapError(
        "local bootstrap directory could not be admitted"
    )


@dataclass(frozen=True, slots=True)
class LocalServerIdentityV1:
    schema_version: str
    server_id: str
    host_platform: str
    project_root_digest: str
    project_ref: str
    session_ref: str
    actor_ref: str
    authority_id: str

    def __post_init__(self) -> None:
        if self.schema_version != LOCAL_SERVER_IDENTITY_SCHEMA:
            raise ValueError("local server identity schema is unsupported")
        for name, value in (
            ("server_id", self.server_id),
            ("project_root_digest", self.project_root_digest),
            ("project_ref", self.project_ref),
            ("session_ref", self.session_ref),
            ("actor_ref", self.actor_ref),
            ("authority_id", self.authority_id),
        ):
            if type(value) is not str or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"local server identity {name} is invalid")
        if self.host_platform != "darwin":
            raise ValueError("local server identity only admits Darwin")

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "server_id": self.server_id,
            "host_platform": self.host_platform,
            "project_root_digest": self.project_root_digest,
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "actor_ref": self.actor_ref,
            "authority_id": self.authority_id,
        }


def _local_authority(
    evidence_root_fd: int,
    *,
    project_ref: str,
    session_ref: str,
    server_id: str,
) -> LocalHostAuthorityHandleV1:
    try:
        root_stat = os.fstat(evidence_root_fd)
    except OSError as exc:
        raise LocalHostBootstrapError("local evidence root is unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise LocalHostBootstrapError("local evidence root is not a directory")

    def create() -> dict[str, object]:
        secret = secrets.token_bytes(32)
        authority_id = "local-evidence-" + hashlib.sha256(
            canonical_json_v1(
                {
                    "device": int(root_stat.st_dev),
                    "inode": int(root_stat.st_ino),
                    "project_ref": project_ref,
                    "session_ref": session_ref,
                    "server_id": server_id,
                    "secret_digest": hashlib.sha256(secret).hexdigest(),
                }
            ).encode("utf-8")
        ).hexdigest()[:32]
        return {
            "schema_version": LOCAL_EVIDENCE_AUTHORITY_SCHEMA,
            "authority_id": authority_id,
            "project_ref": project_ref,
            "session_ref": session_ref,
            "server_id": server_id,
            "secret": secret.hex(),
        }

    value = _load_or_create_metadata(evidence_root_fd, _EVIDENCE_AUTHORITY_FILENAME, create)
    if (
        value.get("schema_version") != LOCAL_EVIDENCE_AUTHORITY_SCHEMA
        or value.get("project_ref") != project_ref
        or value.get("session_ref") != session_ref
        or value.get("server_id") != server_id
        or type(value.get("authority_id")) is not str
        or type(value.get("secret")) is not str
    ):
        raise LocalHostBootstrapError("local evidence authority metadata is bound to another project/session")
    try:
        secret = bytes.fromhex(value["secret"])
    except ValueError as exc:
        raise LocalHostBootstrapError("local evidence authority secret is invalid") from exc
    if len(secret) < 32:
        raise LocalHostBootstrapError("local evidence authority secret is too short")
    expected_authority_id = "local-evidence-" + hashlib.sha256(
        canonical_json_v1(
            {
                "device": int(root_stat.st_dev),
                "inode": int(root_stat.st_ino),
                "project_ref": project_ref,
                "session_ref": session_ref,
                "server_id": server_id,
                "secret_digest": hashlib.sha256(secret).hexdigest(),
            }
        ).encode("utf-8")
    ).hexdigest()[:32]
    if value["authority_id"] != expected_authority_id:
        raise LocalHostBootstrapError("local evidence authority identity does not match its durable key")
    return LocalHostAuthorityHandleV1._from_bootstrap(
        authority_id=expected_authority_id,
        scope_ref=project_ref,
        session_ref=session_ref,
        secret=secret,
    )


class LocalHostCompilerV1:
    """Deterministic local implementation of the typed host compiler seam."""

    __slots__ = (
        "_server_id",
        "_compiler_version",
        "_actor_ref",
        "_session_ref",
        "_project_ref",
    )

    def __init__(
        self,
        *,
        server_id: str,
        actor_ref: str,
        session_ref: str,
        project_ref: str,
    ) -> None:
        self._server_id = server_id
        self._compiler_version = "compiler:local:v1.8.9"
        self._actor_ref = actor_ref
        self._session_ref = session_ref
        self._project_ref = project_ref

    def compile(self, request: HostCompilationRequestV1) -> HostCompilationResultV1:
        if type(request) is not HostCompilationRequestV1:
            raise TypeError("local host compilation request is required")
        if (
            request.principal_ref != self._actor_ref
            or request.session_ref != self._session_ref
            or request.project_ref != self._project_ref
            or request.scope_ref != self._project_ref
        ):
            raise LocalHostBootstrapError(
                "local host compilation request is outside the bootstrapped server identity"
            )
        compiled = CompiledWorkflowV1.from_draft(
            request.draft,
            compiler_version=self._compiler_version,
            server_execution_identity=f"compile:{self._server_id}:{request.idempotency_key}",
            preview_fingerprint=sha256_canonical(
                {
                    "semantic_plan_hash": request.draft.semantic_plan_hash,
                    "compiler_version": self._compiler_version,
                    "idempotency_key": request.idempotency_key,
                }
            ),
            plan_diff={
                "effect": request.draft.effect.value,
                "data_impact": "read_dataset" if "read_refs" in request.draft.data_impact else "none",
            },
            risk_level=request.draft.risk_level,
            effect=request.draft.effect,
            resource_budget=request.draft.resource_budget,
            contract_snapshot_refs=request.draft.contract_snapshot_refs,
            catalog_snapshot_ref=request.draft.catalog_snapshot_ref,
        )
        created_at = datetime.now(UTC)
        record = CompilationRecordV1.from_compiled(
            compiled,
            record_id=f"compilation-record:{request.idempotency_key}",
            principal_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            source_commitments=dict(request.source_commitments),
            created_at=created_at.isoformat(),
            expires_at=(created_at + timedelta(minutes=10)).isoformat(),
        )
        return HostCompilationResultV1(
            compiled_plan=compiled,
            record=record,
            reference=ServerCompilationRecordReferenceV1(
                record_id=record.record_id,
                record_digest=record.record_digest,
                semantic_plan_hash=record.semantic_plan_hash,
            ),
        )


class LocalEvidenceCommitterV1:
    """Persist a bounded server-owned receipt for a cutover execution."""

    __slots__ = ("_store", "_identity")

    def __init__(self, store: EvidencePacketStoreV1, identity: LocalServerIdentityV1) -> None:
        self._store = store
        self._identity = identity

    def __call__(self, context: Any, result: Mapping[str, Any]) -> EvidenceCommitReceiptV1:
        if not isinstance(result, Mapping):
            raise TypeError("local evidence commit result must be a mapping")
        required = ("compilation_record_id", "execution_instance_hash", "actor_ref", "session_ref", "project_ref")
        if any(type(getattr(context, name, None)) is not str for name in required):
            raise ValueError("local evidence commit context is incomplete")
        if (
            context.actor_ref != self._identity.actor_ref
            or context.session_ref != self._identity.session_ref
            or context.project_ref != self._identity.project_ref
        ):
            raise ValueError("local evidence commit context is outside the server identity")
        evidence_digest = sha256_canonical(
            {"execution_instance_hash": context.execution_instance_hash, "result": dict(result)}
        )
        record = {
            "schema_version": "local-agent-evidence-receipt.v1",
            "evidence_ref": f"evidence:agent:{evidence_digest}",
            "evidence_digest": evidence_digest,
            "compilation_record_id": context.compilation_record_id,
            "execution_instance_hash": context.execution_instance_hash,
            "actor_ref": context.actor_ref,
            "session_ref": context.session_ref,
            "project_ref": context.project_ref,
            "authority_id": self._identity.authority_id,
        }
        with self._store._lock:  # the store remains the admission-gated writer
            with self._store._index_lock():
                self._store._write_new(
                    ("agent-receipts", f"{evidence_digest}.json"),
                    _canonical_bytes(record),
                )
        return EvidenceCommitReceiptV1(
            evidence_ref=record["evidence_ref"],
            evidence_digest=evidence_digest,
            compilation_record_id=context.compilation_record_id,
            execution_instance_hash=context.execution_instance_hash,
            actor_ref=context.actor_ref,
            session_ref=context.session_ref,
            project_ref=context.project_ref,
        )


@dataclass(slots=True)
class LocalWorkbenchHostBundle:
    identity: LocalServerIdentityV1
    evidence_authority: LocalHostAuthorityHandleV1
    evidence_store: EvidencePacketStoreV1
    evidence_registry: EvidenceRegistryV1
    report_owner_factory: ServerOwnedReportEvidenceOwnerFactoryV1
    identity_resolver: LocalDeploymentIdentityResolverV1
    workflow_endpoint: WorkflowHostEndpointV1
    workflow_post_estimation_execution_port: WorkflowPostEstimationExecutionPortV1
    host_compiler: LocalHostCompilerV1
    evidence_committer: LocalEvidenceCommitterV1
    provider_egress_authority: ProviderEgressAuthorityV1
    runtime: object | None = None

    def close(self) -> None:
        self.provider_egress_authority.close()
        self.report_owner_factory.close()
        self.evidence_store.close()
        self.evidence_authority.close()
        try:
            self.workflow_endpoint.close()
        except (OSError, RuntimeError, TypeError, ValueError):
            pass


def bootstrap_local_workbench_host(
    *,
    project_root: Path | str,
    project_ref: str,
    session_ref: str,
    actor_ref: str,
    app_instance: Any | None = None,
) -> LocalWorkbenchHostBundle:
    """Bootstrap the complete local Darwin authority/evidence bundle."""

    if platform.system() != "Darwin":
        raise LocalHostBootstrapError("local Workbench bootstrap is only verified on macOS/Darwin")
    project_ref = _required_ref(project_ref, "project_ref", "project:")
    session_ref = _required_ref(session_ref, "session_ref", "session:")
    actor_ref = _required_ref(actor_ref, "actor_ref", "principal:")
    raw_root = Path(project_root).expanduser().absolute()
    root = raw_root.resolve(strict=False)
    if raw_root.exists() and raw_root.is_symlink():
        raise LocalHostBootstrapError("local project root is a symlink")
    workflow_endpoint = bootstrap_local_workflow_host(root)
    root_fd = -1
    workbench_fd = -1
    evidence_fd = -1
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root_fd = os.open(
            root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        workbench_fd = _open_child_directory(root_fd, "workbench")
        evidence_fd = _open_child_directory(workbench_fd, "evidence")
        evidence_root = root / "workbench" / "evidence"
        identity_raw = _read_relative(workbench_fd, _SERVER_IDENTITY_FILENAME)
        identity_payload = _parse_canonical(identity_raw) if identity_raw is not None else None
        server_id = (
            identity_payload.get("server_id")
            if identity_payload is not None
            else "server:local:" + hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:32]
        )
        if type(server_id) is not str or not server_id.startswith("server:local:"):
            raise LocalHostBootstrapError("local server identity is invalid")
        authority = _local_authority(
            evidence_fd,
            project_ref=project_ref,
            session_ref=session_ref,
            server_id=server_id,
        )
        authority_id = authority.authority_id
        expected_identity = {
            "schema_version": LOCAL_SERVER_IDENTITY_SCHEMA,
            "server_id": server_id,
            "host_platform": "darwin",
            "project_root_digest": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
            "project_ref": project_ref,
            "session_ref": session_ref,
            "actor_ref": actor_ref,
            "authority_id": authority_id,
        }
        if identity_payload is None:
            _write_new_relative(
                workbench_fd,
                _SERVER_IDENTITY_FILENAME,
                _canonical_bytes(expected_identity),
            )
        elif identity_payload != expected_identity:
            raise LocalHostBootstrapError("local server identity is not bound to this exact project/session")
        identity = LocalServerIdentityV1(
            schema_version=LOCAL_SERVER_IDENTITY_SCHEMA,
            server_id=server_id,
            host_platform="darwin",
            project_root_digest=hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
            project_ref=project_ref,
            session_ref=session_ref,
            actor_ref=actor_ref,
            authority_id=authority_id,
        )
        store = EvidencePacketStoreV1.admit(
            evidence_root,
            authority_handle=authority,
            scope_ref=project_ref,
        )
        registry = EvidenceRegistryV1(scope_ref=project_ref, authority_handle=authority)
        store.rehydrate_registry(registry)
        factory = ServerOwnedReportEvidenceOwnerFactoryV1.from_host(
            store,
            registry,
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            scope_ref=project_ref,
            canonical_project_root=root,
            authority_handle=authority,
        )
        from ..providers.catalog import load_builtin_catalog

        workflow_post_estimation_execution_port = WorkflowPostEstimationExecutionPortV1.from_local_host(
            project_root=root,
            workflow_endpoint=workflow_endpoint,
            project_ref=project_ref,
            session_ref=session_ref,
            catalog_digest=load_builtin_catalog().catalog_digest,
        )
        bundle = LocalWorkbenchHostBundle(
            identity=identity,
            evidence_authority=authority,
            evidence_store=store,
            evidence_registry=registry,
            report_owner_factory=factory,
            identity_resolver=LocalDeploymentIdentityResolverV1._from_bootstrap(
                actor_ref=actor_ref,
                project_ref=project_ref,
                session_ref=session_ref,
            ),
            workflow_endpoint=workflow_endpoint,
            workflow_post_estimation_execution_port=workflow_post_estimation_execution_port,
            host_compiler=LocalHostCompilerV1(
                server_id=server_id,
                actor_ref=actor_ref,
                session_ref=session_ref,
                project_ref=project_ref,
            ),
            evidence_committer=LocalEvidenceCommitterV1(store, identity),
            # Deliberately empty on every bootstrap. Persisted project identity
            # and provider credentials do not restore sending permission.
            provider_egress_authority=ProviderEgressAuthorityV1.from_host(
                authority_handle=authority, scope_ref=project_ref,
                project_ref=project_ref, actor_ref=actor_ref,
            ),
        )
        if app_instance is not None:
            from ..app import install_local_workbench_host

            bundle.runtime = install_local_workbench_host(bundle, app_instance=app_instance)
        return bundle
    except Exception:
        try:
            if evidence_fd >= 0:
                os.close(evidence_fd)
        finally:
            if workbench_fd >= 0:
                os.close(workbench_fd)
            if root_fd >= 0:
                os.close(root_fd)
        raise
    finally:
        # The packet store owns its own admission FD. The bootstrap-only
        # directory descriptors are not retained after construction.
        if evidence_fd >= 0:
            try:
                os.close(evidence_fd)
            except OSError:
                pass
        try:
            os.close(workbench_fd)
        except OSError:
            pass
        try:
            os.close(root_fd)
        except OSError:
            pass


__all__ = [
    "LOCAL_EVIDENCE_AUTHORITY_SCHEMA",
    "LOCAL_SERVER_IDENTITY_SCHEMA",
    "LocalEvidenceCommitterV1",
    "LocalHostBootstrapError",
    "LocalHostCompilerV1",
    "LocalServerIdentityV1",
    "LocalWorkbenchHostBundle",
    "bootstrap_local_workbench_host",
]
