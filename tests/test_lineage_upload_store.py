from pathlib import Path

import pytest

from workbench.lineage.upload_store import (
    UploadBlobMissing,
    UploadHashMismatch,
    resolve_upload,
    store_upload_bytes,
    verify_upload,
)


def test_store_returns_sha256_and_writes_blob(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"col\n1\n2\n", filename="d.csv")
    blob = tmp_path / "data" / "uploads" / sha
    assert blob.is_file()
    assert blob.read_bytes() == b"col\n1\n2\n"
    assert len(sha) == 64  # hex sha256


def test_store_is_content_addressed_idempotent(tmp_path: Path):
    a = store_upload_bytes(tmp_path, b"same", filename="a.csv")
    b = store_upload_bytes(tmp_path, b"same", filename="b.csv")
    assert a == b  # same content -> same key, stored once


def test_resolve_returns_path(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"x", filename="x.csv")
    assert resolve_upload(tmp_path, sha).read_bytes() == b"x"


def test_resolve_missing_blob_raises(tmp_path: Path):
    with pytest.raises(UploadBlobMissing):
        resolve_upload(tmp_path, "0" * 64)


def test_verify_detects_corruption(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"original", filename="x.csv")
    (tmp_path / "data" / "uploads" / sha).write_bytes(b"tampered")
    with pytest.raises(UploadHashMismatch):
        verify_upload(tmp_path, sha)
