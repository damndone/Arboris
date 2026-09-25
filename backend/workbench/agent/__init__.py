"""Agent harness primitives for Workbench."""

from .core import (
    AgentCore,
    AgentCoreBusyError,
    AgentCoreBudgetError,
    AgentCoreContinuationError,
    AgentRunBudget,
)
from .chains import (
    ChainStore,
    ForkStore,
    RerunExecutionRequest,
    RerunExecutionResult,
    RerunExecutor,
)
from .events import AgentEvent, AgentEventStream
from .model import (
    ModelAdapter,
    ModelRequest,
    ModelStreamEvent,
    OpenAICompatibleModelAdapter,
)
from .operations import (
    OperationDefinition,
    OperationRecord,
    OperationRecordStore,
    OperationRecordTransitionError,
    OperationRegistry,
    OperationValidationError,
    UnknownOperationError,
)
from .proposals import (
    ProposalConfirmation,
    ProposalConfirmationError,
    ProposalRevision,
    ProposalStaleError,
    ProposalStore,
)
from .session import EntryRef, JsonlSessionRepository, SessionTreeEntry
from .tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    ToolRuntime,
)

# Importing leaf contracts must not bootstrap their consumers. In particular,
# the data manifest imports operations before the host resolver can consume it.
_LAZY_EXPORTS = {
    **dict.fromkeys((
        "AnalysisLoopContextError", "AnalysisLoopPacketPayloadError",
        "InspectArtifactPreviewRequest", "InspectDiagnosticsRequest",
        "InspectNodeContextRequest", "InspectOperationContractRequest",
        "InspectResultSummaryRequest", "NodeOperationContextProvider",
        "WorkbenchContextProvider", "inspect_analysis_loop_context",
        "parse_analysis_loop_packet_payloads",
    ), ".context_tools"),
    "AgentCommand": ".orchestrator",
    "WorkbenchOrchestrator": ".orchestrator",
}


def __getattr__(name: str):
    from importlib import import_module

    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "AgentCore",
    "AgentCoreBusyError",
    "AgentCoreBudgetError",
    "AgentCoreContinuationError",
    "AgentRunBudget",
    "AnalysisLoopContextError",
    "AnalysisLoopPacketPayloadError",
    "ChainStore",
    "AgentEvent",
    "AgentEventStream",
    "InspectNodeContextRequest",
    "InspectDiagnosticsRequest",
    "InspectArtifactPreviewRequest",
    "InspectOperationContractRequest",
    "InspectResultSummaryRequest",
    "NodeOperationContextProvider",
    "WorkbenchContextProvider",
    "inspect_analysis_loop_context",
    "parse_analysis_loop_packet_payloads",
    "AgentCommand",
    "OperationRecord",
    "OperationDefinition",
    "OperationRecordStore",
    "OperationRecordTransitionError",
    "OperationRegistry",
    "OperationValidationError",
    "UnknownOperationError",
    "EntryRef",
    "ForkStore",
    "JsonlSessionRepository",
    "ModelAdapter",
    "ModelRequest",
    "ModelStreamEvent",
    "OpenAICompatibleModelAdapter",
    "ProposalConfirmation",
    "ProposalConfirmationError",
    "ProposalRevision",
    "ProposalStaleError",
    "ProposalStore",
    "RerunExecutionRequest",
    "RerunExecutionResult",
    "RerunExecutor",
    "SessionTreeEntry",
    "ToolContext",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "ToolRuntime",
    "WorkbenchOrchestrator",
]
