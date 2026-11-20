"""Notebook route packets: option drafts and the materialization and execution-result packets sent to the planner."""

from __future__ import annotations

from typing import Any, Mapping

from ..agent.notebook import NotebookService, OptionDraft, TypedProposal
from ..contracts.agent.notebook_option import ExpectedArtifact
from .notebook_route_models import OptionDraftRequest


def _draft(request: OptionDraftRequest) -> OptionDraft:
    expected = tuple(
        ExpectedArtifact(
            artifact_id=item.artifact_id,
            artifact_type=item.artifact_type,
            required=item.required,
            count=item.count,
            step=item.step,
        )
        for item in request.expected_artifacts
    )
    return OptionDraft(
        rank=request.rank,
        rationale=request.rationale,
        assumptions=tuple(request.assumptions),
        proposal=TypedProposal.from_dict(request.proposal),
        expected_artifacts=expected,
        option_id=request.option_id,
        capability_id=request.capability_id,
    )


def _materializations_packet(
    service: NotebookService, notebook_id: str, revisions: list[Any]
) -> dict[str, dict[str, Any]]:
    """Project persisted Draft handoffs alongside the current option revisions."""

    materializations: dict[str, dict[str, Any]] = {}
    for revision in revisions:
        materialization = service.store.read_materialization(
            notebook_id, revision.option_id, revision.option_revision
        )
        if materialization is not None:
            materializations[revision.option_id] = materialization.to_dict()
    return materializations


def _execution_results_packet(
    service: NotebookService, notebook_id: str, revisions: list[Any]
) -> dict[str, dict[str, Any]]:
    """Project the latest result for each current Option revision.

    The Notebook is a durable projection.  A browser remount must therefore
    be able to recover a completed Draft/Run without relying on the transient
    confirmation state that initiated it.  Keep this packet model-neutral:
    the result contract records execution and artifact-contract facts, while
    model-specific result payloads remain in the Run's artifacts.
    """

    results: dict[str, dict[str, Any]] = {}
    for revision in revisions:
        view = service.store.read_option(notebook_id, revision.option_id)
        if not view.execution_results:
            continue
        raw = dict(view.execution_results[-1])
        if raw.get("option_revision") != revision.option_revision:
            # Do not display a result from an older revision as if it proved
            # the current proposal.  The option revision is the pin.
            continue
        validation = raw.get("artifact_validation")
        if not isinstance(validation, dict):
            capability_execution = raw.get("capability_execution")
            if isinstance(capability_execution, dict):
                # CF4 has already committed the full ArtifactContract@1.1
                # aggregate in its own durable store.  The Notebook route
                # exposes only its server-owned refs; it never accepts or
                # reconstructs adapter payloads here.
                results[revision.option_id] = {
                    "option_id": revision.option_id,
                    "option_revision": revision.option_revision,
                    "run_id": raw.get("run_id"),
                    "execution_status": raw.get("execution_status"),
                    "committed": raw.get("committed"),
                    "capability_execution": {
                        key: capability_execution.get(key)
                        for key in (
                            "dispatch_status",
                            "attempt_id",
                            "receipt_ref",
                            "completion_ref",
                            "artifact_validation_ref",
                            "object_graph_ref",
                            "assessment_ref",
                            "output_bundle_ref",
                            "attestation_ref",
                        )
                    },
                }
            continue
        raw_issues = [dict(issue) for issue in validation.get("issues", [])]
        bounded_issues = raw_issues[:64]
        validation_packet: dict[str, Any] = {
            "contract_profile": validation.get("contract_profile"),
            "validation_status": validation.get("validation_status"),
            "checked_dimensions": list(validation.get("checked_dimensions", [])),
            "not_evaluated_dimensions": list(
                validation.get("not_evaluated_dimensions", [])
            ),
            "issues": bounded_issues,
        }
        if len(raw_issues) > len(bounded_issues):
            validation_packet["omitted_issue_count"] = len(raw_issues) - len(bounded_issues)
        results[revision.option_id] = {
            "option_id": revision.option_id,
            "option_revision": revision.option_revision,
            "run_id": raw.get("run_id"),
            "execution_status": raw.get("execution_status"),
            "committed": raw.get("committed") is True,
            "artifact_validation": validation_packet,
            **(
                {"artifact_validation_scope": dict(raw["artifact_validation_scope"])}
                if isinstance(raw.get("artifact_validation_scope"), Mapping)
                else {}
            ),
            **(
                {"workflow_execution": dict(raw["workflow_execution"])}
                if isinstance(raw.get("workflow_execution"), Mapping)
                else {}
            ),
        }
    return results
