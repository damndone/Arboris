"""v1.6.8 genesis: standalone POST /uploads (content-addressable upload store)."""

from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.upload_store import resolve_upload

client = TestClient(app)


def _mkproject(tmp_path: Path) -> str:
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "p1"})
    assert r.status_code == 200
    return r.json()["project_root"]


def _post_upload(root: str, name: str, payload: bytes):
    return client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": (name, payload, "text/csv")},
    )


def test_upload_roundtrip(tmp_path: Path):
    root = _mkproject(tmp_path)
    csv = b"y,x\n1,2\n3,4\n"
    r = _post_upload(root, "data.csv", csv)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "data.csv"
    assert resolve_upload(Path(root), body["sha256"]).read_bytes() == csv


def test_upload_dedups_identical_bytes(tmp_path: Path):
    root = _mkproject(tmp_path)
    csv = b"y,x\n1,2\n3,4\n"
    first = _post_upload(root, "data.csv", csv)
    second = _post_upload(root, "renamed.csv", csv)
    assert first.status_code == 200
    assert second.status_code == 200
    # Content-addressing contract: same bytes → same sha, regardless of filename.
    assert first.json()["sha256"] == second.json()["sha256"]


def test_upload_rejects_oversize(tmp_path: Path):
    root = _mkproject(tmp_path)
    # Real per-project config path: cap far below the ~10-byte payload.
    (Path(root) / "config.yml").write_text("max_single_file_gb: 0.000000001\n")
    r = _post_upload(root, "big.csv", b"yy,xx\n1,2\n")
    assert r.status_code == 413


def test_upload_nonexistent_project_root_404(tmp_path: Path):
    r = _post_upload(str(tmp_path / "no-such-project"), "data.csv", b"y,x\n1,2\n")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"
