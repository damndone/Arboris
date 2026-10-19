"""agent turn routes: extracted HTTP responsibility."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from fastapi import Query
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.compaction import CompactionPolicy
from ..agent.core import AgentCore
from ..agent.plan_control import PlanControl, PlanControlError
from .agent_plan_requests import AgentPlanApproveRequest, AgentPlanPatchRequest
from .responses.agent import AgentPlanResponse, AgentPlanMutationResponse, AgentTurnStateResponse
from ..agent.runtime_adapter import runtime_config_identity
from ..agent.operations import OperationRegistry
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.tools import ToolRegistry
from ..api_errors import WorkbenchAPIError
from ..agent.protocol import CONTINUATION_NOTE
from ..agent.turn_runtime import turn_budget, turn_registry
from ..egress import egress_project
from .responses.agent import AgentEvents, AgentMessageQueued, AgentTurn, AgentTurnCancelling
from .agent_operation_routes import (_run_read_only_proposal, _tell_agent_finished_outcomes)
from .agent_route_context import (_ensure_current_global_protocol, _ensure_main_session, _get_session, _project_root, _refresh_main_context)
from .agent_route_permissions import (_project_permission_rules, _session_grants)
from .agent_route_projection import (_messages, _public_session)
from .agent_route_requests import (AgentContinueRequest, AgentResumeRequest, AgentSteerRequest, AgentTurnRequest)
from .agent_route_runtime import (_agent_llm_config, _agent_llm_configured, _agent_model_adapter, _reserve_turn)

from fastapi import APIRouter
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

@router.post("/agent/sessions/{session_id}/turns")
async def run_agent_turn(
    session_id: str,
    project_root: str,
    body: AgentTurnRequest,
) -> AgentTurn:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    turn_key = _reserve_turn(root, session_id)
    return await turn_registry.run_owned(turn_key, lambda: _run_reserved_agent_turn(
        root, session_id, body, repository, events, metadata, turn_key
    ))


@router.get("/agent/sessions/{session_id}/plan")
def get_agent_plan(session_id: str, project_root: str) -> AgentPlanResponse:
    """The conversation's current plan and version history."""
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    return PlanControl(root, repository, session_id).view()


def _plan_control_error(error: PlanControlError) -> WorkbenchAPIError:
    return WorkbenchAPIError(status_code=error.status, code=error.code,
                             message=str(error), details=error.details)


@router.post("/agent/sessions/{session_id}/plan/approve")
def approve_agent_plan(session_id: str, project_root: str, body: AgentPlanApproveRequest) -> AgentPlanMutationResponse:
    """Approve exactly the version the person reviewed, without a model call."""
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    try:
        return PlanControl(root, repository, session_id).approve(body.version)
    except PlanControlError as exc:
        raise _plan_control_error(exc) from exc


@router.patch("/agent/sessions/{session_id}/plan")
def revise_agent_plan(session_id: str, project_root: str, body: AgentPlanPatchRequest) -> AgentPlanMutationResponse:
    """Apply a versioned human edit; execution state is server-owned."""
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    try:
        return PlanControl(root, repository, session_id).revise(
            body.version, body.model_dump(exclude_unset=True, exclude={"version"}))
    except PlanControlError as exc:
        raise _plan_control_error(exc) from exc


@router.post("/agent/sessions/{session_id}/continue")
async def continue_agent_turn(
    session_id: str,
    project_root: str,
    body: AgentContinueRequest,
) -> AgentTurn:
    """Resume the Agent after a confirmed proposal finished (Ask every step)."""

    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    turn_key = _reserve_turn(root, session_id)
    return await turn_registry.run_owned(turn_key, lambda: _run_reserved_agent_turn(
        root, session_id, body, repository, events, metadata, turn_key, continuation=True
    ))


