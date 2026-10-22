"""HTTP seam for the v1.8.1 Agent Notebook lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import threading
from typing import Any

from fastapi import APIRouter, Request

from ..agent.context_compiler import (
    NotebookPlanningContextV1,
    attach_domain_memory_projection,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from ..agent.workflow_contracts import notebook_workflow_capability_ids
from ..agent.notebook import NotebookService
from ..agent.notebook.evidence import DataEvidencePackV1
from ..agent.notebook.errors import NotebookOptionError, OptionRevisionStale
from ..agent.model import CancellableOpenAICompatibleModelAdapter
from ..agent.notebook.planning_agent import (
    NotebookNoEligibleCapability,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    NotebookPlanningUnavailable,
    PlanningRefusal,
)
from ..analysis_ledger import record_ui_action
from ..egress import egress_project
from ..llm.config import load_llm_config
from ..agent.trace import (
    TraceWriter,
    record_compiled_context,
    record_domain_memory_retrieval,
)
from ..api_errors import WorkbenchAPIError
from ..engine.capabilities import build_capabilities
from .responses.notebook import (
    Dispatched,
    ExecutionCompleted,
    Materialized,
    NotebookOptions,
    NotebookProjection,
    NotebookTrace,
    NotebookView,
    OptionConfirmed,
    OptionDecisionRecorded,
    OptionRevalidated,
    PlanningCancelled,
    PlanningContextView,
)
from .typed_routes import TypedAPIRoute

from ..agent.planning.factory import (
    _baseline_planning_evidence,
    _no_eligible_capability_message,
    _supports_rerun_model_options,
)
from .notebook_route_models import (
    NotebookCreateRequest,
    NotebookProjectionRequest,
    RunDatasetNotebookProjectionRequest,
    NotebookFocusRequest,
    ProposeOptionsRequest,
    RevalidateOptionRequest,
    ConfirmOptionRequest,
    DecisionRequest,
    ExecuteOptionRequest,
)
from .notebook_domain_memory import _domain_memory_projection
from .notebook_packets import (  # noqa: F401  (moved; re-exported)
    _draft,
    _materializations_packet,
    _execution_results_packet,
)

router = APIRouter(route_class=TypedAPIRoute)

NOTEBOOK_PROVIDER_TIMEOUT_S = 300.0

# A local user can cancel a planning pass at any time. Do not impose a short
# aggregate deadline across its bounded provider turns: a valid inspect →
# correction → submit conversation can legitimately outlast it. Each provider
# call still has the five-minute timeout above, and inspection/correction turn
# limits remain owned by NotebookPlanningAgent.
NOTEBOOK_PLANNING_DEADLINE_S: float | None = None
_ACTIVE_PLANNING_ATTEMPTS: dict[
    tuple[str, str, str], asyncio.Task[Any]
] = {}
_ACTIVE_PLANNING_ATTEMPTS_LOCK = threading.Lock()

_TRACE_VERSIONS = {
    "app_commit": "local-workbench",
    "model_id": "notebook-planner",
    "prompt_version": "notebook-plan/1",
    "vocabulary_version": "notebook/1",
    "context_profile": "notebook-plan/v1",
}


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


def _service(request: Request, project_root: str) -> tuple[Path, NotebookService]:
    root = _project_root(project_root)
    from .notebook_runtime import notebook_service_from_state
    return root, notebook_service_from_state(root, request.app.state)


def _trace(
    root: Path,
    notebook_id: str,
    run_family_id: str,
    *,
    trace_id: str | None = None,
) -> TraceWriter:
    return TraceWriter(
        root,
        scope={
            "project_id": root.name,
            "notebook_id": notebook_id,
            "run_family_id": run_family_id,
        },
        versions=dict(_TRACE_VERSIONS),
        trace_id=trace_id,
    )


def _notebook_trace(root: Path, service: NotebookService, notebook_id: str) -> TraceWriter:
    """Open the Notebook's persisted trace, creating it exactly once."""

    notebook = service.get_notebook(notebook_id)
    trace_id = service.store.ensure_trace_id(notebook_id)
    return _trace(
        root,
        notebook.notebook_id,
        notebook.run_family_id,
        trace_id=trace_id,
    )


