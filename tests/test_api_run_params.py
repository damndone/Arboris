import io
import time
import pandas as pd
import pytest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from workbench.api import app, _parse_json_str_array


def _csv() -> bytes:
    return pd.DataFrame({"y": [1.0, 2, 3, 4], "x": [1.0, 2, 3, 4],
                         "firm": ["a", "a", "b", "b"], "yr": [1, 2, 1, 2]}).to_csv(index=False).encode()


def test_run_endpoint_forwards_new_params(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    # Patch _run_workflow in run_service (the module where _bg_run now lives and
    # binds the name), so a positional swap in executor.submit(_bg_run, ...) is caught.
    with patch(
        "workbench.services.run_service._run_workflow",
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


def test_run_endpoint_forwards_cs_params(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    # Patch _run_workflow in run_service (the module where _bg_run now lives and
    # binds the name), so a positional swap in executor.submit(_bg_run, ...) is caught.
    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post("/runs", data={
            "project_root": root, "mode": "auto", "model_type": "cs_did",
            "y": "y", "x": "x",
            "entity_col": "firm", "time_col": "yr",
            "did_mode": "cohort", "did_cohort_col": "first_treat",
            "cs_control_group": "never", "cs_est_method": "dr",
            "cs_base_period": "varying", "cs_cluster_var": "firm",
            "cs_anticipation": "1",
        }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})
        # _bg_run runs on the executor thread — poll until _run_workflow is called.
        for _ in range(100):
            if m.call_args is not None:
                break
            time.sleep(0.05)

    assert resp.status_code == 200
    kw = m.call_args.kwargs
    assert kw["cs_control_group"] == "never"
    assert kw["cs_est_method"] == "dr"
    assert kw["cs_base_period"] == "varying"
    assert kw["cs_cluster_var"] == "firm"
    assert kw["cs_anticipation"] == 1  # Form(int) parsed to int


def test_parse_json_str_array_valid():
    assert _parse_json_str_array('["educ"]', "iv_endog") == ["educ"]


def test_parse_json_str_array_empty():
    assert _parse_json_str_array("", "iv_endog") == []
    assert _parse_json_str_array("   ", "iv_endog") == []


def test_parse_json_str_array_non_array_raises_422():
    # valid JSON but not a string-array -> clean 422, not a downstream 500
    with pytest.raises(HTTPException) as exc:
        _parse_json_str_array("5", "iv_endog")
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        _parse_json_str_array('{"a": 1}', "iv_endog")
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        _parse_json_str_array("[1, 2]", "iv_endog")  # array but not strings
    assert exc.value.status_code == 422


def test_parse_json_str_array_malformed_json_raises_422():
    with pytest.raises(HTTPException) as exc:
        _parse_json_str_array("[not json", "iv_endog")
    assert exc.value.status_code == 422


def test_run_endpoint_rejects_non_array_iv_endog(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    resp = client.post("/runs", data={
        "project_root": root, "mode": "auto", "model_type": "iv_2sls",
        "y": "y", "x": "x",
        "iv_endog": "5",  # valid JSON, wrong shape
    }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})
    assert resp.status_code == 422


def test_run_endpoint_accepts_valid_iv_endog(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post("/runs", data={
            "project_root": root, "mode": "auto", "model_type": "iv_2sls",
            "y": "y", "x": "x",
            "iv_endog": '["educ"]', "iv_instruments": '["dist"]',
        }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})
        for _ in range(100):
            if m.call_args is not None:
                break
            time.sleep(0.05)

    assert resp.status_code == 200
    kw = m.call_args.kwargs
    assert kw["iv_endog"] == ["educ"]
    assert kw["iv_instruments"] == ["dist"]
