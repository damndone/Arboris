"""One native declaration supplies both statistical execution surfaces.

The injected arithmetic family is an extension probe, not a shipped method or
an independent numerical oracle. Existing numerical tests certify regressions.
"""
from dataclasses import replace

import pandas as pd
import pytest

from workbench import statistical_tests
from workbench.contracts.common.errors import OperationValidationError


def _probe(monkeypatch, *, named=True):
    parameter_type = getattr(statistical_tests, "TestParameter", None)
    assert parameter_type is not None, "statistical parameters still have separate workflow owners"
    base = statistical_tests.TEST_FAMILIES["correlations"]
    monkeypatch.setitem(statistical_tests.TEST_FAMILIES, "extension_probe", replace(base,
        artifact_filename="extension_probe.json", summary="Offline extension wiring probe.",
        parameters={**base.parameters,
            "offset":parameter_type("Declared numeric offset.", "number", {"type":"number"}),
            "contrast_column":parameter_type("Exact contrast source column.", "string", {"type":"string", "minLength":1}, column_role="column")}))
    def calculate(frame, *, analysis_columns, offset=0, contrast_column=None, **kwargs):
        return {"test_type":"extension_probe", "results":[{
            "statistic":float(frame[contrast_column].sum()) + offset,
            "assumptions":["Offline arithmetic wiring probe."]}]}
    original_named = statistical_tests.run_named_statistical_test
    def named_probe(frame, *, family, **kwargs):
        return calculate(frame, **kwargs) if family == "extension_probe" else original_named(frame, family=family, **kwargs)
    def automatic(frame, **kwargs):
        # Only the probe is executed here; the eight real families retain their
        # unchanged native implementation and automatic multiplicity scope.
        return {"extension_probe":calculate(frame, **kwargs)}
    monkeypatch.setattr(statistical_tests, "run_named_statistical_test", named_probe)
    monkeypatch.setattr(statistical_tests, "run_statistical_tests", automatic)
    from workbench.agent.workflow_contract_parts.declarations import statistical_workflow_step_contracts
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    from workbench.agent.workflow_capability_registry import workflow_capability_step_contracts
    monkeypatch.setitem(WORKFLOW_STEP_SPEC_CONTRACTS, "test.extension_probe",
        (statistical_workflow_step_contracts() if named else workflow_capability_step_contracts())["test.extension_probe"])
    return "test.extension_probe"


def test_native_declaration_publishes_validates_and_binds_new_parameters(tmp_path, monkeypatch):
    operation_id = _probe(monkeypatch)
    from workbench.agent.workflow_contract_parts.validation import _validate_step_spec
    from workbench.agent.workflow_contract_parts.graph import _spec_columns
    from workbench.agent.workflow_capability_registry import workflow_capability_registry
    from workbench.agent.workflow_contracts import workflow_step_vocabulary

    spec = {"analysis_columns":["x", "y"], "offset":2.5, "contrast_column":"z"}
    published = workflow_step_vocabulary()["step_operations"][operation_id]
    assert published["field_types"]["offset"] == "number"
    assert "contrast_column" in published["fields"]
    _validate_step_spec(operation_id, spec)
    assert _spec_columns(operation_id, spec) == {"x", "y", "z"}
    with pytest.raises(OperationValidationError, match="offset"):
        _validate_step_spec(operation_id, {**spec, "offset":"invalid"})
    operation = workflow_capability_registry().require(operation_id)
    assert operation.request_schema["properties"]["options"]["properties"]["offset"] == {"type":"number"}
    with pytest.raises(ValueError, match="offset"):
        operation.validate({"operation_id":operation_id, "input_mode":"frame",
            "column_bindings":{"columns":["x", "y", "z"]}, "options":{"offset":True}})
    request = operation.validate({"operation_id":operation_id, "input_mode":"frame",
        "column_bindings":{"columns":["x", "y", "z"]}, "options":{"offset":2.5, "contrast_column":"z"}})
    frame = pd.DataFrame({"x":[1.,2.,3.], "y":[2.,1.,4.], "z":[2.,3.,4.]})
    assert operation.execute(frame, request)["result"]["results"][0]["statistic"] == 11.5

    # Exercise the actual named-workflow dispatcher and its persisted receipt.
    from types import SimpleNamespace
    from tests.test_data_column_cast import _source_project
    from workbench.artifacts import sha256_file
    from workbench.agent.workflow_runtime_parts.operations import _execute_named_statistical_step
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    effect = _execute_named_statistical_step(root=project,
        draft=SimpleNamespace(target={"run_id":run_id}),
        lineage={"sha256":sha256_file(project / "runs" / run_id / "data.csv"),
                 "artifact_id":artifact_id, "node_ref":"stage:source"},
        step=SimpleNamespace(operation_id=operation_id, spec=spec, fingerprint="probe-original"), frame=frame)
    assert effect.payload["result"]["results"][0]["statistic"] == 11.5
    assert len(effect.artifact_ids) == 1


def test_new_column_parameter_cannot_read_an_undeclared_adapter_column(monkeypatch):
    operation_id = _probe(monkeypatch)
    from workbench.agent.workflow_capability_registry import workflow_capability_registry
    operation = workflow_capability_registry().require(operation_id)
    with pytest.raises(ValueError, match="contrast_column.*declared"):
        operation.validate({"operation_id":operation_id, "input_mode":"frame",
            "column_bindings":{"columns":["x", "y"]}, "options":{"contrast_column":"private"}})


def test_declared_parameters_reach_current_workflow_receipt_without_model_calls(tmp_path, monkeypatch):
    import json
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent.workflow_contracts import workflow_step_vocabulary

    operation_id = _probe(monkeypatch, named=False)
    fixture = _Fixture(tmp_path)
    published = workflow_step_vocabulary()["step_operations"][operation_id]
    assert "offset" in published["field_schemas"]["options"]["properties"]
    receipt = fixture.propose([{"step_id":"probe", "operation_id":operation_id,
        "spec":{"input_mode":"frame", "column_bindings":{"columns":["wage", "group"]},
                "options":{"offset":2.5, "contrast_column":"wage"}}}])
    assert receipt["executed"] and receipt["operation"]["status"] == "completed", receipt
    row = receipt["results"][0]["artifacts"][0]["result"]["results"][0]
    run_root = fixture.project_root / "runs" / fixture.run_id
    expected = float(pd.read_csv(run_root / "data.csv")["wage"].sum()) + 2.5
    assert row["statistic"] == expected
    [path] = (run_root / "artifacts" / "workflow_capability").glob("*test_extension_probe*.json")
    persisted = json.loads(path.read_text())
    assert persisted["request"]["options"] == {"offset":2.5, "contrast_column":"wage"}
