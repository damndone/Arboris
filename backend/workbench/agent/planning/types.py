"""Shared planning values and exception identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ...contracts.agent.notebook_option import EvidenceRef, ExpectedArtifact
from ..context_compiler import NotebookPlanningContextV1

if TYPE_CHECKING:
    from ..notebook.evidence import DataEvidencePackV1, InspectionRequest
    from ..notebook.proposal import TypedProposal


class NotebookPlanningUnavailable(RuntimeError):
    """The provider or typed planning boundary could not produce a plan."""

    code = "NOTEBOOK_PLANNING_UNAVAILABLE"


class NotebookPlanningTimeout(NotebookPlanningUnavailable):
    """The provider did not finish one bounded planning turn in time."""

    code = "NOTEBOOK_PLANNING_TIMEOUT"


class NotebookNoEligibleCapability(NotebookPlanningUnavailable):
    code = "NOTEBOOK_NO_ELIGIBLE_CAPABILITY"


class NotebookPlanningContractError(NotebookPlanningUnavailable):
    """The provider returned an untrusted or untyped planning payload."""

    code = "NOTEBOOK_PLANNING_CONTRACT_INVALID"


@dataclass(frozen=True)
class AgentOptionSubmission:
    rank: int
    rationale: str
    proposal: TypedProposal
    assumptions: tuple[str, ...] = ()
    expected_artifacts: tuple[ExpectedArtifact, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    comparative_claims: tuple[str, ...] = ()
    option_id: str | None = None
    capability_id: str = ""


@dataclass(frozen=True)
class PlanningResult:
    inspection_requests: tuple[InspectionRequest, ...]
    evidence_pack: DataEvidencePackV1
    submissions: tuple[AgentOptionSubmission, ...]
    option_drafts: tuple[Any, ...]
    decision: Any
    rounds: int


@dataclass(frozen=True)
class PlanningRefusal:
    """A typed, terminal refusal that never becomes an executable Draft."""

    reason_code: str
    message: str
    inspection_requests: tuple[InspectionRequest, ...]
    evidence_pack: DataEvidencePackV1
    submissions: tuple[AgentOptionSubmission, ...] = ()
    option_drafts: tuple[Any, ...] = ()
    decision: Any | None = None
    rounds: int = 0


InspectionExecutor = Callable[
    [tuple["InspectionRequest", ...], "DataEvidencePackV1"],
    "DataEvidencePackV1 | Awaitable[DataEvidencePackV1]",
]
ProposalValidator = Callable[[NotebookPlanningContextV1, AgentOptionSubmission], None]
