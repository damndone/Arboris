import io
import pandas as pd
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.events import get_event_manager


def _csv() -> bytes:
    return pd.DataFrame({"y": [1.0, 2, 3, 4], "x": [1.0, 2, 3, 4],
                         "firm": ["a", "a", "b", "b"], "yr": [1, 2, 1, 2]}).to_csv(index=False).encode()


def test_run_endpoint_forwards_new_params(tmp_path):
    client = TestClient(app)
    proj = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    root = proj.json()["project_root"]

    captured = {}

    def _fake_bg(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        # _bg_run normally releases the run slot in its finally block; mirror that
        # so we don't leak the slot to subsequent tests in this process.
        get_event_manager().release_slot(args[1])

    with patch("workbench.api._bg_run", _fake_bg):
        resp = client.post("/runs", data={
            "project_root": root, "mode": "auto", "model_type": "panel_ols",
            "y": "y", "x": "x",
            "entity_col": "firm", "time_col": "yr", "covariance": "robust",
            "prediction_model_type": "prediction_ridge", "prediction_cv_folds": "3",
            "prediction_sampling_method": "smote",
        }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})

    assert resp.status_code == 200
    flat = list(captured.get("args", ())) + list(captured.get("kwargs", {}).values())
    assert "firm" in flat and "yr" in flat
    assert "prediction_ridge" in flat and "smote" in flat
    assert 3 in flat  # prediction_cv_folds parsed to int
