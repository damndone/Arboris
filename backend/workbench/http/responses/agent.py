"""Agent sessions, proposals, operations, navigation and the analysis loop.

Navigation refs and projections, events, hierarchy nodes, recovery actions and
intent decisions are the agent's own dataclasses (their JSON form is their
fields, None-valued optional fields omitted); proposals and operation records
are derived with view_of. Analysis-loop packets and plan diffs are versioned
contracts of their own and stay objects here.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from ...agent.analysis_loop_driver import AnalysisLoopDecision
from ...agent.events import AgentEvent
from ...agent.numeric_grounding import Finding
from ...agent.navigation import (
    AgentActivityEventItem,
    AgentActivityItem,
    AgentNavigationProjection,
    AgentNavigationRef,
)
from ...agent.proposals import ProposalConfirmation, ProposalDecision, ProposalRevision
from ...analysis_loop.recovery import RecoveryAction
from ...analysis_loop.validation import PacketStatus
from .common import JsonSchema, define_view, view_of, viewed
from .data_operations import OperationRecordView

# to_dict omits ``reason`` when there is none.
NavigationRefView = define_view(AgentNavigationRef, reason=NotRequired[str])
AgentEventView = viewed(AgentEvent)
FindingView = viewed(Finding)
RecoveryActionView = viewed(RecoveryAction)

ProposalConfirmationView = view_of(ProposalConfirmation, "ProposalConfirmationView", record_type=Literal["confirmation"])
ProposalDecisionView = view_of(ProposalDecision, "ProposalDecisionView", record_type=Literal["decision"])
PublicProposal = view_of(
    ProposalRevision,
    "PublicProposal",
    record_type=Literal["revision"],
    status=str,
    readable=list[str],
    confirmation=NotRequired[ProposalConfirmationView],
    decision=NotRequired[ProposalDecisionView],
)
ActivityOperationItem = view_of(AgentActivityItem, "ActivityOperationItem", kind=Literal["operation"])
ActivityEventItem = view_of(AgentActivityEventItem, "ActivityEventItem", kind=Literal["event"])
IntentDecisionView = view_of(AnalysisLoopDecision, "IntentDecisionView", omit=("packets",))


class HierarchyNodeView(TypedDict):
    """A node of the Agent hierarchy; leaves carry an empty ``children``."""

    ref: NavigationRefView
    status: str | None
    children: list[HierarchyNodeView]


NavigationProjectionView = view_of(
    AgentNavigationProjection, "NavigationProjectionView", hierarchy=NotRequired[HierarchyNodeView]
)


class NumericCheckUnverified(TypedDict):
    """Reply numbers no result supports, with the closest real values."""

    unverified: list[FindingView]


class NumericCheckFailed(TypedDict):
    """The check could not run; the reply carries an unchecked note."""

    error: str


class AgentMessage(TypedDict):
    entry_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    name: str | None
    stop_reason: str | None
    error: str | None
    numeric_check: NotRequired[NumericCheckUnverified | NumericCheckFailed]
    navigation: list[NavigationRefView]


class AgentSession(TypedDict):
    session_id: str
    role: Literal["main", "chain"] | None
    chain_id: str | None
    status: str | None
    context_fingerprint: str | None
    model: str | None
    provider_id: str | None
    context_window_tokens: int | None
    messages: list[AgentMessage]
    proposals: list[PublicProposal]


class AgentTurn(TypedDict):
    session: AgentSession
    assistant: AgentMessage
    status: str | None


class AgentTurnCancelling(TypedDict):
    status: Literal["cancelling"]
    session_id: str


class AgentAuditExport(TypedDict):
    """The session audit (a versioned audit document) with its renderings."""

    audit: dict[str, Any]
    markdown: str
    html: str


class AgentProposalList(TypedDict):
    proposals: list[PublicProposal]


class NavigationProjectionResponse(TypedDict):
    projection: NavigationProjectionView


class AgentActivity(TypedDict):
    activities: list[ActivityOperationItem]
    events: list[ActivityEventItem]
    hierarchy: HierarchyNodeView | None


class OperationCapability(TypedDict):
    operation_id: str
    operation_version: str
    effect_level: str
    scope: str
    scope_requirements: list[str]
    risk_level: str
    risk_authorization_policy: str
    confirmation_policy: str
    proposal_schema: JsonSchema
    editable_schema: JsonSchema
    executor: str
    reconciler: str
    diff_builder: str
    verification_builder: str
    ui_description: str
    example_prompts: list[str]
    natural_language_enabled: bool


class BoundaryItem(TypedDict):
    id: str
    label: str
    description: str


class CapabilityBoundary(TypedDict):
    advisory: list[BoundaryItem]
    unsupported: list[BoundaryItem]


class AgentCapabilities(TypedDict):
    project_root: str
    scope: str | None
    control_plane_mode: str
    workers: int
    capabilities: list[OperationCapability]
    boundary: CapabilityBoundary


class AnalysisSample(TypedDict):
    row_count: int | None
    row_order: list[Any]


class AnalysisLoopRunFacts(TypedDict):
    run_id: str
    status: str | None
    model: str | None
    contract_version: str | None
    covariance: str | None
    covariance_product: str | None
    covariance_wire: str | None
    entity_col: str | None
    stable_result_ids: list[str]
    primary_estimand: Any
    analysis_sample: AnalysisSample | None
    fingerprints: dict[str, Any]


class UnavailableRun(TypedDict):
    run_id: str
    status: Literal["unavailable"]


class AnalysisLoopPacketBundle(TypedDict):
    """One child run's terminal packets (each a versioned contract of its own)."""

    child_run_id: str
    source_run_id: str
    plan_diff: dict[str, Any] | None
    validation_packet: dict[str, Any]
    compare_packet: dict[str, Any] | None


class AnalysisLoopPackets(TypedDict):
    status: PacketStatus | Literal["absent"]
    run: AnalysisLoopRunFacts
    source_run: AnalysisLoopRunFacts | UnavailableRun | None
    packet: AnalysisLoopPacketBundle | None
    children: list[AnalysisLoopPacketBundle]


class AnalysisLoopContext(TypedDict):
    status: str
    context: dict[str, Any]
    registered_actions: list[RecoveryActionView]


class AnalysisLoopIntent(TypedDict):
    status: Literal["accepted", "rejected"]
    decision: IntentDecisionView
    registered_actions: list[RecoveryActionView]


class AnalysisLoopProposal(TypedDict):
    session_id: str
    proposal: PublicProposal
    plan_diff: dict[str, Any]
    registered_action: RecoveryActionView
    timings_ms: dict[str, float]
    status: Literal["pending"]


class ForkProposal(TypedDict):
    session_id: str
    source_session_entry_id: str
    proposal: PublicProposal
    navigation: NavigationRefView
    status: Literal["pending"]


class AgentOperationProjection(TypedDict):
    operation: OperationRecordView
    projection: NavigationProjectionView


class ProposalStatus(TypedDict):
    proposal: PublicProposal
    status: str


class ProposalConfirmed(TypedDict):
    proposal: PublicProposal
    operation: OperationRecordView
    status: str


class OperationReconciled(TypedDict):
    operation: OperationRecordView
    status: str


class AgentEvents(TypedDict):
    events: list[AgentEventView]
