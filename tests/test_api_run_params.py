import io
import time
import pandas as pd
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench.api import app


def _csv() -> bytes:
    return pd.DataFrame({"y": [1.0, 2, 3, 4], "x": [1.0, 2, 3, 4],
                         "firm": ["a", "a", "b", "b"], "yr": [1, 2, 1, 2]}).to_csv(index=False).encode()


def test_run_endpoint_forwards_new_params(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    # Patch _run_workflow (the symbol _bg_run actually calls). Names bind there,
    # so a positional swap in executor.submit(_bg_run, ...) is caught.
    with patch(
        "workbench.api._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post("/runs", data={
            "project_root": root, "mode": "auto", "model_type": "panel_ols",
            "y": "y", "x": "x",
            "entity_col": "firm", "time_col": "yr", "covariance": "robust",
            "prediction_model_type": "prediction_ridge", "prediction_cv_folds": "3",
            "prediction_sampling_method": "smote",
        }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})
        # _bg_run runs on the executor thread — poll until _run_workflow is called.
        for _ in range(100):
            if m.call_args is not None:
                break
            time.sleep(0.05)

    assert resp.status_code == 200
    kw = m.call_args.kwargs
    assert kw["entity_col"] == "firm"
    assert kw["time_col"] == "yr"
    assert kw["covariance"] == "robust"
    assert kw["prediction_model_type"] == "prediction_ridge"
    assert kw["prediction_cv_folds"] == 3  # parsed to int
    assert kw["prediction_sampling_method"] == "smote"
