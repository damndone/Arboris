"""Registration: bounded read-only context projection."""

from __future__ import annotations
import json
from typing import Any
from ...analysis_loop.recovery import RECOVERY_ACTIONS
from ..operations import OperationRegistry
from ..tools import ToolContext, ToolDefinition, ToolVisibleError
from ..skill_tools import skill_tool_definitions
from ..extension_tools import extension_tool
from ..statistical_claim_tools import statistical_claim_tool
from .analysis_loop import (
    AnalysisLoopContextError,
    inspect_analysis_loop_context,
    parse_analysis_loop_packet_payloads,
)
from .tool_specs import chain_tool_specs, global_tool_specs
from .requests import (
    InspectArtifactPreviewRequest,
    InspectCompletedOperationsRequest,
    InspectDataSchemaRequest,
    InspectDiagnosticsRequest,
    InspectNodeContextRequest,
    InspectNotebookWorkflowResultsRequest,
    InspectOperationArtifactRequest,
    InspectOperationContractRequest,
    InspectProjectCoefficientTransformsRequest,
    InspectProjectDatasetSchemaRequest,
    InspectProjectLinearInteractionEffectsRequest,
    InspectProjectModelCoefficientsRequest,
    InspectProjectModelFigureEvidenceRequest,
    InspectProjectNotebookWorkflowResultsRequest,
    InspectProjectNumericSummaryRequest,
    InspectProjectStatisticalEvidenceRequest,
    InspectRepeatedMeasuresRecipeRequest,
    InspectResultSummaryRequest,
    InspectTimeSeriesSummaryRequest,
    ListProjectDatasetsRequest,
    _run_local_node_id,
)



