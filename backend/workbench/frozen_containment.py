"""Frozen, fail-closed source containment for the v1.7.3 evaluator.

This is deliberately *not* a replacement for :mod:`workbench.sandbox`.  The
G3 sandbox has a different threat model and intentionally permits host reads.
This module presently provides source attribution and static refusal only: it
never launches a candidate, evaluator, Python interpreter, or arbitrary
command.  A future OS adapter may use these trusted inputs only after a full
canary has established the separate execution contract.
"""

from __future__ import annotations

import hashlib
import contextlib
import json
import os
import platform
import re
import selectors
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Mapping


_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_BACKENDS = frozenset({"seatbelt", "bubblewrap"})
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_MAX_ARCHIVE_PATH_DEPTH = 64


class FrozenContainmentError(RuntimeError):
    """Base error for the isolated frozen-containment capability."""


class FrozenMaterializationError(FrozenContainmentError):
    """Trusted Git content could not be materialised safely."""


class RuntimePolicyError(FrozenContainmentError):
    """Integration-owned runtime policy did not satisfy the C1 contract."""


class StaticContainmentRejection(FrozenContainmentError):
    """A required invariant is absent, so no child process may be started."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class FileIdentity:
    path: Path
    device: int
    inode: int
    byte_size: int
    content_sha256: str
    owner_uid: int
    mode: int


@dataclass(frozen=True)
class _OpenedExecutable:
    descriptor: int
    identity: FileIdentity

    @property
    def argv0(self) -> str:
        return f"/dev/fd/{self.descriptor}"


@dataclass(frozen=True)
class DirectoryIdentity:
    path: Path
    device: int
    inode: int
    manifest_sha256: str


@dataclass(frozen=True)
class SupportedHost:
    """An Integration-approved OS/backend/version range, never an ambient host."""

    os_name: str
    architecture: str
    backend: str
    backend_executable: Path
    minimum_version: tuple[int, ...]
    maximum_version: tuple[int, ...]

    def validate(self) -> None:
        if not self.os_name or not self.architecture or self.backend not in _ALLOWED_BACKENDS:
            raise RuntimePolicyError("supported host has invalid OS, architecture, or backend")
        _immutable_root_owned_executable(
            self.backend_executable,
            "supported backend executable",
        )
        if not self.minimum_version or not self.maximum_version:
            raise RuntimePolicyError("supported host requires an explicit backend version range")
        if any(value < 0 for value in (*self.minimum_version, *self.maximum_version)):
            raise RuntimePolicyError("supported host version components must be non-negative")
        if self.minimum_version > self.maximum_version:
            raise RuntimePolicyError("supported host version range is inverted")

    def accepts(self, os_name: str, architecture: str, backend: str, version: tuple[int, ...]) -> bool:
        return (
            self.os_name == os_name
            and self.architecture == architecture
            and self.backend == backend
            and self.minimum_version <= version <= self.maximum_version
        )


@dataclass(frozen=True)
class FrozenSnapshot:
    root: Path
    commit_sha: str
    tree_sha: str
    manifest: tuple[ManifestEntry, ...]
    manifest_digest: str
    source_evidence_digest: str
    git_executable: Path
    git_identity: FileIdentity
    git_version: str
    extraction_limits: Mapping[str, int]
    snapshot_parent_identity: DirectoryIdentity
    snapshot_root_identity: DirectoryIdentity


@dataclass(frozen=True)
class ValidatedRuntimePolicy:
    schema_version: str
    approved_backends: tuple[str, ...]
    python_interpreter: Path
    runner: Path
    runtime_read_roots: tuple[Path, ...]
    fixture_read_roots: tuple[Path, ...]
    snapshot_parent_root: Path
    max_archive_files: int
    max_archive_file_bytes: int
    max_archive_total_bytes: int
    max_archive_path_depth: int
    approved_owner_uids: tuple[int, ...]
    supported_hosts: tuple[SupportedHost, ...]
    interpreter_identity: FileIdentity
    runner_identity: FileIdentity
    runtime_root_identities: tuple[DirectoryIdentity, ...]
    fixture_root_identities: tuple[DirectoryIdentity, ...]
    snapshot_parent_identity: DirectoryIdentity
    backend_identities: tuple[FileIdentity, ...]
    digest: str

    def revalidate(self) -> None:
        """Refuse a policy whose bound executable or root identity has changed."""

        interpreter = _trusted_regular_file(
            self.python_interpreter,
            "python interpreter",
            executable=True,
            approved_owner_uids=self.approved_owner_uids,
        )
        runner = _trusted_regular_file(
            self.runner,
            "runner",
            executable=False,
            approved_owner_uids=self.approved_owner_uids,
        )
        if _file_identity(interpreter) != self.interpreter_identity:
            raise RuntimePolicyError("python interpreter identity changed after policy validation")
        if _file_identity(runner) != self.runner_identity:
            raise RuntimePolicyError("runner identity changed after policy validation")
        runtime = _validate_read_roots(
            self.runtime_read_roots,
            "runtime",
            (),
            self.approved_owner_uids,
        )
        fixtures = _validate_read_roots(
            self.fixture_read_roots,
            "fixture",
            (),
            self.approved_owner_uids,
        )
        if tuple(
            _validated_directory_identity(root, "runtime read root", approved_owner_uids=self.approved_owner_uids)
            for root in runtime
        ) != self.runtime_root_identities:
            raise RuntimePolicyError("runtime root identity changed after policy validation")
        if tuple(
            _validated_directory_identity(root, "fixture read root", approved_owner_uids=self.approved_owner_uids)
            for root in fixtures
        ) != self.fixture_root_identities:
            raise RuntimePolicyError("fixture root identity changed after policy validation")
        if _validated_directory_identity(
            self.snapshot_parent_root,
            "snapshot parent root",
            approved_owner_uids=self.approved_owner_uids,
        ) != self.snapshot_parent_identity:
            raise RuntimePolicyError("snapshot parent root identity changed after policy validation")
        current_backend_identities = tuple(
            _immutable_root_owned_executable(
                host.backend_executable,
                "supported backend executable",
            )
            for host in self.supported_hosts
        )
        if current_backend_identities != self.backend_identities:
            raise RuntimePolicyError("supported backend identity changed after policy validation")


@dataclass(frozen=True)
class RuntimePolicy:
    """Versioned, Integration-owned configuration; never caller request data."""

    schema_version: str
    approved_backends: tuple[str, ...]
    python_interpreter: Path
    runner: Path
    runtime_read_roots: tuple[Path, ...]
    fixture_read_roots: tuple[Path, ...]
    snapshot_parent_root: Path
    max_archive_files: int
    max_archive_file_bytes: int
    max_archive_total_bytes: int
    max_archive_path_depth: int
    approved_owner_uids: tuple[int, ...] = (0, os.getuid())
    supported_hosts: tuple[SupportedHost, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return constructor-shaped data for explicit policy review/tests."""

        return {
            "schema_version": self.schema_version,
            "approved_backends": self.approved_backends,
            "python_interpreter": self.python_interpreter,
            "runner": self.runner,
            "runtime_read_roots": self.runtime_read_roots,
            "fixture_read_roots": self.fixture_read_roots,
            "snapshot_parent_root": self.snapshot_parent_root,
            "max_archive_files": self.max_archive_files,
            "max_archive_file_bytes": self.max_archive_file_bytes,
            "max_archive_total_bytes": self.max_archive_total_bytes,
            "max_archive_path_depth": self.max_archive_path_depth,
            "approved_owner_uids": self.approved_owner_uids,
            "supported_hosts": self.supported_hosts,
        }

    def validate(self, *, prohibited_roots: Iterable[Path] = ()) -> ValidatedRuntimePolicy:
        """Canonicalise and validate the finite trusted runtime configuration."""

        if self.schema_version != "1.0":
            raise RuntimePolicyError("unsupported RuntimePolicy schema version")
        if not self.approved_backends or not set(self.approved_backends) <= _ALLOWED_BACKENDS:
            raise RuntimePolicyError("RuntimePolicy names an unsupported containment backend")
        if len(set(self.approved_backends)) != len(self.approved_backends):
            raise RuntimePolicyError("RuntimePolicy repeats an approved backend")
        for value in (
            self.max_archive_files,
            self.max_archive_file_bytes,
            self.max_archive_total_bytes,
            self.max_archive_path_depth,
        ):
            if not isinstance(value, int) or value <= 0:
                raise RuntimePolicyError("archive limits must be positive integers")
        if not self.approved_owner_uids or any(
            not isinstance(uid, int) or uid < 0 for uid in self.approved_owner_uids
        ):
            raise RuntimePolicyError("RuntimePolicy requires non-negative approved owner UIDs")
        if len(set(self.approved_owner_uids)) != len(self.approved_owner_uids):
            raise RuntimePolicyError("RuntimePolicy repeats an approved owner UID")
        if not self.supported_hosts:
            raise RuntimePolicyError("RuntimePolicy requires an explicit supported-host matrix")
        for host in self.supported_hosts:
            host.validate()

        interpreter = _trusted_regular_file(
            self.python_interpreter,
            "python interpreter",
            executable=True,
            approved_owner_uids=self.approved_owner_uids,
        )
        runner = _trusted_regular_file(
            self.runner,
            "runner",
            executable=False,
            approved_owner_uids=self.approved_owner_uids,
        )
        blocked = tuple(_canonical_existing_root(root, "prohibited root") for root in prohibited_roots)
        runtime = _validate_read_roots(
            self.runtime_read_roots, "runtime", blocked, self.approved_owner_uids
        )
        fixtures = _validate_read_roots(
            self.fixture_read_roots, "fixture", blocked, self.approved_owner_uids
        )
        snapshot_parent_identity = _validated_directory_identity(
            self.snapshot_parent_root,
            "snapshot parent root",
            approved_owner_uids=self.approved_owner_uids,
        )
        snapshot_parent = snapshot_parent_identity.path
        if set(runtime) & set(fixtures):
            raise RuntimePolicyError("runtime and fixture roots must be explicitly distinct")
        all_roots = (*runtime, *fixtures)
        for index, root in enumerate(all_roots):
            if any(
                other != root and (root.is_relative_to(other) or other.is_relative_to(root))
                for other in all_roots[index + 1 :]
            ):
                raise RuntimePolicyError("runtime and fixture roots may not overlap or nest")
        interpreter_identity = _file_identity(interpreter)
        runner_identity = _file_identity(runner)
        runtime_identities = tuple(
            _validated_directory_identity(root, "runtime read root", approved_owner_uids=self.approved_owner_uids)
            for root in runtime
        )
        fixture_identities = tuple(
            _validated_directory_identity(root, "fixture read root", approved_owner_uids=self.approved_owner_uids)
            for root in fixtures
        )
        backend_identities = tuple(
            _immutable_root_owned_executable(
                host.backend_executable,
                "supported backend executable",
            )
            for host in self.supported_hosts
        )

        canonical = {
            "schema_version": self.schema_version,
            "approved_backends": list(self.approved_backends),
            "python_interpreter": str(interpreter),
            "runner": str(runner),
            "runtime_read_roots": [str(root) for root in runtime],
            "fixture_read_roots": [str(root) for root in fixtures],
            "snapshot_parent_root": str(snapshot_parent),
            "approved_owner_uids": list(self.approved_owner_uids),
            "supported_hosts": [_host_dict(host) for host in self.supported_hosts],
            "identities": {
                "interpreter": _identity_dict(interpreter_identity),
                "runner": _identity_dict(runner_identity),
                "runtime_roots": [_identity_dict(identity) for identity in runtime_identities],
                "fixture_roots": [_identity_dict(identity) for identity in fixture_identities],
                "snapshot_parent": _identity_dict(snapshot_parent_identity),
                "backends": [_identity_dict(identity) for identity in backend_identities],
            },
            "limits": {
                "max_archive_files": self.max_archive_files,
                "max_archive_file_bytes": self.max_archive_file_bytes,
                "max_archive_total_bytes": self.max_archive_total_bytes,
                "max_archive_path_depth": self.max_archive_path_depth,
            },
        }
        digest = _canonical_digest(canonical)
        return ValidatedRuntimePolicy(
            schema_version=self.schema_version,
            approved_backends=self.approved_backends,
            python_interpreter=interpreter,
            runner=runner,
            runtime_read_roots=runtime,
            fixture_read_roots=fixtures,
            snapshot_parent_root=snapshot_parent,
            max_archive_files=self.max_archive_files,
            max_archive_file_bytes=self.max_archive_file_bytes,
            max_archive_total_bytes=self.max_archive_total_bytes,
            max_archive_path_depth=self.max_archive_path_depth,
            approved_owner_uids=self.approved_owner_uids,
            supported_hosts=self.supported_hosts,
            interpreter_identity=interpreter_identity,
            runner_identity=runner_identity,
            runtime_root_identities=runtime_identities,
            fixture_root_identities=fixture_identities,
            snapshot_parent_identity=snapshot_parent_identity,
            backend_identities=backend_identities,
            digest=digest,
        )


