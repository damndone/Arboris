"""Independent sidecar boundary review; no production or central test edits.

Two provenance tests deliberately document accepted hostile adapters. They are
not acceptance tests: the trusted artifact adapter must close those gaps.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from workbench.contracts.common.envelope import ContractError, thaw_json
from workbench.script_export.plan import ScriptPlan, ScriptStep
from workbench.script_export import result_snapshot as subject


def plan():
    step = ScriptStep("fit", "model", "model.custom", {"model_type": "custom"}, (),
                      expected={"coefficients": {"x": 999.}})
    return ScriptPlan("project", "run", (), (step,), "1.8.11", "a" * 64)


def payload():
    p = plan()
    return {
        "contract": subject.RESULT_SNAPSHOT_CONTRACT,
        "schema_version": 1,
        "binding": subject.result_snapshot_binding(p, p.steps[0]),
        "source": {"artifact_id": "model:actual", "artifact_sha256": "b" * 64,
                   "result_contract": "model-result/v1"},
        "values": {"nobs": 10, "coefficients": {"x": 2.},
                   "std_errors": {"x": .3}, "statistics": {}},
    }


def validate(value):
    return subject.validate_result_snapshot(value, expected_binding=payload()["binding"])


@pytest.mark.parametrize("field,new", [
    ("project_id", "other"), ("run_id", "other"), ("lineage_hash", "c" * 64),
    ("step_id", "other"), ("kind", "postestimation"),
    ("operation", "model.other"), ("parameters_sha256", "c" * 64),
    ("inputs", ["other"]), ("models", ["other"]),
])
def test_execution_binding_cannot_be_swapped(field, new):
    value = payload()
    value["binding"][field] = new
    with pytest.raises(ContractError):
        validate(value)


@pytest.mark.parametrize("filename", ["..json", ".hidden.json", "a:b.json", "a\x00.json",
                                      "a\r.json", "a/b.json", "a\\b.json", "file://a.json"])
def test_ref_filename_rejects_escape(filename):
    with pytest.raises(ContractError):
        subject.ResultSnapshotRef(filename, "a" * 64)


@pytest.mark.parametrize("version", [True, 1., 0, 2, "1"])
def test_ref_version_is_exact_integer_one(version):
    with pytest.raises(ContractError):
        subject.ResultSnapshotRef("fit.json", "a" * 64, version)


@pytest.mark.parametrize("field", ["nobs", "coefficients", "std_errors", "statistics"])
def test_missing_value_field_rejected(field):
    value = payload()
    del value["values"][field]
    with pytest.raises(ContractError):
        validate(value)


def test_large_coefficient_is_contract_refusal_not_overflow():
    value = payload()
    value["values"]["coefficients"]["x"] = 10 ** 400
    with pytest.raises(ContractError):
        validate(value)


def test_nobs_not_representable_as_finite_script_number_is_rejected():
    value = payload()
    value["values"]["nobs"] = 10 ** 400
    with pytest.raises(ContractError):
        validate(value)


def test_distribution_is_opaque_metadata_not_inference_admission():
    value = payload()
    value["values"]["statistics"]["test"] = {
        "value": 2., "df": None, "df_denominator": None,
        "p_value": .5, "distribution": "invented-law",
    }
    assert thaw_json(validate(value))["statistics"]["test"]["distribution"] == "invented-law"


def test_bounded_read_and_nested_duplicate_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "MAX_RESULT_SNAPSHOT_BYTES", 64)
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * 65)
    with pytest.raises(ContractError, match="bounded|size"):
        subject._read_bytes(path)
    with pytest.raises(ContractError, match="duplicate"):
        subject._strict_json(b'{"nested":{"x":1,"x":2}}')


def test_fifo_and_final_symlink_are_refused(tmp_path):
    import os
    path = tmp_path / "fifo.json"
    os.mkfifo(path)
    with pytest.raises(ContractError, match="regular"):
        subject._read_bytes(path)
    actual = tmp_path / "actual.json"
    actual.write_bytes(b"{}")
    link = tmp_path / "link.json"
    link.symlink_to(actual)
    with pytest.raises(ContractError):
        subject._read_bytes(link)


def test_expected_does_not_change_binding_or_actual_with_honest_adapter(tmp_path):
    p = plan()
    alternate = replace(p, steps=(replace(p.steps[0], expected={"coefficients": {"x": -999.}}),))
    binding = subject.result_snapshot_binding(p, p.steps[0])
    assert binding == subject.result_snapshot_binding(alternate, alternate.steps[0])
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(payload()["values"]))
    raw = subject.build_result_snapshot(path, binding=binding, artifact_id="actual",
        result_contract="model-result/v1", projector=lambda asset: asset)
    assert json.loads(raw)["values"]["coefficients"]["x"] == 2.


def test_builder_currently_accepts_wrong_source_identity(tmp_path):
    artifact = {"artifact_id": "model:other-run", "run_id": "other-run",
                "contract": "different-result/v2", "values": payload()["values"]}
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    raw = subject.build_result_snapshot(path, binding=payload()["binding"],
        artifact_id="model:actual", result_contract="model-result/v1",
        projector=lambda source: source["values"])
    minted = json.loads(raw)
    assert minted["binding"]["run_id"] != artifact["run_id"]
    assert minted["source"]["artifact_id"] != artifact["artifact_id"]
    assert minted["source"]["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert thaw_json(validate(minted))["coefficients"]["x"] == 2.


def test_arbitrary_projector_can_ignore_asset_and_copy_expected(tmp_path):
    path = tmp_path / "failed_artifact.json"
    path.write_text(json.dumps({"status": "failed", "issues": ["INFERENCE_UNCERTIFIED"]}))
    fabricated = deepcopy(payload()["values"])
    fabricated["coefficients"]["x"] = plan().steps[0].expected["coefficients"]["x"]
    raw = subject.build_result_snapshot(path, binding=payload()["binding"],
        artifact_id="actual", result_contract="model-result/v1",
        projector=lambda ignored_source: fabricated)
    assert json.loads(raw)["values"]["coefficients"]["x"] == 999.
