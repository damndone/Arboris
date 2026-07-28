"""Provider-backed, read-only Workbench context tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from ..artifacts import read_json
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
class InspectOperationArtifactRequest:
    request_id: str
    owner_run_id: str
    op_node_id: str
    active_head_run_id: str
    operation_record_id: str
    artifact_id: str


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

    def inspect_time_series_summary(
        self,
        request: InspectTimeSeriesSummaryRequest,
    ) -> dict[str, Any]:
        """Return public ARMA-GARCH evidence without exposing raw series."""

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        from .recipes.arma_garch import build_arma_garch_public_result_view

        run_root = self.project_root / "runs" / request.owner_run_id
        artifacts, metadata = _read_time_series_artifacts(run_root)
        summary = build_arma_garch_public_result_view(artifacts)
        try:
            run_inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            run_inputs = {}
        if "ts.analysis_contract" not in artifacts:
            recovered = _analysis_contract_from_run_inputs(run_inputs)
            if recovered is not None:
                artifacts["ts.analysis_contract"] = recovered
            summary = build_arma_garch_public_result_view(artifacts)
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
            },
            "omitted_sections": ["raw_artifact_payloads"],
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
    }


def _bounded_coefficient_row(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "variable",
        "display_name",
        "estimate",
        "std_error",
        "p_value",
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
        "source_rows",
        "row_ids",
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

    if artifact_type != "statistical_exploration":
        return None, ["raw_artifact_payloads"]
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, ["raw_artifact_payloads"]
    return _bounded_public_result_value(result), ["raw_artifact_payloads", "raw_rows"]


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