@dataclass(frozen=True)
class ContainmentBackend:
    name: str
    executable: Path
    version: str


@dataclass(frozen=True)
class _OpaqueCapability:
    """Private parent handle.  It intentionally carries no command or argv."""

    token: str


@dataclass
class _CapabilityRecord:
    candidate_manifest_digest: str
    evaluator_manifest_digest: str
    policy_digest: str
    expires_at: float
    consumed: bool = False


class _CapabilityRegistry:
    """Private, single-use parent registry; no raw child execution surface."""

    def __init__(self) -> None:
        self._records: dict[str, _CapabilityRecord] = {}

    def issue(
        self,
        candidate: FrozenSnapshot,
        evaluator: FrozenSnapshot,
        policy: ValidatedRuntimePolicy,
        *,
        ttl_seconds: float,
    ) -> _OpaqueCapability:
        if ttl_seconds <= 0:
            raise StaticContainmentRejection("INVALID_CAPABILITY_TTL", "capability ttl must be positive")
        token = os.urandom(32).hex()
        self._records[token] = _CapabilityRecord(
            candidate_manifest_digest=candidate.manifest_digest,
            evaluator_manifest_digest=evaluator.manifest_digest,
            policy_digest=policy.digest,
            expires_at=time.monotonic() + ttl_seconds,
        )
        return _OpaqueCapability(token)

    def consume(self, capability: _OpaqueCapability) -> _CapabilityRecord:
        record = self._records.get(capability.token)
        if record is None:
            raise StaticContainmentRejection("UNKNOWN_CAPABILITY", "capability is not parent-issued")
        if record.consumed:
            raise StaticContainmentRejection("REPLAYED_CAPABILITY", "capability was already consumed")
        if time.monotonic() >= record.expires_at:
            raise StaticContainmentRejection("EXPIRED_CAPABILITY", "capability expired before use")
        record.consumed = True
        return record


