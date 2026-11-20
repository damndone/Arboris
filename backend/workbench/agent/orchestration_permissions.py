"""orchestration permissions: methods over the existing shared state."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _proposal_matches_plan_source(project_root, proposal, source):
    """Verify the actual input artifact, including reruns of that same source."""
    from ..graph_model import NodeKind
    from ..lineage.model_inputs import input_datasets
    from ..lineage.run_inputs import read_run_inputs
    from ..services.rerun_service import rerun_input_fingerprint
    from .completion import _DATA_TYPES, _Products
    from .plan_preflight import registered_workflow_source
    from .plans import MAX_STEPS

    if project_root is None:
        return False
    root = Path(project_root).resolve()
    products = _Products(root)
    try:
        approved = products.load(source)
        if (approved is None or approved.artifact_type not in _DATA_TYPES
                or approved.sha256 != source.get("sha256")):
            return False
        run_id, node_ref = proposal.target["run_id"], proposal.target["node_ref"]
        if (not run_id or Path(run_id).name != run_id or run_id.startswith(".") or "\\" in run_id
                or (products.runs / run_id).resolve() != products.runs / run_id):
            return False
        lineage = input_datasets(root, run_id, node_ref)
        if lineage is None:
            return False
        kind, inputs, datasets = lineage
        if kind == NodeKind.MODEL and len(inputs) == 1:
            node_ref = inputs[0]
        bound = registered_workflow_source(root, {"run_id": run_id, "node_ref": node_ref})
        if proposal.operation_id == "operation.multi_step" and bound.artifact_id != proposal.target.get("artifact_id"):
            return False
        ancestors = products.ancestors(bound.view())
        if not any(item.artifact_id == approved.artifact_id and item.sha256 == approved.sha256 for item in ancestors):
            return False
        if proposal.operation_id == "model.rerun":
            # Bind the upload RerunService will consume to the selected model's
            # own raw snapshot, including when that model belongs to a rerun.
            raw_node = "stage:raw" if "stage:raw" in datasets else "stage:source"
            raw = registered_workflow_source(root, {"run_id": run_id, "node_ref": raw_node})
            raw_artifact = products.load(raw.view())
            saved = read_run_inputs(products.runs / run_id)
            if (raw_artifact is None or raw_artifact.artifact_type != "raw_data" or raw_artifact not in ancestors
                    or rerun_input_fingerprint(saved) != proposal.preconditions.get("rerun_input_fingerprint")
                    or saved["upload"]["sha256"] != raw_artifact.sha256):
                return False
        if run_id == source["run_id"] or any(products.lineage_cache[child]["source"] == source
                                                for child in products.verified_lineage):
            return True
        # Reruns need both the verified input bytes and a lineage link to the approved run.
        for _ in range(MAX_STEPS):
            run_root = products.runs / run_id
            if (run_root.resolve() != run_root or run_root.parent != products.runs
                    or (run_root / "run_inputs.json").stat().st_size > 2_000_000):
                return False
            inputs = read_run_inputs(run_root)
            parent = inputs.get("rerun_of") if isinstance(inputs, dict) else None
            if parent == source["run_id"]:
                return True
            if not isinstance(parent, str) or not parent or parent == run_id:
                return False
            run_id = parent
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return False


class OrchestrationPermissions:
    @property
    def plan_store(self):
        from .plans import PlanStore

        return PlanStore(self.repository.root)


    def _current_plan(self, session_id: str):
        try:
            return self.plan_store.current(session_id)
        except (OSError, ValueError, KeyError):
            return None


    @staticmethod
    def _proposal_operation_ids(proposal: Any) -> list[str]:
        if str(proposal.operation_id) == "operation.multi_step":
            return [str(step.get("operation_id", "")) for step in proposal.changes.get("steps") or ()
                    if isinstance(step, dict)]
        return [str(proposal.operation_id)]


    def known_plan_operations(self) -> set[str]:
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        return set(WORKFLOW_STEP_SPEC_CONTRACTS) | set(
            self.operation_registry.natural_language_operation_ids(scope_requirements=("chain", "active_head"))
        )


    def _permission_request(self, proposal: Any, *, within_budget: bool):
        from .permissions import request_for_proposal

        scope = self.plan_scope
        if scope and "proposal_ref" in scope:
            from .plans import PlanProposalRef

            if (scope["proposal_ref"] != PlanProposalRef.of(proposal)
                    or scope["session_id"] != proposal.session_id):
                scope = None
        return request_for_proposal(self.repository, self.operation_registry, proposal,
                                    within_budget=within_budget, scope=scope)


    def operation_denied(self, operation_id: str) -> bool:
        """Whether the project's rules refuse this operation itself; names a path, grants nothing."""
        from . import permissions

        rules = self.permission_rules or permissions.Rules()
        if not rules.deny:
            return False
        try:
            definition = self.operation_registry.require(operation_id, "v1")
        except Exception:  # noqa: BLE001 - an unknown operation is simply not named
            return False
        request = permissions.request_for_operation(operation_id, {}, risk_level=definition.risk_level)
        mode = permissions.Mode.AUTO if self.execution_mode == "auto" else permissions.Mode.ASK
        return permissions.decide(mode, request, rules).outcome == permissions.Outcome.DENY


    def _operation_policy_denial(self, arguments, *, allowed_operations=None):
        """Refuse a project-denied request before it becomes a review card."""
        from . import permissions

        rules = self.permission_rules or permissions.Rules()
        if not rules.deny:
            return None
        definition = self.operation_registry.require(arguments["operation_id"], arguments.get("operation_version", "v1"))
        request = permissions.request_for_operation(definition.operation_id, arguments["changes"],
                                                    risk_level=definition.risk_level)
        mode = permissions.Mode.AUTO if self.execution_mode == "auto" else permissions.Mode.ASK
        decision = permissions.decide(mode, request, rules)
        if decision.outcome != permissions.Outcome.DENY:
            return None

        blocked = list(dict.fromkeys(part.operation_id for part in request.components
                                    if permissions.decide(mode, part, rules).outcome == permissions.Outcome.DENY))
        denied = {
            "executed": False, "denied": True, "reason": decision.reason,
            "blocked_operations": blocked or [request.operation_id],
            "guidance": "No proposal was created. Do not resubmit the denied operation or ask for approval.",
        }
        if (blocked == ["model.genesis"]
                and not any(rule.operation_id and any(rule.matches(part)
                            for part in (request, *request.components)) for rule in rules.deny)
                and (allowed_operations is None or "model.rerun" in allowed_operations)):
            rerun = self.operation_registry.require("model.rerun")
            refit = permissions.request_for_operation(rerun.operation_id, {}, risk_level=rerun.risk_level)
            if permissions.decide(mode, refit, rules).outcome != permissions.Outcome.DENY:
                from ..services.rerun_service import editable_rerun_nodes
                run_id = arguments["target"]["run_id"]
                try:
                    nodes = [node for node in editable_rerun_nodes(
                        getattr(self.context_provider, "project_root", None), run_id) if node.startswith("model:")]
                except Exception:
                    nodes = []
                # binary_logit.open.r3 (7821c4c7): told to refit only a model matching its intended
                # specification (with added controls), the Agent never refitted the existing model
                # with Logit, which answers the question, and ran only tests.
                denied["recovery"] = {
                    "inspection_tool": "inspect_operation_contract",
                    "operation_id": "model.rerun",
                    "source_run_id": run_id,
                    **({"model_nodes": nodes} if nodes else {}),
                    "guidance": (
                        "model.rerun refits a verified existing model on this exact dataset: it keeps that "
                        "model's outcome, predictors, terms and sample, and may change its estimator "
                        "(model_type) to a family declared for the outcome. Inspect its contract with "
                        "op_node_id set to the existing model node"
                        + (f" ({', '.join(nodes)})" if nodes else "") + ". If that refit answers the "
                        "research question, propose it; it has its own permission and approval. Predictors "
                        "or terms the existing model lacks stay blocked: state them as a limitation, never "
                        "as completed. Run post-estimation only against the new fitted result."
                    ),
                }
        return denied


    def _auto_plan_report_recovery(self, operation, *, plan, session_id, plan_source_verified=False):
        """Check a report that would receive credit under the approved analysis plan."""
        if self.execution_mode != "auto" or plan is None or not plan.completion:
            return None
        if operation.operation_id != "operation.multi_step" or plan.completion.get("scope", "analysis") != "analysis":
            return None
        steps = operation.changes.get("steps") or ()
        operation_ids = [step["operation_id"] for step in steps]
        if "report.compose" not in operation_ids:
            return None
        project_root = getattr(self.context_provider, "project_root", None)
        if project_root is None:
            return None
        if not plan_source_verified:
            from .plans import scope_for

            if not scope_for(plan, operation_ids)["in_plan"]:
                return None
            if not _proposal_matches_plan_source(project_root, operation, plan.completion["source"]):
                return None

        from .report_sources import validate_plan_report_sources
        from .workflow import WorkflowExecutionError
        from .workflow_contracts import validate_workflow_steps

        try:
            validate_plan_report_sources(project_root, operation.target, validate_workflow_steps(steps))
        except WorkflowExecutionError as exc:
            reason = str(exc)
        else:
            return None

        from .delivery import delivery_check, delivery_digest

        check = delivery_check(project_root, plan, session_id=session_id)
        return {
            "executed": False,
            "error_code": "PLAN_REPORT_RESULT_REFS_REQUIRED",
            "guidance": reason + " Follow the delivery check to select evidence or obtain its exact report request.",
            "delivery_check": delivery_digest(check),
        }


    async def _run_or_await_confirmation(self, proposal: Any, *, session_id: str,
                                         checked_plan=None, bound_preflight_ready: bool = False) -> dict[str, Any]:
        """Run what the person's mode, rules and grants allow; leave the rest for them.

        The model receives an executed operation's results in the same turn, so
        it answers with the numbers instead of asking for a click.
        """

        from ..analysis_ledger import inferential_count, read as read_ledger
        from . import permissions
        from .read_only_policy import ACTOR, decide as read_only_budget

        project_root = getattr(self.context_provider, "project_root", None)
        prior = inferential_count(read_ledger(project_root), session_id=session_id) if project_root else 0
        plan = self._current_plan(session_id)
        operation_ids = self._proposal_operation_ids(proposal)
        source_mismatch = False
        if plan is not None:
            from . import plans as plan_module

            ref = plan_module.PlanProposalRef.of(proposal)
            self.plan_scope = plan_module.scope_for(plan, operation_ids,
                executed_steps=sum(s.status == "done" for s in plan.steps),
                proposal_ref=ref,
                bound_preflight_ready=bound_preflight_ready and checked_plan == plan)
            source = (plan.completion or {}).get("source")
            if (self.execution_mode == "auto" and source is not None and self.plan_scope["in_plan"]
                    and not _proposal_matches_plan_source(project_root, proposal, source)):
                self.plan_scope["in_plan"] = False
                source_mismatch = True
            self.plan_scope.update(proposal_ref=ref, session_id=session_id, plan_snapshot=plan)
        elif self.plan_scope and "proposal_ref" in self.plan_scope:
            self.plan_scope = None
        budget = read_only_budget(proposal.operation_id, proposal.changes, prior_inferential_steps=prior)
        request = self._permission_request(proposal, within_budget=True)
        if request.permission_class == permissions.PermissionClass.ANALYZE:
            # Read-only analysis has its own limits (steps per workflow, tests per
            # conversation), because many tests is where p-hacking lives.
            from dataclasses import replace

            request = replace(request, within_budget=request.within_budget and budget.allowed)
        configured_rules = self.permission_rules or permissions.Rules()
        rules = permissions.with_execution_policy(configured_rules, self.execution_policy)
        mode = permissions.Mode(self.execution_mode if self.execution_mode in {"ask", "auto"} else "ask")
        decision = permissions.decide(mode, request, rules, self.session_grants or permissions.Grants())
        if decision.outcome == permissions.Outcome.DENY:
            return {"executed": False, "denied": True, "proposal_id": proposal.proposal_id,
                    "reason": decision.reason,
                    "guidance": "A project rule forbids this operation. Tell the person; do not try another route to it."}
        if request.in_plan and decision.outcome == permissions.Outcome.ALLOW:
            report_recovery = self._auto_plan_report_recovery(proposal, plan=plan, session_id=session_id,
                                                             plan_source_verified=True)
            if report_recovery is not None:
                return report_recovery
        if decision.outcome == permissions.Outcome.ASK or self.read_only_runner is None or project_root is None:
            reason = decision.reason if decision.outcome == permissions.Outcome.ASK else "no runner is attached"
            spent_analysis_budget = (request.permission_class == permissions.PermissionClass.ANALYZE
                and reason == "the approved plan's budget is spent"
                and (self.plan_scope or {}).get("within_budget", True))
            if not decision.floor and not budget.allowed and (mode == permissions.Mode.ASK or spent_analysis_budget):
                # The read-only policy names what made it wait (a data change,
                # the session's test budget), which is the more useful reason.
                reason = budget.reason
            if self.execution_policy != "auto_read_only" and decision.outcome == permissions.Outcome.ASK and not decision.floor:
                # Review only explains an extra wait it introduced. Preserve
                # project, plan and budget reasons that already required ASK.
                configured_decision = permissions.decide(mode, request, configured_rules,
                                                         self.session_grants or permissions.Grants())
                reason = ("Review before execution was requested for this turn."
                          if configured_decision.outcome == permissions.Outcome.ALLOW else configured_decision.reason)
                if not budget.allowed and request.permission_class == permissions.PermissionClass.ANALYZE:
                    without_session_budget = permissions.decide(mode, replace(request, within_budget=True),
                        configured_rules, self.session_grants or permissions.Grants())
                    if without_session_budget.outcome == permissions.Outcome.ALLOW:
                        reason = budget.reason
            if source_mismatch and reason == "this step is not in the approved plan":
                reason = "The approved plan's source is a different registered dataset."
            elif (mode == permissions.Mode.AUTO and checked_plan is not None and checked_plan == plan
                    and plan.status == "approved" and not bound_preflight_ready
                    and reason == "this step is not in the approved plan"):
                reason = "This exact proposal still has deferred parameter checks and needs your review."
            return {"requires_confirmation": True, "proposal": proposal.to_dict(), "confirmation_reason": reason,
                    **({"plan_recovery": self.plan_scope["plan_recovery"]}
                       if self.plan_scope and self.plan_scope.get("plan_recovery") else {}),
                    "permission_class": request.permission_class.value}
        actor = ACTOR if request.permission_class == permissions.PermissionClass.ANALYZE else decision.authority
        try:
            record = await (self.read_only_runner(proposal) if actor == ACTOR
                            else self.read_only_runner(proposal, actor))
        except Exception as exc:  # noqa: BLE001 - reported to the model, never swallowed
            # A tool exception would end the turn as a runtime error; the user
            # is better served by the Agent explaining what stopped the run.
            detail = getattr(exc, "message", None) or str(exc) or type(exc).__name__
            return {
                "executed": False,
                "proposal_id": proposal.proposal_id,
                "error": f"{type(exc).__name__}: {detail}",
                "guidance": (
                    "The operation could not run. Tell the user what stopped it; do not report any result."
                ),
            }
        results = []
        results_reader = getattr(self.context_provider, "executed_workflow_results", None)
        if record.status == "completed" and results_reader is not None:
            results = results_reader(record)
        plan_update_conflict = False
        if plan is not None and request.in_plan:
            from . import plans as plan_module

            expected_plan = plan
            def mark_current(current):
                if current != expected_plan:
                    raise plan_module.PlanError("plan changed during execution")
                return plan_module.mark_executed(current, operation_ids, record.status,
                                                  proposal_ref=plan_module.PlanProposalRef.of(proposal))
            try:
                plan = self.plan_store.update(session_id, mark_current,
                    operation_record_id=record.record_id if record.status in {"completed", "failed"} else None)
            except plan_module.PlanError:
                # The operation already happened. Preserve its result and the
                # user's newer plan; do not replay or replace either of them.
                plan_update_conflict = True
        tests_run = prior + (budget.inferential_steps if record.status == "completed" else 0)
        from .delivery import delivery_check, delivery_digest

        digest = delivery_digest(delivery_check(project_root, self._current_plan(session_id), session_id=session_id))
        return {
            **({"delivery_check": digest} if digest else {}),
            "executed": True,
            "authorized_by": actor,
            "authorization_reason": decision.reason,
            "proposal_id": proposal.proposal_id,
            "operation": {
                "record_id": record.record_id,
                "status": record.status,
                "error": record.error,
            },
            "results": results,
            "inferential_tests_run_this_session": tests_run,
            **({"plan_update_conflict": True,
                "plan_update_note": "The plan changed during execution. The operation is recorded; review its step status without rerunning it."}
               if plan_update_conflict else {}),
            "guidance": (
                "This operation ran without a confirmation ("
                + decision.reason
                + ") and is recorded in the analysis ledger. Answer from these results only; say how many "
                "tests were run in this session when you report a p-value."
                if record.status == "completed"
                else "The workflow failed; tell the user what failed from operation.error."
            ),
        }