async def _run_reserved_agent_turn(
    root: Path,
    session_id: str,
    body: AgentTurnRequest,
    repository: Any,
    events: Any,
    metadata: dict[str, Any],
    turn_key: tuple[str, str],
    *,
    continuation: bool = False,
    resume_turn_id: str | None = None,
) -> dict[str, Any]:
    from ..agent.turn_journal import TurnJournal
    from ..agent.turn_store import TurnStore, TurnStoreError

    permission_rules = _project_permission_rules(root)
    if resume_turn_id is None:
        if any(record.session_id == session_id for record in TurnStore(root).list_active()):
            raise WorkbenchAPIError(
                status_code=409, code="AGENT_TURN_RECOVERY_REQUIRED",
                message="This conversation has an unfinished durable turn; resume or reconcile it before starting another.",
                details={"session_id": session_id},
            )
        _tell_agent_finished_outcomes(root, session_id)
    config = _agent_llm_config()
    if not _agent_llm_configured(config):
        raise WorkbenchAPIError(
            status_code=503,
            code="LLM_NOT_CONFIGURED",
            # A broken explicit store must say so — "configure a provider" is
            # the wrong advice when the operator already did and the pinned
            # file is missing.
            message=config.configuration_error_message(),
        )
    agent = AgentCore(
        repository,
        events,
        _agent_model_adapter(config),
        session_id=session_id,
        compaction_policy=CompactionPolicy.from_config(config.context_window_tokens, supports_1m=config.supports_1m),
        model_name=config.model,
        model_config_identity=runtime_config_identity(config),
        turn_journal=TurnJournal(TurnStore(root), repository, session_id=session_id,
                                 execution_mode=body.execution_mode or "ask"),
    )
    tool_context: dict[str, Any] | None = None
    if metadata.get("role") == "main" and resume_turn_id is None:
        _ensure_current_global_protocol(repository, session_id)
        if body.context_packet:
            _refresh_main_context(repository, session_id, body.context_packet)
    if metadata.get("role") == "chain":
        # Handoff §7 slice: the ROUTE registers the chain-scoped read-only
        # tools through the existing orchestrator boundary — the model never
        # discovers Workbench capabilities on its own, and a plain inspection
        # turn performs zero Workbench mutation. Proposals stay allowlisted to
        # registry-enabled operations and remain confirmation-gated audit records.
        operation_registry = OperationRegistry()
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id=_ensure_main_session(repository, root),
            operation_registry=operation_registry,
            context_provider=NodeOperationContextProvider(root),
        )
        orchestrator.execution_policy = body.execution_policy
        orchestrator.execution_mode = body.execution_mode
        if resume_turn_id is None and metadata.get("execution_mode") != body.execution_mode:
            repository.update_metadata(session_id, execution_mode=body.execution_mode)
            repository.append(session_id, "custom_message", {
                "message_type": "agent_execution_mode",
                "audience": "model",
                "name": "workbench_mode",
                "content": (
                    "Workbench: execution mode is now Auto within plan. Write the plan with update_plan; once the "
                    "person approves it, planned steps run without a card."
                    if body.execution_mode == "auto" else
                    "Workbench: execution mode is now Ask every step. Each step that changes something is shown "
                    "to the person as a card; read-only analysis runs at once."
                ),
            })
        orchestrator.permission_rules = permission_rules
        orchestrator.session_grants = _session_grants(repository, session_id)
        orchestrator.register_chain(str(metadata.get("chain_id")), session_id, agent)
        orchestrator.read_only_runner = lambda proposal, actor=None: _run_read_only_proposal(
            root, orchestrator, proposal, actor
        )
        tool_context = {
            "allowed_operations": operation_registry.natural_language_operation_ids(
                scope_requirements=("chain", "active_head")
            )
        }
    else:
        provider = NodeOperationContextProvider(root)
        registry = ToolRegistry()
        for definition in provider.global_tool_definitions(session_id=session_id):
            registry.register(definition)
        agent.attach_tools(registry.descriptors(), registry)
    turn_registry.activate(turn_key, agent)
    try:
        with egress_project(root):
            budget = turn_budget(body.execution_mode)
            if resume_turn_id is not None:
                await agent.resume(resume_turn_id, tool_context=tool_context)
            elif continuation:
                repository.append(session_id, "custom_message", {
                    "message_type": "agent_continuation",
                    "audience": "model",
                    "model_role": "user",
                    "name": "workbench_continuation",
                    "content": CONTINUATION_NOTE,
                })
                await agent.continue_(budget=budget, tool_context=tool_context)
            else:
                await agent.prompt(body.question.strip(), budget=budget, tool_context=tool_context)
    except TurnStoreError as exc:
        raise WorkbenchAPIError(status_code=409, code="AGENT_TURN_RECOVERY_REQUIRED",
            message="The durable turn needs recovery or reconciliation before continuing.",
            details={"reason": str(exc), "session_id": session_id}) from exc
    finally:
        turn_registry.deactivate(turn_key, agent)
    messages = _messages(repository, session_id)
    assistant = next(
        (message for message in reversed(messages) if message["role"] == "assistant"),
        None,
    )
    if assistant is None:
        raise WorkbenchAPIError(
            status_code=502,
            code="AGENT_NO_ASSISTANT_MESSAGE",
            message="Agent completed without producing an assistant message.",
        )
    return {
        "session": _public_session(repository, session_id, metadata, config),
        "assistant": assistant,
        "status": repository.get_metadata(session_id).get("status"),
    }


