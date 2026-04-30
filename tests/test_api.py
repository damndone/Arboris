from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

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
