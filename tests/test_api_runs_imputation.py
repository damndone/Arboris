from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.events import get_event_manager


def test_post_runs_parses_imputation_json_and_passes_to_background_worker(
    tmp_path: Path,
    monkeypatch,
):
    client = TestClient(app)
    project_response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = project_response.json()["project_root"]
    source = tmp_path / "data.csv"
    pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}).to_csv(
        source,
        index=False,
    )

    captured: dict[str, object] = {}

    def fake_submit(fn, *args):
        captured["fn"] = fn
        captured["args"] = args
        get_event_manager().release_slot(args[1])

    monkeypatch.setattr(get_event_manager().executor, "submit", fake_submit)

    with source.open("rb") as handle:
        response = client.post(
            "/runs",
            data={
                "project_root": project_root,
                "mode": "auto",
                "y": "y",
                "x": "x",
                "imputation": json.dumps({"method": "mice"}),
            },
            files={"file": ("data.csv", handle, "text/csv")},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert {"method": "mice"} in captured["args"]