def _compile(
    root: Path,
    service: NotebookService,
    notebook_id: str,
    *,
    focused_run_id: str | None = None,
    request: Request | None = None,
) -> tuple[NotebookPlanningContextV1, TraceWriter]:
    notebook = service.get_notebook(notebook_id)
    trace = _notebook_trace(root, service, notebook.notebook_id)
    context = replace(
        service.compile_context(notebook_id, focused_run_id=focused_run_id), trace_id=trace.trace_id
    )
    projection = _domain_memory_projection(
        request,
        root,
        service,
        notebook_id,
        context=context,
    )
    if projection is not None:
        context = attach_domain_memory_projection(context, projection)
        record_domain_memory_retrieval(trace, projection)
    record_compiled_context(trace, context)
    return context, trace


def _context_packet(context: NotebookPlanningContextV1) -> dict[str, Any]:
    """Serialize the context plus the two distinct contract fingerprints."""

    packet = context.to_dict()
    packet["generation_context_hash"] = generation_context_hash(context)
    packet["freshness_dependency_fingerprint"] = freshness_dependency_fingerprint(context)
    if NOTEBOOK_PLANNING_DEADLINE_S is not None:
        packet["planning_deadline_s"] = NOTEBOOK_PLANNING_DEADLINE_S
    return packet


def _notebook_error(exc: NotebookOptionError) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=exc.status_code,
        code=exc.code,
        message=str(exc),
        details=exc.details,
    )


def _record_planning_terminal_error(
    trace: TraceWriter | None,
    *,
    code: str,
    fatal: bool,
    detail: str,
) -> None:
    """Persist one bounded terminal outcome for a planning attempt.

    A planning failure is a user-visible product event, not merely an HTTP
    response. Provider bodies and prompts never enter this record: the typed
    code is sufficient for replay, diagnosis, and the UI timeline.
    """

    if trace is not None:
        trace.emit(
            "operation.error",
            payload={"code": code, "fatal": fatal, "detail": detail},
        )


def _planning_agent(root: Path, service: NotebookService, notebook_id: str,
                    context: NotebookPlanningContextV1, trace: TraceWriter) -> NotebookPlanningAgent:
    from ..agent.planning.factory import build_planner
    # The same factory as Agent turns: a headless or offline runtime scope
    # (replay, fake model) governs Notebook planning too, with its own config.
    from ..agent.runtime_adapter import active_runtime, make_adapter, resolve_config
    config = resolve_config(load_llm_config)
    if not config.is_configured():
        raise NotebookPlanningUnavailable(config.configuration_error_message())
    notebook_config = (
        config
        if active_runtime() or config.timeout_s >= NOTEBOOK_PROVIDER_TIMEOUT_S
        else replace(config, timeout_s=NOTEBOOK_PROVIDER_TIMEOUT_S)
    )
    adapter = make_adapter(notebook_config, default_factory=CancellableOpenAICompatibleModelAdapter)

    async def run_planning_phase(phase):
        # The endpoint owns the project identity. The planning context is a
        # bounded model packet and must never be used to infer a storage root.
        from ..agent.core import AgentCore
        from ..agent.events import AgentEventStream
        from ..agent.session import JsonlSessionRepository

        repository = JsonlSessionRepository(root / "workbench")
        session_id = f"notebook_planning_{phase.episode_id}"
        repository.create_session(session_id, chain_id=notebook_id, role="planning")
        core = AgentCore(repository, AgentEventStream(repository.root), adapter, session_id=session_id)
        return await core.run_phase(phase)

    return build_planner(root, service, notebook_id, context, trace, adapter=adapter,
                         phase_runner=run_planning_phase, provider_timeout_s=notebook_config.timeout_s,
                         planning_timeout_s=NOTEBOOK_PLANNING_DEADLINE_S)


def _request_error(exc: Exception) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=422,
        code="NOTEBOOK_REQUEST_INVALID",
        message="The Notebook request could not be validated.",
        details={"reason": str(exc)},
    )