class RegistrationMixin:
    def tool_definitions(
        self,
        *,
        chain_id: str,
        session_id: str,
        operation_registry: OperationRegistry | None = None,
    ) -> list[ToolDefinition]:
        """Expose the provider's read-only tools without coupling the registry."""

        registry = operation_registry or OperationRegistry()
        from ..workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        # Workflow children are executable only inside the parent
        # operation.multi_step proposal. Publishing them as direct inspection
        # choices invites the Agent to ask for a model-node contract that the
        # provider must reject. Keep this enum declaration-derived while
        # leaving the runtime guard in inspect_operation_contract as defense in
        # depth.
        top_level_operation_ids = [
            operation_id
            for operation_id in registry.operation_ids()
            if operation_id not in WORKFLOW_STEP_SPEC_CONTRACTS
        ]

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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
                    operation_id=str(arguments["operation_id"]),
                    operation_version=str(arguments.get("operation_version") or "v1"),
                    step_operation_ids=tuple(str(item) for item in arguments.get("step_operation_ids") or ()),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
                )
            )

        def inspect_design_advisories(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_design_advisories(
                InspectResultSummaryRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-design-advisories"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
                )
            )

        def inspect_statistical_evidence(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            return self.inspect_statistical_evidence(
                InspectResultSummaryRequest(
                    request_id=str(
                        arguments.get("request_id") or "inspect-statistical-evidence"
                    ),
                    owner_run_id=str(arguments["owner_run_id"]),
                    op_node_id=str(arguments["op_node_id"]),
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
                    active_head_run_id=self._tool_active_head(chain_id, str(arguments["active_head_run_id"]), arguments.get("owner_run_id")),
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
            from ..analysis_loop_driver import forward_analysis_intent

            decision = forward_analysis_intent(arguments["intent"])
            return {
                "status": "accepted" if decision.accepted else "rejected",
                "decision": decision.to_dict(),
                "registered_actions": [
                    action.to_dict() for action in RECOVERY_ACTIONS.values()
                ],
            }

        def list_project_datasets(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            raw_detail = arguments.get("detail_for", [])
            if not isinstance(raw_detail, list) or len(raw_detail) > 8:
                raise ToolVisibleError(
                    "PROJECT_DATASET_DETAIL_INVALID: detail_for must contain at most eight run/node pairs."
                )
            detail_for: list[dict[str, str]] = []
            for index, item in enumerate(raw_detail):
                if not isinstance(item, dict) or set(item) != {"run_id", "node_id"}:
                    raise ToolVisibleError(
                        "PROJECT_DATASET_DETAIL_INVALID: "
                        f"detail_for[{index}] must contain exactly run_id and node_id."
                    )
                run_id = item.get("run_id")
                node_id = item.get("node_id")
                if not isinstance(run_id, str) or not run_id.strip() or not isinstance(node_id, str) or not node_id.strip():
                    raise ToolVisibleError(
                        "PROJECT_DATASET_DETAIL_INVALID: detail_for identities must be non-empty strings."
                    )
                detail_for.append({"run_id": run_id, "node_id": node_id})
            return self.list_project_datasets(
                ListProjectDatasetsRequest(detail_for=tuple(detail_for))
            )

        def export_dataset(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            from ...data_operations import DataColumnCastValidationError
            from ...services.data_export import export_dataset as write_export
            from ...tabular_io import StatisticalFileError

            run_id = str(arguments.get("run_id") or "")
            self._project_run_root(run_id)  # refuses anything but a project run id
            options = {
                key: arguments[key]
                for key in ("format", "columns", "filters", "dta_version", "value_labels", "missing_codes", "filename")
                if key in arguments
            }
            try:
                exported = write_export(
                    self.project_root,
                    run_id,
                    _run_local_node_id(str(arguments.get("node_id") or "")),
                    options,
                )
            except (DataColumnCastValidationError, StatisticalFileError, ValueError) as exc:
                raise ToolVisibleError(f"DATASET_EXPORT_UNAVAILABLE: {exc}") from exc
            from ...analysis_ledger import record_agent_action

            # The same record a UI export leaves, so the ledger shows every export.
            record_agent_action(
                self.project_root,
                source="agent.export_dataset",
                steps=["export.dataset"],
                session_id=context.session_id,
                run_id=run_id,
                node_id=_run_local_node_id(str(arguments.get("node_id") or "")),
                summary=json.dumps(options, ensure_ascii=False, sort_keys=True)[:300],
            )
            report = exported["report"]
            return {
                "artifact_id": exported["artifact_id"],
                "filename": exported["filename"],
                "download_url": exported["download_url"],
                "rows": report["rows"],
                "columns": report["columns"],
                "renamed": report["renamed"],
                # What the format could not hold; tell the user every item.
                "notes": report["notes"][:40],
                "notes_omitted": max(len(report["notes"]) - 40, 0),
            }

        def export_analysis_script(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            from ...services.script_export import export_analysis_script as write_script
            from ...egress import EgressPolicyError
            from ...script_export.plan import ScriptExportRefusal
            run_id = str(arguments.get("run_id") or "")
            self._project_run_root(run_id)
            try:
                result = write_script(self.project_root, run_id, str(arguments.get("target") or ""),
                    str(arguments.get("language") or ""), require_native=arguments.get("require_native", False))
            except (ScriptExportRefusal, EgressPolicyError) as exc:
                raise ToolVisibleError(f"SCRIPT_EXPORT_UNAVAILABLE: {exc}") from exc
            from ...analysis_ledger import record_agent_action
            record_agent_action(self.project_root, source="agent.export_analysis_script", steps=["export.analysis_script"],
                session_id=context.session_id, run_id=run_id, node_id=str(arguments.get("target") or ""),
                summary="Local " + result["language"] + " script export")
            # Keep the download and coverage useful without sending local data,
            # script parameters, file-system locations, or numeric results.
            return {key: result[key] for key in ("artifact_id", "filename", "language", "fully_native", "coverage", "required_packages", "sha256", "bytes")} | {
                "download_url": f"/runs/{run_id}/artifacts/{result['artifact_id']}"}

        specs = chain_tool_specs(top_level_operation_ids=top_level_operation_ids)
        return [
            self.show_dataset_rows_tool(session_id=session_id, scope_requirements=("project", "chain")),
            *skill_tool_definitions(self.project_root, session_id=session_id),
            extension_tool(self.project_root, session_id=session_id),
            statistical_claim_tool(self, session_id=session_id),
            self.calculate_tool(session_id=session_id, scope_requirements=("project", "chain")),
            *self.conversation_recall_tools(session_id=session_id, scope_requirements=("project", "chain")),
            ToolDefinition(**specs["export_analysis_script"], handler=export_analysis_script),
            ToolDefinition(**specs["export_dataset"], handler=export_dataset),
            ToolDefinition(**specs["list_project_datasets"], handler=list_project_datasets),
            ToolDefinition(**specs["inspect_data_schema"], handler=inspect_data_schema),
            ToolDefinition(**specs["inspect_completed_operations"], handler=inspect_completed_operations),
            ToolDefinition(**specs["inspect_notebook_workflow_results"], handler=inspect_notebook_workflow_results),
            ToolDefinition(**specs["inspect_operation_artifact"], handler=inspect_operation_artifact),
            ToolDefinition(**specs["inspect_analysis_loop_context"], handler=inspect_analysis_loop_context_tool),
            ToolDefinition(**specs["submit_analysis_loop_intent"], handler=submit_analysis_loop_intent),
            ToolDefinition(**specs["inspect_node_context"], handler=inspect_node_context),
            ToolDefinition(**specs["inspect_operation_contract"], handler=inspect_operation_contract,
                           normalize=_workflow_step_contract_request),
            ToolDefinition(**specs["inspect_diagnostics"], handler=inspect_diagnostics),
            ToolDefinition(**specs["inspect_design_advisories"], handler=inspect_design_advisories),
            ToolDefinition(**specs["inspect_statistical_evidence"], handler=inspect_statistical_evidence),
            ToolDefinition(**specs["inspect_result_summary"], handler=inspect_result_summary),
            ToolDefinition(**specs["inspect_project_model_coefficients"], handler=inspect_project_model_coefficients),
            ToolDefinition(**specs["inspect_time_series_summary"], handler=inspect_time_series_summary),
            ToolDefinition(**specs["inspect_repeated_measures_recipe"], handler=inspect_repeated_measures_recipe),
            ToolDefinition(**specs["inspect_artifact_preview"], handler=inspect_artifact_preview),
        ]

    def show_dataset_rows_tool(
        self, *, session_id: str, scope_requirements: tuple[str, ...]
    ) -> ToolDefinition:
        """Rows for the user's screen; the provider receives only the summary
        unless the project's sharing policy allows rows (workbench.egress)."""

        def show_dataset_rows(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered scope")
            from ...data_operations import DataColumnCastValidationError
            from ...services.dataset_view import dataset_page

            run_id = str(arguments.get("run_id") or "")
            node_id = _run_local_node_id(str(arguments.get("node_id") or ""))
            self._project_run_root(run_id)
            offset = int(arguments.get("offset") or 0)
            limit = int(arguments.get("limit") or 20)
            try:
                page = dataset_page(self.project_root, run_id, node_id, offset=offset, limit=limit)
            except (DataColumnCastValidationError, ValueError, FileNotFoundError) as exc:
                raise ToolVisibleError(f"DATASET_ROWS_UNAVAILABLE: {exc}") from exc
            requested = [str(column) for column in arguments.get("columns") or []]
            unknown = [column for column in requested if column not in page["columns"]]
            if unknown:
                raise ToolVisibleError(
                    f"DATASET_ROWS_UNAVAILABLE: unknown columns {unknown}; the dataset has {page['columns']}"
                )
            columns = requested or page["columns"]
            rows = [{column: row.get(column) for column in columns} for row in page["rows"]]
            shown = len(rows)
            first = offset + 1 if shown else offset
            return {
                "run_id": run_id,
                "node_id": node_id,
                "columns": columns,
                "total_rows": page["total_rows"],
                "offset": offset,
                "row_numbers": page["row_numbers"],
                "rows": rows,
                # The only part of this result a remote provider receives under
                # the default data-sharing policy (see workbench.egress).
                "egress_summary": (
                    f"Rows {first}-{offset + shown} of {page['total_rows']} "
                    f"({len(columns)} column{'s' if len(columns) != 1 else ''}) "
                    f"of {node_id} in run {run_id} are shown to the user in Workbench."
                ),
            }


        return ToolDefinition(
            tool_id="show_dataset_rows",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_id", "node_id"],
                "properties": {
                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "node_id": {"type": "string", "minLength": 1, "maxLength": 300},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 40,
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=scope_requirements,
            max_output_budget=16384,
            handler=show_dataset_rows,
            description=(
                "Show rows of one dataset node (e.g. stage:raw, stage:cleaned or a "
                "derived dataset) to the user as a table in Workbench, when the user "
                "asks to see records. Under the project's data-sharing policy the rows "
                "may stay on the user's computer: you then receive only a summary of "
                "what was shown. Do not repeat or guess row values; describe data with "
                "summaries, frequencies or models instead."
            ),
        )

    def conversation_recall_tools(
        self, *, session_id: str, scope_requirements: tuple[str, ...]
    ) -> list[ToolDefinition]:
        """Search and read this project's earlier conversations (agent/recall.py)."""

        from ..recall import read, search
        from ..session import JsonlSessionRepository

        def repository() -> JsonlSessionRepository:
            return JsonlSessionRepository(self.project_root / "workbench", create=False)

        def search_conversations(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered scope")
            hits = search(repository(), str(arguments["query"]), limit=int(arguments.get("limit") or 8))
            return {"hits": hits, "note": "A record of what was said, not verified results."}

        def read_conversation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered scope")
            try:
                return read(
                    repository(),
                    str(arguments["session_id"]),
                    around_entry_id=arguments.get("around_entry_id"),
                    before=int(arguments.get("before", 4)),
                    after=int(arguments.get("after", 4)),
                )
            except KeyError as exc:
                raise ToolVisibleError(f"PROJECT_CONVERSATION_NOT_FOUND: {exc.args[0]}") from exc

        return [
            ToolDefinition(
                tool_id="search_project_conversations",
                version="v1",
                description=(
                    "Search this project's conversations (including the earlier, summarized part of this one) "
                    "for what the person asked or decided and what you answered. Returns passages with their "
                    "session and entry ids. Tool results are not searchable; inspect evidence again by id."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 300},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=scope_requirements,
                max_output_budget=8192,
                handler=search_conversations,
            ),
            ToolDefinition(
                tool_id="read_project_conversation",
                version="v1",
                description=(
                    "Read messages of one of this project's conversations, around an entry id from "
                    "search_project_conversations, or from its start."
                ),
                input_schema={
                    "type": "object",
                    "required": ["session_id"],
                    "properties": {
                        "session_id": {"type": "string", "minLength": 1, "maxLength": 200},
                        "around_entry_id": {"type": "string", "minLength": 1, "maxLength": 128},
                        "before": {"type": "integer", "minimum": 0, "maximum": 12},
                        "after": {"type": "integer", "minimum": 0, "maximum": 12},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                scope_requirements=scope_requirements,
                max_output_budget=12288,
                handler=read_conversation,
            ),
        ]

    def calculate_tool(
        self, *, session_id: str, scope_requirements: tuple[str, ...]
    ) -> ToolDefinition:
        """Arithmetic on result values, done in code (agent.numeric_grounding)."""

        def calculate(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered scope")
            from ..numeric_grounding import calculate as run

            return run(arguments.get("calculations") or ())

        return ToolDefinition(
            tool_id="calculate",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["calculations"],
                "properties": {
                    "calculations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "required": ["expression"],
                            "properties": {
                                "label": {"type": "string", "maxLength": 120},
                                "expression": {"type": "string", "minLength": 1, "maxLength": 400},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=scope_requirements,
            max_output_budget=8192,
            handler=calculate,
            description=(
                "Do arithmetic on numbers from results: differences, ratios, sums, "
                "percentages, odds ratios (exp), logs, square roots. Write each "
                "expression with the full values copied from the results, e.g. "
                "'5.1234 - 4.0221' or 'exp(0.4312)'. Never compute or round a number "
                "yourself: every number in your answer is checked against the results "
                "and this tool's values before the user sees it."
            ),
        )

    def global_tool_definitions(self, *, session_id: str) -> list[ToolDefinition]:
        """Expose bounded project evidence readers to the Main Agent.

        These tools inspect server-persisted aggregate evidence without transferring model
        payloads into its context. It can show data rows to the user; they
        reach the model only when the project's sharing policy allows rows.
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

        def inspect_project_statistical_evidence(
            arguments: dict[str, Any],
            context: ToolContext,
        ) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered project scope")
            return self.inspect_project_statistical_evidence(
                InspectProjectStatisticalEvidenceRequest(
                    run_ids=tuple(str(run_id) for run_id in arguments["run_ids"])
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

        from .notebook_state import notebook_state_tool

        specs = global_tool_specs()
        return [
            notebook_state_tool(self.project_root, session_id=session_id),
            *skill_tool_definitions(self.project_root, session_id=session_id),
            extension_tool(self.project_root, session_id=session_id),
            statistical_claim_tool(self, session_id=session_id),
            self.show_dataset_rows_tool(session_id=session_id, scope_requirements=("project",)),
            self.calculate_tool(session_id=session_id, scope_requirements=("project",)),
            *self.conversation_recall_tools(session_id=session_id, scope_requirements=("project",)),
            ToolDefinition(**specs["inspect_project_model_coefficients"], handler=inspect_project_model_coefficients),
            ToolDefinition(**specs["inspect_project_dataset_schema"], handler=inspect_project_dataset_schema),
            ToolDefinition(**specs["inspect_project_numeric_summary"], handler=inspect_project_numeric_summary),
            ToolDefinition(**specs["inspect_project_model_figure_evidence"], handler=inspect_project_model_figure_evidence),
            ToolDefinition(**specs["inspect_project_linear_interaction_effects"], handler=inspect_project_linear_interaction_effects),
            ToolDefinition(**specs["inspect_project_coefficient_transforms"], handler=inspect_project_coefficient_transforms),
            ToolDefinition(**specs["inspect_project_notebook_workflow_results"], handler=inspect_project_notebook_workflow_results),
            ToolDefinition(**specs["inspect_project_statistical_evidence"], handler=inspect_project_statistical_evidence),
        ]


def _workflow_step_contract_request(arguments: dict[str, Any]) -> dict[str, Any]:
    """A workflow step named as the operation means that step of operation.multi_step (8 refusals)."""

    from ..tools import tool_note
    from ..workflow_contracts import workflow_step_vocabulary

    named = arguments.get("operation_id")
    if (not isinstance(named, str) or named in OperationRegistry().natural_language_operation_ids()
            or named not in workflow_step_vocabulary()["step_operations"]):
        return arguments
    tool_note(f"{named} is a workflow step; read as operation.multi_step with step_operation_ids [{named}].")
    return {**arguments, "operation_id": "operation.multi_step",
            "step_operation_ids": [named, *(arguments.get("step_operation_ids") or ())]}
