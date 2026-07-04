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


def delete_upload_if_unreferenced(project_root: Path, sha256: str) -> bool:
    """Delete the blob unless any run_inputs.json or any (other) draft references it.

    v1.6.8 F6 — called on genesis draft discard only (AFTER the discarded draft's
    own json is deleted, so it no longer counts as a reference); full orphan GC is
    a followup. Substring scan over the small json files is conservative and
    unambiguous (a sha256 hex string has no partial-collision surface).

    Defensive reads: an unreadable json during the scan is treated as REFERENCED
    (return False, keep the blob) — losing a few KB of blob is better than
    deleting data a corrupt-but-recoverable run might still need.

    Returns True iff the blob existed and was deleted.
    """
    runs_dir = project_root / "runs"
    if runs_dir.is_dir():
        for run_dir in runs_dir.iterdir():
            ri = run_dir / "run_inputs.json"
            try:
                if ri.is_file() and sha256 in ri.read_text(encoding="utf-8"):
                    return False
            except OSError:
                return False  # unreadable -> treat as referenced
    drafts_dir = project_root / "data" / "pipeline_drafts"
    if drafts_dir.is_dir():
        for p in drafts_dir.glob("*.json"):
            try:
                if sha256 in p.read_text(encoding="utf-8"):
                    return False
            except OSError:
                return False  # unreadable -> treat as referenced
    path = _uploads_dir(project_root) / sha256
    if path.is_file():
        path.unlink()
        return True
    return False


def verify_upload(project_root: Path, sha256: str) -> Path:
    """Resolve and re-verify the blob hashes to its key; raise on mismatch."""
    path = resolve_upload(project_root, sha256)
    actual = sha256_bytes(path.read_bytes())
    if actual != sha256:
        raise UploadHashMismatch(
            f"Upload blob {sha256} content hashes to {actual}"
        )
    return path