@router.post("/notebooks", status_code=201)
def create_notebook_endpoint(
    request: Request, project_root: str, body: NotebookCreateRequest
) -> NotebookView:
    _root, service = _service(request, project_root)
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
    request: Request, project_root: str, body: NotebookProjectionRequest
) -> NotebookProjection:
    """Ensure a source-bound default projection; this is the new UI boundary."""

    _root, service = _service(request, project_root)
    if (body.from_run_id is None) == (body.dataset is None):
        raise WorkbenchAPIError(
            status_code=422,
            code="NOTEBOOK_PROJECTION_SOURCE_INVALID",
            message="Provide exactly one of from_run_id or dataset.",
        )
    try:
        admitted_native = set(notebook_workflow_capability_ids())
        available_capabilities = tuple(
            str(entry["key"])
            for entry in build_capabilities().get("model_types", [])
            if isinstance(entry, dict) and entry.get("key") in admitted_native
        )
        notebook = service.ensure_default_projection(
            from_run_id=body.from_run_id,
            dataset=(
                {"kind": "dataset", **body.dataset.model_dump()}
                if body.dataset is not None
                else None
            ),
            created_by=body.created_by,
            title=body.title,
            available_capabilities=available_capabilities,
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


@router.post("/notebooks/projection/from-run-dataset")
def ensure_notebook_dataset_projection_from_run_endpoint(
    request: Request,
    project_root: str,
    body: RunDatasetNotebookProjectionRequest,
) -> NotebookProjection:
    """Start a fresh analysis from a selected run's server-verified upload."""

    _root, service = _service(request, project_root)
    try:
        admitted_native = set(notebook_workflow_capability_ids())
        available_capabilities = tuple(
            str(entry["key"])
            for entry in build_capabilities().get("model_types", [])
            if isinstance(entry, dict) and entry.get("key") in admitted_native
        )
        notebook = service.ensure_dataset_projection_from_run(
            from_run_id=body.from_run_id,
            created_by=body.created_by,
            title=body.title,
            available_capabilities=available_capabilities,
        )
        return {
            **notebook.to_dict(),
            "current_family_head_run_id": None,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks")
def list_notebooks_endpoint(request: Request, project_root: str) -> list[NotebookView]:
    _root, service = _service(request, project_root)
    return [notebook.to_dict() for notebook in service.list_notebooks()]


@router.get("/notebooks/{notebook_id}")
def get_notebook_endpoint(
    request: Request, project_root: str, notebook_id: str
) -> NotebookView:
    _root, service = _service(request, project_root)
    try:
        return service.get_notebook(notebook_id).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc


@router.put("/notebooks/{notebook_id}/focus")
def set_notebook_focus_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    body: NotebookFocusRequest,
) -> NotebookView:
    """Persist the user's intent/mode before the planner proposes options."""

    _root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        supplied = body.model_fields_set
        if not ({"goal", "interaction_mode"} & supplied):
            raise ValueError("provide a goal or interaction_mode")
        focus = dict(notebook.user_focus)
        if "goal" in supplied:
            if body.goal is None:
                focus.pop("goal", None)
            else:
                focus["goal"] = body.goal.strip()
        if "interaction_mode" in supplied and body.interaction_mode is not None:
            focus["interaction_mode"] = body.interaction_mode
        return service.set_focus(notebook_id, user_focus=focus).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/context/compile")
def compile_notebook_context_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    focused_run_id: str | None = None,
) -> PlanningContextView:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(
            root,
            service,
            notebook_id,
            focused_run_id=focused_run_id,
            request=request,
        )
        return _context_packet(context)
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


def _planning_attempt_key(
    root: Path,
    notebook_id: str,
    attempt_id: str,
) -> tuple[str, str, str]:
    return (str(root.resolve()), notebook_id, attempt_id)


async def _run_planning_agent(
    agent: NotebookPlanningAgent,
    *,
    context: NotebookPlanningContextV1,
    initial_evidence: DataEvidencePackV1,
):
    plan_async = getattr(agent, "plan_async", None)
    if callable(plan_async):
        return await plan_async(context=context, initial_evidence=initial_evidence)
    return await asyncio.to_thread(
        agent.plan,
        context=context,
        initial_evidence=initial_evidence,
    )


