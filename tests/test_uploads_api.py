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


def test_upload_roundtrip(tmp_path: Path):
    root = _mkproject(tmp_path)
    csv = b"y,x\n1,2\n3,4\n"
    r = client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": ("data.csv", csv, "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "data.csv"
    assert resolve_upload(Path(root), body["sha256"]).read_bytes() == csv


def test_upload_rejects_oversize(tmp_path: Path, monkeypatch):
    root = _mkproject(tmp_path)
    import workbench.api as api_mod

    monkeypatch.setattr(api_mod, "BYTES_PER_GB", 1)
    r = client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": ("big.csv", b"yy,xx\n1,2\n", "text/csv")},
    )
    assert r.status_code == 413
