from pathlib import Path

from workbench.lineage.run_inputs import (
    RUN_INPUT_SCHEMA_VERSION,
    read_run_inputs,
    redact_form,
    write_run_inputs,
)


def test_roundtrip(tmp_path: Path):
    write_run_inputs(
        tmp_path,
        form={"model_type": "ols", "y": "wage", "x": "edu"},
        upload={"sha256": "a" * 64, "filename": "d.csv"},
        rerun_of=None, from_node=None, rerun_reason="initial",
        override_hash=None, dag_hash="d" * 64,
    )
    got = read_run_inputs(tmp_path)
    assert got["run_input_schema_version"] == RUN_INPUT_SCHEMA_VERSION
    assert got["form"]["model_type"] == "ols"
    assert got["upload"]["sha256"] == "a" * 64
    assert got["rerun_reason"] == "initial"
    assert got["dag_hash"] == "d" * 64


def test_write_run_inputs_persists_rerun_from_when_provided(tmp_path: Path):
    rerun_from = {
        "owner_run_id": "run_parent",
        "op_node_id": "model:ols_1",
        "node_hash": "hash_parent_model",
        "context_fingerprint": "nocv1:parent",
        "rerun_request_id": "req_1",
    }

    write_run_inputs(
        tmp_path,
        form={"model_type": "ols", "y": "wage", "x": "edu"},
        upload={"sha256": "a" * 64, "filename": "d.csv"},
        rerun_of="run_parent", from_node="model:ols_1", rerun_reason="manual_override",
        override_hash="override", dag_hash="d" * 64, rerun_from=rerun_from,
    )

    got = read_run_inputs(tmp_path)
    assert got["rerun_from"] == rerun_from


def test_redaction_masks_secret_like_keys():
    out = redact_form({"y": "wage", "api_key": "sk-123", "db_password": "p"})
    assert out["y"] == "wage"
    assert out["api_key"] == "***"
    assert out["db_password"] == "***"