@router.delete("/notebooks/{notebook_id}/planning/{attempt_id}")
async def cancel_planning_attempt_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    attempt_id: str,
) -> PlanningCancelled:
    root, service = _service(request, project_root)
    service.get_notebook(notebook_id)
    key = _planning_attempt_key(root, notebook_id, attempt_id)
    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
        task = _ACTIVE_PLANNING_ATTEMPTS.get(key)
    if task is None or task.done():
        return {"attempt_id": attempt_id, "status": "not_active"}
    task.get_loop().call_soon_threadsafe(task.cancel)
    return {"attempt_id": attempt_id, "status": "cancelled"}


@router.post("/notebooks/{notebook_id}/options/propose")
async def propose_options_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    body: ProposeOptionsRequest,
) -> NotebookOptions:
    root, service = _service(request, project_root)
    trace: TraceWriter | None = None
    planning_started = False
    try:
        notebook = service.get_notebook(notebook_id)
        if notebook.user_focus.get("interaction_mode") == "action":
            if body.count not in {None, 1} or len(body.drafts) > 1:
                raise ValueError(
                    "Action mode permits exactly one checked Draft path"
                )
        context, trace = _compile(
            root,
            service,
            notebook_id,
            request=request,
        )
        recommendation_decision = None
        drafts = (
            [_draft(item) for item in body.drafts]
            if body.drafts
            else []
        )
        if not drafts:
            planning_started = True
            attempt_key = None
            current_task = None
            try:
                agent = _planning_agent(root, service, notebook_id, context, trace)
                initial_evidence = _baseline_planning_evidence(
                    service, notebook_id, context, trace
                )
                attempt_key = (
                    _planning_attempt_key(root, notebook_id, body.attempt_id)
                    if body.attempt_id is not None
                    else None
                )
                current_task = asyncio.current_task()
                if attempt_key is not None and current_task is not None:
                    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
                        active = _ACTIVE_PLANNING_ATTEMPTS.get(attempt_key)
                        if active is not None and not active.done():
                            raise WorkbenchAPIError(
                                status_code=409,
                                code="NOTEBOOK_PLANNING_ATTEMPT_ACTIVE",
                                message="Notebook planning attempt is already active",
                            )
                        _ACTIVE_PLANNING_ATTEMPTS[attempt_key] = current_task
                with egress_project(root):
                    result = await _run_planning_agent(
                        agent,
                        context=context,
                        initial_evidence=initial_evidence,
                    )
            except asyncio.CancelledError as exc:
                _record_planning_terminal_error(
                    trace,
                    code="NOTEBOOK_PLANNING_CANCELLED",
                    fatal=False,
                    detail="notebook planning cancelled by user",
                )
                raise WorkbenchAPIError(
                    status_code=409,
                    code="NOTEBOOK_PLANNING_CANCELLED",
                    message="Notebook planning was cancelled",
                ) from exc
            finally:
                if attempt_key is not None and current_task is not None:
                    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
                        if _ACTIVE_PLANNING_ATTEMPTS.get(attempt_key) is current_task:
                            _ACTIVE_PLANNING_ATTEMPTS.pop(attempt_key, None)
            if isinstance(result, PlanningRefusal):
                _record_planning_terminal_error(
                    trace,
                    code="NOTEBOOK_PLAN_REFUSED",
                    fatal=False,
                    detail=f"planner refused: {result.reason_code}",
                )
                raise WorkbenchAPIError(
                    status_code=422,
                    code="NOTEBOOK_PLAN_REFUSED",
                    message=result.message,
                    details={"reason_code": result.reason_code},
                )
            # Each bounded inspection is persisted separately by the service.
            # Persist the planner's final append-only view as well, because the
            # recommendation decision may cite evidence from more than one
            # inspection round and materialization must be able to replay that
            # exact pack by hash.
            final_evidence = getattr(result, "evidence_pack", None)
            if isinstance(final_evidence, DataEvidencePackV1):
                service.store.append_evidence_pack(notebook_id, final_evidence.to_dict())
            recommendation_evidence = (
                final_evidence
                if isinstance(final_evidence, DataEvidencePackV1)
                else initial_evidence
            )
            # Inspection calls persist Evidence Packs. Recompile the context
            # before pinning the v1.1 revision so evidence_pack_refs belong to
            # the same freshness fingerprint that the Draft gate will observe.
            context, trace = _compile(
                root,
                service,
                notebook_id,
                request=request,
            )
            drafts, recommendation_decision = service.derive_server_recommendation(
                notebook_id,
                context=context,
                drafts=tuple(result.option_drafts),
                batch_id=result.decision.batch_id,
                evidence_pack=recommendation_evidence,
            )
        revisions = service.propose_batch(
            notebook_id,
            context=context,
            drafts=drafts,
            trace=trace,
            batch_id=(recommendation_decision.batch_id if not body.drafts else None),
            recommendation_decision=(recommendation_decision if not body.drafts else None),
            # Provider-generated planning is the only path that may
            # deliberately revalidate existing stable option ids.  Manual
            # draft submission keeps the strict reuse-conflict behavior.
            revalidate_existing=not bool(body.drafts),
        )
        # The Notebook projection is the fold of every persisted option, not
        # only the candidates returned by the latest planning pass.  This is
        # especially important for explicit replans: unchanged/deferred
        # siblings must remain visible while the replanned stable ids expose
        # their new option revisions.
        projected = service.list_options(notebook_id, context=context)
        projected_revisions = [
            replace(
                item.current_revision,
                lifecycle_status=item.lifecycle_status,
                freshness_status=item.freshness_status
                or item.current_revision.freshness_status,
            )
            for item in projected
        ]
        return {
            "context": _context_packet(context),
            "options": [revision.to_dict() for revision in projected_revisions],
            "materializations": _materializations_packet(
                service, notebook_id, projected_revisions
            ),
            "execution_results": _execution_results_packet(
                service, notebook_id, projected_revisions
            ),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise _notebook_error(exc) from exc
    except NotebookNoEligibleCapability as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=409, code=exc.code, message=str(exc)) from exc
    except NotebookPlanningContractError as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=422, code=exc.code, message=str(exc)) from exc
    except NotebookPlanningUnavailable as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=409, code=exc.code, message=str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code="NOTEBOOK_REQUEST_INVALID",
                fatal=True,
                detail="notebook planning failed",
            )
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options")
def list_options_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    focused_run_id: str | None = None,
) -> NotebookOptions:
    """Return the current options against one freshly compiled context.

    This is a display projection. It evaluates freshness for display and
    records the bounded context trace, but it never creates an option
    revision. That lets a browser remount without turning navigation into a
    new agent-generation event. Because it records the trace it is a POST:
    GET routes never write (V1812-LOCAL-API-SECURITY), and only
    state-changing methods are held to the local Origin check.
    """

    root, service = _service(request, project_root)
    try:
        context, trace = _compile(
            root,
            service,
            notebook_id,
            focused_run_id=focused_run_id,
            request=request,
        )
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
            "materializations": _materializations_packet(service, notebook_id, revisions),
            "execution_results": _execution_results_packet(service, notebook_id, revisions),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks/{notebook_id}/traces/{trace_id}")