class FrozenMaterializer:
    """Freeze configured Git objects; never read a live worktree as input."""

    def __init__(
        self,
        trusted_repositories: Mapping[str, Path],
        *,
        git_executable: Path,
        runtime_policy: ValidatedRuntimePolicy,
        approved_git_owner_uids: tuple[int, ...] = (0, os.getuid()),
    ):
        if not trusted_repositories:
            raise FrozenMaterializationError("trusted repository allowlist cannot be empty")
        self._repositories = {
            repository_id: _trusted_repository_root(path)
            for repository_id, path in trusted_repositories.items()
        }
        if any(not repository_id or "/" in repository_id for repository_id in self._repositories):
            raise FrozenMaterializationError("trusted repository identifiers must be non-empty opaque names")
        self._policy = runtime_policy
        self._policy.revalidate()
        self._git = _approved_git_executable(git_executable, approved_git_owner_uids)
        self._git_identity = _file_identity(self._git)

    @property
    def trusted_roots(self) -> tuple[Path, ...]:
        return tuple(self._repositories.values())

    def materialize(self, trusted_repo_id: str, commit_sha: str) -> FrozenSnapshot:
        """Materialise one exact commit into a fresh descriptor-safe directory."""

        self._policy.revalidate()
        if trusted_repo_id not in self._repositories:
            raise FrozenMaterializationError("unknown trusted repository identifier")
        if not _COMMIT_SHA.fullmatch(commit_sha):
            raise FrozenMaterializationError("commit SHA must be exactly 40 lower-case hexadecimal characters")
        repo = self._repositories[trusted_repo_id]
        if _file_identity(self._git) != self._git_identity:
            raise FrozenMaterializationError("approved immutable Git executable identity changed before start")
        with _immutable_executable_guard(self._git, self._git_identity):
            resolved_commit = self._git_text(repo, "rev-parse", "--verify", f"{commit_sha}^{{commit}}")
            if resolved_commit != commit_sha:
                raise FrozenMaterializationError("Git did not resolve the requested exact commit")
            object_type = self._git_text(repo, "cat-file", "-t", commit_sha)
            if object_type != "commit":
                raise FrozenMaterializationError("requested object is not a commit")
            tree_sha = self._git_text(repo, "rev-parse", "--verify", f"{commit_sha}^{{tree}}")
            if not _COMMIT_SHA.fullmatch(tree_sha):
                raise FrozenMaterializationError("Git returned a non-canonical tree object")

        parent = self._policy.snapshot_parent_root
        parent_identity = _validated_directory_identity(
            parent,
            "snapshot parent root",
            approved_owner_uids=self._policy.approved_owner_uids,
        )
        if parent_identity != self._policy.snapshot_parent_identity:
            raise FrozenMaterializationError("snapshot parent root identity changed before materialisation")
        snapshot_root = _create_snapshot_root_from_parent_fd(parent, parent_identity)
        initial_snapshot_root = _validated_directory_identity(
            snapshot_root,
            "snapshot root",
            approved_owner_uids=self._policy.approved_owner_uids,
        )
        try:
            with _immutable_executable_guard(self._git, self._git_identity):
                archive = self._git_archive(repo, commit_sha)
                try:
                    manifest = extract_frozen_archive(
                        archive,
                        snapshot_root,
                        max_files=self._policy.max_archive_files,
                        max_file_bytes=self._policy.max_archive_file_bytes,
                        max_total_bytes=self._policy.max_archive_total_bytes,
                        max_path_depth=self._policy.max_archive_path_depth,
                    )
                finally:
                    archive.close()
        except Exception as exc:
            raise FrozenMaterializationError(
                f"materialisation failed ({exc}); frozen snapshot retained for audit at {snapshot_root}"
            ) from exc
        final_snapshot_root = _validated_directory_identity(
            snapshot_root,
            "snapshot root",
            approved_owner_uids=self._policy.approved_owner_uids,
        )
        if (
            final_snapshot_root.device != initial_snapshot_root.device
            or final_snapshot_root.inode != initial_snapshot_root.inode
        ):
            raise FrozenMaterializationError("snapshot root was replaced during materialisation")
        with _immutable_executable_guard(self._git, self._git_identity):
            git_version = self._git_version()
        evidence = {
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "git_executable": str(self._git),
            "git_version": git_version,
            "limits": {
                "max_files": self._policy.max_archive_files,
                "max_file_bytes": self._policy.max_archive_file_bytes,
                "max_total_bytes": self._policy.max_archive_total_bytes,
                "max_path_depth": self._policy.max_archive_path_depth,
            },
            "runtime_policy_digest": self._policy.digest,
            "git_identity": _identity_dict(self._git_identity),
            "manifest": [entry.__dict__ for entry in manifest],
        }
        return FrozenSnapshot(
            root=snapshot_root,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            manifest=manifest,
            manifest_digest=_canonical_digest([entry.__dict__ for entry in manifest]),
            source_evidence_digest=_canonical_digest(evidence),
            git_executable=self._git,
            git_identity=self._git_identity,
            git_version=git_version,
            extraction_limits=evidence["limits"],
            snapshot_parent_identity=parent_identity,
            snapshot_root_identity=final_snapshot_root,
        )

    def _git_text(self, repo: Path, *args: str) -> str:
        completed = subprocess.run(
            [str(self._git), "--no-replace-objects", "-C", str(repo), *args],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=_hermetic_git_env(),
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            raise FrozenMaterializationError("hermetic Git object verification failed")
        return completed.stdout.strip()

    def _git_archive(self, repo: Path, commit_sha: str) -> BinaryIO:
        """Stream a verified Git archive into a bounded private temporary file."""

        # The tar format itself has at least one 512-byte header per file.  This
        # conservative raw bound prevents an archive stream from becoming an
        # unbounded parent allocation before hostile-entry validation.
        max_raw = (
            self._policy.max_archive_total_bytes
            + self._policy.max_archive_files * 2048
            + 32 * 1024
        )
        temporary = tempfile.TemporaryFile(mode="w+b")
        process = subprocess.Popen(
            [str(self._git), "--no-replace-objects", "-C", str(repo), "archive", "--format=tar", commit_sha],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_hermetic_git_env(),
            close_fds=True,
        )
        assert process.stdout is not None
        total = 0
        deadline = time.monotonic() + 15.0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise FrozenMaterializationError("Git archive exceeded materialisation deadline")
                    if not selector.select(remaining):
                        raise FrozenMaterializationError("Git archive stalled before deadline")
                    chunk = os.read(process.stdout.fileno(), 64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_raw:
                        raise FrozenMaterializationError("Git archive exceeded the bounded materialisation stream")
                    temporary.write(chunk)
            if process.wait(timeout=15) != 0:
                raise FrozenMaterializationError("hermetic Git archive failed")
            temporary.seek(0)
            return temporary
        except (OSError, selectors.Error, subprocess.SubprocessError, FrozenMaterializationError) as exc:
            _terminate_and_reap(process)
            temporary.close()
            if isinstance(exc, FrozenMaterializationError):
                raise
            raise FrozenMaterializationError("Git archive stream failed") from exc
        finally:
            process.stdout.close()

    def _git_version(self) -> str:
        completed = subprocess.run(
            [str(self._git), "--version"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=_hermetic_git_env(),
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            raise FrozenMaterializationError("unable to record approved Git version")
        return completed.stdout.strip()


class FrozenContainmentService:
    """Parent-owned source preparation and fail-closed canary boundary.

    The only public preparation method always raises until a future backend
    adapter implements the complete canary protocol.  It intentionally has no
    ``run``/``execute`` command surface and no Python fallback.
    """

    def __init__(
        self,
        *,
        trusted_repositories: Mapping[str, Path],
        runtime_policy: RuntimePolicy,
        git_executable: Path,
        approved_git_owner_uids: tuple[int, ...] = (0, os.getuid()),
    ):
        trusted_roots = tuple(_trusted_repository_root(path) for path in trusted_repositories.values())
        self._policy = runtime_policy.validate(prohibited_roots=trusted_roots)
        self._materializer = FrozenMaterializer(
            trusted_repositories,
            git_executable=git_executable,
            runtime_policy=self._policy,
            approved_git_owner_uids=approved_git_owner_uids,
        )
        self._registry = _CapabilityRegistry()

    def discover_backend(self) -> ContainmentBackend | None:
        """Find an approved binary only; discovery is not proof of containment."""

        return discover_containment_backend(self._policy)

    def prepare_source_only(
        self,
        candidate_repo_id: str,
        candidate_commit_sha: str,
        evaluator_repo_id: str,
        evaluator_commit_sha: str,
    ) -> None:
        """Refuse static/source-only mode before command construction or Popen."""

        backend = self.discover_backend()
        if backend is None:
            raise StaticContainmentRejection(
                "UNSUPPORTED_OR_UNPROVEN_BACKEND",
                "no approved supported-host containment backend is available",
            )
        # Materialisation is deliberately not reached until the actual canary
        # exists.  Otherwise callers could mistake frozen source as a runnable
        # capability.  The unused request fields are the typed, restricted
        # future interface; they are not paths, commands, or environments.
        del candidate_repo_id, candidate_commit_sha, evaluator_repo_id, evaluator_commit_sha, backend
        raise StaticContainmentRejection(
            "CANARY_REQUIRED",
            "backend discovery alone is not containment proof; no capability was issued",
        )


def discover_containment_backend(policy: ValidatedRuntimePolicy) -> ContainmentBackend | None:
    """Return a candidate backend only when binary/OS policy agrees.

    A returned value is deliberately insufficient to launch anything.  The
    complete deny-default adapter and canary are still required.
    """

    policy.revalidate()
    for host, identity in zip(policy.supported_hosts, policy.backend_identities, strict=True):
        if host.backend not in policy.approved_backends:
            continue
        if host.os_name != platform.system() or host.architecture != platform.machine():
            continue
        try:
            current_identity = _immutable_root_owned_executable(
                host.backend_executable, "supported backend executable"
            )
        except RuntimePolicyError:
            continue
        if current_identity != identity:
            continue
        try:
            with _immutable_executable_guard(host.backend_executable, identity):
                completed = subprocess.run(
                    [str(host.backend_executable), "--version"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                    text=True,
                    timeout=5,
                )
        except (OSError, subprocess.SubprocessError):
            continue
        version = completed.stdout.strip()
        parsed_version = _version_tuple(version)
        if completed.returncode == 0 and parsed_version and host.accepts(
            platform.system(), platform.machine(), host.backend, parsed_version
        ):
            return ContainmentBackend(name=host.backend, executable=host.backend_executable, version=version)
    return None


def extract_frozen_archive(
    archive_stream: bytes | BinaryIO,
    destination: Path,
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
    max_path_depth: int = 64,
) -> tuple[ManifestEntry, ...]:
    """Safely unpack a hostile tar archive and return a sorted file manifest."""

    if min(max_files, max_file_bytes, max_total_bytes) <= 0:
        raise FrozenMaterializationError("archive extraction limits must be positive")
    if destination.exists():
        if destination.is_symlink() or any(destination.iterdir()):
            raise FrozenMaterializationError("snapshot destination must be a new empty non-symlink directory")
    else:
        destination.mkdir(mode=0o700, parents=False)
    root = destination.resolve(strict=True)
    if root != destination.absolute() or destination.is_symlink():
        raise FrozenMaterializationError("snapshot destination may not be a symlink")
    source: BinaryIO
    if isinstance(archive_stream, bytes):
        import io

        source = io.BytesIO(archive_stream)
    else:
        source = archive_stream
    names: set[str] = set()
    total_bytes = 0
    file_count = 0
    member_count = 0
    root_fd = os.open(root, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        with tarfile.open(fileobj=source, mode="r:") as archive:
            for member in archive:
                relative = _safe_tar_path(member, max_path_depth=max_path_depth)
                member_count += 1
                if member_count > max_files:
                    raise FrozenMaterializationError("archive exceeds configured total member limit")
                if relative in names:
                    raise FrozenMaterializationError("archive contains duplicate path")
                names.add(relative)
                if member.isdir():
                    if member.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | stat.S_IWOTH):
                        raise FrozenMaterializationError("archive directory has unsafe mode")
                    _ensure_parent_directories(root_fd, relative.split("/") + ["placeholder"])
                    continue
                if not member.isreg():
                    raise FrozenMaterializationError("archive contains unsupported non-regular entry")
                if member.size < 0 or member.size > max_file_bytes:
                    raise FrozenMaterializationError("archive member exceeds per-file byte limit")
                file_count += 1
                total_bytes += member.size
                if total_bytes > max_total_bytes:
                    raise FrozenMaterializationError("archive exceeds configured file or byte limit")
                parts = relative.split("/")
                parent_fd = _ensure_parent_directories(root_fd, parts)
                try:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW
                    file_fd = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
                    try:
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise FrozenMaterializationError("regular archive member has no data stream")
                        remaining = member.size
                        while remaining:
                            chunk = extracted.read(min(64 * 1024, remaining))
                            if not chunk:
                                raise FrozenMaterializationError("archive member ended before declared size")
                            _write_all(file_fd, chunk)
                            remaining -= len(chunk)
                        if extracted.read(1):
                            raise FrozenMaterializationError("archive member exceeded declared size")
                    finally:
                        os.close(file_fd)
                finally:
                    os.close(parent_fd)
        return _manifest_from_root(root_fd)
    finally:
        os.close(root_fd)


def _safe_tar_path(member: tarfile.TarInfo, *, max_path_depth: int) -> str:
    name = member.name
    try:
        name.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise FrozenMaterializationError("archive path is not UTF-8") from exc
    if not name or name.startswith("/") or "\\" in name:
        raise FrozenMaterializationError("archive path is absolute or unsupported")
    parts = name.split("/")
    if max_path_depth <= 0 or len(parts) > max_path_depth:
        raise FrozenMaterializationError("archive path exceeds configured depth limit")
    if any(part in {"", ".", "..", "__pycache__"} for part in parts):
        raise FrozenMaterializationError("archive path contains traversal or forbidden bytecode directory")
    if parts[-1].endswith(".pyc"):
        raise FrozenMaterializationError("archive contains forbidden bytecode")
    return "/".join(parts)


def _ensure_parent_directories(root_fd: int, parts: list[str]) -> int:
    """Return a no-follow descriptor for the parent directory of a tar path."""

    current = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _manifest_from_root(root_fd: int) -> tuple[ManifestEntry, ...]:
    entries: list[ManifestEntry] = []

    def visit(directory_fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(directory_fd)):
            relative = f"{prefix}/{name}" if prefix else name
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise FrozenMaterializationError("snapshot entry changed or is a link during manifest walk") from exc
            try:
                before = os.fstat(child_fd)
                if stat.S_ISDIR(before.st_mode):
                    visit(child_fd, relative)
                elif stat.S_ISREG(before.st_mode):
                    digest = hashlib.sha256()
                    size = 0
                    while chunk := os.read(child_fd, 64 * 1024):
                        size += len(chunk)
                        digest.update(chunk)
                    after = os.fstat(child_fd)
                    if not _same_file_state(before, after):
                        raise FrozenMaterializationError("snapshot entry identity changed during manifest read")
                    entries.append(ManifestEntry(relative, size, digest.hexdigest()))
                else:
                    raise FrozenMaterializationError("snapshot contains unsupported entry after extraction")
                after = os.fstat(child_fd)
                if not _same_file_state(before, after):
                    raise FrozenMaterializationError("snapshot entry identity changed during manifest walk")
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if current.st_dev != before.st_dev or current.st_ino != before.st_ino:
                    raise FrozenMaterializationError("snapshot entry was renamed or replaced during manifest walk")
            finally:
                os.close(child_fd)

    duplicate_root_fd = os.dup(root_fd)
    try:
        visit(duplicate_root_fd, "")
    finally:
        os.close(duplicate_root_fd)
    return tuple(entries)


def _canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+)*", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def _trusted_repository_root(path: Path) -> Path:
    root = _canonical_existing_root(path, "trusted repository root")
    git_marker = root / ".git"
    if not git_marker.exists():
        raise FrozenMaterializationError("trusted repository root is not a Git worktree")
    return root


def _approved_git_executable(configured: Path, approved_owner_uids: tuple[int, ...]) -> Path:
    if not isinstance(configured, Path) or not configured.is_absolute():
        raise FrozenMaterializationError("approved Git executable must be an absolute configured path")
    try:
        del approved_owner_uids
        return _immutable_root_owned_executable(configured, "Git executable").path
    except RuntimePolicyError as exc:
        raise FrozenMaterializationError(str(exc)) from exc


def _immutable_root_owned_executable(path: Path, label: str) -> FileIdentity:
    """Allow path execution only from a root-owned non-writable directory chain."""

    identity = _validated_file_identity(
        path,
        label,
        executable=True,
        approved_owner_uids=(0,),
    )
    current = identity.path.parent
    while True:
        if current.is_symlink():
            raise RuntimePolicyError(f"{label} parent chain may not contain symlinks")
        metadata = current.stat()
        if metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise RuntimePolicyError(f"{label} parent chain is candidate-writable")
        if current == Path("/"):
            break
        current = current.parent
    return identity


@contextlib.contextmanager
def _immutable_executable_guard(path: Path, expected_identity: FileIdentity):
    """Reprove immutable path ancestry immediately before path-based exec."""

    current_identity = _immutable_root_owned_executable(path, "approved executable")
    if current_identity != expected_identity:
        raise FrozenMaterializationError("approved executable identity changed before path execution")
    yield


def _hermetic_git_env() -> dict[str, str]:
    """No caller Git state, hooks, replacement refs, or external helpers."""

    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/var/empty",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
        "LANG": "C",
    }


def _terminate_and_reap(process: subprocess.Popen) -> None:
    """Bounded archive-child shutdown; never leave a Git child behind."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
        return
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired) as exc:
        raise FrozenMaterializationError("Git archive child could not be reaped") from exc


def _canonical_existing_root(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimePolicyError(f"{label} must be an absolute Path")
    if path.is_symlink() or not path.exists():
        raise RuntimePolicyError(f"{label} must exist and may not be a symlink")
    canonical = path.resolve(strict=True)
    if canonical == Path("/"):
        raise RuntimePolicyError(f"{label} may not be the filesystem root")
    return canonical


def _trusted_regular_file(
    path: Path,
    label: str,
    *,
    executable: bool,
    approved_owner_uids: tuple[int, ...] | None = None,
) -> Path:
    return _validated_file_identity(
        path,
        label,
        executable=executable,
        approved_owner_uids=approved_owner_uids,
    ).path


def _validated_file_identity(
    path: Path,
    label: str,
    *,
    executable: bool,
    approved_owner_uids: tuple[int, ...] | None = None,
) -> FileIdentity:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimePolicyError(f"{label} must be an absolute Path")
    identity = _file_identity(path)
    if executable and not identity.mode & stat.S_IXUSR:
        raise RuntimePolicyError(f"{label} must be executable")
    if identity.mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimePolicyError(f"{label} may not be group- or world-writable")
    if approved_owner_uids is not None and identity.owner_uid not in approved_owner_uids:
        raise RuntimePolicyError(f"{label} owner is not approved by RuntimePolicy")
    return identity


def _file_identity(path: Path) -> FileIdentity:
    """Read identity and content from the same no-follow descriptor."""

    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimePolicyError("file identity path must be an absolute Path")
    if path.is_symlink():
        raise RuntimePolicyError("file identity path may not be a symlink")
    try:
        descriptor = os.open(path, os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise RuntimePolicyError("file identity path could not be opened without following links") from exc
    try:
        return _identity_from_open_file_descriptor(descriptor, path.absolute())
    finally:
        os.close(descriptor)


def _identity_from_open_file_descriptor(descriptor: int, path: Path) -> FileIdentity:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise RuntimePolicyError("file identity path must be a non-symlink regular file")
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 64 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if not _same_file_state(before, after):
        raise RuntimePolicyError("file identity changed during read")
    return FileIdentity(
        path=path,
        device=before.st_dev,
        inode=before.st_ino,
        byte_size=before.st_size,
        content_sha256=digest.hexdigest(),
        owner_uid=before.st_uid,
        mode=stat.S_IMODE(before.st_mode),
    )


@contextlib.contextmanager
def _opened_executable(path: Path, expected: FileIdentity):
    """Bind exec to the checked inode through inherited ``/dev/fd`` only."""

    if not Path("/dev/fd").is_dir():
        raise FrozenMaterializationError("host lacks safe descriptor execution support")
    try:
        descriptor = os.open(path, os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise FrozenMaterializationError("approved executable could not be opened without following links") from exc
    try:
        identity = _identity_from_open_file_descriptor(descriptor, path.absolute())
        if identity != expected:
            raise FrozenMaterializationError("approved executable identity changed before start")
        yield _OpenedExecutable(descriptor=descriptor, identity=identity)
    finally:
        os.close(descriptor)


def _directory_identity(path: Path) -> DirectoryIdentity:
    """Hash a trusted root without following symlinks or ambient traversal."""

    root_fd = os.open(path, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        root_before = os.fstat(root_fd)
        records: list[dict[str, object]] = []

        def visit(directory_fd: int, prefix: str) -> None:
            for name in sorted(os.listdir(directory_fd)):
                relative = f"{prefix}/{name}" if prefix else name
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                        dir_fd=directory_fd,
                    )
                except OSError as exc:
                    raise RuntimePolicyError("runtime or fixture root entry changed or is a link") from exc
                try:
                    before = os.fstat(child_fd)
                    if stat.S_ISDIR(before.st_mode):
                        visit(child_fd, relative)
                    elif stat.S_ISREG(before.st_mode):
                        digest = hashlib.sha256()
                        while chunk := os.read(child_fd, 64 * 1024):
                            digest.update(chunk)
                        after = os.fstat(child_fd)
                        if not _same_file_state(before, after):
                            raise RuntimePolicyError("runtime or fixture entry identity changed during read")
                        records.append({"path": relative, "sha256": digest.hexdigest(), "size": before.st_size})
                    else:
                        raise RuntimePolicyError("runtime or fixture root contains a non-regular entry")
                    after = os.fstat(child_fd)
                    if not _same_file_state(before, after):
                        raise RuntimePolicyError("runtime or fixture entry identity changed during walk")
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if current.st_dev != before.st_dev or current.st_ino != before.st_ino:
                        raise RuntimePolicyError("runtime or fixture entry was renamed or replaced during walk")
                finally:
                    os.close(child_fd)

        visit(root_fd, "")
        metadata = os.fstat(root_fd)
        if not _same_file_state(root_before, metadata):
            raise RuntimePolicyError("runtime or fixture root identity changed during walk")
        try:
            current_root_fd = os.open(path, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
        except OSError as exc:
            raise RuntimePolicyError("runtime or fixture root changed or is a link during walk") from exc
        try:
            if not _same_file_state(root_before, os.fstat(current_root_fd)):
                raise RuntimePolicyError("runtime or fixture root was renamed or replaced during walk")
        finally:
            os.close(current_root_fd)
        return DirectoryIdentity(
            path=path,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            manifest_sha256=_canonical_digest(records),
        )
    finally:
        os.close(root_fd)


def _validated_directory_identity(
    path: Path,
    label: str,
    *,
    approved_owner_uids: tuple[int, ...],
) -> DirectoryIdentity:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimePolicyError(f"{label} must be an absolute Path")
    if path == Path("/"):
        raise RuntimePolicyError(f"{label} may not be the filesystem root")
    try:
        descriptor = os.open(path, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except OSError as exc:
        raise RuntimePolicyError(f"{label} must be an existing non-symlink directory") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimePolicyError(f"{label} must be a directory")
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise RuntimePolicyError(f"{label} may not be group- or world-writable")
        if metadata.st_uid not in approved_owner_uids:
            raise RuntimePolicyError(f"{label} owner is not approved by RuntimePolicy")
        return _directory_identity_from_open_fd(descriptor, path.absolute())
    finally:
        os.close(descriptor)


def _create_snapshot_root_from_parent_fd(parent: Path, expected: DirectoryIdentity) -> Path:
    """Create the fresh root relative to the policy-bound parent descriptor."""

    try:
        parent_fd = os.open(parent, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except OSError as exc:
        raise FrozenMaterializationError("snapshot parent root could not be opened safely") from exc
    try:
        metadata = os.fstat(parent_fd)
        if metadata.st_dev != expected.device or metadata.st_ino != expected.inode:
            raise FrozenMaterializationError("snapshot parent root was replaced before creation")
        for _ in range(16):
            name = f"frozen-git-{os.urandom(16).hex()}"
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            try:
                root_fd = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
            except OSError as exc:
                raise FrozenMaterializationError("fresh snapshot root could not be reopened safely") from exc
            try:
                root_metadata = os.fstat(root_fd)
                listed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if listed.st_dev != root_metadata.st_dev or listed.st_ino != root_metadata.st_ino:
                    raise FrozenMaterializationError("fresh snapshot root was replaced during creation")
            finally:
                os.close(root_fd)
            return parent / name
        raise FrozenMaterializationError("could not allocate a unique frozen snapshot root")
    finally:
        os.close(parent_fd)


def _directory_identity_from_open_fd(root_fd: int, path: Path) -> DirectoryIdentity:
    """Build a directory identity from an already-opened no-follow root FD."""

    duplicate = os.dup(root_fd)
    try:
        # Preserve the existing descriptor-relative walker while ensuring its
        # root identity was established before any path-based operation.
        records: list[dict[str, object]] = []

        def visit(directory_fd: int, prefix: str) -> None:
            for name in sorted(os.listdir(directory_fd)):
                relative = f"{prefix}/{name}" if prefix else name
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                        dir_fd=directory_fd,
                    )
                except OSError as exc:
                    raise RuntimePolicyError("trusted directory entry changed or is a link") from exc
                try:
                    before = os.fstat(child_fd)
                    if stat.S_ISDIR(before.st_mode):
                        visit(child_fd, relative)
                    elif stat.S_ISREG(before.st_mode):
                        digest = hashlib.sha256()
                        while chunk := os.read(child_fd, 64 * 1024):
                            digest.update(chunk)
                        after = os.fstat(child_fd)
                        if not _same_file_state(before, after):
                            raise RuntimePolicyError("trusted directory entry identity changed during read")
                        records.append({"path": relative, "sha256": digest.hexdigest(), "size": before.st_size})
                    else:
                        raise RuntimePolicyError("trusted directory contains a non-regular entry")
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if current.st_dev != before.st_dev or current.st_ino != before.st_ino:
                        raise RuntimePolicyError("trusted directory entry was renamed or replaced during walk")
                finally:
                    os.close(child_fd)

        before = os.fstat(duplicate)
        visit(duplicate, "")
        after = os.fstat(duplicate)
        if not _same_file_state(before, after):
            raise RuntimePolicyError("trusted directory root identity changed during walk")
        return DirectoryIdentity(
            path=path,
            device=before.st_dev,
            inode=before.st_ino,
            manifest_sha256=_canonical_digest(records),
        )
    finally:
        os.close(duplicate)


def _identity_dict(identity: FileIdentity | DirectoryIdentity) -> dict[str, object]:
    data = identity.__dict__.copy()
    data["path"] = str(identity.path)
    return data


def _host_dict(host: SupportedHost) -> dict[str, object]:
    data = host.__dict__.copy()
    data["backend_executable"] = str(host.backend_executable)
    return data


def _same_file_state(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _write_all(file_descriptor: int, data: bytes) -> None:
    """Handle POSIX short writes; never silently truncate frozen source."""

    view = memoryview(data)
    while view:
        written = os.write(file_descriptor, view)
        if written <= 0:
            raise FrozenMaterializationError("snapshot file write made no forward progress")
        view = view[written:]


def _validate_read_roots(
    roots: tuple[Path, ...],
    label: str,
    prohibited: tuple[Path, ...],
    approved_owner_uids: tuple[int, ...],
) -> tuple[Path, ...]:
    if not roots:
        raise RuntimePolicyError(f"RuntimePolicy requires at least one {label} read root")
    validated: list[Path] = []
    home = Path.home().absolute()
    for root in roots:
        if not isinstance(root, Path) or not root.is_absolute():
            raise RuntimePolicyError(f"{label} read root must be an absolute Path")
        candidate = root.absolute()
        if candidate == Path("/"):
            raise RuntimePolicyError(f"{label} read root may not be the filesystem root")
        if candidate == home or candidate.is_relative_to(home):
            raise RuntimePolicyError(f"{label} read root may not be home or a home subdirectory")
        if any(candidate == forbidden or candidate.is_relative_to(forbidden) for forbidden in prohibited):
            raise RuntimePolicyError(f"{label} read root may not be a trusted repository root")
        identity = _validated_directory_identity(
            candidate,
            f"{label} read root",
            approved_owner_uids=approved_owner_uids,
        )
        validated.append(identity.path)
    if len(set(validated)) != len(validated):
        raise RuntimePolicyError(f"RuntimePolicy repeats a {label} read root")
    return tuple(validated)


__all__ = [
    "ContainmentBackend",
    "FrozenContainmentError",
    "FrozenContainmentService",
    "FrozenMaterializationError",
    "FrozenMaterializer",
    "FrozenSnapshot",
    "FileIdentity",
    "DirectoryIdentity",
    "ManifestEntry",
    "RuntimePolicy",
    "RuntimePolicyError",
    "StaticContainmentRejection",
    "SupportedHost",
    "ValidatedRuntimePolicy",
    "discover_containment_backend",
    "extract_frozen_archive",
]
