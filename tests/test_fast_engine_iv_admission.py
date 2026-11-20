"""The experimental IV choice enters through the shared Genesis contract and draft."""
from __future__ import annotations

import pytest

from workbench.agent.workflow_contracts import GENESIS_RUN_LEVEL_FIELDS, genesis_run_params, validate_model_genesis_spec
from workbench.agent.workflow_contract_parts.validation import _validate_step_spec
from workbench.contracts.common.errors import OperationValidationError
from workbench.contracts.model.genesis_schema import model_genesis_parameters
from workbench.engine.capabilities import build_capabilities
from workbench.services.draft_materialization import _genesis_model_editor_schema


def spec(**changes):
    return {"model_family": "iv_2sls", "covariance": "robust", "iv_endog": ["d"], "iv_instruments": ["z"],
            "branches": [{"branch_id": "main", "outcome": "y", "predictors": ["w"]}], **changes}


def model_params(**changes):
    return {"model_type": "iv_2sls", "y": "y", "x": ["w"], "iv_endog": ["d"],
            "iv_instruments": ["z"], "covariance": "robust", **changes}


def test_shared_declaration_and_manual_schema_publish_the_same_optional_experimental_choice():
    declaration = model_genesis_parameters()
    assert "estimation_engine" in declaration["fields"]
    assert declaration["field_types"]["estimation_engine"] == "string"
    assert declaration["field_enums"]["estimation_engine"] == ("reference", "fast")
    assert "experimental" in declaration["fields"]["estimation_engine"].lower()
    assert "resource acceptance pending" in declaration["fields"]["estimation_engine"].lower()
    assert "estimation_engine" not in declaration["required"]
    manifest = build_capabilities()
    iv = next(item for item in manifest["model_types"] if item["key"] == "iv_2sls")
    control = next(item for item in iv["params"] if item["key"] == "estimation_engine")
    assert control["kind"] == "select" and control["value"] == "reference"
    assert control["options"] == ["reference", "fast"]
    assert "experimental" in control["label"].lower()
    _, controls = _genesis_model_editor_schema("iv_2sls", ("y", "w", "d", "z"))
    assert next(item for item in controls if item["key"] == "estimation_engine")["options"] == control["options"]


@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_fast_is_a_shared_run_parameter_for_single_and_multiple_model_branches(covariance):
    declaration = spec(estimation_engine="fast", covariance=covariance)
    declaration["branches"].append({"branch_id": "second", "outcome": "y", "predictors": []})
    _validate_step_spec("model.genesis", declaration)
    assert "estimation_engine" in GENESIS_RUN_LEVEL_FIELDS
    assert genesis_run_params(declaration) == {"estimation_engine": "fast"}


@pytest.mark.parametrize("choice", [None, "reference"])
def test_default_run_params_keep_the_engine_field_absent(choice):
    declaration = spec(**({"estimation_engine": choice} if choice is not None else {}))
    validate_model_genesis_spec(declaration)
    assert genesis_run_params(declaration) == {}


@pytest.mark.parametrize("changes", [
    {"model_family": "ols"}, {"covariance": "kernel"},
    {"branches": [{"branch_id": "main", "outcome": "y", "predictors": ["w"], "covariance": "kernel"}]},
])
def test_uncovered_fast_requests_are_rejected_by_the_common_agent_validator(changes):
    declaration = spec(estimation_engine="fast", **changes)
    if declaration["model_family"] == "ols":
        declaration.pop("iv_endog"); declaration.pop("iv_instruments")
    with pytest.raises(OperationValidationError, match="ESTIMATION_ENGINE_NOT_COVERED"):
        validate_model_genesis_spec(declaration)


def test_a_branch_cannot_override_or_hide_the_shared_engine_choice():
    declaration = spec()
    declaration["branches"][0]["estimation_engine"] = "fast"
    with pytest.raises(OperationValidationError, match="whole.*step"):
        validate_model_genesis_spec(declaration)