def get_notebook_trace_endpoint(
    request: Request, project_root: str, notebook_id: str, trace_id: str
) -> NotebookTrace:
    """Replay the typed trace for a notebook without exposing other scopes."""

    root, service = _service(request, project_root)
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
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: RevalidateOptionRequest,
) -> OptionRevalidated:
    root, service = _service(request, project_root)
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
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ConfirmOptionRequest,
) -> OptionConfirmed:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        current = service.store.read_option(notebook_id, option_id).current_revision
        proposal = service.store.read_option(notebook_id, option_id).current_stored_revision.proposal
        if proposal.operation_id == "operation.multi_step":
            result = service.confirm_and_execute_workflow(
                notebook_id,
                option_id,
                option_revision=body.option_revision,
                proposal_id=body.proposal_id,
                proposal_revision=body.proposal_revision,
                context=context,
                trace=trace,
            )
            return {**result, "trace_id": trace.trace_id}
        if current.materializable:
            if (body.option_revision, body.proposal_id, body.proposal_revision) != (
                current.option_revision,
                current.typed_proposal_id,
                current.typed_proposal_revision,
            ):
                raise OptionRevisionStale(
                    "materialization request does not match the current option revision",
                    option_id=option_id,
                    requested_revision=body.option_revision,
                    current_revision=current.option_revision,
                    reason="proposal_pin_mismatch",
                )
            result = service.materialize_option(
                notebook_id,
                option_id,
                context=context,
                trace=trace,
            )
            return {**result.to_dict(), "trace_id": trace.trace_id}
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


