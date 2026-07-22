"""Gate 4/5 — Artifact Contract construction and post-execution validation.

Spec §5 and the §9.2 acceptance list, criterion by criterion.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from workbench.agent.notebook import (
    ArtifactNotDeclarable,
    ArtifactSchemaContractUnsupported,
    NotebookService,
    OptionDraft,
    TypedProposal,
    build_artifact_contract,
    validate_produced_artifacts,
)
from workbench.contracts.agent.notebook_option import ExpectedArtifact
from workbench.lineage.run_family import bind_run_to_family

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


def _artifact(artifact_id: str, artifact_type: str = "time_series_json", step: str = "arma_garch"):
    return {"artifact_id": artifact_id, "artifact_type": artifact_type, "step": step}


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


# ----------------------------------------------------------------------
# §5.3 / §9.1 criterion 3 / §9.2 criterion 1 — the commit gate
# ----------------------------------------------------------------------


def _executed_notebook(tmp_path: Path, produced: list[dict]) -> tuple[NotebookService, str, str]:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    context = service.compile_context(notebook.notebook_id)
    (option,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="r",
                proposal=TypedProposal.from_dict(model_rerun_proposal("p1")),
                expected_artifacts=(REQUIRED_PARAMETERS,),
            )
        ],
    )
    service.confirm(
        notebook.notebook_id,
        option.option_id,
        option_revision=1,
        proposal_id="p1",
        proposal_revision=1,
        context=service.compile_context(notebook.notebook_id),
    )
    child = make_run(project, "run_child")
    bind_run_to_family(child, run_family_id=notebook.run_family_id, bound_by="test")
    outcome = service.complete_execution(
        notebook.notebook_id,
        option.option_id,
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
    assert notebook.active_head_run_id is None
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
    execution = option_view.last_execution["execution"]
    assert execution["option_id"] == option_view.option_id
    assert execution["option_revision"] == 1
    assert execution["proposal_id"] == "p1"
    assert execution["proposal_revision"] == 1
    assert execution["freshness_dependency_fingerprint"] == (
        option_view.current_revision.freshness_dependency_fingerprint
    )
