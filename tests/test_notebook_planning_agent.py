"""Typed provider loop tests with deterministic fake adapters."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator

import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord, InspectionRequest
from workbench.contracts.agent.notebook_option import ExpectedArtifact
from workbench.agent.notebook.planning_agent import (
    NOTEBOOK_TOOLS,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    NotebookPlanningTimeout,
    NotebookPlanningUnavailable,
    _canonicalize_provider_option_batch,
    _parse_submissions,
    _submission,
    _strict_typed_proposal,
)
from workbench.agent.notebook.producer import (
    generate_option_batch,
    option_drafts_from_submissions,
)
from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.notebook.store import ProjectionSource, WorkflowSource
from workbench.agent.context_compiler import (
    attach_domain_memory_projection,
    compile_notebook_planning_context,
)
from workbench.agent.context_compiler import freshness_dependency_fingerprint
from workbench.agent.notebook.proposal import TypedProposal
from workbench.agent.notebook.recommendation import (
    RecommendationValidationError,
    RecommendationValidator,
)
from workbench.contracts.agent.notebook_option import MemoryDefaultSource
from workbench.agent.workflow_contracts import validate_workflow_steps
from tests.test_notebook_support import make_project


def _context(
    project: Path,
    *,
    active_head_run_id: str | None = None,
    projection_source: dict | None = None,
):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_plan",
        run_family_id="family_plan",
        active_head_run_id=active_head_run_id,
        analysis_contract={"revision": 1, "target": "y"},
        available_capabilities=["time_series.ets"],
        projection_source=projection_source,
    )


def _evidence() -> DataEvidencePackV1:
    return DataEvidencePackV1(
        source_id="run:run_001",
        records=(
            EvidenceRecord(
                evidence_id="evidence:time",
                inspection_id="time_index.v1",
                source_refs=("time_index:run_001",),
                protocol_version="time-index/v1",
                status="completed",
                observations={
                    "candidate_column": "when",
                    "columns": [{"name": "outcome"}, {"name": "treatment"}],
                },
                result_hash="sha256:time-result",
            ),
        ),
    )


def _complete_baseline_evidence() -> DataEvidencePackV1:
    records = []
    for inspection_id in ("profile.v1", "quality.v1", "time_index.v1", "sample.v1"):
        evidence_id = "evidence:time" if inspection_id == "time_index.v1" else f"evidence:{inspection_id}"
        result_hash = "sha256:time-result" if inspection_id == "time_index.v1" else f"sha256:{inspection_id}"
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                inspection_id=inspection_id,
                source_refs=(f"{inspection_id}:run_001",),
                protocol_version=f"{inspection_id}/v1",
                status="completed",
                observations=(
                    {"columns": [{"name": "when"}, {"name": "outcome"}]}
                    if inspection_id in {"profile.v1", "sample.v1"}
                    else {}
                ),
                result_hash=result_hash,
            )
        )
    return DataEvidencePackV1(source_id="run:run_001", records=tuple(records))


def _submit_call(*, capability_id: str = "time_series.ets", run_id: str = "notebook:nb_plan") -> dict:
    return {
        "options": [
            {
                "rank": 1,
                "rationale": "The time index supports this registered path.",
                "assumptions": ["time semantics remain unchanged"],
                "capability_id": capability_id,
                "option_id": "opt_ets",
                "proposal": {
                    "proposal_id": "prop_ets",
                    "proposal_revision": 1,
                    "operation_id": "model.rerun",
                    "operation_version": "v1",
                    "target": {
                        "run_id": run_id,
                        "node_ref": "stage:model",
                        "node_hash": "node-hash",
                        "forest_node_key": "forest-node-key",
                    },
                    "preconditions": {
                        "context_version": "node-operation-context/v1",
                        "context_fingerprint": "nocv1:test",
                        "active_head_run_id": run_id,
                        "owner_resolution": "single_candidate",
                    },
                    "changes": {"model_options": {"model_type": "ets"}},
                },
                "expected_artifacts": [
                    {
                        "artifact_id": "ets_1",
                        "artifact_type": "model_result",
                        "required": True,
                        "count": 1,
                        "step": None,
                    }
                ],
                "evidence_refs": [
                    {"evidence_id": "evidence:time", "result_hash": "sha256:time-result", "source_refs": ["time_index:run_001"]}
                ],
                "comparative_claims": ["evidence:time supports the path"],
            }
        ]
    }


def _pinned_rerun_submit_call(context) -> dict:
    """Return the generic submit fixture with its server-published pin."""

    pins = NotebookPlanningAgent._execution_pins(context)["rerun_preconditions_by_target"]
    assert len(pins) == 1
    call = _submit_call(run_id=str(context.active_head_run_id))
    proposal = call["options"][0]["proposal"]
    proposal["target"] = pins[0]["target"]
    proposal["preconditions"] = pins[0]["preconditions"]
    return call


class SequencedAdapter:
    def __init__(self, submit_args: dict) -> None:
        self.submit_args = submit_args
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "inspect-1",
                    "tool_id": "request_notebook_inspections",
                    "arguments": {
                        "requests": [
                            {"inspection_id": "time_index.v1", "target_ref": "run:active", "arguments": {"max_rows": 10}, "why_needed": "validate index"}
                        ]
                    },
                },
            )
        else:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {"tool_call_id": "submit-1", "tool_id": "submit_notebook_option_batch", "arguments": self.submit_args},
            )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class ScriptedAdapter:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        call = self.calls[min(len(self.requests) - 1, len(self.calls) - 1)]
        yield ModelStreamEvent.tool_call_delta(request.request_id, call)
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class NoNamedToolChoiceAdapter(ScriptedAdapter):
    supports_named_tool_choice = False


class FailingAdapter:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.from_error(request.request_id, "provider_unavailable")


class TextOnlyAdapter:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.text_delta(request.request_id, "use ETS")
        yield ModelStreamEvent.done(request.request_id)


def test_provider_plan_runs_registered_inspection_then_submits_batch(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    evidence = _evidence()
    adapter = SequencedAdapter(_submit_call())
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: evidence,
    )

    result = agent.plan(context=_context(project), initial_evidence=DataEvidencePackV1("run:run_001", ()))

    assert result.inspection_requests[0].inspection_id == "time_index.v1"
    assert len(result.option_drafts) == 1
    assert [tool["tool_id"] for tool in adapter.requests[0].tools] == [tool["tool_id"] for tool in NOTEBOOK_TOOLS]
    planning_payload = json.loads(adapter.requests[0].messages[1]["content"])
    planning_context = planning_payload["context"]
    assert planning_payload["evidence_citation_policy"] == {
        "completed_evidence_refs": [],
        "non_citable_evidence": [],
    }
    assert planning_context["generation_context_hash"].startswith("sha256:")
    assert planning_context["freshness_dependency_fingerprint"].startswith("fresh1:")
    assert planning_context["execution_pins"]["rerun_preconditions"]["context_version"] == "node-operation-context/v1"
    assert planning_context["typed_operation_contracts"]["model.genesis"]["changes_allowed_fields"] == [
        "table_params",
        "model_params",
        "model_options",
    ]
    recipe_payload = planning_payload["capability_catalog"]["time_series.ets"][
        "recipe_contract"
    ]
    assert recipe_payload["recipe_id"] == "time_series.ets"
    assert recipe_payload["required_inputs"] == ["time_column", "value_column"]
    assert recipe_payload["expected_artifacts"] == {"ets_1": "model_result"}
    assert recipe_payload["result_projection"] == "forecast_summary"
    assert recipe_payload["parameter_vocabulary"]["owner_contract"] == "time_series.ets@v1"
    assert "Comparative claims are bound by the option's structured evidence_refs" in adapter.requests[0].messages[0]["content"]
    assert "Treat completed evidence already supplied in the initial Evidence Pack as sufficient" in adapter.requests[0].messages[0]["content"]
    assert "completed evidence refs" in adapter.requests[0].messages[0]["content"]
    assert "dataset_source_id" in adapter.requests[0].messages[0]["content"]
    assert "execution_pins" in adapter.requests[0].messages[0]["content"]
    assert "automatically materializes residuals_vs_<predictor>" in adapter.requests[0].messages[0]["content"]
    assert "do not claim that a separate scatter step is required" in adapter.requests[0].messages[0]["content"]
    assert "only when the current context includes an eligible approved memory default" in (
        adapter.requests[0].messages[0]["content"]
    )
    assert "Every time-series Recipe must explicitly set" not in (
        adapter.requests[0].messages[0]["content"]
    )
    assert len(adapter.requests) == 2


def test_complete_baseline_evidence_forces_direct_typed_submission_turn(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "submit-first",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            }
        ]
    )

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_complete_baseline_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert [tool["tool_id"] for tool in adapter.requests[0].tools] == [
        "submit_notebook_option_batch"
    ]
    assert adapter.requests[0].model_config == {
        "tool_choice": {
            "type": "function",
            "function": {"name": "submit_notebook_option_batch"},
        }
    }


def test_complete_baseline_evidence_respects_provider_tool_choice_capability(tmp_path: Path) -> None:
    adapter = NoNamedToolChoiceAdapter(
        [
            {
                "tool_call_id": "submit-first",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            }
        ]
    )

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_complete_baseline_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert [tool["tool_id"] for tool in adapter.requests[0].tools] == [
        "submit_notebook_option_batch"
    ]
    assert adapter.requests[0].model_config == {}


def test_action_mode_publishes_and_enforces_one_checked_draft_path(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    adapter = SequencedAdapter(_submit_call())
    context = replace(
        _context(project),
        user_focus={"goal": "Fit the declared model.", "interaction_mode": "action"},
    )

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda _requests, _current: _evidence(),
    ).plan(context=context, initial_evidence=DataEvidencePackV1("run:run_001", ()))

    submit_tool = next(
        tool
        for tool in adapter.requests[0].tools
        if tool["tool_id"] == "submit_notebook_option_batch"
    )
    assert submit_tool["input_schema"]["properties"]["options"]["maxItems"] == 1
    assert "Action mode" in adapter.requests[0].messages[0]["content"]
    assert len(result.option_drafts) == 1


def test_run_notebook_publishes_and_accepts_one_source_pinned_composed_workflow(
    tmp_path: Path,
) -> None:
    """A Notebook must expose the same declared-term workflow the runtime owns."""

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_source"),
        bounded_lineage=[
            {
                "node_id": "stage:raw",
                "kind": "dataset_stage",
                "stage": "source",
                "artifact_id": "_uploads/source.csv",
                "workflow_artifact_id": "raw_source_csv",
                "context_fingerprint": "nocv1:workflow-source",
            }
        ],
    )
    workflow = NotebookPlanningAgent._typed_operation_contracts(context)[
        "operation.multi_step"
    ]
    assert workflow["target_exact"] == {
        "run_id": "run_source",
        "node_ref": "stage:raw",
        "artifact_id": "raw_source_csv",
    }

    evidence = DataEvidencePackV1(
        source_id="run:run_source",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:run_source",),
                protocol_version="profile/v1",
                status="completed",
                observations={
                    "columns": [
                        {"name": "response"},
                        {"name": "exposure"},
                        {"name": "stratum"},
                    ]
                },
                result_hash="sha256:profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "Fit declared categorical and quadratic terms in one reviewable workflow.",
            "assumptions": [],
            "capability_id": "ols",
            "option_id": "opt_composed",
            "proposal": {
                "proposal_id": "prop_composed",
                "proposal_revision": 1,
                "operation_id": "operation.multi_step",
                "operation_version": "v1",
                "target": workflow["target_exact"],
                "preconditions": workflow["preconditions_exact"],
                "changes": {
                    "steps": [
                        {
                            "step_id": "estimate",
                            "operation_id": "model.genesis",
                            "spec": {
                                "model_family": "ols",
                                "covariance": "unadjusted",
                                "branches": [
                                    {
                                        "branch_id": "linear",
                                        "outcome": "response",
                                        "predictors": ["exposure"],
                                    },
                                    {
                                        "branch_id": "curved",
                                        "outcome": "response",
                                        "predictors": ["exposure"],
                                        "categorical": ["stratum"],
                                        "polynomials": [
                                            {"column": "exposure", "degree": 2}
                                        ],
                                    }
                                ],
                            },
                        },
                        {
                            "step_id": "test_quadratic",
                            "operation_id": "model.joint_f_test",
                            "depends_on": ["estimate"],
                            "spec": {
                                "branch_id": "curved",
                                "term_selectors": [
                                    {"kind": "polynomial", "column": "exposure"}
                                ],
                            },
                        },
                        {
                            "step_id": "stationary_point",
                            "operation_id": "model.quadratic_stationary_point",
                            "depends_on": ["estimate"],
                            "spec": {"branch_id": "curved", "column": "exposure"},
                        },
                    ]
                },
            },
            "expected_artifacts": [],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:profile",
                    "source_refs": ["profile:run_source"],
                }
            ],
            "comparative_claims": [
                "evidence:profile confirms the declared source columns."
            ],
        }
    )
    agent = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(),
        capability_catalog={"ols": {"model_type": "ols"}},
    )

    normalized = agent._validate_submissions(
        context, evidence, (submission,), {"ols": {"model_type": "ols"}}
    )
    draft = option_drafts_from_submissions(context, normalized)[0]

    # A composed workflow creates one independently registered primary model
    # result per declared branch.  The server owns this count and the registry
    # step label; a provider cannot make a healthy workflow fail by guessing
    # either from its human workflow step id.
    assert draft.expected_artifacts == (
        ExpectedArtifact(
            artifact_id="ols_1",
            artifact_type="model_result",
            required=True,
            count=2,
            step=None,
        ),
    )


def test_composed_workflow_derives_artifacts_from_each_declared_model_family(
    tmp_path: Path,
) -> None:
    """A comparison workflow is admitted from its model steps, not one outer label."""

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_source"),
        bounded_lineage=[
            {
                "node_id": "stage:raw",
                "kind": "dataset_stage",
                "stage": "source",
                "artifact_id": "_uploads/source.csv",
                "workflow_artifact_id": "raw_source_csv",
                "context_fingerprint": "nocv1:mixed-workflow-source",
            }
        ],
    )
    workflow = NotebookPlanningAgent._typed_operation_contracts(context)[
        "operation.multi_step"
    ]
    evidence = DataEvidencePackV1(
        source_id="run:run_source",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:run_source",),
                protocol_version="profile/v1",
                status="completed",
                observations={
                    "columns": [
                        {"name": "response"},
                        {"name": "exposure"},
                        {"name": "firm"},
                        {"name": "year"},
                    ]
                },
                result_hash="sha256:mixed-profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "Compare two declared, reviewable estimators over the same source.",
            "assumptions": [],
            "capability_id": "panel_ols",
            "option_id": "opt_mixed_models",
            "proposal": {
                "proposal_id": "prop_mixed_models",
                "proposal_revision": 1,
                "operation_id": "operation.multi_step",
                "operation_version": "v1",
                "target": workflow["target_exact"],
                "preconditions": workflow["preconditions_exact"],
                "changes": {
                    "steps": [
                        {
                            "step_id": "estimate_panel",
                            "operation_id": "model.genesis",
                            "spec": {
                                "model_family": "panel_ols",
                                "covariance": "clustered",
                                "entity_col": "firm",
                                "time_col": "year",
                                "branches": [
                                    {
                                        "branch_id": "within",
                                        "outcome": "response",
                                        "predictors": ["exposure"],
                                    }
                                ],
                            },
                        },
                        {
                            "step_id": "estimate_dummy_fe",
                            "operation_id": "model.genesis",
                            "spec": {
                                "model_family": "ols",
                                "covariance": "robust",
                                "branches": [
                                    {
                                        "branch_id": "dummy_fe",
                                        "outcome": "response",
                                        "predictors": ["exposure"],
                                        "categorical": ["firm", "year"],
                                    }
                                ],
                            },
                        },
                    ]
                },
            },
            "expected_artifacts": [],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:mixed-profile",
                    "source_refs": ["profile:run_source"],
                }
            ],
            "comparative_claims": [
                "evidence:profile confirms the declared source columns."
            ],
        }
    )
    catalog = {
        "ols": {"model_type": "ols"},
        "panel_ols": {"model_type": "panel_ols"},
    }
    agent = NotebookPlanningAgent(adapter=TextOnlyAdapter(), capability_catalog=catalog)

    normalized = agent._validate_submissions(context, evidence, (submission,), catalog)

    assert normalized[0].expected_artifacts == (
        ExpectedArtifact("ols_1", "model_result", required=True, count=1, step=None),
        ExpectedArtifact("panel_ols_1", "model_result", required=True, count=1, step=None),
    )


def test_workflow_capability_id_must_name_its_model_capability(tmp_path: Path) -> None:
    """The workflow tool is an operation; ``capability_id`` stays a model pack."""

    source = ProjectionSource(
        kind="dataset",
        upload_sha256="a" * 64,
        filename="source.csv",
        workflow_source=WorkflowSource(
            run_id="run_source",
            node_ref="stage:raw",
            artifact_id="raw-source.csv",
            source_sha256="b" * 64,
        ),
    )
    context = _context(make_project(tmp_path), projection_source=source.to_dict())
    workflow = NotebookPlanningAgent._typed_operation_contracts(context)[
        "operation.multi_step"
    ]
    submission = _submission(
        {
            "rank": 1,
            "rationale": "Use the declared workflow entry point.",
            "assumptions": [],
            "capability_id": "operation.multi_step",
            "option_id": "opt_wrong_capability_id",
            "proposal": {
                "proposal_id": "prop_wrong_capability_id",
                "proposal_revision": 1,
                "operation_id": "operation.multi_step",
                "operation_version": "v1",
                "target": workflow["target_exact"],
                "preconditions": workflow["preconditions_exact"],
                "changes": {"steps": []},
            },
            "expected_artifacts": [],
            "evidence_refs": [],
            "comparative_claims": [],
        }
    )
    agent = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(),
        capability_catalog={"ols": {"model_type": "ols"}},
    )

    with pytest.raises(NotebookPlanningContractError, match="must name a server-published") as caught:
        agent._validate_submissions(
            context,
            DataEvidencePackV1("dataset:source", ()),
            (submission,),
            {"ols": {"model_type": "ols"}},
        )

    correction = agent._correction_instruction(
        error=caught.value,
        context=context,
        evidence=DataEvidencePackV1("dataset:source", ()),
        correction_number=1,
    )
    assert "not an operation id" in correction
    assert "time_series.ets" in correction


def test_workflow_dependency_shape_error_gets_a_machine_actionable_correction(
    tmp_path: Path,
) -> None:
    """A provider must be told the exact list shape, not merely that a plan failed."""

    context = _context(make_project(tmp_path))
    correction = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "typed proposal failed registry validation: workflow step estimate depends_on "
            "must be step ids"
        ),
        context=context,
        evidence=DataEvidencePackV1("run:run_001", ()),
        correction_number=1,
    )

    assert "JSON array" in correction
    assert "[\"source_step\"]" in correction
    assert "omit depends_on" in correction
    assert "Never use a string, object, branch_id, or artifact id" in correction


def test_workflow_dependency_shape_distinguishes_omitted_empty_and_invalid_string() -> None:
    """No dependency and an empty dependency list are valid but not conflated with a string."""

    base = {
        "step_id": "profile",
        "operation_id": "statistical.explore",
        "spec": {"operation": "summarize", "selected_columns": ["outcome"]},
    }
    explicit_empty = {
        "step_id": "detail",
        "operation_id": "statistical.explore",
        "depends_on": [],
        "spec": {"operation": "summarize_detail", "selected_columns": ["outcome"]},
    }

    omitted = validate_workflow_steps([base])
    empty = validate_workflow_steps([explicit_empty])

    assert omitted[0]["depends_on"] == []
    assert empty[0]["depends_on"] == []
    with pytest.raises(OperationValidationError, match="depends_on must be step ids"):
        validate_workflow_steps([{**explicit_empty, "depends_on": "profile"}])


def test_provider_gets_workflow_step_envelope_correction_after_misplaced_spec_fields(
    tmp_path: Path,
) -> None:
    """A composed workflow must correct parameters misplaced beside ``spec``.

    The step envelope is shared by every workflow operation.  This regression
    protects the Provider correction loop without teaching it about a
    particular dataset, model, or exercise.
    """

    source = ProjectionSource(
        kind="dataset",
        upload_sha256="a" * 64,
        filename="source.csv",
        workflow_source=WorkflowSource(
            run_id="run_source",
            node_ref="stage:raw",
            artifact_id="raw-source.csv",
            source_sha256="b" * 64,
        ),
    )
    context = _context(make_project(tmp_path), projection_source=source.to_dict())
    workflow = NotebookPlanningAgent._typed_operation_contracts(context)[
        "operation.multi_step"
    ]
    evidence = DataEvidencePackV1(
        source_id="dataset:source",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:source",),
                protocol_version="profile/v1",
                status="completed",
                observations={
                    "columns": [
                        {"name": "response"},
                        {"name": "exposure"},
                    ]
                },
                result_hash="sha256:profile",
            ),
        ),
    )
    option = {
        "rank": 1,
        "rationale": "Estimate a bounded, reviewable source-pinned model.",
        "assumptions": [],
        "capability_id": "ols",
        "option_id": "opt_workflow",
        "proposal": {
            "proposal_id": "prop_workflow",
            "proposal_revision": 1,
            "operation_id": "operation.multi_step",
            "operation_version": "v1",
            "target": workflow["target_exact"],
            "preconditions": workflow["preconditions_exact"],
            "changes": {
                "steps": [
                    {
                        "step_id": "estimate",
                        "operation_id": "model.genesis",
                        "spec": {
                            "model_family": "ols",
                            "branches": [
                                {
                                    "branch_id": "primary",
                                    "outcome": "response",
                                    "predictors": ["exposure"],
                                }
                            ],
                        },
                    }
                ]
            },
        },
        "expected_artifacts": [
            {
                "artifact_id": "ols_1",
                "artifact_type": "model_result",
                "required": True,
                "count": 1,
                "step": "estimate",
            }
        ],
        "evidence_refs": [
            {
                "evidence_id": "evidence:profile",
                "result_hash": "sha256:profile",
                "source_refs": ["profile:source"],
            }
        ],
        "comparative_claims": [
            "evidence:profile confirms the declared source columns."
        ],
    }
    invalid = {"options": [json.loads(json.dumps(option))]}
    invalid_step = invalid["options"][0]["proposal"]["changes"]["steps"][0]
    invalid_step["operation"] = "fit"
    invalid_step["selected_columns"] = ["response", "exposure"]

    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-profile",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": {"options": [option]},
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"ols": {"model_type": "ols"}},
        inspection_executor=lambda requests, current: evidence,
    )

    result = agent.plan(
        context=context,
        initial_evidence=DataEvidencePackV1("dataset:source", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "workflow step contains unknown field(s)" in correction
    assert "step_id, operation_id, spec" in correction
    assert "inside spec" in correction


def test_provider_can_request_three_distinct_bounded_inspections_before_submitting(
    tmp_path: Path,
) -> None:
    """Valid sequential inspections must not exhaust a two-turn implementation limit."""

    inspection_ids = ("profile.v1", "quality.v1", "time_index.v1")
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": f"inspect-{inspection_id}",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": inspection_id,
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            }
            for inspection_id in inspection_ids
        ]
        + [
            {
                "tool_call_id": "submit-after-inspections",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            }
        ]
    )

    def inspect(requests: tuple[InspectionRequest, ...], current: DataEvidencePackV1) -> DataEvidencePackV1:
        del current
        inspection_id = requests[0].inspection_id
        if inspection_id == "time_index.v1":
            return _evidence()
        return DataEvidencePackV1(
            source_id="run:run_001",
            records=(
                EvidenceRecord(
                    evidence_id=f"evidence:{inspection_id}",
                    inspection_id=inspection_id,
                    source_refs=(f"{inspection_id}:run_001",),
                    protocol_version=f"{inspection_id}/v1",
                    status="completed",
                    result_hash=f"sha256:{inspection_id}",
                ),
            ),
        )

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=inspect,
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert [request.inspection_id for request in result.inspection_requests] == list(inspection_ids)
    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 4


def test_provider_reuses_an_identical_in_session_inspection_without_executing_it_twice(
    tmp_path: Path,
) -> None:
    """A repeated read-only request replays bounded evidence, not work or failure."""

    repeated = {
        "tool_call_id": "inspect-time",
        "tool_id": "request_notebook_inspections",
        "arguments": {
            "requests": [
                {
                    "inspection_id": "time_index.v1",
                    "target_ref": "run:active",
                    "arguments": {},
                }
            ]
        },
    }
    adapter = ScriptedAdapter(
        [
            repeated,
            {**repeated, "tool_call_id": "inspect-time-again"},
            {
                "tool_call_id": "submit-after-reuse",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    executions: list[tuple[InspectionRequest, ...]] = []

    def inspect(
        requests: tuple[InspectionRequest, ...], current: DataEvidencePackV1
    ) -> DataEvidencePackV1:
        del current
        executions.append(requests)
        return _evidence()

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=inspect,
        max_contract_corrections=0,
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert [request.inspection_id for request in result.inspection_requests] == ["time_index.v1"]
    assert len(executions) == 1
    assert len(adapter.requests) == 3


def test_provider_rejects_a_changed_duplicate_inspection_without_relabeling_evidence(
    tmp_path: Path,
) -> None:
    """Different bounded reads need distinct evidence, not silent reuse."""

    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-time",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-time-changed",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {"max_rows": 5},
                        }
                    ]
                },
            },
        ]
    )
    executions: list[tuple[InspectionRequest, ...]] = []

    def inspect(
        requests: tuple[InspectionRequest, ...], current: DataEvidencePackV1
    ) -> DataEvidencePackV1:
        del current
        executions.append(requests)
        return _evidence()

    with pytest.raises(
        NotebookPlanningContractError,
        match="duplicate inspection id has conflicting arguments",
    ):
        NotebookPlanningAgent(
            adapter=adapter,
            capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
            inspection_executor=inspect,
            max_contract_corrections=0,
        ).plan(
            context=_context(make_project(tmp_path)),
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )

    assert len(executions) == 1


def test_model_custom_planning_contract_exposes_intent_but_rejects_authority_fields(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    context = _context(
        project,
        projection_source={
            "kind": "dataset",
            "upload_sha256": "a" * 64,
        },
    )
    contracts = NotebookPlanningAgent._typed_operation_contracts(context)
    assert contracts["model.custom"]["changes_allowed_fields"] == [
        "operation",
        "input_handle",
        "parameters",
        "consumer_slots",
    ]

    proposal = {
        "proposal_id": "prop_custom",
        "proposal_revision": 1,
        "operation_id": "model.custom",
        "operation_version": "v1",
        "target": {"dataset_source_id": "a" * 64},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "fresh1:test",
            "owner_resolution": "dataset_projection",
        },
        "changes": {
            "operation": "fit",
            "input_handle": "table_1",
            "parameters": {"alpha": 0.1},
            "consumer_slots": ["report_projection"],
        },
    }
    parsed = _strict_typed_proposal(proposal)
    assert parsed.operation_id == "model.custom"
    assert parsed.changes["operation"] == "fit"

    with pytest.raises(NotebookPlanningContractError, match="server-owned"):
        _strict_typed_proposal(
            {
                **proposal,
                "changes": {
                    **proposal["changes"],
                    "binding_ref": "b" * 64,
                },
            }
        )


def test_provider_plan_runs_target_model_options_validator_before_accepting_batch(
    tmp_path: Path,
) -> None:
    """A provider proposal is not executable until the target pack accepts it."""

    calls = [_submit_call(), _submit_call()]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-1",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                            "why_needed": "validate index",
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": calls[0],
            },
            {
                "tool_call_id": "submit-2",
                "tool_id": "submit_notebook_option_batch",
                "arguments": calls[1],
            },
        ]
    )
    seen: list[dict] = []

    def validate_target(_context, submission) -> None:
        seen.append(dict(submission.proposal.changes["model_options"]))
        if len(seen) == 1:
            raise NotebookPlanningContractError(
                "model_options target contract rejected [MODEL_OPTIONS_INVALID_VALUE]"
            )

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: _evidence(),
        proposal_validator=validate_target,
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(seen) == 2
    assert any(
        "model_options target contract rejected" in str(message.get("content"))
        for message in adapter.requests[2].messages
        if message.get("role") == "user"
    )


def test_provider_plan_surfaces_a_bounded_timeout(tmp_path: Path) -> None:
    class SlowAdapter:
        async def stream(self, request):
            await asyncio.sleep(0.05)
            yield ModelStreamEvent.done(request.request_id)

    agent = NotebookPlanningAgent(
        adapter=SlowAdapter(),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        model_timeout_s=0.001,
    )

    with pytest.raises(NotebookPlanningTimeout, match="exceeded"):
        agent.plan(
            context=_context(make_project(tmp_path)),
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )


def test_provider_plan_enforces_one_total_planning_budget(tmp_path: Path) -> None:
    class SlowCorrectingAdapter:
        async def stream(self, request):
            await asyncio.sleep(0.03)
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "unknown",
                    "tool_id": "unknown_tool",
                    "arguments": {},
                },
            )
            yield ModelStreamEvent.done(request.request_id)

    agent = NotebookPlanningAgent(
        adapter=SlowCorrectingAdapter(),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        model_timeout_s=0.1,
        planning_timeout_s=0.05,
    )

    with pytest.raises(NotebookPlanningTimeout, match="total budget"):
        agent.plan(
            context=_context(make_project(tmp_path)),
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )


def test_provider_plan_without_total_deadline_allows_bounded_corrections(
    tmp_path: Path,
) -> None:
    class SlowCorrectingAdapter:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def stream(self, request):
            self.requests.append(request)
            await asyncio.sleep(0.04)
            if len(self.requests) < 4:
                yield ModelStreamEvent.tool_call_delta(
                    request.request_id,
                    {
                        "tool_call_id": f"unknown-{len(self.requests)}",
                        "tool_id": "unknown_tool",
                        "arguments": {},
                    },
                )
            else:
                yield ModelStreamEvent.tool_call_delta(
                    request.request_id,
                    {
                        "tool_call_id": "submit-1",
                        "tool_id": "submit_notebook_option_batch",
                        "arguments": _submit_call(),
                    },
                )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")

    adapter = SlowCorrectingAdapter()
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        model_timeout_s=0.05,
        planning_timeout_s=None,
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_evidence(),
    )

    assert len(adapter.requests) == 4
    assert len(result.option_drafts) == 1


def test_option_parser_rejects_more_than_three_options_at_typed_boundary() -> None:
    payload = _submit_call()
    payload["options"] = payload["options"] * 4

    with pytest.raises(NotebookPlanningContractError, match="at most 3"):
        _parse_submissions(payload)


def test_unregistered_inspection_is_rejected_before_execution_and_corrected(
    tmp_path: Path,
) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "forecast-1",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "forecast_rolling_origin.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                            "why_needed": "compare candidates",
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(run_id="run_001"),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        available_inspections=("profile.v1", "quality.v1", "time_index.v1", "sample.v1"),
        inspection_executor=lambda requests, current: pytest.fail(
            "an unavailable inspection must not reach the executor"
        ),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert any(
        "inspection is not available" in str(message.get("content"))
        for message in adapter.requests[1].messages
        if message.get("role") == "user"
    )


def test_provider_plan_keeps_evidence_from_multiple_inspection_rounds(tmp_path: Path) -> None:
    profile = EvidenceRecord(
        evidence_id="evidence:profile",
        inspection_id="profile.v1",
        source_refs=("profile:run_001",),
        protocol_version="profile/v1",
        status="completed",
        observations={"row_count": 10},
        result_hash="sha256:profile-result",
    )
    calls = [
        {
            "tool_call_id": "inspect-time",
            "tool_id": "request_notebook_inspections",
            "arguments": {
                "requests": [
                    {
                        "inspection_id": "time_index.v1",
                        "target_ref": "run:active",
                        "arguments": {},
                        "why_needed": "validate index",
                    }
                ]
            },
        },
        {
            "tool_call_id": "inspect-profile",
            "tool_id": "request_notebook_inspections",
            "arguments": {
                "requests": [
                    {
                        "inspection_id": "profile.v1",
                        "target_ref": "run:active",
                        "arguments": {},
                        "why_needed": "validate sample size",
                    }
                ]
            },
        },
        {
            "tool_call_id": "submit-both",
            "tool_id": "submit_notebook_option_batch",
            "arguments": {
                **_submit_call(),
                "options": [
                    {
                        **_submit_call()["options"][0],
                        "evidence_refs": [
                            {
                                "evidence_id": "evidence:time",
                                "result_hash": "sha256:time-result",
                                "source_refs": ["time_index:run_001"],
                            },
                            {
                                "evidence_id": "evidence:profile",
                                "result_hash": "sha256:profile-result",
                                "source_refs": ["profile:run_001"],
                            },
                        ],
                    }
                ],
            },
        },
    ]
    adapter = ScriptedAdapter(calls)

    def inspect(requests, current):
        del current
        if requests[0].inspection_id == "time_index.v1":
            return _evidence()
        return DataEvidencePackV1(source_id="run:run_001", records=(profile,))

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=inspect,
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert {record.evidence_id for record in result.evidence_pack.records} == {
        "evidence:time",
        "evidence:profile",
    }
    assert result.option_drafts[0].evidence_refs[-1].evidence_id == "evidence:profile"
    assert "evidence:time" in adapter.requests[2].messages[-1]["content"]
    assert "evidence:profile" in adapter.requests[2].messages[-1]["content"]


def test_provider_gets_bounded_correction_for_invalid_inspection_id(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-invalid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "inspect_head",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    executor_calls: list[tuple[InspectionRequest, ...]] = []
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: (executor_calls.append(requests) or _evidence()),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert result.inspection_requests[0].inspection_id == "time_index.v1"
    assert len(executor_calls) == 1
    assert len(adapter.requests) == 3
    correction_messages = adapter.requests[1].messages
    assert any(message.get("role") == "tool" and "rejected" in message["content"] for message in correction_messages)
    assert "inspect_head" in correction_messages[-1]["content"]
    assert "time_index.v1" in correction_messages[-1]["content"]


def test_provider_gets_projection_target_correction_for_failed_inspection(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-wrong-target",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-right-target",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    failed = DataEvidencePackV1(
        "run:run_001",
        (
            EvidenceRecord(
                evidence_id="evidence:target-failed",
                inspection_id="profile.v1",
                source_refs=("inspection_failure:run:run_001",),
                protocol_version="inspection-error/v1",
                status="failed",
                failure_code="TARGET_REF_INVALID",
                result_hash="sha256:target-failed",
            ),
        ),
    )
    calls = 0

    def execute(requests, current):
        nonlocal calls
        calls += 1
        if calls == 1:
            return failed
        return DataEvidencePackV1(
            "run:run_001",
            (
                *_evidence().records,
                EvidenceRecord(
                    evidence_id="evidence:profile-recovered",
                    inspection_id="profile.v1",
                    source_refs=("dataset_profile:run_001",),
                    protocol_version="profile/v1",
                    status="completed",
                    observations={"row_count": 35},
                    result_hash="sha256:profile-recovered",
                ),
            ),
        )

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=execute,
    )
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "run", "run_id": "run_001"},
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("run:run_001", ()))

    assert len(result.option_drafts) == 1
    assert result.decision.outcome == "recommended"
    assert any("TARGET_REF_INVALID" in str(message) for message in adapter.requests[1].messages)
    assert any(
        "target_ref exactly 'run:active'" in str(message)
        for message in adapter.requests[1].messages
    )


def test_provider_gets_bounded_correction_for_invalid_submission(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["evidence_refs"][0]["result_hash"] = "sha256:not-the-time-result"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 3
    correction_messages = adapter.requests[2].messages
    assert any(message.get("role") == "tool" and "rejected" in message["content"] for message in correction_messages)
    assert "option evidence ref is missing, changed, or incomplete" in correction_messages[-1]["content"]
    assert "sha256:time-result" in correction_messages[-1]["content"]


def test_provider_corrects_a_server_recommendation_validation_error(tmp_path: Path) -> None:
    """Server-side recommendation rejection remains a bounded Agent correction.

    This occurs after a syntactically valid provider submission.  It must not
    escape as a generic request error because the Agent can submit a corrected,
    evidence-bound candidate batch on its next turn.
    """

    class RejectOnceRecommendationValidator:
        def __init__(self) -> None:
            self.calls = 0
            self.delegate = RecommendationValidator()

        def decide(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RecommendationValidationError("candidate batch is not comparable")
            return self.delegate.decide(**kwargs)

    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-rejected",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
            {
                "tool_call_id": "submit-corrected",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
        recommendation_validator=RejectOnceRecommendationValidator(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 3
    assert "server recommendation validation failed" in adapter.requests[2].messages[-1]["content"]


def test_provider_accepts_comparative_claim_bound_by_structured_evidence_ref(
    tmp_path: Path,
) -> None:
    """The evidence_refs field, not prose text, binds a comparison claim."""

    submission = _submit_call()
    submission["options"][0]["comparative_claims"] = [
        "The observed time index supports this registered path."
    ]
    agent = NotebookPlanningAgent(
        adapter=SequencedAdapter(submission),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1


def test_provider_correction_names_only_completed_refs_after_partial_sample_rejection() -> None:
    evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": [{"name": "outcome"}, {"name": "predictor"}]},
                result_hash="sha256:profile",
            ),
            EvidenceRecord(
                evidence_id="evidence:sample",
                inspection_id="sample.v1",
                source_refs=("sample:dataset",),
                protocol_version="sample/v1",
                status="partial",
                observations={"columns": [{"name": "outcome"}]},
                omissions=(
                    {
                        "section": "sample.columns",
                        "included_count": 8,
                        "available_count": 18,
                        "reason": "sample_column_cap",
                    },
                ),
                result_hash="sha256:sample",
            ),
        ),
    )

    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "option evidence ref is missing, changed, or incomplete"
        ),
        context=object(),  # this correction does not consult planning context
        evidence=evidence,
        correction_number=1,
    )

    assert "evidence:profile" in message
    assert "sha256:profile" in message
    assert "evidence:sample" in message
    assert "partial" in message
    assert "must not be cited as completed" in message


def test_provider_correction_closes_option_batch_top_level_shape() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "option tool arguments must contain only options"
        ),
        context=object(),  # this correction does not consult planning context
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "exactly one top-level field named options" in message
    assert "Do not include" in message
    assert "reasoning" in message


def test_provider_correction_closes_option_submission_field_shape() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "option submission fields are incomplete or unknown"
        ),
        context=object(),
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "rank, rationale, proposal, evidence_refs" in message
    assert "comparative_claims, capability_id, and option_id" in message
    assert "Do not add reasoning" in message


def test_provider_option_envelope_is_repaired_once_from_server_evidence() -> None:
    """Wrapper omissions do not consume a provider correction turn.

    The model still supplies the executable proposal and rationale.  Evidence
    references, the empty comparative-claim set, and the option identity are
    deterministic server-owned envelope fields and can be filled without
    weakening the later typed validation.
    """

    payload = _submit_call(capability_id="ols")
    option = payload["options"][0]
    option.pop("evidence_refs")
    option.pop("comparative_claims")
    option.pop("option_id")
    option.pop("capability_id")
    option["proposal"]["operation_id"] = "model.genesis"
    option["proposal"]["target"] = {"dataset_source_id": "sha256:upload"}
    option["proposal"]["changes"] = {
        "model_params": {
            "model_type": "ols",
            "y": "outcome",
            "x": ["treatment"],
        }
    }
    normalized = _canonicalize_provider_option_batch(
        payload,
        evidence=_evidence(),
        catalog={"ols": {"model_type": "ols"}},
    )

    parsed = _parse_submissions(normalized)
    assert parsed[0].option_id == "option_1"
    assert parsed[0].capability_id == "ols"
    assert parsed[0].comparative_claims == ()
    assert parsed[0].evidence_refs[0].evidence_id == "evidence:time"


def test_model_options_policy_follows_nested_model_type_not_stale_capability_label() -> None:
    payload = _submit_call(capability_id="ols")
    option = payload["options"][0]
    option["proposal"]["operation_id"] = "model.genesis"
    option["proposal"]["target"] = {"dataset_source_id": "sha256:upload"}
    option["proposal"]["changes"] = {
        "model_params": {
            "model_type": "logit",
            "y": "outcome",
            "x": ["treatment"],
            "model_options": {"covariance": "robust"},
        },
        "model_options": {"covariance": "robust"},
    }
    submission = _submission(option)
    normalized = NotebookPlanningAgent._strip_unsupported_model_options(
        submission,
        {
            "ols": {
                "model_type": "ols",
                "notebook_model_options_policy": {
                    "supported": True,
                    "allowed_fields": ["covariance"],
                },
            },
            "logit": {
                "model_type": "logit",
                "notebook_model_options_policy": {
                    "supported": False,
                    "allowed_fields": [],
                },
            },
        },
    )

    changes = normalized.proposal.changes
    assert "model_options" not in changes
    assert "model_options" not in changes["model_params"]


def test_provider_correction_omits_unsupported_model_options() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "model_options target contract rejected [MODEL_OPTIONS_UNSUPPORTED]: "
            "Model type panel_ols does not declare model_options."
        ),
        context=object(),
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "omit model_options entirely" in message
    assert "related model family" in message


def test_provider_correction_omits_legacy_covariance_for_non_ols_family() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "typed proposal failed registry validation: "
            "model.genesis logit does not accept OLS covariance settings"
        ),
        context=object(),
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "model_params.covariance" in message
    assert "model_options" in message
    assert "omit" in message


def test_planner_drops_options_when_catalog_declares_family_has_no_options() -> None:
    """A provider cannot keep retrying an explicitly unsupported option envelope."""

    submission = _submission(
        {
            "rank": 1,
            "rationale": "The binary outcome supports the registered family.",
            "capability_id": "logit",
            "option_id": "opt-logit",
            "proposal": {
                "proposal_id": "prop-logit",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": "sha256:upload"},
                "preconditions": {},
                "changes": {
                    "model_params": {
                        "model_type": "logit",
                        "y": "outcome",
                        "x": ["x"],
                        "model_options": {"covariance": "robust"},
                    },
                    "model_options": {"covariance": "robust"},
                },
            },
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": [],
        }
    )
    catalog = {
        "logit": {
            "model_type": "logit",
            "notebook_model_options_policy": {
                "supported": False,
                "allowed_fields": [],
                "forbidden_fields": ["covariance", "model_options"],
                "submission_rule": "omit_model_options",
            },
        }
    }

    agent = NotebookPlanningAgent(adapter=TextOnlyAdapter(), capability_catalog=catalog)
    normalized = agent._strip_unsupported_model_options(submission, catalog)

    changes = normalized.proposal.changes
    assert "model_options" not in changes
    assert "model_options" not in changes["model_params"]


def test_planner_drops_legacy_covariance_when_family_has_no_covariance_contract() -> None:
    """A copied OLS legacy field must not create a retry for a non-OLS family."""

    submission = _submission(
        {
            "rank": 1,
            "rationale": "The binary outcome supports the registered family.",
            "capability_id": "logit",
            "option_id": "opt-logit-legacy-covariance",
            "proposal": {
                "proposal_id": "prop-logit-legacy-covariance",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": "sha256:upload"},
                "preconditions": {},
                "changes": {
                    "model_params": {
                        "model_type": "logit",
                        "y": "outcome",
                        "x": ["x"],
                        "covariance": "robust",
                    },
                    "model_options": {"covariance": "robust"},
                },
            },
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": [],
        }
    )
    catalog = {
        "logit": {
            "model_type": "logit",
            "notebook_model_options_policy": {
                "supported": False,
                "allowed_fields": [],
                "forbidden_fields": ["covariance", "model_options"],
                "submission_rule": "omit_model_options",
            },
        }
    }

    normalized = NotebookPlanningAgent._strip_unsupported_model_options(
        submission, catalog
    )

    changes = normalized.proposal.changes
    assert "model_options" not in changes
    assert "covariance" not in changes["model_params"]


def test_provider_correction_keeps_ols_model_options_narrow() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "model_options target contract rejected [OLS_MODEL_OPTIONS_UNKNOWN_FIELD]: "
            "Model type ols rejected model_options: OLS model_options contains unsupported field(s): branches"
        ),
        context=object(),
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "OLS model_options may contain" in message
    assert "covariance field" in message
    assert "branches" in message
    assert "operation.multi_step" in message


def test_provider_correction_keeps_expected_artifact_with_selected_capability() -> None:
    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "expected artifact failed published artifact vocabulary validation: "
            "'logit_1' is not in the published artifact vocabulary"
        ),
        context=object(),
        evidence=DataEvidencePackV1("dataset:active", ()),
        correction_number=1,
    )

    assert "selected capability" in message
    assert "logit_1" in message
    assert "ols_1" in message


def test_provider_prompt_separates_completed_and_partial_evidence_refs(
    tmp_path: Path,
) -> None:
    partial = EvidenceRecord(
        evidence_id="evidence:sample",
        inspection_id="sample.v1",
        source_refs=("sample:run_001",),
        protocol_version="sample/v1",
        status="partial",
        observations={"columns": [{"name": "outcome"}]},
        omissions=({"section": "sample.columns", "reason": "sample_column_cap"},),
        result_hash="sha256:sample-result",
    )
    evidence = DataEvidencePackV1(
        source_id="run:run_001",
        records=(*_evidence().records, partial),
    )
    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:test",
            }
        ],
    )
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _pinned_rerun_submit_call(context),
            }
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
    )

    agent.plan(context=context, initial_evidence=evidence)

    payload = json.loads(adapter.requests[0].messages[1]["content"])
    policy = payload["evidence_citation_policy"]
    assert policy["completed_evidence_refs"] == [
        {
            "evidence_id": "evidence:time",
            "result_hash": "sha256:time-result",
            "source_refs": ["time_index:run_001"],
        }
    ]
    assert policy["non_citable_evidence"] == [
        {
            "evidence_id": "evidence:sample",
            "status": "partial",
            "omissions": [{"section": "sample.columns", "reason": "sample_column_cap"}],
        }
    ]


def test_provider_reuses_a_canonical_terminal_partial_inspection(
    tmp_path: Path,
) -> None:
    partial = EvidenceRecord(
        evidence_id="evidence:sample",
        inspection_id="sample.v1",
        source_refs=("sample:run_001",),
        protocol_version="sample/v1",
        status="partial",
        observations={"columns": [{"name": "outcome"}]},
        omissions=({"section": "sample.columns", "reason": "sample_column_cap"},),
        result_hash="sha256:sample-result",
    )
    evidence = DataEvidencePackV1(
        source_id="run:run_001",
        records=(*_evidence().records, partial),
    )
    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:test",
            }
        ],
    )
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-sample-again",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "sample.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                            "why_needed": "remove the column cap",
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _pinned_rerun_submit_call(context),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: pytest.fail(
            "a terminal partial inspection must not execute again"
        ),
    )

    result = agent.plan(
        context=context,
        initial_evidence=evidence,
    )

    assert len(result.option_drafts) == 1
    assert json.loads(adapter.requests[1].messages[-1]["content"])[
        "reused_inspection_ids"
    ] == ["sample.v1"]


def test_provider_reuses_a_canonical_terminal_completed_inspection(
    tmp_path: Path,
) -> None:
    """A default run-root inspection is deterministic for its pinned source."""

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:test",
            }
        ],
    )
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-time-again",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-after-reuse",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _pinned_rerun_submit_call(context),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: pytest.fail(
            f"initial terminal evidence should be reused, got {requests!r}"
        ),
    )

    result = agent.plan(
        context=context,
        initial_evidence=_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert json.loads(adapter.requests[1].messages[-1]["content"])[
        "reused_inspection_ids"
    ] == ["time_index.v1"]


def test_provider_normalizes_server_owned_dataset_pin_without_correction_turn(tmp_path: Path) -> None:
    upload_sha256 = "sha256:upload-123"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    genesis_preconditions = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": "sha256:not-the-upload"},
        "preconditions": genesis_preconditions,
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=context,
        initial_evidence=DataEvidencePackV1("dataset", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 2
    assert result.option_drafts[0].proposal.target == {"dataset_source_id": upload_sha256}


def test_dataset_root_submission_is_canonicalized_to_server_owned_source_pin(
    tmp_path: Path,
) -> None:
    """A provider cannot redirect a dataset-bound Notebook proposal.

    The Notebook already has one immutable source projection.  A malformed
    provider pin is therefore not a user choice that needs a retry; it is
    server-owned envelope data and should be normalized before model-family
    validation.  This keeps source binding as one generic boundary rule for
    every native model family.
    """

    upload_sha256 = "sha256:canonical-upload"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    genesis_preconditions = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The source profile supports the declared model.",
            "capability_id": "ols",
            "option_id": "opt-ols-source-pin",
            "proposal": {
                "proposal_id": "prop-ols-source-pin",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": "sha256:provider-guessed"},
                "preconditions": genesis_preconditions,
                "changes": {
                    "model_params": {
                        "model_type": "ols",
                        "y": "outcome",
                        "x": ["treatment"],
                    }
                },
            },
            "expected_artifacts": [
                {
                    "artifact_id": "ols_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:time",
                    "result_hash": "sha256:time-result",
                    "source_refs": ["time_index:run_001"],
                }
            ],
            "comparative_claims": [],
        }
    )

    (normalized,) = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(),
        capability_catalog={"ols": {"model_type": "ols"}},
    )._validate_submissions(
        context,
        _evidence(),
        (submission,),
        {"ols": {"model_type": "ols"}},
    )

    assert normalized.proposal.target == {"dataset_source_id": upload_sha256}


def test_native_capability_artifacts_are_canonicalized_from_published_vocabulary(
    tmp_path: Path,
) -> None:
    """Native result ids are server output, not provider guesses."""

    upload_sha256 = "sha256:canonical-artifact-upload"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    payload = _submit_call(capability_id="logit")
    option = payload["options"][0]
    option["proposal"] = {
        **option["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": freshness_dependency_fingerprint(context),
            "owner_resolution": "single_candidate",
        },
        "changes": {
            "model_params": {
                "model_type": "logit",
                "y": "outcome",
                "x": ["treatment"],
            }
        },
    }
    option["expected_artifacts"] = [
        {
            "artifact_id": "provider_guess",
            "artifact_type": "json",
            "required": True,
            "count": 1,
            "step": None,
        }
    ]

    (normalized,) = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(),
        capability_catalog={"logit": {"model_type": "logit"}},
    )._validate_submissions(
        context,
        _evidence(),
        (_submission(option),),
        {"logit": {"model_type": "logit"}},
    )

    assert normalized.expected_artifacts == (
        ExpectedArtifact(
            artifact_id="logit_1",
            artifact_type="model_result",
            required=True,
            count=1,
            step=None,
        ),
    )


def test_genesis_stale_capability_label_is_bound_to_nested_model_family(
    tmp_path: Path,
) -> None:
    """One stale wrapper label must not select OLS policy or artifacts."""

    upload_sha256 = "sha256:stale-capability-label"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    option = _submit_call(capability_id="ols")["options"][0]
    option["proposal"] = {
        **option["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": freshness_dependency_fingerprint(context),
            "owner_resolution": "single_candidate",
        },
        "changes": {
            "model_params": {
                "model_type": "logit",
                "y": "outcome",
                "x": ["treatment"],
                "model_options": {"covariance": "robust"},
            },
            "model_options": {"covariance": "robust"},
        },
    }
    submission = _submission(option)
    catalog = {
        "ols": {
            "model_type": "ols",
            "notebook_model_options_policy": {
                "supported": True,
                "allowed_fields": ["covariance"],
            },
        },
        "logit": {
            "model_type": "logit",
            "notebook_model_options_policy": {
                "supported": False,
                "allowed_fields": [],
            },
        },
    }

    normalized = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(), capability_catalog=catalog
    )._validate_submissions(context, _evidence(), (submission,), catalog)

    assert normalized[0].capability_id == "logit"
    assert "model_options" not in normalized[0].proposal.changes
    assert normalized[0].expected_artifacts == (
        ExpectedArtifact("logit_1", "model_result", required=True, count=1, step=None),
    )


def test_provider_normalizes_incomplete_genesis_preconditions_without_correction_turn(
    tmp_path: Path,
) -> None:
    upload_sha256 = "sha256:upload-preconditions"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {},
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("dataset", ()))

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 2
    assert result.option_drafts[0].proposal.preconditions == {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }


def test_provider_normalizes_custom_dataset_pin_without_provider_guess(
    tmp_path: Path,
) -> None:
    """Custom dataset proposals use the same source-owned pin as Genesis."""

    upload_sha256 = "sha256:custom-source-pin"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    option = _submit_call(capability_id="custom-capability")["options"][0]
    option["proposal"] = {
        **option["proposal"],
        "operation_id": "model.custom",
        "target": {},
        "preconditions": {},
        "changes": {
            "operation": "fit",
            "input_handle": "dataset:active",
            "parameters": {},
            "consumer_slots": ["result"],
        },
    }
    submission = _submission(option)

    normalized = NotebookPlanningAgent._canonicalize_server_owned_pins(
        context, submission
    )

    assert normalized.proposal.target == {"dataset_source_id": upload_sha256}
    assert normalized.proposal.preconditions == {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }


def test_notebook_agent_accepts_did_genesis_with_family_timing_and_no_covariates(
    tmp_path: Path,
) -> None:
    """The typed planner must not impose OLS X requirements on DID options."""

    upload_sha256 = "sha256:upload-did"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={
                    "columns": [
                        {"name": "outcome"},
                        {"name": "unit"},
                        {"name": "period"},
                        {"name": "first_treat"},
                    ]
                },
                result_hash="sha256:did-profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The declared timing fields support a cohort DID design.",
            "assumptions": ["cohort timing is correctly recorded"],
            "capability_id": "cs_did",
            "option_id": "opt_cs_did",
            "proposal": {
                "proposal_id": "prop_cs_did",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": upload_sha256},
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": freshness_dependency_fingerprint(context),
                    "owner_resolution": "single_candidate",
                },
                "changes": {
                    "model_params": {
                        "model_type": "cs_did",
                        "y": "outcome",
                        "x": [],
                        "entity_col": "unit",
                        "time_col": "period",
                        "cohort_col": "first_treat",
                    }
                },
            },
            "expected_artifacts": [
                {
                    "artifact_id": "cs_did_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:did-profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": ["evidence:profile confirms the declared source columns."],
        }
    )
    catalog = {"cs_did": {"model_type": "cs_did"}}

    normalized = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(), capability_catalog=catalog
    )._validate_submissions(context, evidence, (submission,), catalog)

    assert normalized[0].proposal.changes["model_params"]["cohort_col"] == "first_treat"


def test_notebook_agent_rejects_an_incomplete_iv_genesis_spec(
    tmp_path: Path,
) -> None:
    """An IV option needs both declared endogeneity and instrument columns."""

    upload_sha256 = "sha256:upload-iv"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={
                    "columns": [
                        {"name": "outcome"},
                        {"name": "endogenous"},
                        {"name": "instrument"},
                    ]
                },
                result_hash="sha256:iv-profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The proposed IV design needs an instrument declaration.",
            "assumptions": ["the instrument is relevant and exogenous"],
            "capability_id": "iv_2sls",
            "option_id": "opt_iv",
            "proposal": {
                "proposal_id": "prop_iv",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": upload_sha256},
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": freshness_dependency_fingerprint(context),
                    "owner_resolution": "single_candidate",
                },
                "changes": {
                    "model_params": {
                        "model_type": "iv_2sls",
                        "y": "outcome",
                        "x": [],
                        "iv_endog": ["endogenous"],
                    }
                },
            },
            "expected_artifacts": [
                {
                    "artifact_id": "iv_2sls_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:iv-profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": ["evidence:profile confirms the declared source columns."],
        }
    )
    catalog = {"iv_2sls": {"model_type": "iv_2sls"}}

    with pytest.raises(
        NotebookPlanningContractError,
        match="model.genesis iv_2sls requires a non-empty iv_instruments column list",
    ):
        NotebookPlanningAgent(
            adapter=TextOnlyAdapter(), capability_catalog=catalog
        )._validate_submissions(context, evidence, (submission,), catalog)

    completed_params = dict(submission.proposal.changes["model_params"])
    completed_params["iv_instruments"] = ["instrument"]
    complete_submission = replace(
        submission,
        proposal=TypedProposal.from_dict(
            {
                **submission.proposal.to_dict(),
                "changes": {"model_params": completed_params},
            }
        ),
    )
    normalized = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(), capability_catalog=catalog
    )._validate_submissions(context, evidence, (complete_submission,), catalog)

    assert normalized[0].proposal.changes["model_params"]["iv_instruments"] == ["instrument"]


@pytest.mark.parametrize("active_head_run_id", [None, "run_001"])
def test_notebook_agent_admits_recipe_genesis_without_y_or_x_and_rejects_legacy_shape(
    tmp_path: Path, active_head_run_id: str | None
) -> None:
    """A Recipe is a separate input contract, not a univariate regression."""

    upload_sha256 = "sha256:upload-recipe"
    context = _context(
        make_project(tmp_path),
        active_head_run_id=active_head_run_id,
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": [{"name": "when"}, {"name": "value"}]},
                result_hash="sha256:recipe-profile",
            ),
        ),
    )
    model_params = {
        "model_type": "time_series.ets",
        "model_options": {
            "time_column": "when",
            "value_column": "value",
            "error": "add",
            "trend": None,
                "seasonal": None,
                "damped_trend": False,
                "time_index_semantics": "observation_order",
            },
        }
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The evidence-backed time and value fields define one series.",
            "assumptions": ["the declared observation order is meaningful"],
            "capability_id": "time_series.ets",
            "option_id": "opt_recipe",
            "proposal": {
                "proposal_id": "prop_recipe",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": upload_sha256},
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": freshness_dependency_fingerprint(context),
                    "owner_resolution": "single_candidate",
                },
                "changes": {"model_params": model_params},
            },
            "expected_artifacts": [
                {
                    "artifact_id": "ets_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:recipe-profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": [
                "evidence:profile confirms the declared source columns."
            ],
        }
    )
    catalog = {"time_series.ets": {"model_type": "time_series.ets"}}
    agent = NotebookPlanningAgent(adapter=TextOnlyAdapter(), capability_catalog=catalog)

    normalized = agent._validate_submissions(context, evidence, (submission,), catalog)

    assert normalized[0].proposal.changes["model_params"] == model_params

    legacy_params = {**model_params, "y": "value"}
    legacy_submission = replace(
        submission,
        proposal=TypedProposal.from_dict(
            {
                **submission.proposal.to_dict(),
                "changes": {"model_params": legacy_params},
            }
        ),
    )
    with pytest.raises(
        NotebookPlanningContractError,
        match="RECIPE_REGRESSION_FIELD_FORBIDDEN",
    ):
        agent._validate_submissions(context, evidence, (legacy_submission,), catalog)


def test_notebook_agent_applies_recipe_memory_default_then_rechecks_current_columns(
    tmp_path: Path,
) -> None:
    """A bounded Recipe default remains subject to current evidence validation."""

    upload_sha256 = "sha256:upload-recipe-memory"
    context = attach_domain_memory_projection(
        _context(
            make_project(tmp_path),
            projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
        ),
        {
            "contract_version": "domain-memory-context-input/v3",
            "retrieval_ref": "retrieval-recipe-memory",
            "scope_ref": "scope-recipe-memory",
            "outcome": "used",
            "reason": "approved hint",
            "entries": [
                {
                    "memory_id": "memory-recipe-observation-order",
                    "revision": 3,
                    "content_hash": "b" * 64,
                    "memory_kind": "project_domain_fact",
                    "domain_tags": ["time-series"],
                    "compact_lesson": "This source is an observation-order series.",
                    "recommended_effect_kind": "assumption_check_hint",
                    "recommended_target_refs": [
                        "model.genesis.time_series.ets.time_index_semantics.observation_order"
                    ],
                    "source_summary_refs": ["summary-recipe-memory"],
                    "match_reason": ["project-domain"],
                    "apply_mode": "suggest_default",
                    "apply_mode_reason": "verifier_current",
                    "vocabulary_version": "notebook-memory-defaults-v1",
                    "source_scope_ref": "scope-recipe-memory",
                    "memory_source": {
                        "memory_id": "memory-recipe-observation-order",
                        "revision": 3,
                    },
                    "memory_authority": "non_authoritative_hint",
                }
            ],
            "omissions": [],
            "bounded": True,
            "preference_ref": "preference-recipe-memory",
            "memory_authority": "non_authoritative",
        },
    )
    complete_evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:recipe-profile",
                inspection_id="profile.v1",
                source_refs=("profile:recipe-dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": [{"name": "when"}, {"name": "value"}]},
                result_hash="sha256:recipe-memory-profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The verified source contains one time-indexed series.",
            "assumptions": ["Observation order is the approved interpretation."],
            "capability_id": "time_series.ets",
            "option_id": "opt-recipe-memory",
            "proposal": {
                "proposal_id": "prop-recipe-memory",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": upload_sha256},
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": freshness_dependency_fingerprint(context),
                    "owner_resolution": "single_candidate",
                },
                "changes": {
                    "model_params": {
                        "model_type": "time_series.ets",
                        "model_options": {
                            "time_column": "when",
                            "value_column": "value",
                            "error": "add",
                            "trend": None,
                            "seasonal": None,
                            "damped_trend": False,
                        },
                    }
                },
            },
            "expected_artifacts": [
                {
                    "artifact_id": "ets_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:recipe-profile",
                    "result_hash": "sha256:recipe-memory-profile",
                    "source_refs": ["profile:recipe-dataset"],
                }
            ],
            "comparative_claims": [
                "evidence:recipe-profile confirms the declared source columns."
            ],
        }
    )
    catalog = {"time_series.ets": {"model_type": "time_series.ets"}}
    agent = NotebookPlanningAgent(adapter=TextOnlyAdapter(), capability_catalog=catalog)

    (normalized,) = agent._validate_submissions(
        context, complete_evidence, (submission,), catalog
    )

    assert normalized.proposal.changes["model_params"]["model_options"][
        "time_index_semantics"
    ] == "observation_order"
    assert normalized.proposal.memory_default_sources[0] == MemoryDefaultSource(
        memory_id="memory-recipe-observation-order",
        revision=3,
        target_ref="model.genesis.time_series.ets.time_index_semantics.observation_order",
        target_label="Time-index interpretation",
        method_risk="high",
        restore_value=None,
    )

    missing_value_evidence = replace(
        complete_evidence,
        records=(
            replace(
                complete_evidence.records[0],
                observations={"columns": [{"name": "when"}]},
            ),
        ),
    )
    with pytest.raises(NotebookPlanningContractError, match="RECIPE_SOURCE_COLUMN_MISSING"):
        agent._validate_submissions(context, missing_value_evidence, (submission,), catalog)


def test_recipe_model_options_rejection_republishes_exact_required_inputs(
    tmp_path: Path,
) -> None:
    correction = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "RECIPE_MODEL_OPTIONS_REQUIRED: time_series.ets requires a model_options object."
        ),
        context=_context(make_project(tmp_path)),
        evidence=_evidence(),
        correction_number=1,
    )

    assert "time_series.ets" in correction
    assert "model_params.model_options" in correction
    assert "model_options" in correction
    assert "time_column" in correction
    assert "value_column" in correction


def test_notebook_agent_applies_a_current_memory_default_with_exact_provenance(
    tmp_path: Path,
) -> None:
    """A planner cannot turn a hint into an unowned or free-text default."""

    upload_sha256 = "sha256:upload-memory-default"
    context = attach_domain_memory_projection(
        _context(
            make_project(tmp_path),
            projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
        ),
        {
            "contract_version": "domain-memory-context-input/v3",
            "retrieval_ref": "retrieval-memory-default",
            "scope_ref": "scope-memory-default",
            "outcome": "used",
            "reason": "approved hint",
            "entries": [
                {
                    "memory_id": "memory-ols-covariance",
                    "revision": 2,
                    "content_hash": "a" * 64,
                    "memory_kind": "project_domain_fact",
                    "domain_tags": ["education"],
                    "compact_lesson": "Use robust covariance for this approved default.",
                    "recommended_effect_kind": "assumption_check_hint",
                    "recommended_target_refs": [
                        "model.genesis.ols.covariance.robust"
                    ],
                    "source_summary_refs": ["summary-memory-default"],
                    "match_reason": ["goal"],
                        "apply_mode": "suggest_default",
                        "apply_mode_reason": "verifier_current",
                        "vocabulary_version": "notebook-memory-defaults-v1",
                        "source_scope_ref": "scope-memory-default",
                        "memory_source": {
                        "memory_id": "memory-ols-covariance",
                        "revision": 2,
                    },
                    "memory_authority": "non_authoritative_hint",
                }
            ],
            "omissions": [],
            "bounded": True,
            "preference_ref": "preference-memory-default",
            "memory_authority": "non_authoritative",
        },
    )
    evidence = DataEvidencePackV1(
        source_id="dataset:active",
        records=(
            EvidenceRecord(
                evidence_id="evidence:profile",
                inspection_id="profile.v1",
                source_refs=("profile:dataset",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": [{"name": "outcome"}, {"name": "exposure"}]},
                result_hash="sha256:memory-default-profile",
            ),
        ),
    )
    submission = _submission(
        {
            "rank": 1,
            "rationale": "The profile confirms the requested OLS columns.",
            "assumptions": ["the approved covariance convention remains applicable"],
            "capability_id": "ols",
            "option_id": "opt_memory_default",
            "proposal": {
                "proposal_id": "prop_memory_default",
                "proposal_revision": 1,
                "operation_id": "model.genesis",
                "operation_version": "v1",
                "target": {"dataset_source_id": upload_sha256},
                "preconditions": {
                    "context_version": "node-operation-context/v1",
                    "context_fingerprint": freshness_dependency_fingerprint(context),
                    "owner_resolution": "single_candidate",
                },
                "changes": {
                    "model_params": {
                        "model_type": "ols",
                        "y": "outcome",
                        "x": ["exposure"],
                    }
                },
            },
            "expected_artifacts": [
                {
                    "artifact_id": "ols_1",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": None,
                }
            ],
            "evidence_refs": [
                {
                    "evidence_id": "evidence:profile",
                    "result_hash": "sha256:memory-default-profile",
                    "source_refs": ["profile:dataset"],
                }
            ],
            "comparative_claims": [
                "evidence:profile confirms the declared source columns."
            ],
        }
    )

    (normalized,) = NotebookPlanningAgent(
        adapter=TextOnlyAdapter(), capability_catalog={"ols": {"model_type": "ols"}}
    )._validate_submissions(context, evidence, (submission,), {"ols": {"model_type": "ols"}})

    assert normalized.proposal.changes["model_options"] == {"covariance": "robust"}
    assert normalized.proposal.memory_default_sources == (
        MemoryDefaultSource(
            memory_id="memory-ols-covariance",
            revision=2,
            target_ref="model.genesis.ols.covariance.robust",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
        ),
    )


def test_provider_rejects_genesis_without_evidence_backed_target(tmp_path: Path) -> None:
    upload_sha256 = "a" * 64
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    invalid = _submit_call(capability_id="time_series.ets")
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": freshness_dependency_fingerprint(context),
            "owner_resolution": "single_candidate",
        },
        "changes": {"model_params": {"model_type": "ols", "x": ["treatment"]}},
    }
    valid = json.loads(json.dumps(invalid))
    valid["options"][0]["proposal"]["changes"]["model_params"]["y"] = "outcome"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-profile",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-missing-y",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-with-y",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=context,
        initial_evidence=DataEvidencePackV1("dataset", ()),
    )

    assert len(result.option_drafts) == 1
    assert "model.genesis model_params must include evidence-backed y" in adapter.requests[2].messages[-1]["content"]


def test_provider_gets_exact_genesis_changes_envelope_after_invalid_fields(tmp_path: Path) -> None:
    upload_sha256 = "sha256:upload-changes"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    genesis_preconditions = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": genesis_preconditions,
        "changes": {"capability_id": "ols", "params": {"model_type": "ols"}},
    }
    valid = {"options": [dict(invalid["options"][0])]}
    valid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("dataset", ()))

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "model.genesis changes contain unknown field(s)" in correction
    assert "table_params" in correction
    assert "model_params" in correction
    assert "model_options" in correction


def test_provider_gets_correction_for_duplicate_executable_options(tmp_path: Path) -> None:
    duplicate = _submit_call()
    duplicate["options"].append(
        {
            **duplicate["options"][0],
            "rank": 2,
            "option_id": "opt_ets_duplicate",
        }
    )
    valid = _submit_call()
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": duplicate,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "duplicate executable proposals" in correction
    assert "fewer options" in correction


def test_provider_artifact_guess_is_ignored_for_published_capability(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = [
        {
            "artifact_id": "regression_summary",
            "artifact_type": "json",
            "required": True,
            "count": 1,
            "step": None,
        }
    ]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 2
    assert result.option_drafts[0].expected_artifacts == (
        ExpectedArtifact(
            artifact_id="ets_1",
            artifact_type="model_result",
            required=True,
            count=1,
            step=None,
        ),
    )


def test_provider_missing_capability_artifact_is_filled_from_published_vocabulary(
    tmp_path: Path,
) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = []
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 2
    assert result.option_drafts[0].expected_artifacts == (
        ExpectedArtifact(
            artifact_id="ets_1",
            artifact_type="model_result",
            required=True,
            count=1,
            step=None,
        ),
    )


def test_provider_gets_bounded_correction_for_malformed_typed_fields(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = [{"artifact_id": "ts.parameters"}]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "typed fields are invalid" in correction
    assert "not executed" in correction


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("assumptions", 7),
        ("comparative_claims", 7),
        ("rank", []),
        ("capability_id", []),
    ],
)
def test_provider_scalar_shape_errors_enter_bounded_correction(
    tmp_path: Path, field: str, value: object
) -> None:
    invalid = _submit_call()
    invalid["options"][0][field] = value
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "not executed" in adapter.requests[2].messages[-1]["content"]


def test_provider_inspection_shape_errors_enter_bounded_correction(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-invalid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": 7,
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "inspection target_ref" in adapter.requests[1].messages[-1]["content"]


def test_provider_rejects_unknown_nested_proposal_fields_with_correction(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["proposal"]["unexpected"] = "do not ignore"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "typed proposal fields" in adapter.requests[2].messages[-1]["content"]


def test_provider_contract_error_names_missing_and_unknown_proposal_fields(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["proposal"].pop("proposal_revision")
    invalid["options"][0]["proposal"]["unexpected"] = "do not ignore"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "missing proposal_revision" in correction
    assert "unknown unexpected" in correction


def test_run_execution_pins_include_the_registry_context_fingerprint(tmp_path: Path) -> None:
    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:active-model",
            }
        ],
    )

    pins = NotebookPlanningAgent._execution_pins(context)["rerun_preconditions"]

    assert pins["context_fingerprint"] == "nocv1:active-model"
    assert pins["context_fingerprint_by_node"] == {
        "stage:model": "nocv1:active-model"
    }


def test_workflow_execution_pins_use_server_resolved_raw_artifact_id(tmp_path: Path) -> None:
    """A raw node's CAS path must never be passed as an artifact registry ID."""

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:raw",
                "kind": "dataset_stage",
                "stage": "source",
                "artifact_id": "_uploads/source.csv",
                "workflow_artifact_id": "raw_source_csv",
                "context_fingerprint": "nocv1:raw-source",
            }
        ],
    )

    pins = NotebookPlanningAgent._execution_pins(context)["workflow_source"]

    assert pins["target"] == {
        "run_id": "run_001",
        "node_ref": "stage:raw",
        "artifact_id": "raw_source_csv",
    }