@router.post("/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute")
def confirm_and_execute_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ConfirmOptionRequest,
) -> Dispatched:
    """Explicitly dispatch one low-risk bound option through server CF4.

    The request carries only the current option/proposal pins.  Authorization,
    Run intent, dispatch reservation, and all result facts are server-owned.
    """

    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        current = service.store.read_option(notebook_id, option_id).current_revision
        if (body.option_revision, body.proposal_id, body.proposal_revision) != (
            current.option_revision,
            current.typed_proposal_id,
            current.typed_proposal_revision,
        ):
            raise OptionRevisionStale(
                "execution request does not match the current option revision",
                option_id=option_id,
                requested_revision=body.option_revision,
                current_revision=current.option_revision,
                reason="proposal_pin_mismatch",
            )
        dispatch = service.confirm_and_execute(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )
        record_ui_action(
            root, source="POST /notebooks/{notebook_id}/options/{option_id}/confirm-and-execute",
            steps=["run.submit"], summary=f"notebook={notebook_id} option={option_id}",
        )
        return {"dispatch": dispatch.to_dict(), "trace_id": trace.trace_id}
    except PermissionError as exc:
        raise WorkbenchAPIError(status_code=403, code="OPERATION_PERMISSION_DENIED", message=str(exc)) from exc
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/materialize")
def materialize_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
) -> Materialized:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        result = service.materialize_option(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )
        record_ui_action(
            root, source="POST /notebooks/{notebook_id}/options/{option_id}/materialize",
            steps=["run.submit"], summary=f"notebook={notebook_id} option={option_id}",
        )
        return {**result.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/decision")
def record_decision_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: DecisionRequest,
) -> OptionDecisionRecorded:
    root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        trace = _notebook_trace(root, service, notebook.notebook_id)
        option = service.record_decision(
            notebook_id,
            option_id,
            decision=body.decision,
            actor=body.actor,
            edited_fields=body.edited_fields,
            note_ref=body.note_ref,
            trace=trace,
        )
        # The service needs the full OptionView to fold lifecycle state, but
        # this public route is consumed by the frontend revision parser. Do
        # not leak the internal view (revisions, execution history, and
        # materialization details) as if it were a NotebookOptionRevision.
        return {**option.current_revision.to_dict(), "lifecycle_status": option.lifecycle_status}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/execute")
def complete_option_execution_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ExecuteOptionRequest,
) -> ExecutionCompleted:
    root, service = _service(request, project_root)
    try:
        if (
            body.execution_status is not None
            or body.produced_artifacts is not None
            or body.error_code is not None
        ):
            raise WorkbenchAPIError(
                status_code=409,
                code="NOTEBOOK_CLIENT_EXECUTION_FACTS_FORBIDDEN",
                message=(
                    "Notebook execution completion accepts only a server-owned "
                    "terminal run reference; status and artifact facts are not client-authored."
                ),
                details={"required_field": "run_id"},
            )
        if body.run_id is None:
            raise WorkbenchAPIError(
                status_code=422,
                code="NOTEBOOK_SERVER_RUN_REQUIRED",
                message="Notebook execution completion requires a server-owned run_id.",
            )
        notebook = service.get_notebook(notebook_id)
        trace = _notebook_trace(root, service, notebook.notebook_id)
        outcome = service.complete_execution_from_server_run(
            notebook_id,
            option_id,
            run_id=body.run_id,
            trace=trace,
        )
        return {**outcome.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


__all__ = ["router"]