@pytest.mark.parametrize("choice", ["turbo", False, None])
def test_malformed_engine_values_do_not_disappear_during_materialization(choice):
    with pytest.raises(OperationValidationError, match="ESTIMATION_ENGINE"):
        validate_model_genesis_spec(spec(estimation_engine=choice))


def test_native_family_projection_preserves_the_shared_choice_and_validates_it():
    from workbench.services.draft_service import _project_native_family_params_for_execution

    assert _project_native_family_params_for_execution({}, model_params(estimation_engine="fast"))["estimation_engine"] == "fast"
    from fastapi import HTTPException
    with pytest.raises(HTTPException, match="ESTIMATION_ENGINE_NOT_COVERED"):
        _project_native_family_params_for_execution({}, model_params(estimation_engine="fast", covariance="kernel"))


def test_an_engine_edit_changes_the_workflow_plan_identity():
    from workbench.agent.workflow import compile_workflow

    def compile(choice):
        declaration = spec(**({"estimation_engine": choice} if choice else {}))
        return compile_workflow(workflow_id="wf", target={"run_id": "run", "node_ref": "stage:cleaned", "artifact_id": "cleaned_dataset"},
                                preconditions={"context_fingerprint": "source"},
                                steps=[{"step_id": "fit", "operation_id": "model.genesis", "spec": declaration}],
                                available_columns=["y", "w", "d", "z"])
    default, fast = compile(None), compile("fast")
    assert default.plan_fingerprint != fast.plan_fingerprint
    assert fast.steps[0].spec["estimation_engine"] == "fast"


def test_sensitivity_reproduces_the_chosen_engine_instead_of_losing_the_primary(tmp_path):
    import json
    from workbench.agent.completion_sensitivity import primary_specification

    run = tmp_path / "runs/run"
    run.mkdir(parents=True)
    (run / "run_inputs.json").write_text(json.dumps({"form": model_params(estimation_engine="fast")}))
    reproduced = primary_specification(tmp_path, "run")
    assert reproduced is not None
    assert reproduced[0]["estimation_engine"] == "fast"


def prepare_draft(tmp_path):
    from workbench.lineage.pipeline_drafts import PipelineDraftStore
    from workbench.lineage.upload_store import store_upload_bytes
    from workbench.projects import create_project
    from workbench.services.draft_materialization import create_genesis_draft

    root = create_project(tmp_path, "engine-admission").root
    digest = store_upload_bytes(root, b"y,w,d,z\n1,2,3,4\n2,3,4,5\n", filename="iv.csv")
    stored = create_genesis_draft(root, upload_sha256=digest, filename="iv.csv", sheet_names=(),
                                 columns=("y", "w", "d", "z"), model_params=model_params())
    store = PipelineDraftStore(root)
    stored = store.update_node_params(stored.draft["draft_id"], "table_1", {"transpose": False})
    stored = store.update_node_params(stored.draft["draft_id"], "model_1", model_params())
    return root, store, stored


def test_manual_draft_rejects_uncovered_fast_covariance_before_confirmation(tmp_path):
    from workbench.lineage.pipeline_drafts import DraftValidationFailure
    _, store, stored = prepare_draft(tmp_path)
    with pytest.raises(DraftValidationFailure, match="ESTIMATION_ENGINE_NOT_COVERED"):
        store.update_node_params(stored.draft["draft_id"], "model_1", {"estimation_engine": "fast", "covariance": "kernel"})


def test_uncovered_fast_save_keeps_the_explanation_and_correction_in_the_existing_error_path(tmp_path):
    from workbench.lineage.pipeline_drafts import DraftValidationFailure
    from workbench.estimation_engine.iv import COVERED_COVARIANCES

    _, store, stored = prepare_draft(tmp_path)
    with pytest.raises(DraftValidationFailure) as refused:
        store.update_node_params(stored.draft["draft_id"], "model_1", {"estimation_engine": "fast", "covariance": "hac"})
    message = str(refused.value)
    assert message.startswith("ESTIMATION_ENGINE_NOT_COVERED:")
    assert all(covariance in message for covariance in COVERED_COVARIANCES)
    assert "Choose reference" in message
    from workbench.http.drafts_routes import _draft_http_error
    http_error = _draft_http_error(refused.value)
    assert http_error.status_code == 422 and http_error.detail == message


