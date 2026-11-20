"""orchestration tools: methods over the existing shared state."""
from __future__ import annotations
import inspect
from pathlib import Path
from typing import Any
from .chains import ChainHeadConflict
from .context_tools import InspectNodeContextRequest
from .operation_requests import OperationRequest
from .operations import RERUN_OPERATIONS, is_rerun_operation
from .proposals import ProposalConfirmationError, ProposalInvocation, ProposalRevision
from .tools import ToolRegistry, ToolVisibleError
from .toolsets import build_chain_tool_registry, plan_tool_view
from .operations import normalize_operation_target
from .operation_handlers.proposal_arguments import _canonicalize_data_columns_cast_arguments, _canonicalize_workflow_arguments, _precheck_model_options, _clustered_analysis_loop_intent

_AUTO_WORKFLOW_PLAN_REQUIRED = {
    "executed": False,
    "plan_required": True,
    "guidance": (
        "Auto within plan needs an approved plan before a workflow can run. "
        "Call update_plan with the research question, criteria fixed before seeing results, and typed steps. "
        "For exact parameter checks, first call run_operation with prepare_only: true and bind its proposal_ref "
        "to a step. After plan approval, resume execution within the plan."
    ),
}


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

    def _auto_draft_classes(self, steps):
        from .permissions import on_floor, request_for_operation
        from .plans import PLANNABLE
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        classes = set()
        for operation_id in {operation for step in steps for operation in step.operation_ids}:
            if operation_id == "operation.multi_step":
                continue  # The preflight rejects wrapper IDs in place of concrete operations.
            contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id) or self.operation_registry.require(operation_id)
            request = request_for_operation(operation_id, {}, risk_level=contract.risk_level)
            if request.permission_class in PLANNABLE and not on_floor(request):
                classes.add(request.permission_class.value)
        return sorted(classes)


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
        except (KeyError, FileNotFoundError):
            chain_id = None
        active_head = str(preconditions.get("active_head_run_id") or target["run_id"])
        if isinstance(chain_id, str) and chain_id:
            try:
                active_head = self._resolve_chain_head(chain_id, active_head)
            except ChainHeadConflict as exc:
                import json

                head = self._resolve_chain_head(chain_id, None)
                if str(target["run_id"]) == head:
                    # QRData 054 and 283 (3f281a47 round) targeted the head but miscopied it into
                    # preconditions; the inspect detour cost a call each. Fresh preconditions are
                    # still checked when it is proposed again.
                    raise ToolVisibleError(
                        f"ACTIVE_HEAD_MISMATCH: preconditions.active_head_run_id {active_head} is not the current "
                        f"head; target.run_id {head} is. The operation was not executed. Copy {head} exactly into "
                        "preconditions.active_head_run_id and propose again; target is unchanged."
                    ) from exc
                read_arguments = {"owner_run_id": str(target["run_id"]),
                    "op_node_id": str(target["node_ref"]), "active_head_run_id": head}
                raise ToolVisibleError(
                    f"ACTIVE_HEAD_MISMATCH: current conversation head is {head}, not {active_head}. "
                    "The operation was not executed; target.run_id and target.node_ref remain unchanged. "
                    "Verify the original source with inspect_node_context "
                    + json.dumps(read_arguments, ensure_ascii=False)
                    + "; then re-propose only after checking that source and fresh preconditions."
                ) from exc
        snapshot = inspect(
            InspectNodeContextRequest(
                request_id=f"propose:{target['run_id']}",
                owner_run_id=str(target["run_id"]),
                op_node_id=str(target["node_ref"]),
                active_head_run_id=active_head,
            )
        )
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
        from ..services.rerun_service import saved_rerun_input_fingerprint

        resolved = resolve_analysis_loop_inputs(
            project_root,
            run_id=source_run_id,
            cluster_variable=cluster_variable,
        )
        if resolved.source.run_id != source_run_id:
            raise ValueError("analysis_loop_source_identity_mismatch")
        try:
            input_fingerprint = saved_rerun_input_fingerprint(project_root, source_run_id)
        except FileNotFoundError:
            # Registered result history can be inspected without legacy rerun inputs.
            input_fingerprint = None
        except (OSError, TypeError, ValueError) as exc:
            raise ToolVisibleError("MODEL_RERUN_SOURCE_UNAVAILABLE: The saved inputs cannot be verified.") from exc

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
            rerun_input_fingerprint=input_fingerprint,
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
            plan_only = arguments.get("prepare_only") is True
            bound_proposal = None
            if "proposal_ref" in arguments:
                from .plans import PlanProposalRef
                from .plan_preflight import PlanBindingError, resolve_proposal

                ref = PlanProposalRef.from_dict(arguments["proposal_ref"])
                try:
                    bound_proposal = resolve_proposal(self.repository, session_id, ref)
                except PlanBindingError as exc:
                    raise ToolVisibleError(str(exc)) from exc
                arguments = bound_proposal.to_dict()
            referenced = "request_ref" in arguments
            if referenced:
                from .operation_request_refs import resolve_completion_request
                arguments = resolve_completion_request(self, session_id=session_id, request_ref=arguments["request_ref"])
                bound_target, bound_preconditions = dict(arguments["target"]), dict(arguments["preconditions"])
            operation_id = str(arguments["operation_id"])
            if bound_proposal is not None:
                operation_chain = bound_proposal.chain_id
            else:
                if plan_only:
                    run_id = arguments["target"]["run_id"]
                    if Path(run_id).name != run_id or run_id.startswith(".") or "\\" in run_id:
                        raise ToolVisibleError("Plan preparation needs a project run identifier.")
                operation_chain = self._operation_chain(session_id, arguments["target"])
                if plan_only:
                    arguments = self._bind_plan_workflow_source(arguments, session_id, operation_chain)
                else:
                    arguments = self._canonicalize_proposal_arguments(
                        operation_id, arguments, session_id=session_id, chain_id=operation_chain,
                    )
            if referenced and (arguments["target"] != bound_target or arguments["preconditions"] != bound_preconditions):
                from .operation_request_refs import _fail
                raise _fail("canonical source or preconditions changed")
            metadata = context.metadata
            allowed_operations = None
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
            invocation = (ProposalInvocation(invocation_id=metadata["invocation_id"],
                provider_step=metadata["provider_step"], tool_call_id=metadata["tool_call_id"])
                if metadata.get("invocation_id") is not None else None)
            denial = self._operation_policy_denial(arguments, allowed_operations=allowed_operations)
            if denial is not None:
                return denial
            if bound_proposal is not None:
                return await self._run_bound_plan_proposal(bound_proposal, session_id, invocation)
            if plan_only:
                from .plan_preflight import operation_ids
                from .plans import PlanProposalRef

                proposal = self.admit_operation_request(OperationRequest.from_arguments(arguments),
                    chain_id=operation_chain, session_id=session_id, command_id=command_id,
                    invocation=invocation, plan_only=True).proposal
                return {"prepared": True, "proposal_ref": PlanProposalRef.of(proposal).to_dict(),
                        "operation_ids": operation_ids(proposal),
                        "guidance": "Bind proposal_ref to a plan step with update_plan. This request has not executed."}
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
            preconditions = dict(arguments["preconditions"])
            if is_rerun_operation(operation_id):
                preconditions.pop("rerun_input_fingerprint", None)
                input_fingerprint = self._preflight_model_rerun_declarations(
                    arguments, metadata_edit=operation_id == "metadata.edit"
                )
                if input_fingerprint is not None:
                    preconditions["rerun_input_fingerprint"] = input_fingerprint
            current_plan = None
            if operation_id == "operation.multi_step":
                if self.execution_mode == "auto":
                    current_plan = self._current_plan(session_id)
                    if current_plan is None or current_plan.status in {"draft", "needs_approval"}:
                        return dict(_AUTO_WORKFLOW_PLAN_REQUIRED)
                source_sha = self._preflight_workflow_columns(arguments)
                if source_sha is not None:
                    preconditions["source_artifact_fingerprint"] = source_sha
                self._preflight_pack_steps(arguments)
                self._preflight_claimed_exclusions(arguments, self._latest_user_text(session_id))
            request = OperationRequest.from_arguments(
                {**arguments, "operation_id": operation_id, "preconditions": preconditions})
            if current_plan is not None:
                report_recovery = self._auto_plan_report_recovery(request, plan=current_plan, session_id=session_id)
                if report_recovery is not None:
                    return report_recovery
            receipt = self.admit_operation_request(
                request,
                chain_id=operation_chain,
                session_id=session_id,
                command_id=command_id,
                invocation=invocation,
            )
            proposal = receipt.proposal
            return await self._run_or_await_confirmation(proposal, session_id=session_id)

        async def update_plan(arguments: dict[str, Any], context) -> dict[str, Any]:
            from . import plans as plan_module
            from .completion import source_receipt, validate_completion_evidence, CompletionEvidenceError
            from .completion_targets import contract_targets
            from .plan_preflight import PROJECT_OPERATION_DENIED, WORKFLOW_STEP_OPERATIONS_REQUIRED, check_plan
            from .task_requirements import enforce
            from dataclasses import replace

            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            preflight = None
            try:
                completion = arguments.get("completion")
                if completion is not None:
                    root = getattr(self.context_provider, "project_root", self.repository.root.parent)
                    given = completion["source"]
                    receipt = source_receipt(root, {"run_id": given["run_id"], "artifact_id": given["artifact_id"]})
                    if receipt is None and str(given["artifact_id"]).startswith("stage:"):
                        # A dataset node names its registered payload exactly (the graph owns the
                        # reference); "stage:cleaned" was refused and resent twice on 2026-11-08.
                        from ..data_operations.casts import dataset_node_artifact_id
                        resolved = dataset_node_artifact_id(root, given["run_id"], given["artifact_id"])
                        receipt = source_receipt(root, {"run_id": given["run_id"], "artifact_id": resolved}) if resolved else None
                        if receipt is not None:
                            from .tools import tool_note
                            tool_note(f"completion.source named the dataset node {given['artifact_id']}; it is bound "
                                      f"to that node's registered dataset artifact_id {resolved}.")
                    if receipt is None:
                        raise plan_module.PlanError(
                            f"completion source {given['run_id']}/{given['artifact_id']} is not a registered dataset; "
                            "name the cleaned dataset (for example artifact_id cleaned_dataset) of a run in this chain")
                    if given.get("sha256") not in (None, receipt["sha256"]):
                        from .tools import tool_note
                        wrong = sum(a != b for a, b in zip(str(given["sha256"]), receipt["sha256"]))
                        tool_note(f"completion.source.sha256 is bound from the registered dataset; the value given "
                                  f"differed in {wrong} of 64 characters and was not used.")
                    completion = {**completion, "source": receipt}
                    arguments = {**arguments, "completion": completion}
                known_operations = self.known_plan_operations()
                def revise(previous):
                    nonlocal preflight
                    if "steps" not in arguments and previous is not None:
                        # Omitted steps are kept, as an omitted question or criteria are: an update
                        # that sent only its completion was refused and resent whole (2026-11-08).
                        steps = previous.steps
                    elif "steps" not in arguments:
                        raise plan_module.PlanError("steps are required for a new plan")
                    else:
                        steps = plan_module.parse_steps(arguments.get("steps"), known_operations,
                            previous_steps=previous.steps if previous else ())
                    if 'completion_evidence' in arguments:
                        effective_completion = completion if completion is not None else previous.completion if previous else None
                        root = getattr(self.context_provider, 'project_root', self.repository.root.parent)
                        validate_completion_evidence(root, effective_completion, arguments['completion_evidence'])
                    requirements = self._bind_task_requirements(session_id, previous)
                    previous_targets = contract_targets(previous.completion) if previous and previous.completion else []
                    for target in contract_targets(completion):
                        if (requirements['status'] == 'verified' and target['estimand'] not in requirements['estimands']
                                and target not in previous_targets):
                            # A target is the person's requirement, not the Agent's choice: IV Auto
                            # (2026-10-31) volunteered ATE on an IV question, which no producer can
                            # certify, and spent all eight nudges on a requirement nobody had asked for.
                            raise plan_module.PlanError(
                                f"completion target {target['estimand']} was not requested by the person. Remove it and "
                                "state in your answer which quantity the method identifies under which assumptions.")
                    if completion is not None and requirements['status'] == 'verified':
                        named = contract_targets(completion)
                        requested = enforce({'scope': completion.get('scope', 'analysis'),
                            **({'targets': named} if len(named) > 1 else {'target': named[0]} if named else {}),
                            'status': 'requirements_met', 'missing': []}, requirements)
                        if requested['missing']:
                            raise plan_module.PlanError('Completion contract conflicts with the user request: '
                                + ', '.join(requested['missing']) + '. Keep the server-bound task requirements; only a human plan revision can narrow them.')
                    # A status update that leaves out the question or criteria keeps them:
                    # reading the omission as "now empty" made each such update a change
                    # of criteria needing approval again (paid fix2 round, panel, Auto).
                    question = (str(arguments["question"]).strip()[:1000] if "question" in arguments
                                else previous.question if previous is not None else "")
                    criteria = ([str(c)[:300] for c in arguments.get("criteria") or ()][:12] if "criteria" in arguments
                                else list(previous.criteria) if previous is not None else [])
                    basis = previous
                    if (previous is not None and previous.completion is not None and completion is not None
                            and previous.completion.get('scope') == 'question'
                            and completion.get('scope', 'analysis') == 'analysis'
                            and requirements['status'] == 'verified' and requirements['scope'] == 'analysis'
                            and {k: v for k, v in previous.completion.items() if k not in {'scope', 'playbooks'}}
                                == {k: v for k, v in completion.items() if k not in {'scope', 'playbooks'}}):
                        # A real user expanded the task. Draft the stronger contract;
                        # preserve source/target and retire the old approval/evidence.
                        basis = replace(previous, completion=completion, completion_evidence=None,
                                        status='needs_approval' if previous.approved_version is not None else 'draft')
                    allowed_classes = arguments.get("allowed_classes")
                    if self.execution_mode == "auto" and (previous is None or previous.status == "draft"):
                        # Show the classes the concrete steps need before the person approves the draft.
                        allowed_classes = self._auto_draft_classes(steps)
                    plan = plan_module.merge(
                        basis,
                        question=question,
                        criteria=criteria,
                        steps=steps,
                        budget={k: int(v) for k, v in (arguments.get("budget") or {}).items()
                                if k in {"steps", "wall_s", "inferential"} and str(v).isdigit()},
                        allowed_classes=allowed_classes,
                        completion=arguments.get("completion"),
                        completion_evidence=arguments.get("completion_evidence"),
                    )
                    plan = replace(plan, task_requirements=requirements)
                    if not plan.question:
                        raise plan_module.PlanError("question is required")
                    has_bound_steps = any(step.proposal_ref is not None for step in plan.steps)
                    if self.execution_mode == "auto" or has_bound_steps:
                        report = check_plan(self.data_operation_project_root or self.repository.root.parent,
                                            self.repository, session_id, plan, registry=self.operation_registry)
                        checks = [(step["step_id"], check) for step in report["steps"] for check in step["checks"]
                                  if check["status"] == "blocked"]
                        if self.execution_mode == "auto":
                            if any(check["code"] == WORKFLOW_STEP_OPERATIONS_REQUIRED for _, check in checks):
                                raise plan_module.PlanError(
                                    "operation.multi_step wraps a workflow. Fill operation_ids with the actual "
                                    "workflow step operation IDs from changes.steps. To bind exact parameters, "
                                    "copy operation_ids and proposal_ref from run_operation with prepare_only. "
                                    "Project rules apply to each step."
                                )
                            denied = [check["operation_id"] for _, check in checks
                                      if check["code"] == PROJECT_OPERATION_DENIED]
                            if denied:
                                operations = ", ".join(dict.fromkeys(denied))
                                raise plan_module.PlanError(
                                    f"The current project rules deny the planned operations: {operations}. "
                                    "Revise the plan around an allowed method only if it answers the question."
                                )
                        if has_bound_steps:
                            preflight = {"status": report["status"], "blockers": [
                                {"step_id": step_id, "message": check["message"]} for step_id, check in checks[:5]]}
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
            except CompletionEvidenceError as exc:
                return {'saved': False, 'error': str(exc), 'error_code': exc.code,
                        'evidence_corrections': exc.corrections,
                        'guidance': 'The rejected bindings were not saved. Copy exact registered completion_ref values; '
                                    'keep existing results and recheck completion after correcting the plan.'}
            except plan_module.PlanError as exc:
                return {"saved": False, "error": str(exc),
                        "guidance": "The rejected change was not applied. Follow the error; if it requires a "
                                    "human revision, pause for takeover rather than retrying the same change."}
            needs_person = (self.execution_mode == "auto" and plan.status in {"draft", "needs_approval"}
                            and (preflight is None or preflight["status"] != "blocked"))
            reopened = plan.status == "needs_approval" and plan.approved_version is not None
            return {
                "saved": True,
                **({"preflight": preflight} if preflight is not None else {}),
                "plan": plan_tool_view(plan.to_dict()),
                "update_hint": "For step updates, send plan.steps; plan.step_state is read-only audit evidence.",
                **({"approval_reopened": (
                    "The approved plan's question, criteria, budget or allowed kinds changed, so it needs the "
                    "person's approval again, and the change is recorded. Question and criteria are fixed "
                    "once approved: to record progress, send update_plan without them.")} if reopened else {}),
                **({"requires_confirmation": True, "awaiting": "plan_approval"} if needs_person else {}),
                "guidance": (
                    "The plan contains a blocked parameter or source check. Correct the exact proposal and "
                    "update its binding before requesting plan approval."
                    if preflight and preflight["status"] == "blocked" else
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

        def inspect_analysis_completion(arguments, context):
            if context.session_id != session_id:
                raise ValueError("tool session is outside the registered chain scope")
            result = self._completion_check(session_id, suggest=True)
            from .operation_request_refs import offer_completion_requests
            result = offer_completion_requests(self, session_id=session_id, result=result, metadata=context.metadata)
            if "source" in arguments:
                from .completion import source_receipt
                root = getattr(self.context_provider, "project_root", self.repository.root.parent)
                source = {key: arguments["source"][key] for key in ("run_id", "artifact_id")}
                result["source"] = source_receipt(root, source)
                given = arguments["source"].get("sha256")
                if given and isinstance(result["source"], dict) and result["source"].get("sha256") not in (None, given):
                    from .tools import tool_note
                    tool_note("source.sha256 differs from the verified dataset; use the sha256 returned here.")
            return result

        return build_chain_tool_registry(
            context_tools=context_tools,
            proposal_tool_schema=lambda: self.operation_registry.proposal_tool_schema(),
            update_plan=update_plan,
            run_operation=run_operation,
            plan_analysis=plan_analysis,
            inspect_analysis_completion=inspect_analysis_completion,
            normalize_target=lambda arguments: normalize_operation_target(self.operation_registry, arguments),
        )

    def _bind_plan_workflow_source(self, arguments, session_id, chain_id):
        from .operation_handlers.proposal_arguments import _workflow_dataset_node
        from .plan_preflight import PlanBindingError, registered_workflow_source
        from .plans import MAX_STEPS

        root = self.data_operation_project_root
        if root is None or arguments["operation_id"] != "operation.multi_step":
            raise ToolVisibleError("Plan preparation requires a project dataset workflow.")
        if len(arguments["changes"]["steps"]) > MAX_STEPS:
            raise ToolVisibleError(f"A plan-bound workflow can contain at most {MAX_STEPS} workflow steps.")
        target = dict(arguments["target"])
        try:
            target["node_ref"] = _workflow_dataset_node(root, target["run_id"], target["node_ref"])
            source = registered_workflow_source(root, target)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, PlanBindingError) else "Inspect the dataset and select a registered source."
            raise ToolVisibleError(f"PLAN_SOURCE_UNAVAILABLE: {reason}") from exc
        if target.get("artifact_id") not in (None, source.artifact_id):
            from .tools import tool_note

            tool_note("The source artifact was bound from the selected dataset node. Inspect its registered identity.")
        target["artifact_id"] = source.artifact_id
        bound = self._bind_workflow_preconditions({**arguments, "target": target}, session_id=session_id, chain_id=chain_id)
        return {**bound, "preconditions": {**bound["preconditions"], "source_artifact_fingerprint": source.sha256}}

    async def _run_bound_plan_proposal(self, proposal, session_id, invocation):
        from .operation_requests import publish
        from .plan_preflight import check_step
        from .plans import PlanProposalRef

        plan = self._current_plan(session_id)
        ref = PlanProposalRef.of(proposal)
        step = next((item for item in (plan.steps if plan else ()) if item.proposal_ref == ref), None)
        if step is None or step.status in {"done", "skipped", "failed"}:
            raise ToolVisibleError("Bind the exact proposal to an open step of the current plan before running it.")
        root = self.data_operation_project_root or self.repository.root.parent
        check = check_step(root, self.repository, session_id, step, registry=self.operation_registry, cache={},
                           completion=plan.completion)
        if check["status"] == "blocked":
            reason = next(item["message"] for item in check["checks"] if item["status"] == "blocked")
            raise ToolVisibleError(f"PLAN_PREFLIGHT_BLOCKED: {reason}")
        if proposal.operation_id == "operation.multi_step":
            self._preflight_claimed_exclusions(proposal.to_dict(), self._latest_user_text(session_id))
            if self.execution_mode == "auto" and plan.status in {"draft", "needs_approval"}:
                return dict(_AUTO_WORKFLOW_PLAN_REQUIRED)
        try:
            active = self.proposal_store.activate_plan_proposal(proposal)
        except ProposalConfirmationError as exc:
            raise ToolVisibleError(str(exc)) from exc
        if proposal.status == "plan_prepared":
            publish(active, repository=self.repository, events=self.events, invocation=invocation)
        return await self._run_or_await_confirmation(active, session_id=session_id, checked_plan=plan,
                                                     bound_preflight_ready=check["status"] == "ready")

