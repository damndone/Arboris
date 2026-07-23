"""HTTP seam for the v1.8.1 Agent Notebook lifecycle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..agent.context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from ..agent.notebook import NotebookService, OptionDraft, TypedProposal
from ..agent.notebook.errors import NotebookOptionError
from ..agent.trace import TraceWriter, record_compiled_context
from ..api_errors import WorkbenchAPIError
from ..contracts.agent.notebook_option import ExpectedArtifact

router = APIRouter()

_TRACE_VERSIONS = {
    "app_commit": "local-workbench",
    "model_id": "notebook-planner",
    "prompt_version": "notebook-plan/1",
    "vocabulary_version": "notebook/1",
    "context_profile": "notebook-plan/v1",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotebookCreateRequest(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    created_by: str = Field(min_length=1, max_length=200)
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    analysis_contract: dict[str, Any] = Field(default_factory=dict)
    user_focus: dict[str, Any] = Field(default_factory=dict)
    available_capabilities: list[str] = Field(default_factory=list, max_length=100)


class DatasetProjectionRequest(_StrictModel):
    upload_sha256: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    sheet_names: list[str] = Field(default_factory=list, max_length=100)


class NotebookProjectionRequest(_StrictModel):
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    dataset: DatasetProjectionRequest | None = None
    created_by: str = Field(min_length=1, max_length=200)
    title: str = Field(default="Analysis Notebook", min_length=1, max_length=300)


class ExpectedArtifactRequest(_StrictModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    artifact_type: str = Field(min_length=1, max_length=200)
    required: bool = True
    count: int = Field(default=1, ge=0)
    step: str | None = Field(default=None, min_length=1, max_length=200)


class OptionDraftRequest(_StrictModel):
    rank: int = Field(ge=1, le=3)
    rationale: str = Field(min_length=1, max_length=4_000)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    proposal: dict[str, Any]
    expected_artifacts: list[ExpectedArtifactRequest] = Field(
        default_factory=list, max_length=50
    )
    option_id: str | None = Field(default=None, min_length=1, max_length=200)


class ProposeOptionsRequest(_StrictModel):
    drafts: list[OptionDraftRequest] = Field(default_factory=list, max_length=3)
    count: int | None = Field(default=None, ge=1, le=3)


class RevalidateOptionRequest(OptionDraftRequest):
    pass


class ConfirmOptionRequest(_StrictModel):
    option_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=200)
    proposal_revision: int = Field(ge=1)


class DecisionRequest(_StrictModel):
    decision: Literal[
        "selected",
        "deferred",
        "rejected",
        "edited",
        "requested_more_options",
        "requested_explanation",
    ]
    actor: str = Field(min_length=1, max_length=200)
    edited_fields: list[str] | None = Field(default=None, max_length=50)
    note_ref: str | None = Field(default=None, max_length=500)


class ExecuteOptionRequest(_StrictModel):
    execution_status: str = Field(min_length=1, max_length=100)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    produced_artifacts: list[dict[str, Any]] | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=200)


def _project_root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _service(project_root: str) -> tuple[Path, NotebookService]:
    root = _project_root(project_root)
    return root, NotebookService(root)


def _trace(root: Path, notebook_id: str, run_family_id: str) -> TraceWriter:
    return TraceWriter(
        root,
        scope={
            "project_id": root.name,
            "notebook_id": notebook_id,
            "run_family_id": run_family_id,
        },
        versions=dict(_TRACE_VERSIONS),
    )


def _compile(
    root: Path, service: NotebookService, notebook_id: str, *, focused_run_id: str | None = None
) -> tuple[NotebookPlanningContextV1, TraceWriter]:
    notebook = service.get_notebook(notebook_id)
    trace = _trace(root, notebook.notebook_id, notebook.run_family_id)
    context = replace(
        service.compile_context(notebook_id, focused_run_id=focused_run_id), trace_id=trace.trace_id
    )
    record_compiled_context(trace, context)
    return context, trace


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
    )


def _context_packet(context: NotebookPlanningContextV1) -> dict[str, Any]:
    """Serialize the context plus the two distinct contract fingerprints."""

    packet = context.to_dict()
    packet["generation_context_hash"] = generation_context_hash(context)
    packet["freshness_dependency_fingerprint"] = freshness_dependency_fingerprint(context)
    return packet


def _notebook_error(exc: NotebookOptionError) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=exc.status_code,
        code=exc.code,
        message=str(exc),
        details=exc.details,
    )


def _request_error(exc: Exception) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=422,
        code="NOTEBOOK_REQUEST_INVALID",
        message="The Notebook request could not be validated.",
        details={"reason": str(exc)},
    )


@router.post("/notebooks", status_code=201)
def create_notebook_endpoint(
    project_root: str, body: NotebookCreateRequest
) -> dict[str, Any]:
    _root, service = _service(project_root)
    try:
        return service.create_notebook(
            title=body.title,
            created_by=body.created_by,
            from_run_id=body.from_run_id,
            analysis_contract=body.analysis_contract,
            user_focus=body.user_focus,
            available_capabilities=body.available_capabilities,
        ).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/projection")
def ensure_notebook_projection_endpoint(
    project_root: str, body: NotebookProjectionRequest
) -> dict[str, Any]:
    """Ensure a source-bound default projection; this is the new UI boundary."""

    _root, service = _service(project_root)
    if (body.from_run_id is None) == (body.dataset is None):
        raise WorkbenchAPIError(
            status_code=422,
            code="NOTEBOOK_PROJECTION_SOURCE_INVALID",
            message="Provide exactly one of from_run_id or dataset.",
        )
    try:
        notebook = service.ensure_default_projection(
            from_run_id=body.from_run_id,
            dataset=(
                {"kind": "dataset", **body.dataset.model_dump()}
                if body.dataset is not None
                else None
            ),
            created_by=body.created_by,
            title=body.title,
        )
        return {
            **notebook.to_dict(),
            "current_family_head_run_id": (
                notebook.focused_run_id if notebook.projection_source and notebook.projection_source.kind == "run" else None
            ),
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks")
def list_notebooks_endpoint(project_root: str) -> list[dict[str, Any]]:
    _root, service = _service(project_root)
    return [notebook.to_dict() for notebook in service.list_notebooks()]


@router.get("/notebooks/{notebook_id}")
def get_notebook_endpoint(project_root: str, notebook_id: str) -> dict[str, Any]:
    _root, service = _service(project_root)
    try:
        return service.get_notebook(notebook_id).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc


@router.post("/notebooks/{notebook_id}/context/compile")
def compile_notebook_context_endpoint(
    project_root: str, notebook_id: str, focused_run_id: str | None = None
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        context, trace = _compile(root, service, notebook_id, focused_run_id=focused_run_id)
        return _context_packet(context)
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/propose")
def propose_options_endpoint(
    project_root: str, notebook_id: str, body: ProposeOptionsRequest
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        drafts = (
            [_draft(item) for item in body.drafts]
            if body.drafts
            else []
        )
        if not drafts:
            raise WorkbenchAPIError(
                status_code=409,
                code="NOTEBOOK_PLANNING_UNAVAILABLE",
                message="Typed notebook planning is introduced in the planning-agent slice.",
            )
        revisions = service.propose_batch(
            notebook_id,
            context=context,
            drafts=drafts,
            trace=trace,
        )
        return {
            "context": _context_packet(context),
            "options": [revision.to_dict() for revision in revisions],
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks/{notebook_id}/options")
def list_options_endpoint(
    project_root: str, notebook_id: str, focused_run_id: str | None = None
) -> dict[str, Any]:
    """Return the current options against one freshly compiled context.

    This is intentionally a read-time projection. It evaluates freshness for
    display and records the bounded context trace, but it never creates an
    option revision. That lets a browser remount without turning navigation
    into a new agent-generation event.
    """

    root, service = _service(project_root)
    try:
        context, trace = _compile(root, service, notebook_id, focused_run_id=focused_run_id)
        options = service.list_options(notebook_id, context=context)
        revisions = [
            replace(
                item.current_revision,
                lifecycle_status=item.lifecycle_status,
                freshness_status=item.freshness_status
                or item.current_revision.freshness_status,
            )
            for item in options
        ]
        return {
            "context": _context_packet(context),
            "options": [revision.to_dict() for revision in revisions],
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks/{notebook_id}/traces/{trace_id}")
def get_notebook_trace_endpoint(
    project_root: str, notebook_id: str, trace_id: str
) -> dict[str, Any]:
    """Replay the typed trace for a notebook without exposing other scopes."""

    root, service = _service(project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        events = TraceWriter.replay(root, trace_id)
        if events and any(
            event.get("scope", {}).get("notebook_id") != notebook_id
            or event.get("scope", {}).get("run_family_id") != notebook.run_family_id
            for event in events
        ):
            raise WorkbenchAPIError(
                status_code=404,
                code="NOTEBOOK_TRACE_SCOPE_MISMATCH",
                message="The requested trace does not belong to this notebook.",
            )
        return {"trace_id": trace_id, "events": events}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/revalidate")
def revalidate_option_endpoint(
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: RevalidateOptionRequest,
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        revision = service.revalidate_option(
            notebook_id,
            option_id,
            context=context,
            draft=_draft(body),
            trace=trace,
        )
        return {
            "context": _context_packet(context),
            "option": revision.to_dict(),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/confirm")
def confirm_option_endpoint(
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ConfirmOptionRequest,
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        execution = service.confirm(
            notebook_id,
            option_id,
            option_revision=body.option_revision,
            proposal_id=body.proposal_id,
            proposal_revision=body.proposal_revision,
            context=context,
            trace=trace,
        )
        return {"execution": execution.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/decision")
def record_decision_endpoint(
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: DecisionRequest,
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        trace = _trace(root, notebook.notebook_id, notebook.run_family_id)
        option = service.record_decision(
            notebook_id,
            option_id,
            decision=body.decision,
            actor=body.actor,
            edited_fields=body.edited_fields,
            note_ref=body.note_ref,
            trace=trace,
        )
        return {**option.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/execute")
def complete_option_execution_endpoint(
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ExecuteOptionRequest,
) -> dict[str, Any]:
    root, service = _service(project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        trace = _trace(root, notebook.notebook_id, notebook.run_family_id)
        outcome = service.complete_execution(
            notebook_id,
            option_id,
            execution_status=body.execution_status,
            run_id=body.run_id,
            produced_artifacts=body.produced_artifacts,
            error_code=body.error_code,
            trace=trace,
        )
        return {**outcome.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


__all__ = ["router"]