def test_existing_non_engine_draft_errors_keep_their_code_only_contract(tmp_path):
    from workbench.lineage.pipeline_drafts import DraftValidationFailure

    _, store, stored = prepare_draft(tmp_path)
    with pytest.raises(DraftValidationFailure) as refused:
        store.update_node_params(stored.draft["draft_id"], "model_1", {"unknown_setting": "x"})
    assert str(refused.value) == "NON_EDITABLE_PARAM"


def test_manual_unknown_branch_field_is_rejected_before_engine_semantics(tmp_path):
    from workbench.lineage.pipeline_drafts import DraftValidationFailure

    _, store, stored = prepare_draft(tmp_path)
    with pytest.raises(DraftValidationFailure, match="^NON_EDITABLE_PARAM$"):
        store.update_node_params(stored.draft["draft_id"], "model_1", {"branches": 1, "estimation_engine": "fast"})


def test_engine_edit_invalidates_a_previously_validated_draft_hash(tmp_path):
    from fastapi import HTTPException
    from workbench.services.draft_service import execute_genesis_draft

    root, store, before = prepare_draft(tmp_path)
    after = store.update_node_params(before.draft["draft_id"], "model_1", {"estimation_engine": "fast"})
    assert after.draft_hash != before.draft_hash
    with pytest.raises(HTTPException, match="VALIDATED_DRAFT_HASH_MISMATCH"):
        execute_genesis_draft(after.draft["draft_id"], root, store, after,
                              validated_draft_hash=before.draft_hash, execution_mode="genesis", idempotency_key=None)
    assert list((root / "runs").iterdir()) == []


def test_auto_model_selector_cannot_defer_an_uncovered_fast_choice_until_execution():
    from workbench.agent.workflow_contract_parts.validation import _validate_auto_workflow_spec

    with pytest.raises(OperationValidationError, match="ESTIMATION_ENGINE_NOT_COVERED"):
        _validate_auto_workflow_spec("model.auto", {"estimation_engine": "fast", "branches": spec()["branches"]})


@pytest.mark.parametrize("family", ["iv_2sls", "auto"])
def test_existing_branch_list_validation_precedes_engine_semantics(family):
    from workbench.agent.workflow_contract_parts.validation import _validate_auto_workflow_spec

    with pytest.raises(OperationValidationError, match="non-empty branches list"):
        if family == "auto":
            _validate_auto_workflow_spec("model.auto", {"branches": 1})
        else:
            validate_model_genesis_spec(spec(branches=1))


@pytest.mark.parametrize("engine", [None, "fast"])
def test_the_shared_genesis_dispatch_preserves_the_choice_and_dispatches_only_once(tmp_path, monkeypatch, engine):
    import json
    from types import SimpleNamespace
    from workbench.services import draft_service

    root, store, stored = prepare_draft(tmp_path)
    if engine:
        stored = store.update_node_params(stored.draft["draft_id"], "model_1", {"estimation_engine": engine})
    calls = []
    def submit(project, *, form, before_dispatch, **kwargs):
        calls.append(dict(form))
        run_root = project / "runs/one-dispatch"
        run_root.mkdir()
        (run_root / "run_inputs.json").write_text(json.dumps({"form": form}))
        before_dispatch("one-dispatch")
        return {"run_id": "one-dispatch"}
    monkeypatch.setattr(draft_service, "_submit_run", submit)
    monkeypatch.setattr(draft_service, "get_event_manager", lambda: SimpleNamespace(try_acquire_slot=lambda: True))
    def execute():
        return draft_service.execute_genesis_draft(stored.draft["draft_id"], root, store, stored,
            validated_draft_hash=stored.draft_hash, execution_mode="genesis", idempotency_key=None)
    first, repeat = execute(), execute()
    assert first["run_id"] == repeat["run_id"] == "one-dispatch" and repeat["deduped"] is True
    assert len(calls) == 1
    if engine:
        assert calls[0]["estimation_engine"] == engine
    else:
        assert "estimation_engine" not in calls[0]
    snapshot = json.loads((root / "runs/one-dispatch/executed_pipeline_draft.json").read_text())
    assert snapshot["execution_request"]["validated_draft_hash"] == stored.draft_hash