def test_model_rerun_registry_rejects_unknown_change_fields() -> None:
    definition = OperationRegistry().require("model.rerun", "v1")

    changes_schema = definition.proposal_schema["properties"]["changes"]
    assert all(branch["additionalProperties"] is False for branch in changes_schema["oneOf"])

    with pytest.raises(OperationValidationError, match="unknown field"):
        definition.validate(
            target={
                "run_id": "run_001",
                "node_ref": "stage:model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
            },
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "nocv1:active-model",
                "active_head_run_id": "run_001",
                "owner_resolution": "single_candidate",
            },
            changes={"capability": "ols"},
        )


def test_notebook_provider_tools_describe_typed_payloads() -> None:
    inspection_tool = NOTEBOOK_TOOLS[0]
    inspection_item = inspection_tool["input_schema"]["properties"]["requests"]["items"]

    assert inspection_item["additionalProperties"] is False
    assert set(inspection_item["required"]) == {
        "inspection_id",
        "target_ref",
        "arguments",
    }
    assert set(inspection_item["properties"]) == {
        "inspection_id",
        "target_ref",
        "arguments",
        "why_needed",
    }
    assert set(inspection_item["properties"]["inspection_id"]["enum"]) == {
        "profile.v1",
        "quality.v1",
        "time_index.v1",
        "sample.v1",
        "forecast_rolling_origin.v1",
    }

    submission_tool = NOTEBOOK_TOOLS[1]
    submission_item = submission_tool["input_schema"]["properties"]["options"]["items"]
    assert submission_item["additionalProperties"] is False
    assert {
        "rank",
        "rationale",
        "proposal",
        "evidence_refs",
        "comparative_claims",
        "capability_id",
        "option_id",
    }.issubset(submission_item["required"])
    assert submission_item["properties"]["proposal"]["properties"]["changes"]["additionalProperties"] is False
    assert "proposal_revision" in submission_item["properties"]["proposal"]["required"]


