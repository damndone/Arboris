"""Content-addressable upload store. Uploads are keyed by sha256 so their lifecycle
is decoupled from any single run: a rerun references a parent's upload by hash, never
by path. Blobs live at <project_root>/data/uploads/<sha256>."""
from __future__ import annotations

import hashlib
from pathlib import Path


class UploadBlobMissing(FileNotFoundError):
    """The content-addressed blob for a given sha256 does not exist."""


class UploadHashMismatch(ValueError):
    """A stored blob's content no longer hashes to its key (corruption/tamper)."""


def _uploads_dir(project_root: Path) -> Path:
    return project_root / "data" / "uploads"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_upload_bytes(project_root: Path, data: bytes, *, filename: str) -> str:
    """Write `data` content-addressably; return its sha256. Idempotent: identical
    content stores once. `filename` is accepted for API symmetry but not used as the
    key (kept by callers in run_inputs for display only)."""
    sha = sha256_bytes(data)
    target = _uploads_dir(project_root) / sha
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return sha


def resolve_upload(project_root: Path, sha256: str) -> Path:
    path = _uploads_dir(project_root) / sha256
    if not path.is_file():
        raise UploadBlobMissing(f"No upload blob for sha256={sha256}")
    return path


def verify_upload(project_root: Path, sha256: str) -> Path:
    """Resolve and re-verify the blob hashes to its key; raise on mismatch."""
    path = resolve_upload(project_root, sha256)
    actual = sha256_bytes(path.read_bytes())
    if actual != sha256:
        raise UploadHashMismatch(
            f"Upload blob {sha256} content hashes to {actual}"
        )
    return path