@router.get("/agent/sessions/{session_id}/turn-state")
def get_agent_turn_state(session_id: str, project_root: str) -> AgentTurnStateResponse:
    """Inspect compact durable state without executing tools or a provider."""
    from ..agent.turn_store import TurnStore

    root = _project_root(project_root)
    _get_session(root, session_id)
    return {"turns": [record.to_dict() for record in TurnStore(root).list_active()
                      if record.session_id == session_id]}


@router.post("/agent/sessions/{session_id}/resume")
async def resume_agent_turn(session_id: str, project_root: str, body: AgentResumeRequest) -> AgentTurn:
    """Resume the original command, not a new prompt/continuation budget."""
    from ..agent.turn_store import TurnStore, TurnStoreError

    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    try:
        record = TurnStore(root).get(body.turn_id)
    except (TurnStoreError, OSError) as exc:
        raise WorkbenchAPIError(status_code=404, code="AGENT_TURN_NOT_FOUND",
                                message="The durable turn was not found.") from exc
    if record.session_id != session_id:
        raise WorkbenchAPIError(status_code=404, code="AGENT_TURN_NOT_FOUND",
                                message="The durable turn was not found.")
    turn_key = _reserve_turn(root, session_id)
    request = AgentContinueRequest(execution_mode=record.execution_mode)
    return await turn_registry.run_owned(turn_key, lambda: _run_reserved_agent_turn(
        root, session_id, request, repository, events, metadata, turn_key, resume_turn_id=body.turn_id))


@router.post("/agent/sessions/{session_id}/abort")
async def abort_agent_turn(
    session_id: str,
    project_root: str,
) -> AgentTurnCancelling:
    """Request cancellation of the one active provider/tool turn for a session."""

    root = _project_root(project_root)
    _get_session(root, session_id)
    agent = turn_registry.get(root, session_id)
    if agent is None:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_TURN_NOT_ACTIVE",
            message="This Agent session has no active turn to stop.",
            details={"session_id": session_id},
        )
    await agent.abort()
    return {"status": "cancelling", "session_id": session_id}


@router.post("/agent/sessions/{session_id}/steer")
async def steer_agent_turn(session_id: str, project_root: str, body: AgentSteerRequest) -> AgentMessageQueued:
    """Change direction mid-turn: the text reaches the model at the next tool boundary (v1.9.1)."""

    return await _queue_for_active_turn(project_root, session_id, body.text, "steer")


@router.post("/agent/sessions/{session_id}/follow_up")
async def follow_up_agent_turn(session_id: str, project_root: str, body: AgentSteerRequest) -> AgentMessageQueued:
    """Queue a request to run after the current turn finishes (v1.9.1)."""

    return await _queue_for_active_turn(project_root, session_id, body.text, "follow_up")


async def _queue_for_active_turn(project_root: str, session_id: str, text: str, queue: str) -> dict[str, Any]:
    root = _project_root(project_root)
    _get_session(root, session_id)
    agent = turn_registry.get(root, session_id)
    if agent is None:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_TURN_NOT_ACTIVE",
            message="This Agent session has no active turn; send it as a new message instead.",
            details={"session_id": session_id},
        )
    await (agent.steer(text.strip()) if queue == "steer" else agent.follow_up(text.strip()))
    return {"status": "queued", "queue": queue, "session_id": session_id}


@router.get("/agent/sessions/{session_id}/events")
def get_agent_events(
    session_id: str,
    project_root: str,
    after_seq: int = Query(default=0, ge=0),
) -> AgentEvents:
    root = _project_root(project_root)
    _repository, events, _metadata = _get_session(root, session_id)
    return {
        "events": [
            event.to_dict()
            for event in events.replay(session_id, after_seq=after_seq)
        ]
    }

