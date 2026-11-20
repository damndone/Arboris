"""The Agent's analysis plan: a typed, versioned, approvable object.

In Ask every step a plan is shown and needs no approval. In Auto within plan
the person approves it once; approval fixes the question and the judgement
criteria (the ledger's ``criteria_fixed``), and the orchestrator then runs, in
order and without a card, the steps whose operations and permission classes
the approved plan covers. Steps added after results were seen are marked so
the report can call them exploratory.

Design: ``docs/superpowers/specs/2026-10-18-v1.9.1-agent-autonomy-design.md`` §4.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..jsonl_store import _exclusive_jsonl_lock, jsonl_lines
from .business_identity import identity_value
from .permissions import PermissionClass, permission_class, strictest

STEP_STATUSES = ("pending", "running", "awaiting", "done", "skipped", "failed")
PLAN_STATUSES = ("draft", "approved", "needs_approval", "completed", "abandoned")
#: Classes a plan may authorise; leaving the Workbench and high risk always ask.
PLANNABLE = frozenset({PermissionClass.ANALYZE, PermissionClass.DERIVE, PermissionClass.MODIFY})
MAX_STEPS = 40


class PlanError(ValueError):
    """A plan that cannot be accepted, with a message the Agent can act on."""


@dataclass(frozen=True)
class PlanProposalRef:
    proposal_id: str
    revision: int
    fingerprint: str

    @classmethod
    def from_dict(cls, value: Any) -> "PlanProposalRef":
        if (not isinstance(value, dict) or set(value) != {"proposal_id", "revision", "fingerprint"}
                or not isinstance(value["proposal_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value["proposal_id"])
                or type(value["revision"]) is not int or value["revision"] < 1
                or not isinstance(value["fingerprint"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"])):
            raise PlanError("proposal_ref must contain an exact proposal_id, revision and fingerprint")
        return cls(**value)

    @classmethod
    def of(cls, proposal) -> "PlanProposalRef":
        return cls(proposal.proposal_id, proposal.revision, proposal.fingerprint)

    def to_dict(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id, "revision": self.revision, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    title: str
    operation_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    status: str = "pending"
    added_after_results: bool = False
    completed_operation_ids: tuple[str, ...] = ()  # Server execution receipts only.
    proposal_ref: PlanProposalRef | None = None

    @property
    def permission_class(self) -> PermissionClass:
        return strictest(permission_class(op) for op in self.operation_ids) if self.operation_ids else PermissionClass.READ

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "title": self.title, "operation_ids": list(self.operation_ids),
                "depends_on": list(self.depends_on), "expected_outputs": list(self.expected_outputs),
                "status": self.status, "added_after_results": self.added_after_results,
                "permission_class": self.permission_class.value,
                **({"proposal_ref": self.proposal_ref.to_dict()} if self.proposal_ref is not None else {}),
                **({"completed_operation_ids": list(self.completed_operation_ids)} if self.completed_operation_ids else {})}


@dataclass(frozen=True)
class Plan:
    plan_id: str
    version: int
    status: str
    question: str
    criteria: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    allowed_classes: tuple[str, ...]
    budget: dict[str, int] = field(default_factory=dict)
    approved_version: int | None = None
    approved_at: str | None = None
    updated_at: str = ""
    completion: dict[str, Any] | None = None
    completion_evidence: dict[str, Any] | None = None
    task_requirements: dict[str, Any] | None = None  # Server-owned; absent from Agent tool inputs.

    def to_dict(self) -> dict[str, Any]:
        value = {"plan_id": self.plan_id, "version": self.version, "status": self.status, "question": self.question,
                "criteria": list(self.criteria), "steps": [step.to_dict() for step in self.steps],
                "allowed_classes": list(self.allowed_classes), "budget": dict(self.budget),
                "approved_version": self.approved_version, "approved_at": self.approved_at,
                "updated_at": self.updated_at}
        if self.completion is not None:
            value["completion"] = self.completion
        if self.completion_evidence is not None:
            value["completion_evidence"] = self.completion_evidence
        if self.task_requirements is not None:
            value["task_requirements"] = self.task_requirements
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Plan":
        return cls(
            plan_id=value["plan_id"], version=int(value["version"]), status=value["status"],
            question=value["question"], criteria=tuple(value.get("criteria") or ()),
            steps=tuple(PlanStep(step_id=s["step_id"], title=s["title"], operation_ids=tuple(s["operation_ids"]),
                                 depends_on=tuple(s.get("depends_on") or ()),
                                 expected_outputs=tuple(s.get("expected_outputs") or ()),
                                 status=s.get("status", "pending"),
                                 added_after_results=bool(s.get("added_after_results")),
                                 completed_operation_ids=tuple(s.get("completed_operation_ids") or ()),
                                 proposal_ref=(PlanProposalRef.from_dict(s["proposal_ref"])
                                               if s.get("proposal_ref") is not None else None))
                        for s in value.get("steps") or ()),
            allowed_classes=tuple(value.get("allowed_classes") or ()), budget=dict(value.get("budget") or {}),
            approved_version=value.get("approved_version"), approved_at=value.get("approved_at"),
            updated_at=value.get("updated_at", ""),
            completion=value.get("completion"), completion_evidence=value.get("completion_evidence"),
            task_requirements=value.get("task_requirements"),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def parse_steps(raw: Any, known_operations: set[str], *, previous_steps: tuple[PlanStep, ...] = ()) -> tuple[PlanStep, ...]:
    if not isinstance(raw, list) or not raw:
        raise PlanError("steps must be a non-empty list")
    if len(raw) > MAX_STEPS:
        raise PlanError(f"a plan has at most {MAX_STEPS} steps")
    previous_refs = {step.step_id: step.proposal_ref for step in previous_steps}
    steps, seen = [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError(f"step {index + 1} must be an object")
        if "completed_operation_ids" in item:
            raise PlanError("completed_operation_ids is server-owned execution evidence")
        step_id = str(item.get("step_id") or "").strip()
        if not step_id or step_id in seen:
            raise PlanError(f"step {index + 1}: step_id is missing or repeated")
        seen.add(step_id)
        operations = tuple(str(op) for op in item.get("operation_ids") or ())
        unknown = [op for op in operations if op not in known_operations]
        if unknown:
            raise PlanError(f"step {step_id}: unknown operation ids {unknown}; use workflow step ids from "
                            "inspect_operation_contract (operation.multi_step) or a registered operation")
        status = str(item.get("status") or "pending")
        if status not in STEP_STATUSES:
            raise PlanError(f"step {step_id}: status must be one of {STEP_STATUSES}")
        if "proposal_ref" in item:
            ref = None if item["proposal_ref"] is None else PlanProposalRef.from_dict(item["proposal_ref"])
        else:
            ref = previous_refs.get(step_id)
        steps.append(PlanStep(step_id=step_id, title=str(item.get("title") or step_id)[:200], operation_ids=operations,
                              depends_on=tuple(str(d) for d in item.get("depends_on") or ()),
                              expected_outputs=tuple(str(o)[:200] for o in item.get("expected_outputs") or ()),
                              status=status, proposal_ref=ref))
    ids = {step.step_id for step in steps}
    proposal_ids = [step.proposal_ref.proposal_id for step in steps if step.proposal_ref is not None]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise PlanError("an exact proposal may be bound to only one plan step")
    for step in steps:
        missing = [d for d in step.depends_on if d not in ids]
        if missing:
            raise PlanError(f"step {step.step_id} depends on unknown steps {missing}")
    _require_acyclic(steps)
    return tuple(steps)


def _require_acyclic(steps: tuple[PlanStep, ...] | list[PlanStep]) -> None:
    graph = {step.step_id: set(step.depends_on) for step in steps}
    done: set[str] = set()
    while graph:
        ready = [node for node, deps in graph.items() if deps <= done]
        if not ready:
            raise PlanError(f"steps form a cycle: {sorted(graph)}")
        for node in ready:
            done.add(node)
            graph.pop(node)


def merge(previous: Plan | None, *, question: str, criteria: list[str], steps: tuple[PlanStep, ...],
          budget: dict[str, int] | None, allowed_classes: list[str] | None,
          completion: dict[str, Any] | None = None, completion_evidence: dict[str, Any] | None = None,
          human_revision: bool = False) -> Plan:
    """The next version: new steps after approval are exploratory; widening the plan needs approval again."""

    completion_changed = False
    if previous is not None and previous.completion is not None:
        if completion is not None and completion != previous.completion:
            from .plan_criteria import definition_addition
            if not definition_addition(previous.completion, completion):
                raise PlanError("completion source and existing requirements cannot be changed by an Agent plan revision; request a human revision")
            completion_changed = True
        completion = completion if completion is not None else previous.completion
        if completion_evidence is None:
            completion_evidence = previous.completion_evidence
    from .plan_criteria import validate_definitions
    try:
        validate_definitions(completion, criteria, steps)
    except ValueError as exc:
        raise PlanError(str(exc)) from exc
    old_steps = {step.step_id: step for step in previous.steps} if previous else {}
    incoming_ids = {step.step_id for step in steps}
    if not human_revision:
        removed = [step.step_id for step in old_steps.values() if step.operation_ids
                   and (step.completed_operation_ids or step.status in {"done", "running"})
                   and step.step_id not in incoming_ids]
        if removed:
            raise PlanError(f"steps {removed} have execution history; only a human plan revision can remove them")
    preserved = []
    for step in steps:
        old = old_steps.get(step.step_id)
        if (old and old.operation_ids and (old.completed_operation_ids or old.status in {"done", "running"})
                and step.operation_ids != old.operation_ids and not human_revision):
            raise PlanError(f"step {step.step_id} has execution history; only a human plan revision can change its declared operation_ids")
        if (old and (old.completed_operation_ids or old.status in {"done", "running", "failed"})
                and step.proposal_ref != old.proposal_ref):
            raise PlanError(f"step {step.step_id} has execution history; its proposal reference cannot be replaced")
        coverage = old.completed_operation_ids if old else step.completed_operation_ids
        status = step.status
        if old and old.status in {"done", "failed"}:
            # Preserve historical terminal records; missing old receipts remain
            # unverified, never an implicit request to rerun the old operation.
            status = old.status
        elif step.operation_ids and status == "done" and _remaining_operations(step, coverage):
            # Receipts decide a step's status; the claim is not applied. Refusing the whole
            # update also threw away its completion_evidence, the one choice the gate needed.
            from .tools import tool_note
            tool_note(f"step {step.step_id} stays {old.status if old else 'pending'}: no successful execution "
                      "receipt covers it. Bind existing verified results in completion_evidence; "
                      "do not rerun completed operations to create plan history.")
            status = old.status if old else "pending"
        elif human_revision and step.operation_ids and coverage and not _remaining_operations(step, coverage):
            status = "done"
        preserved.append(replace(step, status=status, completed_operation_ids=coverage))
    steps = tuple(preserved)
    classes = sorted({step.permission_class.value for step in steps if step.permission_class in PLANNABLE})
    if previous is not None and allowed_classes is None:
        classes = sorted(set(previous.allowed_classes) | {
            step.permission_class.value for step in steps if step.permission_class in PLANNABLE
            and (step.step_id not in old_steps or step.operation_ids != old_steps[step.step_id].operation_ids)})
    allowed = sorted(set(classes if allowed_classes is None else allowed_classes) & {c.value for c in PLANNABLE})
    effective_budget = {**(previous.budget if previous else {}), **(budget or {})}
    identity_inputs = {"previous": previous.to_dict() if previous else None,
                       "question": question, "criteria": list(criteria),
                       "steps": [step.to_dict() for step in steps], "budget": budget,
                       "allowed_classes": allowed_classes}
    if completion is not None:
        identity_inputs["completion"] = completion
    if completion_evidence is not None:
        identity_inputs["completion_evidence"] = completion_evidence
    if previous is None or previous.approved_version is None:
        # Before any approval a revision is simply a new draft.
        return Plan(plan_id=previous.plan_id if previous else identity_value(
                        owner="agent.plan.merge", slot="plan_id", inputs=identity_inputs,
                        create=lambda: f"plan_{uuid4().hex[:12]}"),
                    version=(previous.version + 1) if previous else 1, status="draft", question=question,
                    criteria=tuple(criteria), steps=steps, allowed_classes=tuple(allowed),
                    budget=effective_budget, completion=completion, completion_evidence=completion_evidence,
                    task_requirements=previous.task_requirements if previous else None, updated_at=identity_value(
                        owner="agent.plan.merge", slot="updated_at", inputs=identity_inputs, create=_now))
    old_ids = {step.step_id for step in previous.steps}
    marked = tuple(replace(step, added_after_results=step.step_id not in old_ids or
                           next((s.added_after_results for s in previous.steps if s.step_id == step.step_id), False))
                   for step in steps)
    dependency_changed = any(step.step_id in old_steps and set(step.depends_on) != set(old_steps[step.step_id].depends_on)
                             for step in steps)
    outputs_changed = {(s.step_id, s.expected_outputs) for s in steps if s.expected_outputs} != {
        (s.step_id, s.expected_outputs) for s in previous.steps if s.expected_outputs}
    binding_changed = {s.step_id: s.proposal_ref for s in steps if s.proposal_ref is not None} != {
        s.step_id: s.proposal_ref for s in previous.steps if s.proposal_ref is not None}
    widened = completion_changed or outputs_changed or dependency_changed or binding_changed or (set(allowed) - set(previous.allowed_classes)) or question.strip() != previous.question.strip() or \
        tuple(criteria) != previous.criteria or _bigger(budget, previous.budget)
    status = "needs_approval" if previous.status in {"approved", "needs_approval", "completed"} and widened else previous.status
    return replace(previous, version=previous.version + 1, status=status, completion=completion,
                   completion_evidence=completion_evidence, question=question, criteria=tuple(criteria),
                   steps=marked, allowed_classes=tuple(allowed) if allowed_classes is not None else tuple(sorted(set(allowed) | set(previous.allowed_classes)))
                   if status == "needs_approval" else previous.allowed_classes,
                   budget=effective_budget, updated_at=identity_value(
                       owner="agent.plan.merge", slot="updated_at", inputs=identity_inputs, create=_now))


def _bigger(new: dict[str, int] | None, old: dict[str, int]) -> bool:
    return any((key == "steps" and value == 0 and old.get(key, 0) > 0)
               or int(value) > int(old.get(key, value)) for key, value in (new or {}).items())


def approve(plan: Plan) -> Plan:
    if plan.status not in {"draft", "needs_approval"}:
        raise PlanError(f"a {plan.status} plan cannot be approved")
    return replace(plan, status="approved", approved_version=plan.version,
                   approved_at=identity_value(owner="agent.plan.approve", slot="approved_at",
                                              inputs=plan.to_dict(), create=_now),
                   updated_at=identity_value(owner="agent.plan.approve", slot="updated_at",
                                             inputs=plan.to_dict(), create=_now))


def _remaining_operations(step: PlanStep, covered: tuple[str, ...] | None = None) -> Counter:
    needed = Counter(step.operation_ids)
    for op in needed:
        if permission_class(op) == PermissionClass.ANALYZE:
            needed[op] = 1  # One read-only batch may repeat the same analysis kind.
    return needed - Counter(step.completed_operation_ids if covered is None else covered)


def _verified_done(step: PlanStep) -> bool:
    return step.status == "done" and not _remaining_operations(step)


def _ready_step_index(plan: Plan, operation_ids: list[str], proposal_ref: PlanProposalRef | None = None,
                      *, bound_preflight_ready: bool = True) -> int | None:
    """Select one covering open step, in plan order, after every dependency succeeded."""

    requested = Counter(operation_ids)
    if not requested:
        return None
    done = {step.step_id for step in plan.steps if _verified_done(step)}
    open_statuses = {"pending", "running", "awaiting"}
    binding_reserved = any(step.proposal_ref is not None and step.status in open_statuses
                           and requested.keys() & set(step.operation_ids) for step in plan.steps)
    mutable_requests = {op: count for op, count in requested.items()
                        if permission_class(op) != PermissionClass.ANALYZE}
    for index, step in enumerate(plan.steps):
        declared = set(step.operation_ids)
        if (step.status not in open_statuses or not requested.keys() <= declared
                or not all(dependency in done for dependency in step.depends_on)):
            continue
        if step.proposal_ref is None:
            remaining = _remaining_operations(step)
            matches = not binding_reserved and all(count <= remaining[op] for op, count in mutable_requests.items())
        else:
            matches = bound_preflight_ready and step.proposal_ref == proposal_ref and requested.keys() == declared
        if matches:
            return index
    return None


def scope_for(plan: Plan | None, operation_ids: list[str], *, executed_steps: int = 0,
              proposal_ref: PlanProposalRef | None = None, bound_preflight_ready: bool = False) -> dict[str, Any]:
    """What the permission engine needs to know about a request and the approved plan."""

    if plan is None:
        return {"in_plan": False, "allowed_classes": []}
    gaps = [{"step_id": step.step_id,
             "missing_operation_ids": sorted(_remaining_operations(step).elements())}
            for step in plan.steps if step.status == "done" and not _verified_done(step)]
    in_plan = plan.status == "approved" and _ready_step_index(plan, operation_ids, proposal_ref,
                                                              bound_preflight_ready=bound_preflight_ready) is not None
    max_steps = int(plan.budget.get("steps") or 0)
    return {"in_plan": in_plan, "allowed_classes": list(plan.allowed_classes),
            "within_budget": not max_steps or executed_steps < max_steps,
            "plan_id": plan.plan_id, "plan_version": plan.version,
            **({"plan_recovery": {"code": "PLAN_EXECUTION_COVERAGE_UNVERIFIED", "steps": gaps,
                "guidance": "Old done labels lack successful execution coverage. Inspect/reconcile the original bound operation receipts, or ask the person to revise the plan for a controlled rerun. No operation was automatically rerun."}} if gaps else {})}


def _with_receipt(step: PlanStep, operation_ids: list[str], status: str) -> PlanStep:
    """Both confirmation and Auto paths accumulate only successful receipt types."""
    if status == "failed":
        return replace(step, status="failed")
    if status != "completed":
        return step
    remaining = _remaining_operations(step)
    received = remaining & Counter(operation_ids)
    covered = tuple(sorted((*step.completed_operation_ids, *received.elements())))
    return replace(step, completed_operation_ids=covered,
                   status="done" if received == remaining else step.status)


def _finished(steps) -> bool:
    return all(step.status == "skipped" or _verified_done(step) for step in steps)


def mark_executed(plan: Plan, operation_ids: list[str], status: str, *, proposal_ref: PlanProposalRef | None = None) -> Plan:
    """Mark the same ready covering step that can supply plan authority."""

    steps = list(plan.steps)
    index = _ready_step_index(plan, operation_ids, proposal_ref)
    if index is not None:
        steps[index] = _with_receipt(steps[index], operation_ids, status)
    finished = _finished(steps)
    return replace(plan, steps=tuple(steps), status="completed" if finished and plan.status == "approved" else plan.status,
                   updated_at=identity_value(owner="agent.plan.mark_executed", slot="updated_at",
                                             inputs={"previous": plan.to_dict(), "operation_ids": operation_ids,
                                                     "status": status}, create=_now))


def mark_covered(plan: Plan, operation_ids: list[str], status: str, *, proposal_ref: PlanProposalRef | None = None) -> Plan:
    """Apply confirmed receipt coverage; partial steps keep their remaining work."""

    selected = _ready_step_index(plan, operation_ids, proposal_ref)
    steps = list(plan.steps)
    if selected is not None:
        steps[selected] = _with_receipt(steps[selected], operation_ids, status)
    else:
        # One workflow can finish several plan steps. Earlier steps it finishes satisfy
        # later steps' dependencies, and each run operation covers one step only
        # (IV Auto, 2026-10-31: fit, AR and weak-IV ran together, only the fit was marked,
        # so the Agent's truthful "done" was refused along with its primary choice).
        unused = Counter(operation_ids)
        progressed = True
        while progressed:
            progressed = False
            done = {step.step_id for step in steps if _verified_done(step)}
            for index, step in enumerate(steps):
                needed = _remaining_operations(step)
                if (step.proposal_ref is None and step.status in {"pending", "running", "awaiting"} and needed
                        and needed <= unused
                        and all(item in done for item in step.depends_on)):
                    steps[index] = _with_receipt(step, list(needed.elements()), status)
                    unused -= needed
                    progressed = status == "completed"
                    if progressed:
                        break
    if steps == list(plan.steps):
        return plan
    return replace(plan, steps=tuple(steps), status="completed" if _finished(steps) and plan.status == "approved" else plan.status,
                   updated_at=identity_value(owner="agent.plan.mark_covered", slot="updated_at",
                                             inputs={"previous": plan.to_dict(), "operation_ids": operation_ids,
                                                     "status": status}, create=_now))


class PlanStore:
    """One append-only JSONL history per session: every version is kept."""

    _lock = threading.Lock()

    def __init__(self, workbench_root: Path) -> None:
        self.root = Path(workbench_root) / "plans"

    def _path(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise PlanError("invalid plan session identifier")
        return self.root / f"{session_id}.jsonl"

    @staticmethod
    def _last_row(contents: str | bytes) -> dict[str, Any] | None:
        return next((json.loads(line) for line in reversed(jsonl_lines(contents)) if line.strip()), None)

    def _current_row(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        return self._last_row(path.read_text(encoding="utf-8"))

    def current(self, session_id: str) -> Plan | None:
        row = self._current_row(session_id)
        return Plan.from_dict(row) if row is not None else None

    def history(self, session_id: str) -> list[Plan]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        return [Plan.from_dict(json.loads(line)) for line in jsonl_lines(path.read_text(encoding="utf-8")) if line.strip()]

    @contextmanager
    def locked(self, session_id: str):
        with self._lock, _exclusive_jsonl_lock(self._path(session_id)):
            yield

    def _append(self, session_id: str, plan: Plan, *, operation_record_id: str | None = None) -> None:
        """Caller owns the plan transaction lock; readers see an old or new file."""
        path = self._path(session_id)
        existing = path.read_bytes() if path.exists() else b""
        if existing and not existing.endswith(b"\n"):
            raise PlanError("incomplete plan history needs reconciliation")
        previous = self._last_row(existing)
        record_ids = list(previous.get("covered_operation_records", ())) if previous and previous["plan_id"] == plan.plan_id else []
        if operation_record_id is not None:
            record_ids.append(operation_record_id)
        row = plan.to_dict()
        if record_ids:
            row["covered_operation_records"] = record_ids
        line = (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, session_id: str, plan: Plan) -> Plan:
        """Append a caller-owned snapshot; compound product changes use update."""
        with self.locked(session_id):
            self._append(session_id, plan)
        return plan

    def update(self, session_id: str, change: Callable[[Plan | None], Plan], *, operation_record_id: str | None = None) -> Plan:
        """Serialize read/validate/write across instances and worker processes.

        A failed callback cannot grant plan authority. Callbacks may first
        write idempotent intent records; those records alone grant nothing.
        """
        with self.locked(session_id):
            row = self._current_row(session_id)
            previous = Plan.from_dict(row) if row is not None else None
            if row and operation_record_id is not None and operation_record_id in row.get("covered_operation_records", ()):
                return previous
            updated = change(previous)
            if not isinstance(updated, Plan):
                raise PlanError("plan update must return a Plan")
            if updated != previous:
                if operation_record_id is None:
                    self._append(session_id, updated)
                else:
                    self._append(session_id, updated, operation_record_id=operation_record_id)
            return updated
