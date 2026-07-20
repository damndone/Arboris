"""Descriptor-relative hostile-output inspection and parent-only verdicts.

Candidate-produced facts are observations only.  A pass can originate solely
from the injected parent evaluator after no-follow output inspection succeeds.
No process, candidate import, or collector integration lives in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Protocol
import uuid

from .frozen_containment_execution import CandidateObservationV1


@dataclass
class ParentOutputRootV1:
    descriptor: int
    device: int
    inode: int

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass(frozen=True)
class OutputPolicyV1:
    allowed_files: tuple[str, ...]
    max_file_bytes: int
    max_total_bytes: int
    forbidden_identities: tuple[tuple[int, int], ...] = ()

    def validate(self) -> None:
        if not self.allowed_files or len(set(self.allowed_files)) != len(self.allowed_files):
            raise ValueError("output allowlist is missing or duplicated")
        if any(not _safe_name(name) for name in self.allowed_files):
            raise ValueError("output allowlist has an unsafe file name")
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (self.max_file_bytes, self.max_total_bytes)):
            raise ValueError("output limits are invalid")
        if self.max_total_bytes < self.max_file_bytes:
            raise ValueError("total output limit is smaller than a file limit")
        if len(set(self.forbidden_identities)) != len(self.forbidden_identities):
            raise ValueError("forbidden output identities are duplicated")


@dataclass(frozen=True)
class OutputManifestEntryV1:
    name: str
    device: int
    inode: int
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class IngestionAuditReceiptV1:
    schema_version: str
    audit_record_sha256: str


@dataclass(frozen=True)
class EvaluatorVerdictV1:
    verdict: str
    code: str
    audit_receipt: IngestionAuditReceiptV1 | None
    output_manifest: tuple[OutputManifestEntryV1, ...]


class ParentEvaluatorV1(Protocol):
    def evaluate(self, *, observation: CandidateObservationV1, output_manifest: tuple[OutputManifestEntryV1, ...]) -> bool: ...


class IngestionAuditStore:
    """No-replace, descriptor-anchored parent audit writer."""

    def __init__(self, root: Path):
        self._root = root

    def publish_success(self, record: dict[str, object]) -> IngestionAuditReceiptV1:
        content = _canonical_bytes(record)
        if len(content) > 16 * 1024:
            raise OSError("ingestion audit record exceeds bounded size")
        digest = hashlib.sha256(content).hexdigest()
        self._write_no_replace(f"ingestion-{digest}.json", content)
        return IngestionAuditReceiptV1("1", digest)

    def record_rejection(self, *, code: str) -> None:
        content = _canonical_bytes({"schema_version": "1", "kind": "ingestion_rejection", "code": code})
        self._write_no_replace(f"reject-{hashlib.sha256(content).hexdigest()}-{uuid.uuid4().hex}.json", content)

    def _write_no_replace(self, name: str, content: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        directory_fd = _open_directory(self._root)
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        fd = -1
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            _write_all(fd, content)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
            if _read_no_follow(directory_fd, name) != content:
                raise OSError("ingestion audit reread mismatch")
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)


def open_parent_output_root(path: Path) -> ParentOutputRootV1:
    """Open a parent-created output directory once; later reads use only its FD."""

    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("parent output root must be a non-symlink directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = os.fstat(descriptor)
    return ParentOutputRootV1(descriptor, opened.st_dev, opened.st_ino)


def ingest_and_evaluate(
    *,
    observation: CandidateObservationV1,
    output_root: ParentOutputRootV1,
    output_policy: OutputPolicyV1,
    parent_evaluator: ParentEvaluatorV1,
    audit_store: IngestionAuditStore,
) -> EvaluatorVerdictV1:
    """Return a verdict from parent evidence only; failure receipts are null."""

    try:
        manifest = inspect_hostile_output(output_root, output_policy)
        if not isinstance(observation, CandidateObservationV1):
            raise ValueError("candidate observation has an invalid type")
        passed = parent_evaluator.evaluate(observation=observation, output_manifest=manifest)
        if passed is not True:
            _best_effort_rejection(audit_store, "C2_EVALUATOR_NONPASSING")
            return EvaluatorVerdictV1("non_passing", "C2_EVALUATOR_NONPASSING", None, manifest)
        receipt = audit_store.publish_success(
            {
                "schema_version": "1",
                "kind": "parent_evaluator_verdict",
                "verdict": "passed",
                "observation_status": observation.status,
                "manifest": [entry.__dict__ for entry in manifest],
            }
        )
        return EvaluatorVerdictV1("passed", "C2_EVALUATOR_PASSED", receipt, manifest)
    except Exception:
        _best_effort_rejection(audit_store, "C2_INGESTION_FAILED")
        return EvaluatorVerdictV1("non_passing", "C2_INGESTION_FAILED", None, ())


def inspect_hostile_output(output_root: ParentOutputRootV1, output_policy: OutputPolicyV1) -> tuple[OutputManifestEntryV1, ...]:
    output_policy.validate()
    if not isinstance(output_root, ParentOutputRootV1) or output_root.descriptor < 0:
        raise ValueError("parent output root descriptor is invalid")
    root_info = os.fstat(output_root.descriptor)
    if (root_info.st_dev, root_info.st_ino) != (output_root.device, output_root.inode) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("parent output root identity changed")
    names = sorted(os.listdir(output_root.descriptor))
    if set(names) - set(output_policy.allowed_files):
        raise ValueError("output root contains an unexpected entry")
    if set(names) != set(output_policy.allowed_files):
        raise ValueError("output root is missing an expected entry")
    total = 0
    manifest: list[OutputManifestEntryV1] = []
    for name in names:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=output_root.descriptor)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("output entry is not an unlinked regular file")
            identity = (before.st_dev, before.st_ino)
            if identity in output_policy.forbidden_identities:
                raise ValueError("output entry aliases a source, runtime, or fixture identity")
            if before.st_size > output_policy.max_file_bytes:
                raise ValueError("output entry exceeds per-file limit")
            contents = _read_exact(descriptor, before.st_size)
            after = os.fstat(descriptor)
            if (after.st_dev, after.st_ino, after.st_size) != (before.st_dev, before.st_ino, before.st_size):
                raise ValueError("output entry changed while read")
            total += before.st_size
            if total > output_policy.max_total_bytes:
                raise ValueError("output total exceeds limit")
            manifest.append(OutputManifestEntryV1(name, before.st_dev, before.st_ino, before.st_size, hashlib.sha256(contents).hexdigest()))
        finally:
            os.close(descriptor)
    return tuple(manifest)


def _best_effort_rejection(audit_store: IngestionAuditStore, code: str) -> None:
    try:
        audit_store.record_rejection(code=code)
    except Exception:
        pass


def _safe_name(name: str) -> bool:
    return isinstance(name, str) and bool(name) and "/" not in name and "\\" not in name and name not in {".", ".."} and "\x00" not in name


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _open_directory(path: Path) -> int:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise OSError("audit root is not a safe directory")
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_no_follow(directory_fd: int, name: str) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("audit record is not regular")
        return _read_exact(descriptor, info.st_size)
    finally:
        os.close(descriptor)


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            data = b"".join(chunks)
            if len(data) != size:
                raise ValueError("descriptor read was short or changed")
            return data
        chunks.append(chunk)


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("could not write complete audit record")
        offset += written


__all__ = [
    "EvaluatorVerdictV1",
    "IngestionAuditReceiptV1",
    "IngestionAuditStore",
    "OutputManifestEntryV1",
    "OutputPolicyV1",
    "ParentOutputRootV1",
    "ingest_and_evaluate",
    "inspect_hostile_output",
    "open_parent_output_root",
]
