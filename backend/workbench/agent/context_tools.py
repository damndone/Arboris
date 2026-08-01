"""Provider-backed, read-only Workbench context tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Protocol

from ..artifacts import read_json, sha256_file
from ..contracts.common.envelope import ContractError
from .chains import ChainHeadConflict, ChainStore
from ..diagnostic_preview import build_diagnostic_summary_preview
from ..diagnostic_preview.artifact_manifest import build_artifact_manifest
from ..graph_store import GraphStore, graph_to_json
from ..lineage.node_write_validation import build_rerun_operation_context
from ..lineage.op_contract import resolve_operation_contract
from ..lineage.run_inputs import read_run_inputs
from ..services.results_service import read_model_results
from ..analysis_loop.compare import ComparePacket
from ..analysis_loop.time_series_compare import read_time_series_artifacts as _read_time_series_artifacts
from ..analysis_loop.plan import PlanDiff
from ..analysis_loop.recovery import RECOVERY_ACTIONS
from ..analysis_loop.validation import ValidationPacket
from .context_compiler import resolve_registered_artifact
from .operations import OperationRecord, OperationRecordStore, OperationRegistry
from .recipes.registry import build_option_vocabulary, validate_model_options_patch
from .storage import read_jsonl
from .tools import ToolContext, ToolDefinition, ToolVisibleError


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


class NodeOperationContextProvider:
    """Read node-operation context from one explicitly scoped project."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()

    def _tool_active_head(self, chain_id: str, requested: str) -> str:
        """Use the durable head when this tool belongs to a managed Chain.

        Legacy read-only sessions have no ChainStore record yet and retain the
        existing selected-run behavior. Mutation canonicalization and HTTP
        confirmation require a managed record before they can proceed.
        """

        try:
            return ChainStore(
                self.project_root / "workbench", create=False
            ).resolve_active_head(
                chain_id,
                requested_active_head_run_id=requested,
            )
        except KeyError:
            return requested
        except ChainHeadConflict:
            raise

    def tool_definitions(
        self,
        *,
        chain_id: str,
        session_id: str,
        operation_registry: OperationRegistry | None = None,
    ) -> list[ToolDefinition]:
        """Expose the provider's read-only tools without coupling the registry."""

        registry = operation_registry or OperationRegistry()

        def inspect_node_context(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_node_context(
                InspectNodeContextRequest(
                    request_id=str(arguments.get("request_id") or "inspect-node-context"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_operation_contract(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_operation_contract(
                InspectOperationContractRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-operation-contract"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                    operation_id=str(arguments["operation_id"]),
                    operation_version=str(arguments.get("operation_version") or "v1"),
                ),
                operation_registry=registry,
            )

        def inspect_project_model_coefficients(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_project_model_coefficients(
                InspectProjectModelCoefficientsRequest(
                    run_ids=tuple(str(run_id) for run_id in arguments["run_ids"]),
                    terms=tuple(str(term) for term in arguments["terms"]),
                )
            )

        def inspect_diagnostics(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_diagnostics(
                InspectDiagnosticsRequest(
                    request_id=str(arguments.get("request_id") or "inspect-diagnostics"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_result_summary(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_result_summary(
                InspectResultSummaryRequest(
                    request_id=str(arguments.get("request_id") or "inspect-result-summary"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_time_series_summary(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_time_series_summary(
                InspectTimeSeriesSummaryRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-time-series-summary"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_repeated_measures_recipe(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_repeated_measures_recipe(
                InspectRepeatedMeasuresRecipeRequest(
                    request_id=str(arguments.get("request_id") or "inspect-repeated-measures-recipe"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_artifact_preview(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_artifact_preview(
                InspectArtifactPreviewRequest(
                    request_id=str(arguments.get("request_id") or "inspect-artifact-preview"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_data_schema(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_data_schema(
                InspectDataSchemaRequest(
                    request_id=str(arguments.get("request_id") or "inspect-data-schema"),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_completed_operations(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_completed_operations(
                InspectCompletedOperationsRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-completed-operations"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                ),
                chain_id=chain_id,
                session_id=session_id,
            )

        def inspect_operation_artifact(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_operation_artifact(
                InspectOperationArtifactRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-operation-artifact"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                    operation_record_id=str(arguments["operation_record_id"]),
                    artifact_id=str(arguments["artifact_id"]),
                ),
                chain_id=chain_id,
                session_id=session_id,
            )

        def inspect_notebook_workflow_results(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_notebook_workflow_results(
                InspectNotebookWorkflowResultsRequest(
                    request_id=str(
                        arguments.get("request_id")
                        or "inspect-notebook-workflow-results"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(
                        chain_id, str(arguments["active_head_run_id"])
                    ),
                )
            )

        def inspect_analysis_loop_context_tool(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            try:
                plan_diff, validation_packet, compare_packet = (
                    parse_analysis_loop_packet_payloads(
                        plan_diff=arguments.get("plan_diff"),
                        validation_packet=arguments.get("validation_packet"),
                        compare_packet=arguments.get("compare_packet"),
                    )
                )
                result = inspect_analysis_loop_context(
                    source_context=arguments.get("source_context", {}),
                    scope=str(arguments.get("scope", "")),
                    plan_diff=plan_diff,
                    validation_packet=validation_packet,
                    compare_packet=compare_packet,
                )
            except AnalysisLoopContextError as exc:
                return {
                    "status": "rejected",
                    "error": {"code": exc.code, "message": str(exc)},
                }
            return {
                "status": result["status"],
                "context": result,
                "registered_actions": [
                    action.to_dict() for action in RECOVERY_ACTIONS.values()
                ],
            }

        def submit_analysis_loop_intent(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            from .analysis_loop_driver import forward_analysis_intent

            decision = forward_analysis_intent(arguments["intent"])
            return {
                "status": "accepted" if decision.accepted else "rejected",
                "decision": decision.to_dict(),
                "registered_actions": [
                    action.to_dict() for action in RECOVERY_ACTIONS.values()
                ],
            }

        return [
            ToolDefinition(
                tool_id="inspect_data_schema",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_data_schema,
            ),
            ToolDefinition(
                tool_id="inspect_completed_operations",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_completed_operations,
            ),
            ToolDefinition(
                tool_id="inspect_notebook_workflow_results",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_notebook_workflow_results,
            ),
            ToolDefinition(
                tool_id="inspect_operation_artifact",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                        "operation_record_id",
                        "artifact_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                        "operation_record_id": {"type": "string"},
                        "artifact_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_operation_artifact,
            ),
            ToolDefinition(
                tool_id="inspect_analysis_loop_context",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["scope", "source_context"],
                    "properties": {
                        "scope": {
                            "type": "string",
                            "enum": ["inspect", "plan", "validation", "compare"],
                        },
                        "source_context": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "plan_diff": {"type": "object"},
                        "validation_packet": {"type": "object"},
                        "compare_packet": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_analysis_loop_context_tool,
            ),
            ToolDefinition(
                tool_id="submit_analysis_loop_intent",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["intent"],
                    "properties": {
                        "intent": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=submit_analysis_loop_intent,
            ),
            ToolDefinition(
                tool_id="inspect_node_context",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_node_context,
            ),
            ToolDefinition(
                tool_id="inspect_operation_contract",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                        "operation_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                        # Enumerate the registered operation identities so the
                        # model cannot guess ("rerun"/"run"/"ols" — observed in
                        # the live DeepSeek smoke) and fail closed repeatedly.
                        "operation_id": {
                            "type": "string",
                            "enum": registry.operation_ids(),
                        },
                        "operation_version": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                # Schema, not data. The 8192 shared by the other inspect tools
                # bounds row dumps; this one returns a pack's field vocabulary,
                # and a pack with 28 editable fields legitimately needs more
                # room. Truncating it does not protect context -- the Agent gets
                # `tool_output_budget_exceeded` and then guesses at field names,
                # which is how a live turn died before this was raised.
                max_output_budget=12288,
                handler=inspect_operation_contract,
            ),
            ToolDefinition(
                tool_id="inspect_diagnostics",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_diagnostics,
            ),
            ToolDefinition(
                tool_id="inspect_result_summary",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_result_summary,
            ),
            ToolDefinition(
                tool_id="inspect_project_model_coefficients",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_ids", "terms"],
                    "properties": {
                        "run_ids": {
                            "type": "array", "minItems": 1, "maxItems": 4,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 200},
                        },
                        "terms": {
                            "type": "array", "minItems": 1, "maxItems": 4,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 300},
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_project_model_coefficients,
            ),
            ToolDefinition(
                tool_id="inspect_time_series_summary",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                # Raised with inspect_operation_contract, and for the same
                # reason: what remains after removing the ~25,000 characters of
                # provenance row ids is all conclusions -- candidate tables
                # bounded at eight rows, scalar metrics, and six acceptance
                # verdicts. An ARMA-GARCH run simply has more *kinds* of
                # conclusion than the OLS-shaped result this default was sized
                # for, and truncating them made a live turn thrash and die.
                max_output_budget=12288,
                handler=inspect_time_series_summary,
            ),
            ToolDefinition(
                tool_id="inspect_repeated_measures_recipe",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_repeated_measures_recipe,
            ),
            ToolDefinition(
                tool_id="inspect_artifact_preview",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": [
                        "owner_run_id",
                        "op_node_id",
                        "active_head_run_id",
                    ],
                    "properties": {
                        "request_id": {"type": "string"},
                        "owner_run_id": {"type": "string"},
                        "op_node_id": {"type": "string"},
                        "active_head_run_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project", "chain"),
                max_output_budget=8192,
                handler=inspect_artifact_preview,
            ),
        ]

    def global_tool_definitions(self, *, session_id: str) -> list[ToolDefinition]:
        """Expose bounded project evidence readers to the Main Agent.

        The Main Agent remains unable to mutate a graph or run.  It may only
        inspect server-persisted aggregate evidence, without transferring model
        payloads or data rows into its context.
        """

        def inspect_project_model_coefficients(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_model_coefficients(
                InspectProjectModelCoefficientsRequest(
                    run_ids=tuple(str(run_id) for run_id in arguments["run_ids"]),
                    terms=tuple(str(term) for term in arguments["terms"]),
                )
            )

        def inspect_project_dataset_schema(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_dataset_schema(
                InspectProjectDatasetSchemaRequest(run_id=str(arguments["run_id"]))
            )

        def inspect_project_numeric_summary(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_numeric_summary(
                InspectProjectNumericSummaryRequest(
                    run_id=str(arguments["run_id"]),
                    columns=tuple(str(column) for column in arguments["columns"]),
                )
            )

        def inspect_project_model_figure_evidence(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_model_figure_evidence(
                InspectProjectModelFigureEvidenceRequest(
                    figures=tuple(
                        {
                            "run_id": str(item["run_id"]),
                            "artifact_id": str(item["artifact_id"]),
                        }
                        for item in arguments["figures"]
                    )
                )
            )

        def inspect_project_linear_interaction_effects(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_linear_interaction_effects(
                InspectProjectLinearInteractionEffectsRequest(
                    effects=tuple(
                        {
                            "run_id": str(effect["run_id"]),
                            "focal_term": str(effect["focal_term"]),
                            "interaction_term": str(effect["interaction_term"]),
                            "moderator_column": str(effect["moderator_column"]),
                        }
                        for effect in arguments["effects"]
                    )
                )
            )

        def inspect_project_coefficient_transforms(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_coefficient_transforms(
                InspectProjectCoefficientTransformsRequest(
                    transforms=tuple(
                        {
                            "run_id": str(item["run_id"]),
                            "term": str(item["term"]),
                            "transform": str(item["transform"]),
                        }
                        for item in arguments["transforms"]
                    )
                )
            )

        def inspect_project_notebook_workflow_results(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_notebook_workflow_results(
                InspectProjectNotebookWorkflowResultsRequest(
                    run_ids=tuple(str(run_id) for run_id in arguments["run_ids"])
                )
            )

        return [
            ToolDefinition(
                tool_id="inspect_project_model_coefficients",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_ids", "terms"],
                    "properties": {
                        "run_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 200},
                        },
                        "terms": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 16,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 300},
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_model_coefficients,
            ),
            ToolDefinition(
                tool_id="inspect_project_dataset_schema",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_id"],
                    "properties": {
                        "run_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_dataset_schema,
            ),
            ToolDefinition(
                tool_id="inspect_project_numeric_summary",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_id", "columns"],
                    "properties": {
                        "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                        "columns": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 300},
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_numeric_summary,
            ),
            ToolDefinition(
                tool_id="inspect_project_model_figure_evidence",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["figures"],
                    "properties": {
                        "figures": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "required": ["run_id", "artifact_id"],
                                "properties": {
                                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                    "artifact_id": {"type": "string", "minLength": 1, "maxLength": 300},
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_model_figure_evidence,
            ),
            ToolDefinition(
                tool_id="inspect_project_linear_interaction_effects",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["effects"],
                    "properties": {
                        "effects": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "required": [
                                    "run_id",
                                    "focal_term",
                                    "interaction_term",
                                    "moderator_column",
                                ],
                                "properties": {
                                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                    "focal_term": {"type": "string", "minLength": 1, "maxLength": 300},
                                    "interaction_term": {"type": "string", "minLength": 1, "maxLength": 300},
                                    "moderator_column": {"type": "string", "minLength": 1, "maxLength": 300},
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_linear_interaction_effects,
            ),
            ToolDefinition(
                tool_id="inspect_project_coefficient_transforms",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["transforms"],
                    "properties": {
                        "transforms": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "required": ["run_id", "term", "transform"],
                                "properties": {
                                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                    "term": {"type": "string", "minLength": 1, "maxLength": 300},
                                    "transform": {
                                        "type": "string",
                                        "enum": ["scale_0_01", "expm1_percent"],
                                    },
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_coefficient_transforms,
            ),
            ToolDefinition(
                tool_id="inspect_project_notebook_workflow_results",
                version="v1",
                input_schema={
                    "type": "object",
                    "required": ["run_ids"],
                    "properties": {
                        "run_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 16,
                            "uniqueItems": True,
                            "items": {"type": "string", "minLength": 1, "maxLength": 200},
                        },
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=("project",),
                max_output_budget=8192,
                handler=inspect_project_notebook_workflow_results,
            ),
        ]

    def inspect_node_context(
        self,
        request: InspectNodeContextRequest,
    ) -> dict[str, Any]:
        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        return {
            **canonical,
            "node": _bounded_node(node),
            "run": {
                "run_id": request.owner_run_id,
                "status": manifest.get("status"),
                "started_at": manifest.get("started_at")
                or manifest.get("created_at"),
            },
        }

    def inspect_operation_contract(
        self,
        request: InspectOperationContractRequest,
        *,
        operation_registry: OperationRegistry,
    ) -> dict[str, Any]:
        """Return the registry identity plus the lineage-owned node contract."""

        operation = operation_registry.require(
            request.operation_id,
            request.operation_version,
        )
        # Registry definitions also exist for workflow children so the
        # dispatcher can validate and execute them. They are not independent
        # Agent proposal surfaces: inspecting one against a model node would
        # otherwise (incorrectly) return that node's OLS/Rerun contract.
        # Return a bounded correction that preserves the parent workflow's
        # one-confirmation authorization boundary.
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        if (
            request.operation_id in WORKFLOW_STEP_SPEC_CONTRACTS
            and not operation.natural_language_enabled
        ):
            raise OperationContractUnavailableError(
                f"{request.operation_id}@{request.operation_version} is a workflow step, "
                "not a top-level proposal contract. Inspect operation.multi_step@v1 "
                "and declare this step in changes.steps."
            )
        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        contract = resolve_operation_contract(stage=node.get("stage"), manifest=manifest)
        if contract is not None:
            contract_payload = {
                "op_type": contract.op_type,
                "schema_id": contract.schema_id,
                "editable_schema": contract.editable_schema,
            }
            # A pack whose whole option surface is a single `model_options` JSON
            # control tells the Agent nothing about what may go inside it. Where
            # the pack publishes a vocabulary, attach it so a proposal can be
            # written against real field names, closed value sets, and server
            # caps instead of guesses.
            vocabulary = build_option_vocabulary(contract.op_type)
            if vocabulary is not None:
                contract_payload["option_vocabulary"] = vocabulary
        elif operation.contract_owner == "operation_registry" and operation.editable_schema:
            # The operation does not act on one node's editable surface, so no
            # lineage pack can answer for it — this definition is the contract.
            # Without this an Agent asked to compose a workflow could not read
            # the shape of the very operation it was told to propose, and spent
            # its whole step budget guessing.
            contract_payload = {
                "op_type": operation.operation_id,
                "schema_id": f"{operation.operation_id}@{operation.operation_version}",
                "editable_schema": operation.editable_schema,
                "contract_owner": "operation_registry",
            }
            if operation.vocabulary_builder is not None:
                contract_payload["step_vocabulary"] = operation.vocabulary_builder()
        elif "data_node" in operation.scope_requirements and operation.editable_schema:
            # Data operations have no per-node lineage contract: `resolve_
            # operation_contract` answers for model nodes only, and a cast's
            # editable shape is identical on every dataset node. The registry is
            # the contract owner here, so say so rather than raising — an Agent
            # allowed to propose an operation must be able to read its contract.
            #
            # Narrow on purpose: model.rerun's registry schema is a permissive
            # `additionalProperties` passthrough, so falling back to it when the
            # lineage contract is missing would claim "anything goes", which is
            # worse than failing closed.
            contract_payload = {
                "op_type": operation.operation_id,
                "schema_id": f"{operation.operation_id}@{operation.operation_version}",
                "editable_schema": operation.editable_schema,
                "contract_owner": "operation_registry",
            }
        else:
            raise OperationContractUnavailableError(
                f"no contract for {request.operation_id}@{request.operation_version}"
            )

        return {
            **canonical,
            "target_type": node.get("stage"),
            "operation": {
                "operation_id": operation.operation_id,
                "operation_version": operation.operation_version,
                "effect_level": operation.effect_level,
                "scope_requirements": list(operation.scope_requirements),
            },
            "contract": contract_payload,
            "node": _bounded_node(node),
        }

    def precheck_model_options_patch(
        self,
        *,
        owner_run_id: str,
        patch: dict[str, Any],
    ) -> None:
        """Raise the owning pack's structured error if the patch cannot execute.

        Silent when the node's pack declares no validator, or when the node's
        current contract cannot be resolved — refusing a patch on the basis of
        evidence we do not have would be worse than letting execution judge it.
        """

        run_root = self.project_root / "runs" / owner_run_id
        try:
            run_inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            run_inputs = {}
        try:
            manifest = read_json(run_root / "run_manifest.json")
        except (FileNotFoundError, OSError, TypeError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        contract = resolve_operation_contract(stage="model", manifest=manifest)
        if contract is not None:
            artifacts, _metadata = _read_time_series_artifacts(run_root)
            current = artifacts.get("ts.analysis_contract")
            if not isinstance(current, dict):
                current = _analysis_contract_from_run_inputs(run_inputs)
            if isinstance(current, dict):
                # A server-persisted analysis contract is more authoritative
                # than a legacy form's model_type.  This matters for reruns
                # whose historical form predates the selected model pack.
                validate_model_options_patch(
                    contract.op_type,
                    current_contract=current,
                    patch=patch,
                )
                return

        source_form = run_inputs.get("form") if isinstance(run_inputs, dict) else None
        if not isinstance(source_form, dict):
            return
        from ..model_options import ModelOptionsError
        from ..services.run_service import merge_form_overrides

        try:
            # This is the same pure merge/bind path the rerun service uses
            # before allocating a child run.  It validates any model pack
            # whose current form is the authoritative contract source.
            merge_form_overrides(
                source_form,
                {"model_options": dict(patch)},
            )
        except ModelOptionsError as exc:
            error = ContractError(str(exc))
            error.code = exc.code  # type: ignore[attr-defined]
            raise error from exc

    def inspect_diagnostics(
        self,
        request: InspectDiagnosticsRequest,
    ) -> dict[str, Any]:
        """Return a bounded, read-only view of the existing diagnostic preview."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        preview = build_diagnostic_summary_preview(
            run_root,
            manifest,
            read_model_results(run_root),
        )
        diagnostics, omitted_sections = _bounded_diagnostics(preview)
        return {
            **canonical,
            "node": _bounded_node(node),
            "diagnostics": diagnostics,
            "omitted_sections": omitted_sections,
        }

    def inspect_result_summary(
        self,
        request: InspectResultSummaryRequest,
    ) -> dict[str, Any]:
        """Return bounded result facts without exposing raw model result payloads."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        model_results = read_model_results(run_root)
        preview = build_diagnostic_summary_preview(run_root, manifest, model_results)
        summary, summary_status = _read_diagnostic_summary(run_root)
        result_summary = _bounded_result_summary(
            summary,
            summary_status=summary_status,
            preview=preview,
            model_results=model_results,
        )
        omitted_sections = ["raw_model_results"]
        if result_summary["coefficient_rows_omitted"]:
            omitted_sections.append("coefficient_rows")
        return {
            **canonical,
            "node": _bounded_node(node),
            "result_summary": result_summary,
            "omitted_sections": omitted_sections,
        }

    def inspect_project_model_coefficients(
        self,
        request: InspectProjectModelCoefficientsRequest,
    ) -> dict[str, Any]:
        """Return exact public coefficient evidence for explicitly named terms.

        This deliberately resolves neither a formula nor a raw-data artifact.
        The caller chooses a small set of known project runs and terms; the
        server projects only the persisted public statistics that answer that
        question.  Missing terms remain visible rather than being inferred.
        """

        models: list[dict[str, Any]] = []
        for run_id in request.run_ids:
            run_root = self._project_run_root(run_id)
            for result in read_model_results(run_root):
                public_model = _public_requested_model_coefficients(
                    run_id=run_id,
                    result=result,
                    requested_terms=request.terms,
                )
                if public_model is not None:
                    models.append(public_model)
        return {
            "models": models,
            "omitted_sections": ["raw_model_results", "raw_rows"],
        }

    def inspect_project_dataset_schema(
        self,
        request: InspectProjectDatasetSchemaRequest,
    ) -> dict[str, Any]:
        """Return bounded column metadata without raw rows or profile statistics."""

        run_root = self._project_run_root(request.run_id)
        try:
            profile = read_json(run_root / "staged" / "data_profile.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: no persisted dataset schema is "
                f"available for {request.run_id!r}."
            ) from exc
        if not isinstance(profile, dict):
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: the persisted dataset schema is invalid."
            )

        source_columns = profile.get("columns")
        if not isinstance(source_columns, dict):
            raise ToolVisibleError(
                "PROJECT_DATASET_SCHEMA_UNAVAILABLE: the persisted dataset schema has no columns."
            )
        columns: list[dict[str, Any]] = []
        for name, metadata in sorted(source_columns.items(), key=lambda item: str(item[0])):
            if not isinstance(name, str) or not name or not isinstance(metadata, dict):
                continue
            columns.append(
                {
                    "name": name,
                    "dtype": metadata.get("dtype") if isinstance(metadata.get("dtype"), str) else None,
                    "missing_rate": _public_stat_number(metadata.get("missing_rate")),
                    "unique_count": _public_positive_int(metadata.get("unique_count")),
                }
            )
        public_columns = columns[:64]
        return {
            "run_id": request.run_id,
            "row_count": _public_positive_int(profile.get("row_count")),
            "column_count": _public_positive_int(profile.get("column_count")),
            "columns": public_columns,
            "columns_omitted": max(len(columns) - len(public_columns), 0),
            "evidence_ref": {
                "run_id": request.run_id,
                "profile_ref": "staged/data_profile.json",
            },
            "omitted_sections": [
                "raw_rows",
                "correlations",
                "column_descriptives",
            ],
        }

    def inspect_project_numeric_summary(
        self,
        request: InspectProjectNumericSummaryRequest,
    ) -> dict[str, Any]:
        """Return persisted numeric aggregates for explicitly requested columns.

        The profile is already a server-produced aggregate.  This reader keeps
        that boundary intact: it discloses no rows, values, correlations, or
        unrequested columns, and it distinguishes an unavailable statistic from
        a zero-valued one.
        """

        run_root = self._project_run_root(request.run_id)
        try:
            profile = read_json(run_root / "staged" / "data_profile.json")
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ToolVisibleError(
                "PROJECT_NUMERIC_SUMMARY_UNAVAILABLE: no persisted numeric summary is "
                f"available for {request.run_id!r}."
            ) from exc
        source_columns = profile.get("columns") if isinstance(profile, dict) else None
        if not isinstance(source_columns, dict):
            raise ToolVisibleError(
                "PROJECT_NUMERIC_SUMMARY_UNAVAILABLE: the persisted dataset profile is invalid."
            )

        numeric_summary: list[dict[str, Any]] = []
        unavailable_columns: list[str] = []
        for column in sorted(set(request.columns)):
            metadata = source_columns.get(column)
            mean = _public_stat_number(metadata.get("mean")) if isinstance(metadata, dict) else None
            if mean is None:
                unavailable_columns.append(column)
                continue
            numeric_summary.append(
                {
                    "column": column,
                    "mean": mean,
                    "std": _public_stat_number(metadata.get("std")),
                }
            )
        return {
            "run_id": request.run_id,
            "numeric_summary": numeric_summary,
            "unavailable_columns": unavailable_columns,
            "evidence_ref": {
                "run_id": request.run_id,
                "profile_ref": "staged/data_profile.json",
            },
            "omitted_sections": ["raw_rows", "correlations"],
        }

    def inspect_project_model_figure_evidence(
        self,
        request: InspectProjectModelFigureEvidenceRequest,
    ) -> dict[str, Any]:
        """Return one bounded numeric projection per requested model figure."""

        evidence: list[dict[str, Any]] = []
        for item in request.figures:
            if set(item) != {"run_id", "artifact_id"} or not all(
                isinstance(value, str) and value for value in item.values()
            ):
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_INVALID: each figure needs one run_id and artifact_id."
                )
            run_id = item["run_id"]
            artifact_id = item["artifact_id"]
            run_root = self._project_run_root(run_id)
            try:
                index = read_json(run_root / "artifacts_index.json")
                records = index.get("artifacts") if isinstance(index, dict) else None
                record = next(
                    (
                        value
                        for value in records or []
                        if isinstance(value, dict) and value.get("artifact_id") == artifact_id
                    ),
                    None,
                )
            except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the persisted artifact index is unavailable."
                ) from exc
            if not isinstance(record, dict) or record.get("artifact_type") != "figure":
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: requested artifact is not a persisted figure."
                )
            models = [result for result in read_model_results(run_root) if isinstance(result, dict)]
            if len(models) != 1 or not isinstance(models[0].get("model_id"), str):
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the figure does not resolve to exactly one persisted model."
                )
            model_id = str(models[0]["model_id"])
            numeric_source = _bounded_model_figure_numeric_source(
                run_root,
                node_id=f"model:{model_id}",
                artifact_id=artifact_id,
            )
            if numeric_source is None:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the figure has no bounded numeric evidence."
                )
            try:
                from ..figure_context import resolve_figure_ai_context

                packet = resolve_figure_ai_context(
                    self.project_root, run_id=run_id, artifact_id=artifact_id
                )
            except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: figure metadata is unavailable."
                ) from exc
            figure = packet.get("figure") if isinstance(packet, dict) else None
            evidence.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "artifact_id": artifact_id,
                    "chart_type": figure.get("chart_type") if isinstance(figure, dict) else None,
                    "numeric_source": numeric_source,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "artifact_id": artifact_id,
                    },
                }
            )
        return {
            "figures": evidence,
            "omitted_sections": ["raw_rows", "raw_model_results", "image_pixels", "figure_paths"],
        }

    def inspect_project_linear_interaction_effects(
        self,
        request: InspectProjectLinearInteractionEffectsRequest,
    ) -> dict[str, Any]:
        """Compute OLS-scale interaction slopes from persisted public inputs.

        This is deliberately a read-only, server-side calculation rather than
        asking a language model to do floating-point arithmetic.  It is only
        available for OLS results, where the requested derivative on the
        recorded outcome scale is beta_focal + beta_interaction * mean(moderator).
        No standard error or interval is implied because that requires a
        covariance term which this bounded reader does not expose.
        """

        effects: list[dict[str, Any]] = []
        for item in request.effects:
            if set(item) != {
                "run_id",
                "focal_term",
                "interaction_term",
                "moderator_column",
            } or not all(isinstance(value, str) and value for value in item.values()):
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_INVALID: each effect must identify one "
                    "run, focal term, interaction term, and moderator column."
                )
            run_id = item["run_id"]
            focal_term = item["focal_term"]
            interaction_term = item["interaction_term"]
            moderator_column = item["moderator_column"]
            if len({focal_term, interaction_term, moderator_column}) != 3:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_INVALID: focal term, interaction term, "
                    "and moderator column must be distinct."
                )
            run_root = self._project_run_root(run_id)
            matches: list[tuple[str, dict[str, Any]]] = []
            for result in read_model_results(run_root):
                model_id = result.get("model_id")
                model_type = result.get("model_type")
                coefficients = result.get("coefficients")
                if (
                    not isinstance(model_id, str)
                    or not isinstance(model_type, str)
                    or not model_type.startswith("ols")
                    or not isinstance(coefficients, dict)
                ):
                    continue
                focal = coefficients.get(focal_term)
                interaction = coefficients.get(interaction_term)
                if (
                    isinstance(focal, dict)
                    and isinstance(interaction, dict)
                    and _public_stat_number(focal.get("estimate")) is not None
                    and _public_stat_number(interaction.get("estimate")) is not None
                ):
                    matches.append((model_id, coefficients))
            if len(matches) != 1:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: exactly one persisted OLS "
                    f"model in {run_id!r} must contain the requested focal and interaction terms."
                )
            try:
                profile = read_json(run_root / "staged" / "data_profile.json")
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: the moderator mean is not persisted."
                ) from exc
            columns = profile.get("columns") if isinstance(profile, dict) else None
            metadata = columns.get(moderator_column) if isinstance(columns, dict) else None
            moderator_mean = (
                _public_stat_number(metadata.get("mean"))
                if isinstance(metadata, dict)
                else None
            )
            if moderator_mean is None:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: the requested moderator has "
                    "no persisted numeric mean."
                )
            model_id, coefficients = matches[0]
            focal_estimate = _public_stat_number(coefficients[focal_term].get("estimate"))
            interaction_estimate = _public_stat_number(
                coefficients[interaction_term].get("estimate")
            )
            assert focal_estimate is not None and interaction_estimate is not None
            marginal_effect = float(focal_estimate) + float(interaction_estimate) * float(moderator_mean)
            if not math.isfinite(marginal_effect):
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: persisted inputs produced a "
                    "non-finite marginal effect."
                )
            effects.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "focal_term": focal_term,
                    "interaction_term": interaction_term,
                    "moderator_column": moderator_column,
                    "moderator_mean": moderator_mean,
                    "marginal_effect": marginal_effect,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "result_ref": f"model_results:{model_id}",
                        "profile_ref": "staged/data_profile.json",
                    },
                }
            )
        return {
            "effects": effects,
            "omitted_sections": ["raw_model_results", "raw_rows", "correlations"],
        }

    def inspect_project_coefficient_transforms(
        self,
        request: InspectProjectCoefficientTransformsRequest,
    ) -> dict[str, Any]:
        """Apply closed, auditable numeric transforms to one stored coefficient.

        The server returns mathematics only.  It does not infer that a term is
        logged, that an outcome is logged, or that a percentage interpretation
        is appropriate; those are separate conclusions which must be supported
        by the persisted model evidence the Agent cites alongside this result.
        """

        values: list[dict[str, Any]] = []
        for item in request.transforms:
            if set(item) != {"run_id", "term", "transform"} or not all(
                isinstance(value, str) and value for value in item.values()
            ):
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_INVALID: each item must identify "
                    "one run, term, and registered transform."
                )
            run_id = item["run_id"]
            term = item["term"]
            transform = item["transform"]
            if transform not in {"scale_0_01", "expm1_percent"}:
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_INVALID: transform must be "
                    "scale_0_01 or expm1_percent."
                )
            run_root = self._project_run_root(run_id)
            matches: list[tuple[str, float]] = []
            for result in read_model_results(run_root):
                model_id = result.get("model_id")
                coefficients = result.get("coefficients")
                coefficient = coefficients.get(term) if isinstance(coefficients, dict) else None
                estimate = (
                    _public_stat_number(coefficient.get("estimate"))
                    if isinstance(coefficient, dict)
                    else None
                )
                if isinstance(model_id, str) and estimate is not None:
                    matches.append((model_id, float(estimate)))
            if len(matches) != 1:
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_UNAVAILABLE: exactly one persisted "
                    f"model in {run_id!r} must contain {term!r}."
                )
            model_id, estimate = matches[0]
            value = estimate * 0.01 if transform == "scale_0_01" else math.expm1(estimate) * 100.0
            if not math.isfinite(value):
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_UNAVAILABLE: persisted input produced "
                    "a non-finite transformed value."
                )
            values.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "term": term,
                    "transform": transform,
                    "value": value,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "result_ref": f"model_results:{model_id}",
                    },
                }
            )
        return {
            "transforms": values,
            "omitted_sections": ["raw_model_results", "raw_rows"],
        }

    def inspect_project_notebook_workflow_results(
        self,
        request: InspectProjectNotebookWorkflowResultsRequest,
    ) -> dict[str, Any]:
        """Read committed workflow receipts for named, visible project runs."""

        workflows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for run_id in sorted(set(request.run_ids)):
            self._project_run_root(run_id)
            for workflow in self._notebook_workflow_results_for_run(run_id):
                workflow_id = workflow.get("workflow_id")
                plan_fingerprint = workflow.get("plan_fingerprint")
                if not isinstance(workflow_id, str) or not isinstance(plan_fingerprint, str):
                    continue
                key = (workflow_id, plan_fingerprint)
                if key in seen:
                    continue
                seen.add(key)
                workflows.append(workflow)
        workflows.sort(
            key=lambda workflow: (
                str(workflow.get("workflow_id") or ""),
                str(workflow.get("plan_fingerprint") or ""),
            )
        )
        payload: dict[str, Any] = {
            "workflows": workflows[:4],
            "omitted_sections": ["raw_artifact_payloads", "raw_rows"],
        }
        if len(workflows) > 4:
            payload["workflows_omitted"] = len(workflows) - 4
        return payload

    def inspect_time_series_summary(
        self,
        request: InspectTimeSeriesSummaryRequest,
    ) -> dict[str, Any]:
        """Return the public projection owned by the run's actual Recipe."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        try:
            run_inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            run_inputs = {}
        routing = manifest.get("model_routing")
        manifest_model_type = (
            routing.get("effective_model_type")
            if isinstance(routing, dict)
            else None
        )
        effective_model_type = manifest_model_type
        input_model_types: list[str] = []
        if isinstance(run_inputs, dict):
            for section_name in ("executed_payload", "confirmed_payload", "form"):
                section = run_inputs.get(section_name)
                model_type = section.get("model_type") if isinstance(section, dict) else None
                if isinstance(model_type, str) and model_type:
                    input_model_types.append(model_type)
        input_model_type_set = set(input_model_types)
        if len(input_model_type_set) > 1 or (
            manifest_model_type in {"time_series.ets", "time_series.arma_garch"}
            and input_model_type_set
            and input_model_type_set != {manifest_model_type}
        ):
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": manifest_model_type,
                },
                "time_series_summary": {
                    "available": False,
                    "reason_code": "TIME_SERIES_MODEL_IDENTITY_CONFLICT",
                },
                "compare": None,
                "omitted_sections": ["raw_series"],
            }
        if input_model_types and effective_model_type not in {
            "time_series.ets",
            "time_series.arma_garch",
        }:
            effective_model_type = input_model_types[0]

        if effective_model_type == "time_series.ets":
            from .recipe_contracts import recipe_contract

            registered = _resolve_verified_registered_artifact(
                run_root,
                artifact_id="ets_1",
                expected_type="model_result",
            )
            summary = (
                recipe_contract(effective_model_type).public_result_projection().build(
                    registered[0],
                    artifact_id="ets_1",
                    artifact_sha256=registered[1],
                )
                if registered is not None
                else {
                    "available": False,
                    "reason_code": "ETS_PUBLIC_RESULT_UNAVAILABLE",
                }
            )
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": effective_model_type,
                },
                "time_series_summary": summary,
                "compare": None,
                "omitted_sections": ["raw_series"],
            }

        if effective_model_type != "time_series.arma_garch":
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": effective_model_type,
                },
                "time_series_summary": {
                    "available": False,
                    "reason_code": "TIME_SERIES_PUBLIC_RESULT_UNSUPPORTED",
                },
                "compare": None,
                "omitted_sections": ["raw_series"],
            }

        from .recipe_contracts import recipe_contract

        artifacts, metadata = _read_time_series_artifacts(run_root)
        projection = recipe_contract(effective_model_type).public_result_projection()
        summary = projection.build(
            {"artifacts": artifacts},
            artifact_id=None,
            artifact_sha256=None,
        )
        if "ts.analysis_contract" not in artifacts:
            recovered = _analysis_contract_from_run_inputs(run_inputs)
            if recovered is not None:
                artifacts["ts.analysis_contract"] = recovered
            summary = projection.build(
                {"artifacts": artifacts},
                artifact_id=None,
                artifact_sha256=None,
            )
        persisted_source_run_id = run_inputs.get("rerun_of")
        declared_source_run_id = metadata.get("source_run_id")
        source_run_id = (
            persisted_source_run_id
            if isinstance(persisted_source_run_id, str) and persisted_source_run_id
            else declared_source_run_id
        )
        compare = None
        if isinstance(source_run_id, str) and source_run_id:
            source_root = self.project_root / "runs" / source_run_id
            source_artifacts, _ = _read_time_series_artifacts(source_root)
            if source_artifacts:
                from ..analysis_loop.time_series_compare import (
                    build_arma_garch_compare_packet,
                )

                compare = build_arma_garch_compare_packet(
                    source_run_id=source_run_id,
                    child_run_id=request.owner_run_id,
                    source_artifacts=source_artifacts,
                    child_artifacts=artifacts,
                    child_source_run_id=(
                        declared_source_run_id
                        if isinstance(declared_source_run_id, str)
                        else persisted_source_run_id
                    ),
                ).to_dict()
        omitted = summary.pop("omitted_sections", [])
        return {
            **canonical,
            "node": _bounded_node(node),
            "lineage": {
                "run_id": request.owner_run_id,
                "source_run_id": source_run_id,
                "node_id": metadata.get("node_id"),
                "dataset_ref": metadata.get("dataset_ref"),
                "dataset_hash": metadata.get("dataset_hash"),
                "contract_hash": metadata.get("contract_hash"),
            },
            "time_series_summary": summary,
            "compare": compare,
            "omitted_sections": omitted,
        }

    def inspect_repeated_measures_recipe(
        self,
        request: InspectRepeatedMeasuresRecipeRequest,
    ) -> dict[str, Any]:
        """Return only the sealed, read-only LMM explanation/recovery view."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        neutral = {
            "proposal": None,
            "plan_diff": None,
            "explanation": "未提供可用于生成说明的受控 LMM 诊断。",
        }
        if manifest.get("requested_model_type") != "linear_mixed_effects":
            recipe = neutral
        else:
            from .recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run

            recipe = build_repeated_measures_recipe_from_run(
                self.project_root / "runs", request.owner_run_id
            )
        return {
            **canonical,
            "node": _bounded_node(node),
            "repeated_measures_recipe": recipe,
            "omitted_sections": ["raw_model_results", "persistence_capability"],
        }

    def inspect_artifact_preview(
        self,
        request: InspectArtifactPreviewRequest,
    ) -> dict[str, Any]:
        """Return bounded artifact availability for the canonical node target."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        artifact_manifest = _bounded_artifact_manifest(
            build_artifact_manifest(run_root, read_model_results(run_root))
        )
        lifecycle = str(manifest.get("status") or "completed")
        if lifecycle in {"queued", "running"}:
            available = False
            preview_status = "pending"
        elif lifecycle in {"interrupted", "cancelled"}:
            available = False
            preview_status = "lifecycle_unavailable"
        else:
            available = True
            preview_status = "complete"
        counts = {
            "sections": len(artifact_manifest),
            "expected": sum(
                value.get("expected") is True for value in artifact_manifest.values()
            ),
            "available": sum(
                value.get("available") is True for value in artifact_manifest.values()
            ),
        }
        return {
            **canonical,
            "node": _bounded_node(node),
            "artifact_preview": {
                "available": available,
                "preview_status": preview_status,
                "run_lifecycle_status": lifecycle,
                "artifact_counts": counts,
                "artifact_manifest": artifact_manifest,
                "public_result_evidence": _node_public_result_evidence(
                    self.project_root,
                    owner_run_id=request.owner_run_id,
                    op_node_id=request.op_node_id,
                ),
                "figure_evidence": _bounded_run_figure_evidence(
                    self.project_root,
                    run_id=request.owner_run_id,
                    node=node,
                ),
            },
            "omitted_sections": ["raw_artifact_payloads", "raw_rows", "image_pixels"],
        }

    def inspect_completed_operations(
        self,
        request: InspectCompletedOperationsRequest,
        *,
        chain_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Discover completed operations only within the current Agent scope."""

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        records = self._completed_operation_records(
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            chain_id=chain_id,
            session_id=session_id,
        )
        omitted = max(len(records) - 8, 0)
        return {
            **canonical,
            "node": _bounded_node(node),
            "completed_operations": [
                _bounded_completed_operation(record) for record in records[:8]
            ],
            "omitted_counts": (
                {"completed_operations": omitted} if omitted else {}
            ),
            "omitted_sections": ["raw_artifact_payloads"],
        }

    def inspect_operation_artifact(
        self,
        request: InspectOperationArtifactRequest,
        *,
        chain_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Return one declared operation artifact through a public result view.

        The caller supplies durable ids, never a path.  The ids are accepted
        only after checking the current node/Chain scope and the operation's
        own emitted artifact list.
        """

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        records = self._completed_operation_records(
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            chain_id=chain_id,
            session_id=session_id,
        )
        record = next(
            (
                candidate
                for candidate in records
                if candidate.record_id == request.operation_record_id
            ),
            None,
        )
        if record is None:
            raise ToolVisibleError(
                "OPERATION_RESULT_NOT_IN_SCOPE: the completed operation is not "
                "available in this Chain and node scope."
            )
        allowed_artifacts = set(_operation_artifact_ids(record))
        if request.artifact_id not in allowed_artifacts:
            raise ToolVisibleError(
                "OPERATION_ARTIFACT_NOT_DECLARED: the artifact was not emitted "
                "by this completed operation."
            )
        artifact = resolve_registered_artifact(
            self.project_root / "runs" / request.owner_run_id,
            request.artifact_id,
        )
        if artifact is None:
            raise ToolVisibleError(
                "OPERATION_ARTIFACT_UNAVAILABLE: the declared artifact is not "
                "available from the active run."
            )
        artifact_type, artifact_sha256, payload = artifact
        public_result, omitted_sections = _public_operation_artifact_result(
            artifact_type,
            payload,
        )
        return {
            **canonical,
            "node": _bounded_node(node),
            "artifact_evidence": {
                "available": public_result is not None,
                "status": (
                    "complete"
                    if public_result is not None
                    else "public_result_not_available"
                ),
                "evidence_ref": {
                    "operation_record_id": record.record_id,
                    "artifact_id": request.artifact_id,
                    "artifact_type": artifact_type,
                    "sha256": artifact_sha256,
                },
                "result": public_result,
                "reason": (
                    None
                    if public_result is not None
                    else "This artifact type has no registered public Agent result view."
                ),
            },
            "omitted_sections": omitted_sections,
        }

    def inspect_notebook_workflow_results(
        self,
        request: InspectNotebookWorkflowResultsRequest,
    ) -> dict[str, Any]:
        """Discover committed Notebook workflows containing the selected run.

        Notebook confirmation has a separate append-only lifecycle from Agent
        operation records.  This bridge exposes only receipts that explicitly
        contain the currently selected run, then projects declared
        post-estimation artifacts through the same public-result boundary used
        elsewhere.  It never accepts a notebook id, option id, path, or source
        run id from the model.
        """

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        workflows = self._notebook_workflow_results_for_run(request.owner_run_id)
        omitted = max(len(workflows) - 4, 0)
        return {
            **canonical,
            "node": _bounded_node(node),
            "notebook_workflows": workflows[:4],
            "omitted_counts": {"notebook_workflows": omitted} if omitted else {},
            "omitted_sections": ["raw_artifact_payloads", "raw_rows"],
        }

    def _notebook_workflow_results_for_run(
        self,
        owner_run_id: str,
    ) -> list[dict[str, Any]]:
        """Read only committed receipts that prove membership of ``owner_run_id``."""

        notebooks_root = self.project_root / "notebooks"
        if not notebooks_root.is_dir():
            return []
        try:
            resolved_notebooks_root = notebooks_root.resolve()
        except OSError:
            return []

        workflows: list[dict[str, Any]] = []
        seen_receipts: set[tuple[str, str, str]] = set()
        for option_path in sorted(notebooks_root.glob("*/options/*.jsonl")):
            try:
                option_path.resolve().relative_to(resolved_notebooks_root)
                records = read_jsonl(option_path)
            except (OSError, ValueError):
                continue
            source_runs_by_revision = _notebook_source_runs_by_revision(records)
            for record in reversed(records):
                receipt = _committed_notebook_workflow_receipt(record)
                if receipt is None:
                    continue
                workflow_id = receipt["workflow_id"]
                option_revision = receipt["option_revision"]
                receipt_key = (str(option_path), workflow_id, str(option_revision))
                if receipt_key in seen_receipts:
                    continue
                branch_runs = receipt["branch_runs"]
                if owner_run_id not in {branch["run_id"] for branch in branch_runs}:
                    continue
                seen_receipts.add(receipt_key)
                source_run_id = source_runs_by_revision.get(option_revision)
                evidence, unavailable = self._notebook_post_estimation_evidence(
                    source_run_id=source_run_id,
                    artifact_ids=receipt["post_estimation_artifact_ids"],
                )
                workflows.append(
                    {
                        "workflow_id": workflow_id,
                        "plan_fingerprint": receipt["plan_fingerprint"],
                        "status": "completed",
                        "branch_runs": branch_runs[:8],
                        "post_estimation_evidence": evidence[:16],
                        "unavailable_post_estimation_artifact_count": unavailable,
                    }
                )
        return workflows

    def _notebook_post_estimation_evidence(
        self,
        *,
        source_run_id: str | None,
        artifact_ids: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        """Resolve receipt-declared source artifacts through a public view only."""

        if source_run_id is None:
            return [], len(artifact_ids)
        try:
            source_root = self._project_run_root(source_run_id)
        except ToolVisibleError:
            return [], len(artifact_ids)
        evidence: list[dict[str, Any]] = []
        unavailable = 0
        for artifact_id in artifact_ids[:16]:
            artifact = resolve_registered_artifact(source_root, artifact_id)
            if artifact is None:
                unavailable += 1
                continue
            artifact_type, sha256, payload = artifact
            public_result, _omitted = _public_operation_artifact_result(
                artifact_type, payload
            )
            if public_result is None:
                unavailable += 1
                continue
            evidence.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "evidence_ref": {
                        "run_id": source_run_id,
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "sha256": sha256,
                    },
                    "result": public_result,
                }
            )
        return evidence, unavailable + max(len(artifact_ids) - 16, 0)

    def _completed_operation_records(
        self,
        *,
        owner_run_id: str,
        op_node_id: str,
        chain_id: str,
        session_id: str,
    ) -> list[OperationRecord]:
        """Select only terminal, caller-owned parent operation records."""

        store = OperationRecordStore(self.project_root / "workbench", create=False)
        records = [
            record
            for record in store.list_records()
            if record.status == "completed"
            and record.chain_id == chain_id
            and record.agent_session_id == session_id
            and record.target.get("run_id") == owner_run_id
            and record.target.get("node_ref") == op_node_id
            and record.workflow_step_id is None
        ]
        return sorted(records, key=lambda record: (record.updated_at, record.record_id), reverse=True)

    def inspect_data_schema(
        self,
        request: InspectDataSchemaRequest,
    ) -> dict[str, Any]:
        """Return a dataset node's columns and dtypes, read-only.

        The Agent needs this to propose a data operation at all: without it the
        only way to name a column is to guess one out of display text. It
        deliberately does NOT return the artifact id — that stays a backend
        fact bound during proposal canonicalization, so a model can never point
        an operation at an artifact it named itself.
        """

        from ..data_operations import (
            DataColumnCastValidationError,
            resolve_data_column_cast_context,
        )

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        try:
            context = resolve_data_column_cast_context(
                self.project_root,
                source_run_id=request.owner_run_id,
                source_node_id=request.op_node_id,
            )
        except DataColumnCastValidationError as exc:
            return {
                **canonical,
                "node": _bounded_node(node),
                "data_schema": {"available": False, "reason": str(exc)},
            }
        return {
            **canonical,
            "node": _bounded_node(node),
            "data_schema": {
                "available": True,
                "row_count": context["row_count"],
                "columns": context["columns"],
                "downstream_invalidation": context["downstream_invalidation"],
            },
            "omitted_sections": ["source_artifact_id", "raw_rows"],
        }

    def _read_node_snapshot(
        self,
        *,
        request_id: str,
        owner_run_id: str,
        op_node_id: str,
        active_head_run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        runs_root = self.project_root / "runs"
        try:
            canonical = build_rerun_operation_context(
                runs_root,
                request_id=request_id,
                owner_run_id=owner_run_id,
                op_node_id=op_node_id,
                active_head_run_id=active_head_run_id,
            )
        except ValueError as exc:
            message = str(exc)
            prefix = message.partition(":")[0]
            if prefix not in {
                "invalid_operation_target",
                "context_stale",
                "context_mismatch",
            }:
                raise
            try:
                valid_ids = sorted(GraphStore(runs_root=runs_root).read(owner_run_id).nodes)
            except Exception:
                valid_ids = []
            targets = ", ".join(valid_ids[:24]) if valid_ids else "none"
            raise ToolVisibleError(
                f"{prefix.upper()}: {message}. Valid node IDs for run "
                f"{owner_run_id}: {targets}."
            ) from exc
        graph = GraphStore(runs_root=runs_root).read(owner_run_id)
        graph_json = graph_to_json(graph)
        node = graph_json["nodes"].get(op_node_id)
        if not isinstance(node, dict):
            valid_ids = ", ".join(sorted(graph_json["nodes"])[:24]) or "none"
            raise ToolVisibleError(
                "INVALID_OPERATION_TARGET: invalid_operation_target: op_node_id. "
                f"Valid node IDs for run {owner_run_id}: {valid_ids}."
            )
        manifest = _read_manifest(runs_root / owner_run_id)
        return canonical.model_dump(), node, manifest

    def _project_run_root(self, run_id: str) -> Path:
        """Resolve a project run identifier without accepting a filesystem path."""

        if not _PROJECT_RUN_ID_RE.fullmatch(run_id):
            raise ToolVisibleError(
                "PROJECT_RUN_ID_INVALID: run_ids must be project run identifiers, not paths."
            )
        runs_root = (self.project_root / "runs").resolve()
        run_root = (runs_root / run_id).resolve()
        if run_root.parent != runs_root or not run_root.is_dir():
            raise ToolVisibleError(
                f"PROJECT_RUN_NOT_FOUND: no completed project run is available for {run_id!r}."
            )
        return run_root


_PROJECT_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")
_MAX_PUBLIC_MODEL_PREDICTORS = 32


def _notebook_source_runs_by_revision(
    records: list[dict[str, Any]],
) -> dict[str, str]:
    """Recover server-recorded source runs without trusting a caller value."""

    source_runs: dict[str, str] = {}
    for record in records:
        if record.get("record_type") != "revision":
            continue
        revision = _notebook_option_revision_key(record.get("option_revision"))
        proposal = record.get("typed_proposal")
        target = proposal.get("target") if isinstance(proposal, dict) else None
        source_run_id = target.get("run_id") if isinstance(target, dict) else None
        if revision is None or not isinstance(source_run_id, str):
            continue
        if _PROJECT_RUN_ID_RE.fullmatch(source_run_id):
            source_runs[revision] = source_run_id
    return source_runs


def _committed_notebook_workflow_receipt(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate the minimal receipt shape needed for bounded read-only evidence."""

    if (
        record.get("record_type") != "execution_result"
        or record.get("execution_status") != "succeeded"
        or record.get("committed") is not True
    ):
        return None
    option_revision = _notebook_option_revision_key(record.get("option_revision"))
    execution = record.get("workflow_execution")
    if option_revision is None or not isinstance(execution, dict):
        return None
    workflow_id = execution.get("workflow_id")
    plan_fingerprint = execution.get("plan_fingerprint")
    if (
        not isinstance(workflow_id, str)
        or not workflow_id
        or len(workflow_id) > 300
        or not isinstance(plan_fingerprint, str)
        or not plan_fingerprint
        or len(plan_fingerprint) > 300
        or execution.get("status") != "completed"
    ):
        return None
    raw_branches = execution.get("branch_runs")
    if not isinstance(raw_branches, list) or not raw_branches:
        return None
    branch_runs: list[dict[str, str]] = []
    for branch in raw_branches:
        if not isinstance(branch, dict):
            return None
        branch_id = branch.get("branch_id")
        run_id = branch.get("run_id")
        if (
            not isinstance(branch_id, str)
            or not branch_id
            or len(branch_id) > 300
            or not isinstance(run_id, str)
            or _PROJECT_RUN_ID_RE.fullmatch(run_id) is None
        ):
            return None
        branch_runs.append({"branch_id": branch_id, "run_id": run_id})
    raw_artifact_ids = execution.get("post_estimation_artifact_ids")
    if not isinstance(raw_artifact_ids, list):
        return None
    artifact_ids = [
        artifact_id
        for artifact_id in raw_artifact_ids
        if isinstance(artifact_id, str) and artifact_id and len(artifact_id) <= 500
    ]
    if len(artifact_ids) != len(raw_artifact_ids):
        return None
    return {
        "option_revision": option_revision,
        "workflow_id": workflow_id,
        "plan_fingerprint": plan_fingerprint,
        "branch_runs": branch_runs,
        "post_estimation_artifact_ids": list(dict.fromkeys(artifact_ids)),
    }


def _notebook_option_revision_key(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return str(int(value))
    return None


def _public_requested_model_coefficients(
    *,
    run_id: str,
    result: dict[str, Any],
    requested_terms: tuple[str, ...],
) -> dict[str, Any] | None:
    """Project one stored result into term-specific, non-row evidence."""

    model_id = result.get("model_id")
    coefficients = result.get("coefficients")
    if not isinstance(model_id, str) or not model_id or not isinstance(coefficients, dict):
        return None

    public_coefficients: list[dict[str, Any]] = []
    missing_terms: list[str] = []
    for term in requested_terms:
        coefficient = coefficients.get(term)
        if not isinstance(coefficient, dict):
            missing_terms.append(term)
            continue
        public_coefficients.append(
            {
                "term": term,
                "estimate": _public_stat_number(coefficient.get("estimate")),
                "std_error": _public_stat_number(coefficient.get("std_error")),
                "p_value": _public_stat_number(coefficient.get("p_value")),
                "ci_lower": _public_stat_number(coefficient.get("ci_lower")),
                "ci_upper": _public_stat_number(coefficient.get("ci_upper")),
                "source_id": (
                    coefficient.get("source_id")
                    if isinstance(coefficient.get("source_id"), str)
                    else None
                ),
            }
        )

    predictors = result.get("x_columns")
    public_predictors = (
        [item for item in predictors if isinstance(item, str)][:_MAX_PUBLIC_MODEL_PREDICTORS]
        if isinstance(predictors, list)
        else []
    )
    predictor_count = (
        len([item for item in predictors if isinstance(item, str)])
        if isinstance(predictors, list)
        else 0
    )
    covariance_evidence = result.get("covariance_evidence")
    covariance_evidence = (
        covariance_evidence if isinstance(covariance_evidence, dict) else {}
    )
    confidence_level = _public_probability(covariance_evidence.get("confidence_level"))
    cluster_variable = covariance_evidence.get("cluster_variable")
    cluster_count = _public_positive_int(covariance_evidence.get("cluster_count"))
    return {
        "run_id": run_id,
        "model_id": model_id,
        "model_type": result.get("model_type") if isinstance(result.get("model_type"), str) else None,
        "nobs": _public_positive_int(result.get("nobs")),
        "r_squared": _public_stat_number(result.get("r_squared")),
        "r_squared_adj": _public_stat_number(result.get("r_squared_adj")),
        "df_model": _public_stat_number(result.get("df_model")),
        "df_resid": _public_stat_number(result.get("df_resid")),
        "outcome": result.get("y_column") if isinstance(result.get("y_column"), str) else None,
        "predictors": public_predictors,
        "predictors_omitted": max(predictor_count - len(public_predictors), 0),
        "entity_col": result.get("entity_col") if isinstance(result.get("entity_col"), str) else None,
        "time_col": result.get("time_col") if isinstance(result.get("time_col"), str) else None,
        "covariance": result.get("covariance") if isinstance(result.get("covariance"), str) else None,
        "covariance_estimator": (
            result.get("covariance_estimator")
            if isinstance(result.get("covariance_estimator"), str)
            else None
        ),
        "confidence_interval": {
            "level": confidence_level,
            "method": (
                covariance_evidence.get("confidence_interval_method")
                if isinstance(covariance_evidence.get("confidence_interval_method"), str)
                else None
            ),
        },
        "covariance_details": {
            "cluster_variable": cluster_variable if isinstance(cluster_variable, str) else None,
            "cluster_count": cluster_count,
            "cluster_entity": (
                covariance_evidence.get("cluster_entity")
                if isinstance(covariance_evidence.get("cluster_entity"), bool)
                else None
            ),
        },
        "coefficients": public_coefficients,
        "missing_terms": missing_terms,
        "evidence_ref": {
            "run_id": run_id,
            "model_id": model_id,
            "result_ref": f"model_results:{model_id}",
        },
    }


def _public_stat_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def _public_probability(value: Any) -> float | None:
    number = _public_stat_number(value)
    if number is None or not 0 < float(number) < 1:
        return None
    return float(number)


def _public_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _read_manifest(run_root: Path) -> dict[str, Any]:
    try:
        value = read_json(run_root / "run_manifest.json")
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _analysis_contract_from_run_inputs(
    run_inputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover the frozen analysis contract from persisted run inputs.

    A run that failed before its artifacts were written still has the options
    it was asked to execute, and those options are the only honest basis for
    judging a patch against that node.
    """

    for section_name in ("executed_payload", "confirmed_payload", "form"):
        section = run_inputs.get(section_name)
        options = section.get("model_options") if isinstance(section, dict) else None
        if not isinstance(options, dict):
            continue
        try:
            from ..contracts.model.arma_garch import ArmaGarchAnalysisContract

            return ArmaGarchAnalysisContract.from_dict(options).to_dict()
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _read_diagnostic_summary(run_root: Path) -> tuple[dict[str, Any] | None, str]:
    summary_path = run_root / "diagnostic_summary.json"
    if not summary_path.is_file():
        return None, "missing"
    try:
        value = read_json(summary_path)
    except (OSError, ValueError):
        return None, "malformed"
    if not isinstance(value, dict):
        return None, "malformed"
    return value, "complete"


def _bounded_result_summary(
    summary: dict[str, Any] | None,
    *,
    summary_status: str,
    preview: dict[str, Any],
    model_results: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = summary.get("model_identity") if isinstance(summary, dict) else None
    identity = identity if isinstance(identity, dict) else {}
    x_variables = identity.get("x_variables")
    if not isinstance(x_variables, list):
        x_variable_count = identity.get("x_variable_count")
    else:
        x_variable_count = len(x_variables)

    model_identity = {
        key: value
        for key, value in {
            "model_family": identity.get("model_family"),
            "model_label": identity.get("model_label"),
            "y_variable": identity.get("y_variable"),
            "n_observations": identity.get("n_observations"),
            "x_variable_count": x_variable_count,
        }.items()
        if value is not None
    }

    quality = summary.get("model_quality") if isinstance(summary, dict) else None
    quality = quality if isinstance(quality, dict) else {}
    raw_metrics = quality.get("metrics")
    metric_items = raw_metrics.items() if isinstance(raw_metrics, dict) else ()
    metrics = {
        str(key): value
        for key, value in metric_items
        if isinstance(raw_metrics, dict)
        and isinstance(key, str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    }
    primary_metric_keys = quality.get("primary_metric_keys")
    if not isinstance(primary_metric_keys, list):
        primary_metric_keys = []
    primary_metric_keys = [key for key in primary_metric_keys if isinstance(key, str)]

    coefficient_summary = summary.get("coefficients_summary") if isinstance(summary, dict) else None
    coefficient_summary = (
        coefficient_summary if isinstance(coefficient_summary, dict) else {}
    )
    raw_rows = coefficient_summary.get("rows")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    coefficient_rows = [
        _bounded_coefficient_row(row)
        for row in raw_rows
        if isinstance(row, dict)
    ]
    coefficient_rows = [row for row in coefficient_rows if row]
    coefficient_rows_omitted = max(len(coefficient_rows) - 8, 0)

    run_status = preview.get("run_status")
    return {
        "available": summary_status == "complete" and preview.get("available") is True,
        "summary_status": summary_status,
        "run_lifecycle_status": preview.get("run_lifecycle_status"),
        "trust_label": preview.get("trust_label"),
        "model_identity": model_identity,
        "metrics": metrics,
        "primary_metric_keys": primary_metric_keys,
        "coefficient_rows": coefficient_rows[:8],
        "coefficient_row_count": len(coefficient_rows),
        "coefficient_rows_omitted": coefficient_rows_omitted,
        "full_table_ref": (
            coefficient_summary.get("full_table_ref")
            if isinstance(coefficient_summary.get("full_table_ref"), str)
            else None
        ),
        "interpretation_mode": (
            coefficient_summary.get("interpretation_mode")
            if isinstance(coefficient_summary.get("interpretation_mode"), str)
            else None
        ),
        "run_status": run_status if isinstance(run_status, dict) else None,
        "persisted_models": _bounded_persisted_model_facts(model_results),
    }


def _bounded_persisted_model_facts(
    model_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project the public facts needed to answer a selected model question.

    Diagnostic summaries are narrative-facing and may intentionally omit a
    coefficient table.  The model-result contract is the durable numerical
    authority, so return a small schema-owned projection rather than forcing
    an Agent to guess from a report or to read a raw result payload.
    """

    projected: list[dict[str, Any]] = []
    for result in model_results[:2]:
        model_id = result.get("model_id")
        coefficients = result.get("coefficients")
        if not isinstance(model_id, str) or not isinstance(coefficients, dict):
            continue
        rows: list[dict[str, Any]] = []
        for term, coefficient in list(coefficients.items())[:8]:
            if not isinstance(term, str) or not isinstance(coefficient, dict):
                continue
            rows.append(
                {
                    "term": term,
                    "estimate": _public_stat_number(coefficient.get("estimate")),
                    "std_error": _public_stat_number(coefficient.get("std_error")),
                    "p_value": _public_stat_number(coefficient.get("p_value")),
                    "ci_lower": _public_stat_number(coefficient.get("ci_lower")),
                    "ci_upper": _public_stat_number(coefficient.get("ci_upper")),
                }
            )
        projected.append(
            {
                "model_id": model_id,
                "r_squared": _public_stat_number(result.get("r_squared")),
                "r_squared_adj": _public_stat_number(result.get("r_squared_adj")),
                "coefficients": rows,
            }
        )
    return projected


def _bounded_coefficient_row(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "variable",
        "display_name",
        "estimate",
        "std_error",
        "p_value",
        "ci_lower",
        "ci_upper",
        "significance_label",
    )
    return {key: row[key] for key in allowed if key in row}


def _bounded_artifact_manifest(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    allowed = (
        "expected",
        "available",
        "readable",
        "artifact_id",
        "filename",
        "schema_valid",
        "model_id",
        "available_count",
        "legacy_debug_only",
    )
    bounded: dict[str, dict[str, Any]] = {}
    for section, value in manifest.items():
        if not isinstance(section, str) or not isinstance(value, dict):
            continue
        bounded[section] = {key: value[key] for key in allowed if key in value}
    return bounded


def _operation_artifact_ids(record: OperationRecord) -> list[str]:
    """Collect only artifact ids already recorded as this operation's output."""

    artifact_ids: list[str] = []
    direct = record.outputs.get("artifact_ids")
    if isinstance(direct, list):
        artifact_ids.extend(item for item in direct if isinstance(item, str) and item)
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    if isinstance(steps, dict):
        for step in steps.values():
            step_artifacts = step.get("artifact_ids") if isinstance(step, dict) else None
            if isinstance(step_artifacts, list):
                artifact_ids.extend(
                    item for item in step_artifacts if isinstance(item, str) and item
                )
    return list(dict.fromkeys(artifact_ids))


def _bounded_completed_operation(record: OperationRecord) -> dict[str, Any]:
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    workflow_steps: list[dict[str, Any]] = []
    if isinstance(steps, dict):
        for step_id, step in sorted(steps.items()):
            if not isinstance(step_id, str) or not isinstance(step, dict):
                continue
            artifact_ids = step.get("artifact_ids")
            row_counts = step.get("row_counts")
            workflow_steps.append(
                {
                    "step_id": step_id,
                    "status": str(step.get("status") or "unknown"),
                    "artifact_ids": [
                        item
                        for item in (artifact_ids if isinstance(artifact_ids, list) else [])
                        if isinstance(item, str) and item
                    ][:16],
                    "row_counts": {
                        str(key): value
                        for key, value in (row_counts.items() if isinstance(row_counts, dict) else ())
                        if isinstance(value, int) and not isinstance(value, bool)
                    },
                }
            )
    return {
        "operation_record_id": record.record_id,
        "operation_id": record.operation_id,
        "operation_version": record.operation_version,
        "status": record.status,
        "artifact_ids": _operation_artifact_ids(record)[:16],
        "workflow": {
            "workflow_id": (
                workflow_state.get("workflow_id")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("workflow_id"), str)
                else None
            ),
            "status": (
                workflow_state.get("status")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("status"), str)
                else None
            ),
            "steps": workflow_steps[:16],
        },
    }


_PUBLIC_RESULT_DENIED_KEYS = frozenset(
    {
        "_omitted_item_count",
        "data",
        "dataset",
        "file",
        "filename",
        "path",
        "raw_rows",
        "rows",
        "records",
        "rendered_path",
        "residuals",
        "source_rows",
        "row_ids",
        "fitted_values",
        "values",
    }
)


@dataclass
class _PublicResultBudget:
    """One aggregate budget for a public artifact projection."""

    remaining_items: int = 96
    remaining_string_characters: int = 2048
    remaining_key_characters: int = 1600
    omitted_items: int = 0


def _public_operation_artifact_result(
    artifact_type: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Project a declared result type; unknown types remain deliberately opaque."""

    if artifact_type not in {
        "statistical_exploration",
        "statistical_test",
        "post_estimation",
    }:
        return None, ["raw_artifact_payloads"]
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, ["raw_artifact_payloads"]
    return _bounded_public_result_value(result), ["raw_artifact_payloads", "raw_rows"]


def _node_public_result_evidence(
    project_root: Path,
    *,
    owner_run_id: str,
    op_node_id: str,
) -> list[dict[str, Any]]:
    """Read statistical results whose declared input is the selected data node.

    This is deliberately a relation check, not a run-wide artifact dump.  A
    UI-created statistical exploration records the selected data artifact in
    its artifact-index inputs; only those descendants become Agent evidence.
    """

    try:
        from ..data_operations import resolve_data_column_cast_context

        source = resolve_data_column_cast_context(
            project_root,
            source_run_id=owner_run_id,
            source_node_id=op_node_id,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return []
    source_artifact_id = source.get("source_artifact_id")
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        return []
    run_root = project_root / "runs" / owner_run_id
    try:
        index = read_json(run_root / "artifacts_index.json")
    except (FileNotFoundError, OSError, ValueError):
        return []
    entries = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return []
    evidence: list[dict[str, Any]] = []
    for entry in entries:
        if len(evidence) >= 8 or not isinstance(entry, dict):
            break
        artifact_id = entry.get("artifact_id")
        artifact_type = entry.get("artifact_type")
        inputs = entry.get("inputs")
        if (
            not isinstance(artifact_id, str)
            or not isinstance(artifact_type, str)
            or not isinstance(inputs, list)
            or source_artifact_id not in inputs
        ):
            continue
        artifact = resolve_registered_artifact(run_root, artifact_id)
        if artifact is None:
            continue
        resolved_type, sha256, payload = artifact
        public_result, _omitted = _public_operation_artifact_result(resolved_type, payload)
        if public_result is None:
            continue
        evidence.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "sha256": sha256,
                "result": public_result,
            }
        )
    return evidence


def _bounded_run_figure_evidence(
    project_root: Path,
    *,
    run_id: str,
    node: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose numeric figure backing facts, never image pixels or paths."""

    if node.get("stage") != "model":
        return []
    try:
        from ..figure_context import FigureContextError, resolve_figure_ai_context

        run_root = project_root / "runs" / run_id
        try:
            index = read_json(run_root / "artifacts_index.json")
        except (FileNotFoundError, OSError, ValueError):
            return []
        records = index.get("artifacts") if isinstance(index, dict) else None
        if not isinstance(records, list):
            return []
        evidence: list[dict[str, Any]] = []
        for record in records:
            if len(evidence) >= 4 or not isinstance(record, dict):
                break
            artifact_id = record.get("artifact_id")
            if record.get("artifact_type") != "figure" or not isinstance(artifact_id, str):
                continue
            try:
                packet = resolve_figure_ai_context(project_root, run_id=run_id, artifact_id=artifact_id)
            except (FigureContextError, FileNotFoundError, OSError, TypeError, ValueError):
                continue
            source = packet.get("source")
            source_preview = source.get("preview_json") if isinstance(source, dict) else None
            try:
                raw_source = json.loads(source_preview) if isinstance(source_preview, str) else None
            except (TypeError, ValueError):
                raw_source = None
            model_figure_source = _bounded_model_figure_numeric_source(
                run_root,
                node_id=str(node.get("id") or ""),
                artifact_id=artifact_id,
            )
            numeric_source = (
                model_figure_source
                if model_figure_source is not None
                else _bounded_public_result_value(raw_source)
                if raw_source is not None
                else None
            )
            evidence.append(
                {
                    "artifact_id": artifact_id,
                    "chart_type": packet.get("figure", {}).get("chart_type") if isinstance(packet.get("figure"), dict) else None,
                    "numeric_source": numeric_source,
                    "source_available": numeric_source is not None,
                    "scope": "run",
                }
            )
        return evidence
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return []


def _bounded_model_figure_numeric_source(
    run_root: Path,
    *,
    node_id: str,
    artifact_id: str,
) -> dict[str, Any] | None:
    """Aggregate model vectors into chart facts without returning observations."""

    if not artifact_id.startswith(("residuals_fitted", "residuals_vs_", "qq_residuals")):
        return None
    model_key = node_id.split(":", 1)[1] if node_id.startswith("model:") else ""
    candidates = [
        result
        for result in read_model_results(run_root)
        if isinstance(result, dict)
        and (
            not model_key
            or str(result.get("model_id") or result.get("result_id") or "") == model_key
        )
    ]
    if not candidates and model_key:
        return None
    if not candidates:
        candidates = [result for result in read_model_results(run_root) if isinstance(result, dict)]
    if len(candidates) != 1:
        return None
    result = candidates[0]
    model_id = result.get("model_id") or result.get("result_id")
    residuals = _finite_numeric_values(result.get("residuals"))
    if not residuals:
        return None
    nobs = result.get("nobs")
    analysis_observations = nobs if isinstance(nobs, int) and not isinstance(nobs, bool) and nobs >= len(residuals) else len(residuals)
    if artifact_id.startswith("qq_residuals"):
        return {
            "kind": "residual_distribution_quantiles",
            "model_id": model_id if isinstance(model_id, str) else None,
            "analysis_observations": analysis_observations,
            "plotted_observations": len(residuals),
            "residual_mean": _numeric_mean(residuals),
            "residual_standard_deviation": _numeric_standard_deviation(residuals),
            "quantiles": [
                {"quantile": quantile, "residual": _numeric_quantile(residuals, quantile)}
                for quantile in (0.05, 0.25, 0.5, 0.75, 0.95)
            ],
        }
    if artifact_id.startswith("residuals_vs_"):
        return _bounded_residuals_vs_predictor_source(
            run_root,
            result=result,
            artifact_id=artifact_id,
            residuals=residuals,
            analysis_observations=analysis_observations,
        )
    fitted = _finite_numeric_values(result.get("fitted_values"))
    pairs = sorted(zip(fitted, residuals, strict=False), key=lambda pair: pair[0])
    if len(pairs) < 8:
        return None
    bin_count = min(12, max(1, len(pairs) // 5))
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = index * len(pairs) // bin_count
        stop = (index + 1) * len(pairs) // bin_count
        chunk = pairs[start:stop]
        if len(chunk) < 2:
            continue
        fitted_chunk = [pair[0] for pair in chunk]
        residual_chunk = [pair[1] for pair in chunk]
        bins.append(
            {
                "n": len(chunk),
                "fitted_min": min(fitted_chunk),
                "fitted_max": max(fitted_chunk),
                "residual_mean": _numeric_mean(residual_chunk),
                "residual_standard_deviation": _numeric_standard_deviation(residual_chunk),
                "residual_absolute_mean": _numeric_mean([abs(value) for value in residual_chunk]),
            }
        )
    if not bins:
        return None
    return {
        "kind": "residuals_vs_fitted_bins",
        "model_id": model_id if isinstance(model_id, str) else None,
        "analysis_observations": analysis_observations,
        "plotted_observations": len(pairs),
        "binning": "equal_count_by_fitted_value",
        "bins": bins,
    }


def _bounded_residuals_vs_predictor_source(
    run_root: Path,
    *,
    result: dict[str, Any],
    artifact_id: str,
    residuals: list[float],
    analysis_observations: int,
) -> dict[str, Any] | None:
    """Reconstruct one persisted predictor diagnostic as bounded bin statistics.

    The figure renderer aligns the model's residual vector to the cleaned data
    through ``analysis_sample.row_order``.  Reusing that same deterministic
    alignment here lets an Agent describe the chart it is shown without
    releasing any observation-level predictor or residual values.
    """

    suffix = artifact_id.removeprefix("residuals_vs_")
    x_columns = result.get("x_columns")
    if not isinstance(x_columns, list):
        return None
    candidates = [
        str(column)
        for column in x_columns
        if _figure_artifact_suffix(str(column)) == suffix
    ]
    if len(candidates) != 1:
        return None
    predictor = candidates[0]
    frame = _read_cleaned_dataset_for_figure_context(run_root)
    if frame is None or predictor not in frame.columns:
        return None
    aligned = _align_figure_context_rows(frame, result, len(residuals))
    if aligned is None:
        return None
    try:
        import pandas as pd

        values = pd.to_numeric(aligned[predictor], errors="coerce")
    except (ImportError, TypeError, ValueError):
        return None
    pairs = sorted(
        (
            (float(value), residual)
            for value, residual in zip(values, residuals, strict=True)
            if not pd.isna(value) and math.isfinite(float(value))
        ),
        key=lambda pair: pair[0],
    )
    if len(pairs) < 8:
        return None
    bin_count = min(12, max(1, len(pairs) // 5))
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = index * len(pairs) // bin_count
        stop = (index + 1) * len(pairs) // bin_count
        chunk = pairs[start:stop]
        if len(chunk) < 2:
            continue
        predictor_chunk = [pair[0] for pair in chunk]
        residual_chunk = [pair[1] for pair in chunk]
        bins.append(
            {
                "n": len(chunk),
                "predictor_min": min(predictor_chunk),
                "predictor_max": max(predictor_chunk),
                "residual_mean": _numeric_mean(residual_chunk),
                "residual_standard_deviation": _numeric_standard_deviation(residual_chunk),
                "residual_absolute_mean": _numeric_mean([abs(value) for value in residual_chunk]),
            }
        )
    if not bins:
        return None
    return {
        "kind": "residuals_vs_predictor_bins",
        "model_id": result.get("model_id") if isinstance(result.get("model_id"), str) else None,
        "predictor": predictor,
        "analysis_observations": analysis_observations,
        "plotted_observations": len(pairs),
        "binning": "equal_count_by_predictor",
        "bins": bins,
    }


def _figure_artifact_suffix(column: str) -> str:
    suffix = re.sub(r"[^0-9A-Za-z_]+", "_", column).strip("_")
    return suffix or "predictor"


def _read_cleaned_dataset_for_figure_context(run_root: Path) -> Any | None:
    try:
        index = read_json(run_root / "artifacts_index.json")
        records = index.get("artifacts") if isinstance(index, dict) else None
        if not isinstance(records, list):
            return None
        record = next(
            (
                item
                for item in records
                if isinstance(item, dict) and item.get("artifact_id") == "cleaned_dataset"
            ),
            None,
        )
        path_value = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path_value, str) or not path_value:
            return None
        path = (run_root / path_value).resolve()
        path.relative_to(run_root.resolve())
        if not path.is_file():
            return None
        import pandas as pd

        return pd.read_parquet(path)
    except (FileNotFoundError, OSError, ValueError, TypeError, ImportError):
        return None


def _align_figure_context_rows(frame: Any, result: dict[str, Any], size: int) -> Any | None:
    if size < 1 or len(frame) < size:
        return None
    sample = result.get("analysis_sample")
    row_order = sample.get("row_order") if isinstance(sample, dict) else None
    if isinstance(row_order, list) and len(row_order) >= size:
        positions = {str(value): position for position, value in enumerate(frame.index)}
        selected = [positions.get(str(value)) for value in row_order[:size]]
        if any(position is None for position in selected):
            return None
        return frame.iloc[[int(position) for position in selected]]
    # Older persisted results may predate row identities.  Their existing
    # visualization uses the first diagnostic-vector rows, so this retains
    # that explicitly bounded legacy behavior rather than silently inventing
    # a new alignment rule.
    return frame.iloc[:size]


def _finite_numeric_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    values: list[float] = []
    for item in value:
        if isinstance(item, bool):
            return []
        try:
            numeric = float(item)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(numeric):
            return []
        values.append(numeric)
    return values


def _numeric_mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _numeric_standard_deviation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _numeric_mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _numeric_quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bounded_public_result_value(
    value: Any,
    *,
    depth: int = 0,
    budget: _PublicResultBudget | None = None,
) -> Any:
    """Keep a numerical result compact and reject row-shaped/raw payload fields."""

    budget = budget or _PublicResultBudget()
    if budget.remaining_items <= 0:
        budget.omitted_items += 1
        return "[omitted: result item budget]"
    budget.remaining_items -= 1
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        limit = min(300, budget.remaining_string_characters)
        if limit <= 0:
            budget.omitted_items += 1
            return "[omitted: result string budget]"
        budget.remaining_string_characters -= limit
        if len(value) > limit:
            budget.omitted_items += 1
        return value[:limit]
    if depth >= 4:
        budget.omitted_items += 1
        return "[omitted: nesting limit]"
    if isinstance(value, list):
        bounded_list: list[Any] = []
        for item in value:
            if len(bounded_list) >= 16 or budget.remaining_items <= 0:
                budget.omitted_items += 1
                break
            if isinstance(item, (dict, list, str, int, float, bool)) or item is None:
                bounded_list.append(
                    _bounded_public_result_value(item, depth=depth + 1, budget=budget)
                )
        return bounded_list
    if not isinstance(value, dict):
        budget.omitted_items += 1
        return "[omitted: unsupported value]"
    bounded: dict[str, Any] = {}
    omissions_at_entry = budget.omitted_items
    for key in sorted(value):
        if not isinstance(key, str):
            continue
        normalized = key.lower()
        if normalized in _PUBLIC_RESULT_DENIED_KEYS or normalized.startswith("raw_"):
            continue
        if (
            len(bounded) >= 24
            or budget.remaining_items <= 0
            or budget.remaining_key_characters <= 0
        ):
            budget.omitted_items += 1
            break
        key_limit = min(64, budget.remaining_key_characters)
        bounded_key = key[:key_limit]
        budget.remaining_key_characters -= len(bounded_key)
        if len(key) > key_limit:
            budget.omitted_items += 1
        if bounded_key in bounded:
            budget.omitted_items += 1
            continue
        bounded[bounded_key] = _bounded_public_result_value(
            value[key], depth=depth + 1, budget=budget
        )
    omitted_here = budget.omitted_items - omissions_at_entry
    if omitted_here:
        bounded["_omitted_item_count"] = omitted_here
    return bounded


def _bounded_node(node: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "kind",
        "stage",
        "display_label",
        "parent_stage_id",
        "branch_id",
        "trust",
    )
    return {key: node[key] for key in allowed if key in node}


def _resolve_verified_registered_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    expected_type: str,
) -> tuple[dict[str, Any], str] | None:
    """Resolve a known artifact id and verify its registered content digest."""

    resolved = resolve_registered_artifact(run_root, artifact_id)
    if resolved is None:
        return None
    artifact_type, registered_sha256, payload = resolved
    if artifact_type != expected_type or not isinstance(registered_sha256, str):
        return None
    if re.fullmatch(r"[0-9a-f]{64}", registered_sha256) is None:
        return None
    try:
        index = read_json(run_root / "artifacts_index.json")
    except (OSError, ValueError):
        return None
    entries = index.get("artifacts") if isinstance(index, dict) else None
    entry = next(
        (
            item
            for item in entries or ()
            if isinstance(item, dict) and item.get("artifact_id") == artifact_id
        ),
        None,
    )
    relative_path = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
        return None
    try:
        resolved_root = run_root.resolve()
        path = (run_root / relative_path).resolve()
        path.relative_to(resolved_root)
        if not path.is_file() or sha256_file(path) != registered_sha256:
            return None
    except (OSError, ValueError):
        return None
    return payload, registered_sha256


def _bounded_diagnostics(preview: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    allowed = (
        "available",
        "preview_contract_version",
        "source_schema_version",
        "preview_status",
        "contract_warnings",
        "run_lifecycle_status",
        "run_status",
        "trust_label",
        "trust_counts",
        "primary_reasons",
        "diagnostic_highlights",
        "interpretation_restrictions",
        "recommended_actions",
    )
    diagnostics = {key: preview[key] for key in allowed if key in preview}
    omitted_sections = ["artifact_manifest", "coefficient_risk"]

    identity = preview.get("model_identity")
    if isinstance(identity, dict):
        diagnostics["model_identity"] = {
            key: identity[key]
            for key in (
                "primary_model_id",
                "model_label",
                "model_type",
                "y_variable",
                "n_observations",
                "x_variable_count",
            )
            if key in identity
        }

    for key, limit in (
        ("contract_warnings", 8),
        ("diagnostic_highlights", 8),
        ("interpretation_restrictions", 8),
    ):
        values = diagnostics.get(key)
        if not isinstance(values, list) or len(values) <= limit:
            continue
        diagnostics[key] = values[:limit]
        omitted_sections.append(key)
        diagnostics.setdefault("omitted_item_counts", {})[key] = len(values) - limit

    return diagnostics, omitted_sections

# v1.7.2 Analysis Loop read-only context seam. This is intentionally appended
# to preserve the existing provider/request API above.
_ANALYSIS_LOOP_SCOPES = frozenset({"inspect", "plan", "validation", "compare"})
_ANALYSIS_LOOP_SOURCE_FIELDS = frozenset({
    "run_id",
    "status",
    "model",
    "covariance",
    "primary_target",
    "diagnostics",
})


class AnalysisLoopContextError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class AnalysisLoopPacketPayloadError(AnalysisLoopContextError):
    """A JSON packet cannot cross the typed Agent context boundary."""


def _safe_analysis_loop_source_context(source_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source_context, dict):
        raise AnalysisLoopContextError(
            "source_context must be a mapping",
            code="SOURCE_CONTEXT_INVALID",
        )
    extra = set(source_context) - _ANALYSIS_LOOP_SOURCE_FIELDS
    if extra:
        raise AnalysisLoopContextError(
            "source_context contains unsupported fields",
            code="SOURCE_CONTEXT_SCOPE_VIOLATION",
        )
    return {key: source_context[key] for key in sorted(source_context)}


def _analysis_loop_packet_payload(
    packet: Any,
    expected_type: type[Any],
    scope: str,
) -> dict[str, Any] | None:
    if packet is None:
        return None
    if not isinstance(packet, expected_type):
        raise AnalysisLoopContextError(
            f"{scope} packet has an unsupported type",
            code="PACKET_TYPE_INVALID",
        )
    return packet.to_dict()


def parse_analysis_loop_packet_payloads(
    *,
    plan_diff: Any = None,
    validation_packet: Any = None,
    compare_packet: Any = None,
) -> tuple[PlanDiff | None, ValidationPacket | None, ComparePacket | None]:
    """Deserialize optional JSON packets for the read-only context seam."""

    try:
        parsed_plan = PlanDiff.from_dict(plan_diff) if plan_diff is not None else None
        parsed_validation = (
            ValidationPacket.from_dict(validation_packet)
            if validation_packet is not None
            else None
        )
        parsed_compare = (
            ComparePacket.from_dict(compare_packet)
            if compare_packet is not None
            else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisLoopPacketPayloadError(
            "analysis-loop packet payload is invalid",
            code="ANALYSIS_LOOP_PACKET_INVALID",
        ) from exc
    return parsed_plan, parsed_validation, parsed_compare


def inspect_analysis_loop_context(
    *,
    source_context: dict[str, Any],
    scope: str = "inspect",
    plan_diff: PlanDiff | None = None,
    validation_packet: ValidationPacket | None = None,
    compare_packet: ComparePacket | None = None,
) -> dict[str, Any]:
    """Return only typed, read-only context for one declared scope.

    The seam accepts packets supplied by a trusted backend resolver. It never
    reads files, calls providers, computes comparisons, or infers fields.
    """
    if type(scope) is not str or scope not in _ANALYSIS_LOOP_SCOPES:
        raise AnalysisLoopContextError(
            "unsupported analysis-loop context scope",
            code="CONTEXT_SCOPE_UNSUPPORTED",
        )
    result: dict[str, Any] = {
        "scope": scope,
        "source": _safe_analysis_loop_source_context(source_context),
    }
    if scope == "inspect":
        result["status"] = "available"
        return result
    if scope == "plan":
        payload = _analysis_loop_packet_payload(plan_diff, PlanDiff, scope)
        result.update({
            "status": "available" if payload is not None else "not_available",
            "packet": payload,
        })
    elif scope == "validation":
        payload = _analysis_loop_packet_payload(
            validation_packet,
            ValidationPacket,
            scope,
        )
        result.update({
            "status": validation_packet.status if validation_packet is not None else "absent",
            "packet": payload,
        })
    else:
        payload = _analysis_loop_packet_payload(compare_packet, ComparePacket, scope)
        result.update({
            "status": "available" if payload is not None else "not_available",
            "packet": payload,
        })
    return result
