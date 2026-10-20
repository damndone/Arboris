"""orchestration permissions: methods over the existing shared state."""
from __future__ import annotations
from typing import Any

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
        from . import permissions

        definition = self.operation_registry.require(proposal.operation_id, proposal.operation_version)
        request = permissions.request_for_operation(proposal.operation_id, proposal.changes,
            risk_level=definition.risk_level, within_budget=within_budget, scope=self.plan_scope)
        run_id, node_ref = proposal.target.get("run_id"), proposal.target.get("node_ref")
        if run_id and node_ref:
            from dataclasses import replace
            from ..analysis_loop.lifecycle import latest_target_correction

            correction = latest_target_correction(self.repository, proposal.session_id, run_id, node_ref)
            if correction is not None and not correction["confirmed"]:
                request = replace(request, target_decision_required=True)
        return request


    async def _run_or_await_confirmation(self, proposal: Any, *, session_id: str) -> dict[str, Any]:
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
        if plan is not None:
            from . import plans as plan_module

            self.plan_scope = plan_module.scope_for(plan, operation_ids,
                                                    executed_steps=sum(s.status == "done" for s in plan.steps))
        budget = read_only_budget(proposal.operation_id, proposal.changes, prior_inferential_steps=prior)
        request = self._permission_request(proposal, within_budget=True)
        if request.permission_class == permissions.PermissionClass.ANALYZE:
            # Read-only analysis has its own limits (steps per workflow, tests per
            # conversation), because many tests is where p-hacking lives.
            from dataclasses import replace

            request = replace(request, within_budget=budget.allowed)
        rules = self.permission_rules or permissions.Rules()
        if self.execution_policy != "auto_read_only":
            # "Review before running": every class asks, read-only analysis included.
            rules = permissions.Rules(allow=rules.allow, deny=rules.deny,
                                      ask=(*rules.ask, permissions.Rule(permissions.PermissionClass.ANALYZE)))
        mode = permissions.Mode(self.execution_mode if self.execution_mode in {"ask", "auto"} else "ask")
        decision = permissions.decide(mode, request, rules, self.session_grants or permissions.Grants())
        if decision.outcome == permissions.Outcome.DENY:
            return {"executed": False, "denied": True, "proposal_id": proposal.proposal_id,
                    "reason": decision.reason,
                    "guidance": "A project rule forbids this operation. Tell the person; do not try another route to it."}
        if decision.outcome == permissions.Outcome.ASK or self.read_only_runner is None or project_root is None:
            reason = decision.reason if decision.outcome == permissions.Outcome.ASK else "no runner is attached"
            if not decision.floor and not budget.allowed:
                # The read-only policy names what made it wait (a data change,
                # the session's test budget), which is the more useful reason.
                reason = budget.reason
            if self.execution_policy != "auto_read_only" and decision.outcome == permissions.Outcome.ASK and not decision.floor:
                reason = "Review before execution was requested for this turn."
            return {"requires_confirmation": True, "proposal": proposal.to_dict(), "confirmation_reason": reason,
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
        if plan is not None and actor == "approved_plan":
            from . import plans as plan_module

            expected_plan = plan
            def mark_current(current):
                if current != expected_plan:
                    raise plan_module.PlanError("plan changed during execution")
                return plan_module.mark_executed(current, operation_ids, record.status)
            try:
                plan = self.plan_store.update(session_id, mark_current)
            except plan_module.PlanError:
                # The operation already happened. Preserve its result and the
                # user's newer plan; do not replay or replace either of them.
                plan_update_conflict = True
        tests_run = prior + (budget.inferential_steps if record.status == "completed" else 0)
        return {
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

