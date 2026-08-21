"""Gate 4/5 — Artifact Contract construction and post-execution validation.

Spec §5 and the §9.2 acceptance list, criterion by criterion.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.agent.notebook import (
    ArtifactContractEmpty,
    ArtifactNotDeclarable,
    ArtifactSchemaContractUnsupported,
    NotebookService,
    OptionDraft,
    TypedProposal,
    build_artifact_contract,
    validate_produced_artifacts,
)
from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from workbench.agent.trace import TraceWriter
from workbench.contracts.agent.notebook_option import ExpectedArtifact, RecommendationDecision
from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.run_family import bind_run_to_family
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)
from workbench.services.server_run_artifacts import (
    ServerOwnedArtifactManifestError,
    register_server_owned_run_artifact,
    read_server_owned_run_artifacts,
)

from tests.test_notebook_support import (
    make_project,
    make_run,
    model_rerun_proposal,
)

REQUIRED_PARAMETERS = ExpectedArtifact(
    artifact_id="ts.parameters", artifact_type="time_series_json", required=True, count=1
)
OPTIONAL_QQ = ExpectedArtifact(
    artifact_id="ts.chart.qq", artifact_type="time_series_json", required=False, count=1
)


def test_an_empty_artifact_contract_is_refused_before_persistence() -> None:
    with pytest.raises(ArtifactContractEmpty, match="at least one expected artifact"):
        build_artifact_contract([])


def _artifact(artifact_id: str, artifact_type: str = "time_series_json", step: str = "arma_garch"):
    return {"artifact_id": artifact_id, "artifact_type": artifact_type, "step": step}


def _register_server_artifacts(
    project: Path, run_id: str, records: list[dict]
) -> list[dict]:
    """Create the server-owned files and integrity-bound index records."""

    run_root = project / "runs" / run_id
    registered = []
    for record in records:
        artifact_id = str(record["artifact_id"])
        artifact_path = run_root / f"{artifact_id}.json"
        artifact_path.write_text("{}", encoding="utf-8")
        registered.append(
            register_server_owned_run_artifact(
                project,
                run_id,
                artifact_id=artifact_id,
                artifact_path=artifact_path,
                artifact_type=str(record["artifact_type"]),
                step=str(record["step"]),
                inputs=[],
            )
        )
    return registered


def test_server_owned_reader_rejects_a_non_object_artifact_index(tmp_path: Path) -> None:
    """Malformed compiler-owned state must become a typed completion refusal."""

    run_root = tmp_path / "runs" / "run_malformed"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ServerOwnedArtifactManifestError, match="unreadable"):
        read_server_owned_run_artifacts(tmp_path, "run_malformed", required=True)


# ----------------------------------------------------------------------
# §5.3 / §9.2 criterion 5 — schema_ref is refused, never ignored
# ----------------------------------------------------------------------


def test_a_contract_requesting_schema_ref_is_refused_at_build_time() -> None:
    with pytest.raises(ArtifactSchemaContractUnsupported) as excinfo:
        build_artifact_contract(
            [
                {
                    "artifact_id": "ts.parameters",
                    "artifact_type": "time_series_json",
                    "schema_ref": "https://example.invalid/params.json",
                }
            ]
        )

    assert excinfo.value.code == "ARTIFACT_SCHEMA_CONTRACT_UNSUPPORTED"
    assert excinfo.value.details["unsupported_fields"] == ["schema_ref"]


def test_an_option_declaring_schema_ref_is_never_stored(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")

    with pytest.raises(ArtifactSchemaContractUnsupported):
        service.propose_batch(
            notebook.notebook_id,
            context=service.compile_context(notebook.notebook_id),
            drafts=[
                OptionDraft(
                    rank=1,
                    rationale="r",
                    proposal=TypedProposal.from_dict(model_rerun_proposal("p1")),
                    expected_artifacts=(
                        {
                            "artifact_id": "ts.parameters",
                            "artifact_type": "time_series_json",
                            "schema_ref": "x",
                        },
                    ),
                )
            ],
        )

    assert service.list_options(notebook.notebook_id) == []


# ----------------------------------------------------------------------
# §5.4 — required may only name a published artifact
# ----------------------------------------------------------------------


def test_a_hallucinated_artifact_cannot_be_required() -> None:
    with pytest.raises(ArtifactNotDeclarable) as excinfo:
        build_artifact_contract(
            [{"artifact_id": "ts.chart.imaginary", "artifact_type": "figure", "required": True}]
        )

    assert excinfo.value.code == "ARTIFACT_REQUIRED_NOT_DECLARABLE"
    assert excinfo.value.details["artifact_id"] == "ts.chart.imaginary"


def test_a_hallucinated_artifact_may_still_be_optional() -> None:
    contract = build_artifact_contract(
        [{"artifact_id": "ts.chart.imaginary", "artifact_type": "figure", "required": False}]
    )

    assert contract.required_ids == ()
    assert contract.expected[0].artifact_id == "ts.chart.imaginary"


def test_requiring_a_declared_artifact_with_the_wrong_type_is_refused() -> None:
    with pytest.raises(ArtifactNotDeclarable) as excinfo:
        build_artifact_contract(
            [{"artifact_id": "ts.parameters", "artifact_type": "figure", "required": True}]
        )

    assert excinfo.value.details["declared_artifact_type"] == "time_series_json"


# ----------------------------------------------------------------------
# §5.5 / §9.2 criteria 1-4, 6 — the processing matrix
# ----------------------------------------------------------------------


def test_missing_required_artifact_fails_validation() -> None:
    contract = build_artifact_contract([REQUIRED_PARAMETERS])

    result = validate_produced_artifacts(contract, [_artifact("ts.final_model")])

    assert result["validation_status"] == "failed"
    codes = [issue["code"] for issue in result["issues"]]
    assert "ARTIFACT_REQUIRED_MISSING" in codes
    missing = [i for i in result["issues"] if i["code"] == "ARTIFACT_REQUIRED_MISSING"]
    assert missing[0]["artifact_id"] == "ts.parameters"


def test_wrong_artifact_type_fails_validation() -> None:
    contract = build_artifact_contract([REQUIRED_PARAMETERS])

    result = validate_produced_artifacts(
        contract, [_artifact("ts.parameters", artifact_type="figure")]
    )

    assert result["validation_status"] == "failed"
    issue = [i for i in result["issues"] if i["code"] == "ARTIFACT_TYPE_MISMATCH"][0]
    assert issue["expected_artifact_type"] == "time_series_json"
    assert issue["observed_artifact_types"] == ["figure"]


def test_missing_optional_artifact_passes_with_warnings() -> None:
    contract = build_artifact_contract([REQUIRED_PARAMETERS, OPTIONAL_QQ])

    result = validate_produced_artifacts(contract, [_artifact("ts.parameters")])

    assert result["validation_status"] == "passed_with_warnings"
    assert [i["code"] for i in result["issues"]] == ["ARTIFACT_OPTIONAL_MISSING"]


def test_an_extra_legal_artifact_passes_with_an_informational_issue() -> None:
    contract = build_artifact_contract([REQUIRED_PARAMETERS])

    result = validate_produced_artifacts(
        contract, [_artifact("ts.parameters"), _artifact("ts.chart.acf")]
    )

    assert result["validation_status"] == "passed"
    assert [i["code"] for i in result["issues"]] == ["ARTIFACT_UNDECLARED"]
    assert result["issues"][0]["artifact_id"] == "ts.chart.acf"


def test_a_wrong_step_fails_validation() -> None:
    contract = build_artifact_contract(
        [
            {
                "artifact_id": "ts.parameters",
                "artifact_type": "time_series_json",
                "required": True,
                "step": "model_fit",
            }
        ]
    )

    result = validate_produced_artifacts(
        contract, [_artifact("ts.parameters", step="data_audit")]
    )

    assert result["validation_status"] == "failed"
    assert {i["code"] for i in result["issues"]} == {
        "ARTIFACT_STEP_MISMATCH",
        "ARTIFACT_COUNT_MISMATCH",
    }


def test_the_report_always_names_what_was_and_was_not_checked() -> None:
    contract = build_artifact_contract([REQUIRED_PARAMETERS])

    result = validate_produced_artifacts(contract, [_artifact("ts.parameters")])

    assert result["contract_profile"] == "artifact-identity-type-count/v1"
    assert result["checked_dimensions"] == ["artifact_id", "artifact_type", "count", "step"]
    assert result["not_evaluated_dimensions"] == ["payload_schema"]
    assert result["validation_status"] == "passed"


def test_completion_projects_the_contract_without_hiding_ambient_artifacts(
    tmp_path: Path,
) -> None:
    """The option contract is narrow, while the durable run index stays complete."""

    project, service, notebook_id, option_id = _materialized_option(
        tmp_path, option_id="opt_ambient"
    )
    notebook = service.get_notebook(notebook_id)
    run_root = make_run(project, "run_ambient")
    ambient = _register_server_artifacts(
        project,
        "run_ambient",
        [
            _artifact("ts.parameters"),
            _artifact("ts.chart.acf"),
            _artifact("ts.chart.qq"),
            _artifact("ts.diagnostics"),
        ],
    )
    bind_run_to_family(run_root, run_family_id=notebook.run_family_id, bound_by="test")

    trace = TraceWriter(
        project,
        scope={
            "project_id": project.name,
            "notebook_id": notebook.notebook_id,
            "run_family_id": notebook.run_family_id,
        },
        versions={
            "app_commit": "test",
            "model_id": "test",
            "prompt_version": "test",
            "vocabulary_version": "test",
            "context_profile": "notebook-plan/v1",
        },
    )
    outcome = service.complete_execution(
        notebook_id,
        option_id,
        execution_status="succeeded",
        run_id="run_ambient",
        trace=trace,
    )

    assert outcome.validation_status == "passed"
    assert outcome.active_head_advanced is True
    assert outcome.artifact_validation_scope == {
        "mode": "contract_projection",
        "ambient_artifact_ids": [
            "ts.chart.acf",
            "ts.chart.qq",
            "ts.diagnostics",
            "ts.parameters",
        ],
        "ambient_artifact_count": 4,
    }
    assert not any(
        issue["code"] == "ARTIFACT_UNDECLARED"
        for issue in outcome.artifact_validation["issues"]
    )
    (option_view,) = service.list_options(notebook.notebook_id)
    persisted = option_view.execution_results[-1]
    assert persisted["artifact_validation_scope"] == outcome.artifact_validation_scope
    assert json.loads((run_root / "artifacts_index.json").read_text())["artifacts"] == ambient
    validation_events = [
        event
        for event in TraceWriter.replay(project, trace.trace_id)
        if event["event_type"] == "artifact_contract.validation.completed/v1"
    ]
    assert validation_events[-1]["payload"]["artifact_validation_scope"] == (
        outcome.artifact_validation_scope
    )


def test_explicit_produced_artifacts_keep_undeclared_detection(tmp_path: Path) -> None:
    """A caller-owned produced list remains strict and is not projected."""

    _, service, notebook_id, option_id = _materialized_option(
        tmp_path, option_id="opt_explicit"
    )
    outcome = service.complete_execution(
        notebook_id,
        option_id,
        execution_status="succeeded",
        produced_artifacts=[_artifact("ts.parameters"), _artifact("ts.chart.acf")],
    )

    assert outcome.validation_status == "passed"
    assert [issue["code"] for issue in outcome.artifact_validation["issues"]] == [
        "ARTIFACT_UNDECLARED"
    ]
    assert outcome.artifact_validation_scope["mode"] == "explicit_produced_artifacts"


def test_contract_projection_keeps_wrong_type_blocking(tmp_path: Path) -> None:
    """Narrowing the projection must not turn a wrong expected type into success."""

    project, service, notebook_id, option_id = _materialized_option(
        tmp_path, option_id="opt_wrong_type"
    )
    notebook = service.get_notebook(notebook_id)
    run_root = make_run(project, "run_wrong_type")
    _register_server_artifacts(
        project,
        "run_wrong_type",
        [
            _artifact("ts.parameters", artifact_type="figure"),
            _artifact("ts.chart.acf"),
        ],
    )
    bind_run_to_family(run_root, run_family_id=notebook.run_family_id, bound_by="test")

    outcome = service.complete_execution(
        notebook_id,
        option_id,
        execution_status="succeeded",
        run_id="run_wrong_type",
    )

    assert outcome.validation_status == "failed"
    assert outcome.active_head_advanced is False
    assert any(
        issue["code"] == "ARTIFACT_TYPE_MISMATCH"
        for issue in outcome.artifact_validation["issues"]
    )


# ----------------------------------------------------------------------
# §5.3 / §9.1 criterion 3 / §9.2 criterion 1 — the commit gate
# ----------------------------------------------------------------------


def _materialized_option(
    tmp_path: Path,
    *,
    option_id: str = "opt_contract",
) -> tuple[Path, NotebookService, str, str]:
    """Build the smallest server-owned, source-bound option for execution tests."""

    project = make_project(tmp_path)
    service = NotebookService(project)
    source_run = make_run(project, "run_source")
    source_run_hash = "a" * 64
    source_upload_sha = "upload-source"
    (source_run / "run_inputs.json").write_text(
        json.dumps(
            {
                "run_input_schema_version": 1,
                "upload": {"sha256": source_upload_sha},
                "form": {
                    "model_type": "ols",
                    "y": "outcome",
                    "x": "predictor",
                    "model_options": {},
                },
            }
        ),
        encoding="utf-8",
    )
    (source_run / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run_source",
                "mode": "manual",
                "status": "completed",
                "model_routing": {
                    "requested_model_type": "ols",
                    "effective_model_type": "ols",
                },
            }
        ),
        encoding="utf-8",
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id="run_source",
            nodes={
                "model:ols_1": Node(
                    id="model:ols_1",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-08-21T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    (source_run / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": source_run_hash, "cas_ref": {}}}),
        encoding="utf-8",
    )

    notebook = service.ensure_default_projection(from_run_id="run_source", created_by="test")
    request = NodeWriteOperationRequestV1(
        request_id="artifact-contract-test",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id="run_source",
        op_node_id="model:ols_1",
        node_hash=source_run_hash,
        forest_node_key=f"{source_run_hash}::model:ols_1",
        owner_resolution="single_candidate",
        active_head_run_id="run_source",
    )
    source_context_fingerprint = compute_context_fingerprint(project / "runs", request)
    context = service.compile_context(notebook.notebook_id)
    proposal = TypedProposal(
        proposal_id=f"proposal_{option_id}",
        proposal_revision=1,
        operation_id="model.rerun",
        operation_version="v1",
        target={
            "run_id": "run_source",
            "node_ref": "model:ols_1",
            "node_hash": source_run_hash,
            "forest_node_key": f"{source_run_hash}::model:ols_1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": source_context_fingerprint,
            "active_head_run_id": "run_source",
            "owner_resolution": "single_candidate",
        },
        changes={"model_options": {}},
    )
    decision = RecommendationDecision(
        recommendation_decision_id=f"decision_{option_id}",
        batch_id=f"batch_{option_id}",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=(option_id,),
        outcome="recommended",
        recommended_option_id=option_id,
        reason_refs=(),
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="server-owned typed artifact contract",
                proposal=proposal,
                expected_artifacts=(REQUIRED_PARAMETERS,),
                option_id=option_id,
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    assert revision.materializable is True
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="test",
    )
    service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    return project, service, notebook.notebook_id, revision.option_id


def _executed_notebook(tmp_path: Path, produced: list[dict]) -> tuple[NotebookService, str, str]:
    project, service, notebook_id, option_id = _materialized_option(tmp_path)
    notebook = service.get_notebook(notebook_id)
    child = make_run(project, "run_child")
    bind_run_to_family(child, run_family_id=notebook.run_family_id, bound_by="test")
    outcome = service.complete_execution(
        notebook_id,
        option_id,
        execution_status="succeeded",
        run_id="run_child",
        produced_artifacts=produced,
    )
    return service, notebook.notebook_id, outcome


def test_a_successful_run_missing_its_required_table_does_not_advance_the_head(
    tmp_path: Path,
) -> None:
    service, notebook_id, outcome = _executed_notebook(
        tmp_path, [_artifact("ts.final_model")]
    )

    assert outcome.execution_status == "succeeded"
    assert outcome.validation_status == "failed"
    assert outcome.active_head_advanced is False
    assert outcome.lifecycle_status == "selected"
    notebook = service.get_notebook(notebook_id)
    assert notebook.active_head_run_id == "run_source"
    assert notebook.last_attempt_run_id == "run_child"


def test_a_run_that_satisfies_the_contract_advances_the_head_and_pins_the_execution(
    tmp_path: Path,
) -> None:
    service, notebook_id, outcome = _executed_notebook(
        tmp_path, [_artifact("ts.parameters")]
    )

    assert outcome.validation_status == "passed"
    assert outcome.active_head_advanced is True
    assert outcome.lifecycle_status == "executed"
    notebook = service.get_notebook(notebook_id)
    assert notebook.active_head_run_id == "run_child"
    assert notebook.last_attempt_run_id is None
    # §9.1 criterion 12: an executed option can always be traced to its branch.
    (option_view,) = service.list_options(notebook_id)
    execution = option_view.execution_results[-1]
    assert execution["option_id"] == option_view.option_id
    assert execution["option_revision"] == 1
    assert execution["run_id"] == "run_child"
    assert execution["execution_status"] == "succeeded"
    assert execution["committed"] is True
    assert option_view.current_revision.typed_proposal_id == "proposal_opt_contract"
    assert option_view.current_revision.typed_proposal_revision == 1
    assert option_view.current_revision.generation_context_hash.startswith("sha256:")
    assert option_view.current_revision.freshness_dependency_fingerprint.startswith("fresh1:")
    assert option_view.current_revision.generation_context_hash != (
        option_view.current_revision.freshness_dependency_fingerprint
    )