def test_provider_failure_is_not_replaced_by_fixed_model_paths(tmp_path: Path) -> None:
    with pytest.raises(NotebookPlanningUnavailable):
        NotebookPlanningAgent(adapter=FailingAdapter()).plan(
            context=_context(make_project(tmp_path)), initial_evidence=_evidence()
        )

    with pytest.raises(NotebookPlanningUnavailable, match="configured NotebookPlanningAgent"):
        generate_option_batch(notebook_id="nb_plan")


def test_text_only_completion_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NotebookPlanningContractError, match="text-only"):
        NotebookPlanningAgent(adapter=TextOnlyAdapter()).plan(
            context=_context(make_project(tmp_path)), initial_evidence=_evidence()
        )


def test_text_only_completion_gets_bounded_typed_tool_correction(
    tmp_path: Path,
) -> None:
    class TextThenToolAdapter:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                yield ModelStreamEvent.text_delta(request.request_id, "I recommend ETS.")
                yield ModelStreamEvent.done(request.request_id)
                return
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "submit-1",
                    "tool_id": "submit_notebook_option_batch",
                    "arguments": _submit_call(),
                },
            )
            yield ModelStreamEvent.done(request.request_id)

    adapter = TextThenToolAdapter()
    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert "must call exactly one" in adapter.requests[1].messages[-1]["content"]


