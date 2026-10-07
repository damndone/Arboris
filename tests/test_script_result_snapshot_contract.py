"""Result snapshots contain real asset values, bound to an executed step."""
from dataclasses import replace
import hashlib
import json

import pytest

from workbench.contracts.common.envelope import ContractError, thaw_json
from workbench.script_export.plan import ScriptPlan, ScriptStep
from workbench.script_export.result_snapshot import (
    ResultSnapshotRef, result_snapshot_binding, validate_result_snapshot,
    read_result_snapshot, build_result_snapshot,
)


def plan(expected=None):
    step = ScriptStep("fit", "model", "model.custom", {"model_type": "custom"}, (),
        expected=expected or {})
    return ScriptPlan("project", "run", (), (step,), "1.8.11", "a"*64)


VALUES = {"nobs": 10, "coefficients": {"x": 2.}, "std_errors": {"x": .3}, "statistics": {}}


def payload(p):
    return {"contract": "workbench.script_result_snapshot.v1", "schema_version": 1,
        "binding": result_snapshot_binding(p, p.steps[0]),
        "source": {"artifact_id": "model:actual", "artifact_sha256": "b"*64,
                   "result_contract": "model-result/v1"}, "values": VALUES}


def test_result_binding_excludes_expected_but_includes_execution_identity():
    p = plan({"coefficients": {"x": 999.}})
    same = replace(p, steps=(replace(p.steps[0], expected={"coefficients": {"x": -123.}}),))
    assert result_snapshot_binding(p, p.steps[0]) == result_snapshot_binding(same, same.steps[0])
    other = replace(p.steps[0], parameters={"model_type": "other"})
    assert result_snapshot_binding(p, other) != result_snapshot_binding(p, p.steps[0])


def test_builder_reads_actual_persisted_bytes_without_expected(tmp_path):
    p = plan({"coefficients": {"x": 999.}})
    artifact = tmp_path/"artifact.json"
    artifact.write_text(json.dumps(VALUES))
    data = build_result_snapshot(artifact, binding=result_snapshot_binding(p,p.steps[0]),
        artifact_id="model:actual", result_contract="model-result/v1", projector=lambda value: value)
    actual = json.loads(data)
    assert actual["values"]["coefficients"]["x"] == 2.
    assert actual["source"]["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert thaw_json(validate_result_snapshot(actual, expected_binding=actual["binding"])) == VALUES


def test_reader_verifies_same_bytes_and_binding(tmp_path):
    p = plan()
    raw = json.dumps(payload(p)).encode()
    asset = tmp_path/"fit.json"
    asset.write_bytes(raw)
    ref = ResultSnapshotRef("fit.json", hashlib.sha256(raw).hexdigest())
    assert thaw_json(read_result_snapshot(tmp_path,ref,expected_binding=result_snapshot_binding(p,p.steps[0]))) == VALUES
    asset.write_bytes(raw+b" ")
    with pytest.raises(ContractError,match="SHA"):
        read_result_snapshot(tmp_path,ref,expected_binding=result_snapshot_binding(p,p.steps[0]))


@pytest.mark.parametrize("filename", ["../fit.json", "/tmp/fit.json", "https://x/fit.json", "a\\b.json", "a\n.json"])
def test_ref_rejects_nonlocal_or_unsafe_filenames(filename):
    with pytest.raises(ContractError):
        ResultSnapshotRef(filename,"a"*64)


def test_reader_rejects_symlink_and_duplicate_keys(tmp_path):
    p=plan()
    raw=json.dumps(payload(p)).encode()
    (tmp_path/"actual.json").write_bytes(raw)
    (tmp_path/"fit.json").symlink_to(tmp_path/"actual.json")
    with pytest.raises(ContractError):
        read_result_snapshot(tmp_path,ResultSnapshotRef("fit.json",hashlib.sha256(raw).hexdigest()),
            expected_binding=result_snapshot_binding(p,p.steps[0]))
    duplicate=raw[:-1]+b',"schema_version":1}'
    (tmp_path/"duplicate.json").write_bytes(duplicate)
    with pytest.raises(ContractError,match="duplicate"):
        read_result_snapshot(tmp_path,ResultSnapshotRef("duplicate.json",hashlib.sha256(duplicate).hexdigest()),
            expected_binding=result_snapshot_binding(p,p.steps[0]))


@pytest.mark.parametrize("change", ["unknown", "wrong_binding", "bool_number", "nonfinite", "negative_se"])
def test_payload_rejects_invalid_schema_binding_or_numbers(change):
    p=plan()
    value=json.loads(json.dumps(payload(p)))
    if change=="unknown": value["future"]=1
    if change=="wrong_binding": value["binding"]["run_id"]="other"
    if change=="bool_number": value["values"]["coefficients"]["x"]=True
    if change=="nonfinite": value["values"]["coefficients"]["x"]=float("inf")
    if change=="negative_se": value["values"]["std_errors"]["x"]=-.3
    with pytest.raises(ContractError):
        validate_result_snapshot(value,expected_binding=result_snapshot_binding(p,p.steps[0]))
