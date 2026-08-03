import io
import time
import pandas as pd
import pytest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from workbench.api import app, _parse_json_str_array
from workbench.artifacts import read_json


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
            "prediction_data_structure": "grouped", "prediction_group_column": "firm",
            "prediction_time_column": "yr", "prediction_final_holdout_fraction": "0.25",
            "prediction_shuffle": "false",
            "frequency_weight": "freq",
            "analysis_weight": "analytic",
            "sampling_weight": "sample",
            "model_options": "{}",
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
    assert kw["prediction_data_structure"] == "grouped"
    assert kw["prediction_group_column"] == "firm"
    assert kw["prediction_time_column"] == "yr"
    assert kw["prediction_final_holdout_fraction"] == 0.25
    assert kw["prediction_shuffle"] is False
    assert kw["frequency_weight"] == "freq"
    assert kw["analysis_weight"] == "analytic"
    assert kw["sampling_weight"] == "sample"
    assert kw["model_options"] == {}
    assert kw["model_options_binding"] is None


def test_run_endpoint_forwards_explicit_labels(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "labels"}
    ).json()["project_root"]
    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post(
            "/runs",
            data={
                "project_root": root,
                "mode": "auto",
                "model_type": "ols",
                "y": "y",
                "x": "x",
                "labels": '{"variable_labels":{"y":"Outcome"},"value_labels":{"x":{"0":"Control"}}}',
            },
            files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
        )
        for _ in range(100):
            if m.call_args is not None:
                break
            time.sleep(0.05)
    assert resp.status_code == 200
    assert m.call_args.kwargs["labels"] == {
        "variable_labels": {"y": "Outcome"},
        "value_labels": {"x": {"0": "Control"}},
    }


def test_run_endpoint_rejects_invalid_labels_shape(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "invalid-labels"}
    ).json()["project_root"]
    response = client.post(
        "/runs",
        data={
            "project_root": root,
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x",
            "labels": '{"unexpected":{}}',
        },
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    assert response.status_code == 422
    assert "INVALID_LABELS" in response.json()["detail"]


def test_run_endpoint_executes_frequency_weight_in_ols_packet(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "weighted"}
    ).json()["project_root"]
    frame = pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index + (5.0 if index % 3 == 0 else 0.0) for index in range(36)],
            "x": [float(index) for index in range(36)],
            "freq": [1.0 if index < 18 else 8.0 for index in range(36)],
        }
    )
    response = client.post(
        "/runs",
        data={
            "project_root": root,
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x",
            "frequency_weight": "freq",
            "covariance": "unadjusted",
        },
        files={"file": ("weighted.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    terminal = None
    for _ in range(100):
        detail = client.get(f"/runs/{run_id}", params={"project_root": root}).json()
        terminal = detail.get("status")
        if terminal in {"completed", "failed", "blocked", "partial"}:
            break
        time.sleep(0.1)
    assert terminal == "completed"
    model = read_json(
        tmp_path / "weighted" / "runs" / run_id / "model_results" / "ols_1.json"
    )
    assert model["weights"] == {"kind": "frequency", "column": "freq", "executed": True}


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


# --- x column-selector wire format (v1.7 smoke finding) -----------------------
#
# `x` historically was comma-separated while iv_endog/iv_instruments are JSON
# arrays. JSON-array x "worked" only because normalize_column_name stripped the
# brackets, and `x=[]` produced a blocked run with `missing_columns: [""]`.
# The selector now accepts BOTH forms explicitly, and an empty x is legal over
# HTTP so zero-covariate DID/CS families can be submitted (the engine and
# run_workflow tests already support x=[]).


def _submit_x(client, root, x_value: str | None, model_type: str = "panel_ols"):
    data = {
        "project_root": root, "mode": "auto", "model_type": model_type,
        "y": "y", "entity_col": "firm", "time_col": "yr",
    }
    if x_value is not None:
        data["x"] = x_value
    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as m:
        resp = client.post("/runs", data=data,
                           files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})
        for _ in range(100):
            if m.call_args is not None or resp.status_code != 200:
                break
            time.sleep(0.05)
    return resp, m


def test_run_endpoint_accepts_json_array_x(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]
    resp, m = _submit_x(client, root, '["x"]')
    assert resp.status_code == 200
    assert m.call_args.args[5] == ["x"]


def test_run_endpoint_accepts_empty_json_array_x(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]
    resp, m = _submit_x(client, root, "[]")
    assert resp.status_code == 200
    assert m.call_args.args[5] == []


def test_run_endpoint_accepts_omitted_x_for_did_families(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]
    resp, m = _submit_x(client, root, None)
    assert resp.status_code == 200
    assert m.call_args.args[5] == []


def test_run_endpoint_rejects_malformed_json_x(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]
    resp, _ = _submit_x(client, root, '["a"')
    assert resp.status_code == 422
    assert "x" in str(resp.json()["detail"])


def test_run_endpoint_rejects_non_string_json_x(tmp_path):
    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]
    resp, _ = _submit_x(client, root, "[1, 2]")
    assert resp.status_code == 422
