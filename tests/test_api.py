from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench import api
from workbench.api import app


def test_api_creates_project_and_runs_upload(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    assert response.status_code == 200
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"


def test_api_rejects_oversized_upload_and_cleans_temp_dir(
    tmp_path: Path, monkeypatch
):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = Path(response.json()["project_root"])
    (project_root / "config.yml").write_text(
        "max_single_file_gb: 0.000000001\n", encoding="utf-8"
    )
    original_temp_dir = api.tempfile.TemporaryDirectory

    def tracked_temp_dir(prefix: str):
        return original_temp_dir(prefix=prefix, dir=tmp_path)

    monkeypatch.setattr(api.tempfile, "TemporaryDirectory", tracked_temp_dir)
    data = tmp_path / "large.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")

    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": str(project_root), "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("large.csv", handle, "text/csv")},
        )

    assert run_response.status_code == 413
    assert not list(tmp_path.glob("workbench_upload_*"))