def test_single_model_agent_materialization_uses_the_same_run_level_choice(tmp_path):
    from workbench.agent.notebook import NotebookService
    from workbench.agent.notebook.materialization import NotebookOptionMaterializer
    from workbench.lineage.upload_store import store_upload_bytes
    from workbench.projects import create_project

    root = create_project(tmp_path, "agent-engine").root
    digest = store_upload_bytes(root, b"y,w,d,z\n1,2,3,4\n2,3,4,5\n", filename="iv.csv")
    service = NotebookService(root)
    notebook = service.ensure_default_projection(dataset={"kind": "dataset", "upload_sha256": digest,
        "filename": "iv.csv", "sheet_names": []}, created_by="ui")
    stored = NotebookOptionMaterializer(service)._materialize_dataset(notebook,
        {"operation_id": "model.genesis", "target": {"dataset_source_id": digest},
         "changes": {"model_params": model_params(estimation_engine="fast")}},
        {"notebook_id": notebook.notebook_id, "option_id": "iv-engine", "option_revision": "1"})
    model = next(node for node in stored.draft["graph"]["nodes"] if node["node_type"] == "model")
    assert model["params"]["estimation_engine"] == "fast"
    assert list((root / "runs").iterdir()) == []


@pytest.mark.parametrize("mode", ["ASK", "AUTO"])
def test_engine_choice_preserves_the_permission_class_and_budget(mode):
    from workbench.agent.permissions import Mode, Outcome, PermissionClass, decide, request_for_operation

    def request(engine=None):
        declaration = spec(**({"estimation_engine": engine} if engine else {}))
        return request_for_operation("operation.multi_step", {"steps": [
            {"operation_id": "model.genesis", "spec": declaration}]}, within_budget=False)
    default, fast = request(), request("fast")
    assert default == fast and len(fast.components) == 1 and fast.permission_class == PermissionClass.HIGH
    assert decide(Mode[mode], fast).outcome == Outcome.ASK


def test_a_changed_engine_requires_a_new_proposal_fingerprint_and_one_bound_approval(tmp_path):
    from workbench.agent.proposals import ProposalConfirmationError, ProposalStore
    from workbench.operation_approvals import OperationApprovalStore

    store = ProposalStore(tmp_path)
    first = store.create(session_id="session", chain_id="chain", operation_id="model.genesis",
        target={"dataset_source_id": "source"}, preconditions={}, changes={"model_params": model_params()},
        evidence_refs=[], expected_effect=[], risks=[])
    changed = store.revise(first.proposal_id, base_revision=first.revision,
        changes={"model_params": model_params(estimation_engine="fast")})
    assert changed.fingerprint != first.fingerprint
    with pytest.raises(ProposalConfirmationError, match="fingerprint"):
        store.confirm(changed.proposal_id, revision=changed.revision, fingerprint=first.fingerprint,
            actor_type="user", current_context_fingerprint=None, current_active_head_run_id=None)
    confirmed = store.confirm(changed.proposal_id, revision=changed.revision, fingerprint=changed.fingerprint,
        actor_type="user", current_context_fingerprint=None, current_active_head_run_id=None)
    approvals = OperationApprovalStore(tmp_path)
    first_approval = approvals.issue(confirmed)
    assert approvals.issue(confirmed) == first_approval
    assert first_approval["fingerprint"] == changed.fingerprint
    assert len(list((tmp_path / "operation-approvals").glob("*.jsonl"))) == 1
