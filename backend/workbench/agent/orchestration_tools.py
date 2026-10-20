"""orchestration tools: methods over the existing shared state."""
from __future__ import annotations
import inspect
from pathlib import Path
from typing import Any
from .chains import ChainHeadConflict
from .context_tools import InspectNodeContextRequest
from .operation_requests import OperationRequest
from .operations import RERUN_OPERATIONS, is_rerun_operation
from .proposals import ProposalInvocation, ProposalRevision
from .tools import ToolRegistry, ToolVisibleError
from .toolsets import build_chain_tool_registry
from .operation_handlers.proposal_arguments import _canonicalize_data_columns_cast_arguments, _canonicalize_workflow_arguments, _precheck_model_options, _clustered_analysis_loop_intent

class OrchestrationTools:
    _clustered_analysis_loop_intent = staticmethod(_clustered_analysis_loop_intent)

    @property
    def data_operation_project_root(self) -> Path | None:
        """The project the context provider is bound to, if there is one.

        Derived rather than injected: the provider already owns the project
        identity, and a second source for it could disagree with the one the
        read-only tools answer from.
        """

        root = getattr(self.context_provider, "project_root", None)
        return Path(root) if root is not None else None


    def _canonicalize_data_columns_cast_arguments(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return _canonicalize_data_columns_cast_arguments(
            arguments, project_root=self.data_operation_project_root
        )


    def _canonicalize_workflow_arguments(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return _canonicalize_workflow_arguments(
            arguments, project_root=self.data_operation_project_root
        )


    def _bind_workflow_preconditions(
        self, arguments: dict[str, Any], *, session_id: str, chain_id: str | None = None
    ) -> dict[str, Any]:
        """Derive a workflow's preconditions from the node it actually targets.

        A workflow runs on a dataset node, but the Agent copies preconditions
        from whatever node it inspected -- the selected model node, when the
        user had clicked one. Confirmation re-derives the fingerprint of the
        target node, so every such proposal was rejected as stale although
        nothing had changed. The backend derives them here, from the target,
        as it already does for reruns.
        """

        inspect = getattr(self.context_provider, "inspect_node_context", None)
        target = dict(arguments.get("target") or {})
        preconditions = dict(arguments.get("preconditions") or {})
        if inspect is None or not target.get("run_id") or not target.get("node_ref"):
            return arguments
        from .context_tools import InspectNodeContextRequest

        try:
            chain_id = chain_id or self.repository.get_metadata(session_id).get("chain_id")
        except (KeyError, FileNotFoundError, ValueError):
            chain_id = None
        active_head = str(preconditions.get("active_head_run_id") or target["run_id"])
        if isinstance(chain_id, str) and chain_id:
            try:
                active_head = self._resolve_chain_head(chain_id, active_head)
            except ChainHeadConflict as exc:
                raise ValueError("active_head_run_id: " + str(exc)) from exc
        try:
            snapshot = inspect(
                InspectNodeContextRequest(
                    request_id=f"propose:{target['run_id']}",
                    owner_run_id=str(target["run_id"]),
                    op_node_id=str(target["node_ref"]),
                    active_head_run_id=active_head,
                )
            )
        except (KeyError, OSError, ValueError):
            # An unresolvable target is the typed validator's to report.
            return arguments
        fingerprint = snapshot.get("context_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            return arguments
        preconditions.update(
            context_version=snapshot["context_version"],
            context_fingerprint=fingerprint,
            owner_resolution=snapshot["owner_resolution"],
            active_head_run_id=snapshot["active_head_run_id"],
        )
        return {**arguments, "preconditions": preconditions}


    def _prepare_analysis_loop_proposal_from_agent_arguments(
        self,
        *,
        chain_id: str,
        session_id: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> tuple[ProposalRevision, dict[str, Any]]:
        """Create the typed OLS proposal from backend-resolved source facts.

        The generic ``model.rerun`` registry remains available for operations
        outside v1.7.2.  A conventional-to-clustered OLS request, however,
        must enter the Analysis Loop seam so its PlanDiff binding is present
        before confirmation.  The unified operation tool preserves exact-result selection
        before applying the common permission decision.
        """

        project_root = self.data_operation_project_root
        if project_root is None:
            raise ValueError("analysis_loop_project_root_unavailable")
        provider = self.context_provider
        inspect = getattr(provider, "inspect_node_context", None)
        if inspect is None:
            raise ValueError("analysis_loop_context_provider_unavailable")

        target = dict(arguments.get("target") or {})
        source_run_id = str(
            arguments.get("source_run_id") or target.get("run_id") or ""
        )
        source_node_ref = str(
            arguments.get("source_node_ref") or target.get("node_ref") or ""
        )
        requested_active_head = str(
            arguments.get("active_head_run_id")
            or (arguments.get("preconditions") or {}).get("active_head_run_id")
            or ""
        )
        cluster_variable = str(arguments.get("cluster_variable") or "")
        if not source_run_id or not source_node_ref:
            raise ValueError("analysis_loop_source_identity_required")
        if not cluster_variable:
            raise ValueError("analysis_loop_cluster_variable_required")

        active_head_run_id = self._resolve_chain_head(
            chain_id,
            requested_active_head,
        )
        if not active_head_run_id:
            raise ValueError("analysis_loop_active_head_required")

        snapshot = inspect(
            InspectNodeContextRequest(
                request_id=f"analysis-loop-proposal:{source_run_id}:{source_node_ref}",
                owner_run_id=source_run_id,
                op_node_id=source_node_ref,
                active_head_run_id=str(active_head_run_id),
            )
        )
        if snapshot.get("active_head_run_id") != active_head_run_id:
            raise ValueError("analysis_loop_active_head_context_mismatch")
        context_fingerprint = str(snapshot.get("context_fingerprint") or "")
        if not context_fingerprint:
            raise ValueError("analysis_loop_context_fingerprint_missing")
        command_context_fingerprint = (metadata or {}).get("context_fingerprint")
        if (
            command_context_fingerprint is not None
            and context_fingerprint != command_context_fingerprint
        ):
            raise ValueError("context_fingerprint_mismatch")

        from ..analysis_loop.lifecycle import create_analysis_loop_proposal
        from ..analysis_loop.resolver import resolve_analysis_loop_inputs
        from ..analysis_loop.storage import PlanDiffStore

        resolved = resolve_analysis_loop_inputs(
            project_root,
            run_id=source_run_id,
            cluster_variable=cluster_variable,
        )
        if resolved.source.run_id != source_run_id:
            raise ValueError("analysis_loop_source_identity_mismatch")

        proposal = create_analysis_loop_proposal(
            orchestrator=self,
            chain_id=chain_id,
            session_id=session_id,
            command_id=(metadata or {}).get("command_id"),
            plan_store=PlanDiffStore(self.repository.root, create=False),
            source=resolved.source,
            intent={
                "action_id": "ols.use_clustered_covariance_v1",
                "patch": {
                    "covariance": "clustered",
                    "cluster_variable": cluster_variable,
                },
            },
            cluster_values=resolved.cluster_values,
            model_row_ids=resolved.model_row_ids,
            requested_result_id=target.get("result_id"),
            source_context_fingerprint=context_fingerprint,
            source_identity={
                "run_id": source_run_id,
                "node_ref": source_node_ref,
                "node_hash": str(snapshot.get("node_hash") or ""),
                "forest_node_key": str(snapshot.get("forest_node_key") or ""),
            },
            active_head_run_id=str(active_head_run_id),
            owner_resolution=str(snapshot.get("owner_resolution") or ""),
        )
        plan_store = PlanDiffStore(self.repository.root, create=False)
        packet = plan_store.get_terminal_packet(
            str(proposal.preconditions.get("plan_logical_key") or "")
        )
        if packet is None:
            raise ValueError("analysis_loop_plan_missing")

        source_facts = {
            "run_id": resolved.source.run_id,
            "status": resolved.source.status,
            "model": resolved.source.model,
            "covariance": resolved.source.covariance,
            "contract_version": resolved.source.contract_version,
            "result_ids": list(resolved.source.result_ids),
            "primary_estimand": (
                dict(resolved.source.primary_estimand)
                if resolved.source.primary_estimand is not None
                else None
            ),
            "analysis_row_count": len(resolved.source.analysis_row_ids),
        }
        return proposal, {
            "plan_diff": packet.plan_diff.to_dict(),
            "analysis_loop": {
                "status": "pending",
                "action_id": "ols.use_clustered_covariance_v1",
                "source": source_facts,
                "plan_diff": packet.plan_diff.to_dict(),
            },
        }


    def _canonicalize_proposal_arguments(
        self,
        operation_id: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        chain_id: str | None = None,
    ) -> dict[str, Any]:
        """Re-derive canonical target/precondition facts from the backend.

        Design §5.3: the model supplies references (run id + node ref +
        active head); the backend is the source of truth for node_hash,
        forest_node_key, fingerprint, and owner_resolution. The live DeepSeek
        smoke showed the model copying the UI forest-projection key
        (`<hash>::<node_id>`) into the proposal, which the rerun validator
        then correctly rejected at execution — canonicalize at creation so a
        confirmable proposal is executable. Without a context provider (pure
        contract tests) the arguments pass through unchanged.
        """
        if operation_id == "data.columns.cast":
            return self._canonicalize_data_columns_cast_arguments(arguments)
        if operation_id == "operation.multi_step":
            return self._bind_workflow_preconditions(
                self._canonicalize_workflow_arguments(arguments), session_id=session_id, chain_id=chain_id
            )
        if self.context_provider is None or operation_id not in {*RERUN_OPERATIONS, "graph.fork"}:
            return arguments
        inspect = getattr(self.context_provider, "inspect_node_context", None)
        if inspect is None:
            return arguments
        from .context_tools import InspectNodeContextRequest

        target = dict(arguments.get("target") or {})
        preconditions = dict(arguments.get("preconditions") or {})
        metadata = self.repository.get_metadata(session_id)
        chain_id = chain_id or metadata.get("chain_id")
        if isinstance(chain_id, str) and chain_id:
            try:
                preconditions["active_head_run_id"] = self._resolve_chain_head(
                    chain_id,
                    str(preconditions.get("active_head_run_id")),
                )
            except ChainHeadConflict as exc:
                raise ValueError("active_head_run_id: " + str(exc)) from exc
        snapshot = inspect(
            InspectNodeContextRequest(
                request_id=f"propose:{target.get('run_id')}",
                owner_run_id=str(target.get("run_id")),
                op_node_id=str(target.get("node_ref")),
                active_head_run_id=str(preconditions.get("active_head_run_id")),
            )
        )
        target["node_hash"] = snapshot["node_hash"]
        target["forest_node_key"] = snapshot["forest_node_key"]
        preconditions["context_version"] = snapshot["context_version"]
        preconditions["context_fingerprint"] = snapshot["context_fingerprint"]
        preconditions["owner_resolution"] = snapshot["owner_resolution"]
        preconditions["active_head_run_id"] = snapshot["active_head_run_id"]
        if operation_id == "model.rerun":
            self._precheck_model_options(
                owner_run_id=str(target.get("run_id")),
                changes=arguments.get("changes"),
            )
        if operation_id == "graph.fork":
            current_leaf = metadata.get("leaf_entry_id")
            if not isinstance(current_leaf, str) or not current_leaf:
                raise ValueError("graph_fork_source_entry_missing")
            supplied_entry = target.get("source_session_entry_id")
            if supplied_entry is not None and str(supplied_entry) != current_leaf:
                raise ValueError("graph_fork_source_entry_not_current_leaf")
            target["source_session_entry_id"] = current_leaf
        return {**arguments, "target": target, "preconditions": preconditions}


    def _precheck_model_options(
        self, *, owner_run_id: str, changes: Any
    ) -> None:
        _precheck_model_options(
            owner_run_id=owner_run_id,
            changes=changes,
            context_provider=self.context_provider,
        )


    def tool_registry(self, chain_id: str) -> ToolRegistry:
        """Return the allowlisted Workbench tools scoped to one chain."""

        existing = self._tool_registries.get(chain_id)
        if existing is not None:
            return existing
        session_id, _agent = self._chain(chain_id)
        context_tools = ()

        if self.context_provider is not None:
            context_tools = self.context_provider.tool_definitions(
                chain_id=chain_id,
                session_id=session_id,
                operation_registry=self.operation_registry,
            )

        if self.repository.get_metadata(session_id)["role"] == "main":
            source_tools = {"list_project_datasets", "inspect_data_schema", "inspect_node_context", "inspect_operation_contract"}
            context_tools = (*self.context_provider.global_tool_definitions(session_id=session_id),
                             *(tool for tool in context_tools if tool.tool_id in source_tools))

        async def run_operation(arguments: dict[str, Any], context) -> dict[str, Any]:
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            operation_id = str(arguments["operation_id"])
            operation_chain = self._operation_chain(session_id, arguments["target"])
            arguments = self._canonicalize_proposal_arguments(
                operation_id,
                arguments,
                session_id=session_id, chain_id=operation_chain,
            )
            metadata = context.metadata
            if "allowed_operations" in metadata:
                allowed_operations = {
                    str(item) for item in (metadata.get("allowed_operations") or [])
                }
                if operation_id not in allowed_operations:
                    raise PermissionError("operation_not_allowed")
            command_context_fingerprint = metadata.get("context_fingerprint")
            if (
                command_context_fingerprint is not None
                and arguments["preconditions"].get("context_fingerprint")
                != command_context_fingerprint
            ):
                raise ValueError("context_fingerprint_mismatch")
            command_id = metadata.get("command_id")
            if command_id is not None and not isinstance(command_id, str):
                raise ValueError("invalid_command_id")
            cluster_variable = self._clustered_analysis_loop_intent(arguments)
            if operation_id == "model.rerun" and cluster_variable is not None:
                proposal, details = self._prepare_analysis_loop_proposal_from_agent_arguments(
                    chain_id=operation_chain,
                    session_id=session_id,
                    arguments={
                        **arguments,
                        "source_run_id": arguments["target"]["run_id"],
                        "source_node_ref": arguments["target"]["node_ref"],
                        "active_head_run_id": arguments["preconditions"][
                            "active_head_run_id"
                        ],
                        "cluster_variable": cluster_variable,
                    },
                    metadata=metadata,
                )
                outcome = await self._run_or_await_confirmation(proposal, session_id=session_id)
                status = ("pending" if outcome.get("requires_confirmation") else
                          "denied" if outcome.get("denied") else
                          outcome.get("operation", {}).get("status", "failed"))
                return {**outcome, **details, "analysis_loop": {**details["analysis_loop"], "status": status}}
            if "result_id" in arguments["target"]:
                raise ToolVisibleError("target.result_id is only supported for the clustered OLS Analysis Loop")
            if is_rerun_operation(operation_id):
                self._preflight_model_rerun_declarations(
                    arguments, metadata_edit=operation_id == "metadata.edit"
                )
            receipt = self.admit_operation_request(
                OperationRequest.from_arguments({**arguments, "operation_id": operation_id}),
                chain_id=operation_chain,
                session_id=session_id,
                command_id=command_id,
                invocation=(ProposalInvocation(
                    invocation_id=metadata["invocation_id"],
                    provider_step=metadata["provider_step"],
                    tool_call_id=metadata["tool_call_id"],
                ) if metadata.get("invocation_id") is not None else None),
            )
            proposal = receipt.proposal
            return await self._run_or_await_confirmation(proposal, session_id=session_id)

        async def update_plan(arguments: dict[str, Any], context) -> dict[str, Any]:
            from . import plans as plan_module

            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            try:
                steps = plan_module.parse_steps(arguments.get("steps"), self.known_plan_operations())
                def revise(previous):
                    plan = plan_module.merge(
                        previous,
                        question=str(arguments.get("question") or "").strip()[:1000],
                        criteria=[str(c)[:300] for c in arguments.get("criteria") or ()][:12],
                        steps=steps,
                        budget={k: int(v) for k, v in (arguments.get("budget") or {}).items()
                                if k in {"steps", "wall_s", "inferential"} and str(v).isdigit()},
                        allowed_classes=arguments.get("allowed_classes"),
                    )
                    if not plan.question:
                        raise plan_module.PlanError("question is required")
                    if (previous is not None and previous.approved_version is not None
                            and plan.question != previous.question):
                        from ..analysis_ledger import record_plan_event_once

                        project_root = getattr(self.context_provider, "project_root", None)
                        if project_root is None:
                            raise plan_module.PlanError("a project is required to record a question change")
                        intent = record_plan_event_once(project_root, session_id=session_id, event_type="question_change",
                                                        plan_snapshot=plan.to_dict())
                        plan = plan_module.Plan.from_dict(intent["plan_snapshot"])
                    return plan
                plan = self.plan_store.update(session_id, revise)
            except plan_module.PlanError as exc:
                return {"saved": False, "error": str(exc),
                        "guidance": "Fix the plan as the error says and call update_plan again."}
            needs_person = self.execution_mode == "auto" and plan.status in {"draft", "needs_approval"}
            return {
                "saved": True,
                "plan": plan.to_dict(),
                **({"requires_confirmation": True, "awaiting": "plan_approval"} if needs_person else {}),
                "guidance": (
                    "The plan is shown to the person, who approves it before anything in it runs. End your turn "
                    "with a short summary of the plan; you will be resumed after the approval."
                    if needs_person else
                    "The plan is shown to the person. Carry it out step by step; update it (statuses, new steps) "
                    "as results come in."
                ),
            }


        def plan_analysis(arguments, context):
            from .planning.agent_phase import create_phase

            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            core = self._chain(chain_id)[1]
            phase = create_phase(core=core, orchestrator=self, chain_id=chain_id, arguments=arguments)
            core.enter_phase(phase)
            return {"phase_started":True, "episode_id":phase.episode_id}

        return build_chain_tool_registry(
            context_tools=context_tools,
            proposal_tool_schema=lambda: self.operation_registry.proposal_tool_schema(),
            update_plan=update_plan,
            run_operation=run_operation,
            plan_analysis=plan_analysis,
        )