def test_unregistered_capability_is_rejected(tmp_path: Path) -> None:
    adapter = SequencedAdapter(_submit_call(capability_id="not_registered"))
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )
    with pytest.raises(NotebookPlanningUnavailable, match="not registered"):
        agent.plan(context=_context(make_project(tmp_path)), initial_evidence=DataEvidencePackV1("run:run_001", ()))


def test_run_source_proposal_must_be_rerun_child_of_active_head(tmp_path: Path) -> None:
    adapter = SequencedAdapter(_submit_call(run_id="other_run"))
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )
    with pytest.raises(NotebookPlanningContractError, match="rerun-child"):
        agent.plan(context=_context(make_project(tmp_path), active_head_run_id="run_001"), initial_evidence=DataEvidencePackV1("run:run_001", ()))


def test_provider_correction_pins_a_rerun_target_when_lineage_admits_one(
    tmp_path: Path,
) -> None:
    """A rejected run-source target must come back with the eligible ones.

    The provider produced a target outside the active head's lineage and the
    server correctly refused it, but the refusal named no usable alternative,
    so the pass ended at a contract error with an otherwise workable request.
    """

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:test",
            }
        ],
    )

    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "run-source proposal is not a rerun-child of the active head"
        ),
        context=context,
        evidence=DataEvidencePackV1("run:run_001", ()),
        correction_number=1,
    )

    # The exact server-owned pins, so the provider can resubmit rather than guess.
    assert "stage:model" in message
    assert "forest-node-key" in message
    assert "nocv1:test" in message
    assert "model.rerun" in message


def test_provider_correction_falls_back_to_genesis_when_no_rerun_target_exists(
    tmp_path: Path,
) -> None:
    """When the lineage admits no rerun, the provider must be sent to genesis.

    Repeating "not a rerun-child" against a head with no eligible model node
    would ask the provider to satisfy something impossible.
    """

    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[],
    )

    message = NotebookPlanningAgent._correction_instruction(
        error=NotebookPlanningContractError(
            "run-source proposal is not a rerun-child of the active head"
        ),
        context=context,
        evidence=DataEvidencePackV1("run:run_001", ()),
        correction_number=1,
    )

    assert "model.genesis" in message
    assert "no eligible" in message.lower()
