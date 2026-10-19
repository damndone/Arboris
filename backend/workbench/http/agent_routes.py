"""Register Agent HTTP routes; implementations live with their responsibility owners."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4
from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from ..agent.analysis_loop_driver import forward_analysis_intent
from ..agent.audit_export import (
    build_agent_audit,
    render_agent_audit_html,
    render_agent_audit_markdown,
)
from ..agent.context_tools import (
    AnalysisLoopContextError,
    inspect_analysis_loop_context,
    parse_analysis_loop_packet_payloads,
)
from ..agent.chains import (
    ChainHeadConflict,
    ChainHeadUnavailable,
    ChainStore,
    ensure_chain_root,
)
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..analysis_loop.compare import ComparePacket
from ..analysis_loop.lifecycle import (
    AnalysisLoopProposalError,
    confirm_analysis_loop_proposal,
    create_analysis_loop_proposal,
)
from ..analysis_loop.plan import PlanBindingError, PlanDiff, PlanValidationError
from ..analysis_loop.recovery import RECOVERY_ACTIONS
from ..analysis_loop.resolver import (
    AnalysisLoopSourceResolutionError,
    resolve_analysis_loop_inputs,
    resolve_analysis_loop_run,
)
from ..analysis_loop.storage import (
    ComparePacketStore,
    PlanDiffStore,
    ValidationPacketStore,
)
from ..analysis_loop.validation import ValidationPacket
from ..agent.compaction import CompactionError, CompactionPolicy, compact as compact_session, estimate_messages_tokens
from ..agent.context import ContextBuilder
from ..agent.instructions import INSTRUCTIONS_NAME, compose as compose_instructions
from ..agent.operation_outcome import OUTCOME_NAME, TERMINAL as OUTCOME_TERMINAL, outcome as operation_outcome, outcome_text as operation_outcome_text, unfinished_outcomes
from ..agent.recall import RECALL_NAME, conversation_index, index_text as recall_index_text
from ..agent.core import AgentCore
from ..agent.plan_control import PlanControl, PlanControlError
from .agent_plan_requests import AgentPlanApproveRequest, AgentPlanPatchRequest
from .responses.agent import AgentPlanResponse, AgentPlanMutationResponse, AgentTurnStateResponse
from ..agent.events import AgentEventStream
from ..agent.model import OpenAICompatibleModelAdapter
from ..agent.runtime_adapter import (
    make_adapter as _runtime_model_adapter,
    resolve_config as _runtime_llm_config,
    runtime_configured as _runtime_configured,
    runtime_config_identity,
)
from ..agent.navigation import AgentNavigationProjector, AgentNavigationRef
from ..agent.operations import OperationRecordStore, OperationRegistry
from ..contracts.common.errors import OperationValidationError
from ..agent.execution import OperationClaimConflict
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.operation_requests import OperationRequest
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.session import EntryRef, JsonlSessionRepository
from ..agent.tools import ToolRegistry
from ..api_errors import WorkbenchAPIError
from ..control_plane import control_plane_capability
from ..agent.protocol import (
    CHAIN_AGENT_PROTOCOL,
    CONTINUATION_NOTE,
    MAIN_AGENT_PROTOCOL,
    chain_agent_protocol as _chain_agent_protocol,
    ensure_current_global_protocol,
    step_vocabulary_lines as _step_vocabulary_lines,
)
from ..agent.turn_runtime import (
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_S,
    MODE_BUDGETS,
    active_turn_key as _active_turn_key,
    turn_budget,
    turn_registry,
)
from ..agent.proposal_text import proposal_lines
from ..services.dataset_view import run_labels
from ..egress import egress_project
from ..llm.config import load_llm_config
from ..lineage.node_index import NODE_INDEX_FILENAME
from .responses.agent import (
    AgentActivity,
    AgentAuditExport,
    AgentCapabilities,
    AgentEvents,
    AgentMessageQueued,
    AgentOperationProjection,
    AgentProposalList,
    AgentSession,
    AgentSessionChange,
    AgentTurn,
    AgentTurnCancelling,
    AnalysisLoopContext,
    AnalysisLoopIntent,
    AnalysisLoopPackets,
    AnalysisLoopProposal,
    ForkProposal,
    NavigationProjectionResponse,
    OperationReconciled,
    ProposalConfirmed,
    ProposalStatus,
)
from .typed_routes import TypedAPIRoute

# Preserve initialization order before loading the extracted implementation owners.
from .agent_route_requests import (
    AgentFocus,
    AgentSessionCreateRequest,
    AgentTurnRequest,
    AgentContinueRequest,
    AgentProposalConfirmRequest,
    AgentProposalDeclineRequest,
    AgentProposalRevisionRequest,
    AgentForkProposalRequest,
    AnalysisLoopContextRequest,
    AnalysisLoopIntentRequest,
    AnalysisLoopProposalRequest,
    AgentEntryRequest,
    AgentChapterRequest,
    AgentCompactRequest,
    AgentResumeRequest,
    AgentSteerRequest,
)
from .agent_route_runtime import (
    _agent_llm_config,
    _agent_model_adapter,
    _agent_llm_configured,
    MAX_CONTEXT_CHARS,
    MAX_QUESTION_CHARS,
    _ACTIVE_TURNS,
    _RESERVED_TURNS,
    _TURN_RESERVATION_LOCK,
    _reserve_turn,
    _release_turn,
)
from .agent_route_context import (
    _project_root,
    _stores,
    _context_active_head,
    _canonicalize_chain_context_packet,
    _infer_minimal_chain_target,
    _ensure_chain_scope,
    _authoritative_active_head,
    _refresh_main_context,
    _context_serialized,
    _ensure_current_global_protocol,
    _ensure_main_session,
    _get_session,
)
from .agent_route_projection import (
    _messages,
    _context_usage,
    _context_fingerprint,
    _public_session,
    _public_proposals,
    _proposal_labels,
)
from .agent_route_proposals import (
    _proposal_for_session,
    _public_proposal,
    _current_data_columns_cast_fingerprint,
    _current_proposal_context_fingerprint,
)
from .agent_session_routes import (
    create_agent_session,
    _branch_message,
    _refuse_while_running,
    _before,
    rewind_agent_session,
    fork_agent_session,
    pin_agent_chapter,
    unpin_agent_chapter,
    get_agent_session,
    get_agent_audit_export,
    get_agent_proposals,
    get_agent_session_projection,
    get_agent_graph_navigation,
    get_agent_activity,
    get_agent_capabilities,
    compact_agent_session,
)
from .agent_analysis_routes import (
    _analysis_loop_run_facts,
    _analysis_loop_packet_bundle,
    get_analysis_loop_packets,
    _analysis_loop_packets_from_request,
    inspect_agent_analysis_loop_context,
    submit_agent_analysis_loop_intent,
    create_agent_analysis_loop_proposal,
)
from .agent_fork_routes import (
    _ensure_fork_source_session,
    create_agent_fork_proposal,
)
from .agent_operation_routes import (
    get_agent_operation_projection,
    decline_agent_proposal,
    revise_agent_proposal,
    _run_read_only_proposal,
    confirm_agent_proposal,
    _tell_agent_finished_outcomes,
    _tell_agent_the_outcome,
    reconcile_agent_operation,
)
from .agent_route_permissions import (
    _project_permission_rules,
    _session_grants,
    _grant_for_session,
)
from .agent_turn_routes import (
    run_agent_turn,
    get_agent_plan,
    _plan_control_error,
    approve_agent_plan,
    revise_agent_plan,
    continue_agent_turn,
    _run_reserved_agent_turn,
    get_agent_turn_state,
    resume_agent_turn,
    abort_agent_turn,
    steer_agent_turn,
    follow_up_agent_turn,
    _queue_for_active_turn,
    get_agent_events,
)
from .agent_session_routes import router as _router_0
from .agent_analysis_routes import router as _router_1
from .agent_fork_routes import router as _router_2
from .agent_operation_routes import router as _router_3
from .agent_turn_routes import router as _router_4
router = APIRouter(route_class=TypedAPIRoute)

router.include_router(_router_0)

router.include_router(_router_1)

router.include_router(_router_2)

router.include_router(_router_3)

router.include_router(_router_4)
