"""Human plan control; plan authority and research intent remain distinct."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from .. import analysis_ledger
from . import plans


class PlanControlError(ValueError):
    def __init__(self, code, message, *, status=409, details=None):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details or {}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class PlanControl:
    def __init__(self, root, repository, session_id):
        self.root, self.repository, self.session_id = root, repository, session_id
        self.store = plans.PlanStore(repository.root)

    def view(self):
        plan = self.store.current(self.session_id)
        return {"plan": plan.to_dict() if plan else None,
                "versions": [{"version": item.version, "status": item.status, "updated_at": item.updated_at}
                             for item in self.store.history(self.session_id)]}

    def _require_version(self, plan, version):
        if plan is None:
            raise PlanControlError("AGENT_PLAN_NOT_FOUND", "This conversation has no plan.", status=404)
        if plan.version != version:
            raise PlanControlError("AGENT_PLAN_CHANGED", "The plan changed since it was shown; review the new version.",
                                   details={"current_version": plan.version})

    def approve(self, version):
        from .analysis_history import require_active_session
        require_active_session(self.repository, self.session_id)
        def apply(plan):
            self._require_version(plan, version)
            if plan.status == "approved" and plan.approved_version == version:
                if any(entry.get("event_type") == "criteria_fixed" and entry.get("session_id") == self.session_id
                       and entry.get("plan_id") == plan.plan_id and entry.get("plan_version") == plan.version
                       for entry in analysis_ledger.read(self.root)):
                    return plan
            if plan.status not in {"draft", "needs_approval"}:
                raise plans.PlanError(f"a {plan.status} plan cannot be approved")
            analysis_ledger.record_plan_event_once(self.root, session_id=self.session_id,
                event_type="criteria_fixed", plan_snapshot=plan.to_dict())
            return plans.approve(plan)
        try:
            approved = self.store.update(self.session_id, apply)
        except plans.PlanError as exc:
            raise PlanControlError("AGENT_PLAN_NOT_APPROVABLE", str(exc)) from exc
        self.repository.append_once(self.session_id, "custom_message", {
            "message_type": "agent_plan_approved", "audience": "model", "name": "workbench_plan",
            "content": (f"Workbench: the person approved plan {approved.plan_id} version {approved.version}. "
                        "Its question and criteria are now fixed; planned steps of the allowed kinds run without a card."),
        }, key=f"{approved.plan_id}:{approved.version}", stage="plan_approved")
        from .extension_runtime import dispatch_hooks
        dispatch_hooks(self.root, "plan_approved", {"session_id": self.session_id,
            "plan_id": approved.plan_id, "plan_version": approved.version},
            key=f"{approved.plan_id}:{approved.version}")
        return {"plan": approved.to_dict()}

    def revise(self, version, changes):
        from .analysis_history import require_active_session
        require_active_session(self.repository, self.session_id)
        changes = json.loads(json.dumps(changes, ensure_ascii=False, allow_nan=False))
        notice = ("Workbench: the person revised the analysis plan to version " + str(version + 1)
                  + ". Apply these exact changes to the previous plan for subsequent steps: "
                  + json.dumps(changes, ensure_ascii=False, sort_keys=True))
        if len(notice) > 12_000:
            raise PlanControlError("AGENT_PLAN_EDIT_TOO_LARGE",
                                   "This edit is too large for one plan notice; submit smaller edits.", status=422)

        def apply(previous):
            if previous is None:
                self._require_version(previous, version)
            key = f"{previous.plan_id}:{version + 1}"
            intents = [entry for entry in self.repository.get_branch(self.session_id)
                       if entry.idempotency and entry.idempotency["key"] == key
                       and entry.idempotency["stage"] == "plan_edit_intent"]
            if intents:
                if len(intents) != 1 or intents[0].payload["changes"] != changes:
                    raise PlanControlError("AGENT_PLAN_CHANGED", "This plan revision has a different recorded edit.")
                intent = intents[0].payload
                target = plans.Plan.from_dict(intent["snapshot"])
                if previous == target:
                    return previous  # Repair only the missing notice.
                self._require_version(previous, version)
                if _digest(previous.to_dict()) != intent["before_sha256"]:
                    raise PlanControlError("AGENT_PLAN_CHANGED", "The recorded edit no longer matches this plan.")
                return target

            self._require_version(previous, version)
            if previous.status in {"completed", "abandoned"}:
                raise PlanControlError("AGENT_PLAN_NOT_EDITABLE", f"A {previous.status} plan cannot be revised in place.")
            question = changes.get("question", previous.question).strip()
            if not question:
                raise plans.PlanError("question is required")
            steps = previous.steps
            if "steps" in changes:
                from .operations import OperationRegistry
                from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
                known = set(WORKFLOW_STEP_SPEC_CONTRACTS) | set(OperationRegistry().natural_language_operation_ids(
                    scope_requirements=("chain", "active_head")))
                requested = plans.parse_steps(changes["steps"], known)
                old = {step.step_id: step for step in previous.steps}
                incoming = {step.step_id: step for step in requested}
                for step_id, step in old.items():
                    if step.status in {"done", "running"} and (step_id not in incoming
                            or incoming[step_id].operation_ids != step.operation_ids
                            or incoming[step_id].depends_on != step.depends_on):
                        raise plans.PlanError("A running or completed step cannot be removed or assigned different operations.")
                steps = tuple(replace(step, status=old[step.step_id].status,
                                      added_after_results=old[step.step_id].added_after_results)
                              if step.step_id in old else step for step in requested)
            basis = previous
            contract_changed = "completion" in changes and changes["completion"] != previous.completion
            if contract_changed:
                from .completion import source_receipt
                contract = changes["completion"]
                if source_receipt(self.root, contract["source"]) != contract["source"]:
                    raise plans.PlanError("completion source is unavailable or changed")
                basis = replace(previous, completion=contract, completion_evidence=None)
            plan = plans.merge(basis, question=question, criteria=changes.get("criteria", list(previous.criteria)),
                               steps=steps, budget=previous.budget, allowed_classes=list(previous.allowed_classes))
            # The editor sends the whole form, including an unchanged question.
            # Editing criteria alone cannot authorize narrowing the original task.
            if question != previous.question:
                from .task_requirements import human_revision
                plan = replace(plan, task_requirements=human_revision(self.repository, self.session_id, question,
                    plan_id=plan.plan_id, version=plan.version, changes=changes))
            def execution_scope(items):
                return [(step.step_id, step.operation_ids, step.depends_on, step.expected_outputs) for step in items]
            if previous.approved_version is not None and (contract_changed or execution_scope(steps) != execution_scope(previous.steps)):
                plan = replace(plan, status="needs_approval")
            if previous.approved_version is not None and plan.question != previous.question:
                event = analysis_ledger.record_plan_event_once(self.root, session_id=self.session_id,
                    event_type="question_change", plan_snapshot=plan.to_dict(), actor="user")
                plan = plans.Plan.from_dict(event["plan_snapshot"])
            self.repository.append_once(self.session_id, "plan_edit_intent", {
                "requested_version": version, "changes": changes, "before_sha256": _digest(previous.to_dict()),
                "snapshot": plan.to_dict(),
            }, key=key, stage="plan_edit_intent")
            return plan
        try:
            plan = self.store.update(self.session_id, apply)
        except plans.PlanError as exc:
            raise PlanControlError("AGENT_PLAN_NOT_EDITABLE", str(exc)) from exc
        self.repository.append_once(self.session_id, "custom_message", {
            "message_type": "agent_plan_revised", "audience": "model", "name": "workbench_plan",
            "content": notice,
        }, key=f"{plan.plan_id}:{plan.version}", stage="plan_revised")
        return {"plan": plan.to_dict()}
