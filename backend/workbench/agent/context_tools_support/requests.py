"""Requests: bounded read-only context projection."""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Iterable, Protocol
from ..operations import OperationRegistry
from ..tools import ToolDefinition

@dataclass(frozen=True)
class InspectNodeContextRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectOperationContractRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str
    operation_id: str
    operation_version: str = "v1"


@dataclass(frozen=True)
class InspectDiagnosticsRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectResultSummaryRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectTimeSeriesSummaryRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectRepeatedMeasuresRecipeRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectArtifactPreviewRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectDataSchemaRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectCompletedOperationsRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectNotebookWorkflowResultsRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str


@dataclass(frozen=True)
class InspectOperationArtifactRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str
    operation_record_id: str
    artifact_id: str


@dataclass(frozen=True)
class InspectProjectModelCoefficientsRequest:
    """A bounded, project-wide lookup of persisted model estimates."""

    run_ids: tuple[str, ...]
    terms: tuple[str, ...]


@dataclass(frozen=True)
class InspectProjectDatasetSchemaRequest:
    """A bounded, project-wide lookup of one persisted dataset schema."""

    run_id: str


@dataclass(frozen=True)
class ListProjectDatasetsRequest:
    """List graph-backed dataset identities with optional bounded detail."""

    detail_for: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class InspectProjectNumericSummaryRequest:
    """Read persisted aggregate numeric facts without exposing source rows."""

    run_id: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class InspectProjectModelFigureEvidenceRequest:
    """Read bounded numeric evidence for explicitly named model figures."""

    figures: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class InspectProjectLinearInteractionEffectsRequest:
    """Compute OLS interaction slopes from persisted coefficients and means."""

    effects: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class InspectProjectCoefficientTransformsRequest:
    """Apply a small closed set of numeric transforms to stored coefficients."""

    transforms: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class InspectProjectNotebookWorkflowResultsRequest:
    """Discover committed Notebook workflow receipts for visible project runs."""

    run_ids: tuple[str, ...]


@dataclass(frozen=True)
class InspectProjectStatisticalEvidenceRequest:
    """Read the persisted statistics evidence packet for visible project runs."""

    run_ids: tuple[str, ...]


class OperationContractUnavailableError(ValueError):
    """The selected node has no resolvable contract for the requested operation."""


class WorkbenchContextProvider(Protocol):
    """Explicit project-scoped source for read-only Agent context."""

    def tool_definitions(
        self,
        *,
        chain_id: str,
        session_id: str,
        operation_registry: OperationRegistry | None = None,
    ) -> Iterable[ToolDefinition]:
        """Return provider-owned, scope-bound read-only tool definitions."""


_FOREST_NODE_KEY = re.compile(r"[0-9a-f]{64}::(?P<node>.+)")


def _run_local_node_id(node_id: str) -> str:
    """``stage:raw`` from either ``stage:raw`` or the forest key
    ``<node_hash>::stage:raw`` the Main Agent sees in its project context.
    The run is named separately, so the hash adds nothing here."""

    match = _FOREST_NODE_KEY.fullmatch(node_id)
    return match.group("node") if match else node_id


_PROJECT_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")


_MAX_PUBLIC_MODEL_PREDICTORS = 32

