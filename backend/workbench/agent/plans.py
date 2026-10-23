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
import tempfile
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..jsonl_store import _exclusive_jsonl_lock
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
class PlanStep:
    step_id: str
    title: str
    operation_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    status: str = "pending"
    added_after_results: bool = False

    @property
    def permission_class(self) -> PermissionClass:
        return strictest(permission_class(op) for op in self.operation_ids) if self.operation_ids else PermissionClass.READ

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "title": self.title, "operation_ids": list(self.operation_ids),
                "depends_on": list(self.depends_on), "expected_outputs": list(self.expected_outputs),
                "status": self.status, "added_after_results": self.added_after_results,
                "permission_class": self.permission_class.value}


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
                                 added_after_results=bool(s.get("added_after_results")))
                        for s in value.get("steps") or ()),
            allowed_classes=tuple(value.get("allowed_classes") or ()), budget=dict(value.get("budget") or {}),
            approved_version=value.get("approved_version"), approved_at=value.get("approved_at"),
            updated_at=value.get("updated_at", ""),
            completion=value.get("completion"), completion_evidence=value.get("completion_evidence"),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def parse_steps(raw: Any, known_operations: set[str]) -> tuple[PlanStep, ...]:
    if not isinstance(raw, list) or not raw:
        raise PlanError("steps must be a non-empty list")
    if len(raw) > MAX_STEPS:
        raise PlanError(f"a plan has at most {MAX_STEPS} steps")
    steps, seen = [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError(f"step {index + 1} must be an object")
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
        steps.append(PlanStep(step_id=step_id, title=str(item.get("title") or step_id)[:200], operation_ids=operations,
                              depends_on=tuple(str(d) for d in item.get("depends_on") or ()),
                              expected_outputs=tuple(str(o)[:200] for o in item.get("expected_outputs") or ()),
                              status=status))
    ids = {step.step_id for step in steps}
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
          completion: dict[str, Any] | None = None, completion_evidence: dict[str, Any] | None = None) -> Plan:
    """The next version: new steps after approval are exploratory; widening the plan needs approval again."""

    if previous is not None and previous.completion is not None:
        if completion is not None and completion != previous.completion:
            raise PlanError("completion requirements and source cannot be changed by an Agent plan revision")
        completion = previous.completion
        if completion_evidence is None:
            completion_evidence = previous.completion_evidence
    classes = sorted({step.permission_class.value for step in steps if step.permission_class in PLANNABLE})
    allowed = sorted(set(allowed_classes or classes) & {c.value for c in PLANNABLE})
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
                    budget=dict(budget or {}), completion=completion, completion_evidence=completion_evidence, updated_at=identity_value(
                        owner="agent.plan.merge", slot="updated_at", inputs=identity_inputs, create=_now))
    old_ids = {step.step_id for step in previous.steps}
    marked = tuple(replace(step, added_after_results=step.step_id not in old_ids or
                           next((s.added_after_results for s in previous.steps if s.step_id == step.step_id), False))
                   for step in steps)
    widened = (set(allowed) - set(previous.allowed_classes)) or question.strip() != previous.question.strip() or \
        tuple(criteria) != previous.criteria or _bigger(budget, previous.budget)
    status = "needs_approval" if previous.status in {"approved", "needs_approval"} and widened else previous.status
    return replace(previous, version=previous.version + 1, status=status, completion=completion,
                   completion_evidence=completion_evidence, question=question, criteria=tuple(criteria),
                   steps=marked, allowed_classes=tuple(sorted(set(allowed) | set(previous.allowed_classes)))
                   if status == "needs_approval" else previous.allowed_classes,
                   budget=dict(budget or previous.budget), updated_at=identity_value(
                       owner="agent.plan.merge", slot="updated_at", inputs=identity_inputs, create=_now))


def _bigger(new: dict[str, int] | None, old: dict[str, int]) -> bool:
    return any(int(value) > int(old.get(key, value)) for key, value in (new or {}).items())


def approve(plan: Plan) -> Plan:
    if plan.status not in {"draft", "needs_approval"}:
        raise PlanError(f"a {plan.status} plan cannot be approved")
    return replace(plan, status="approved", approved_version=plan.version,
                   approved_at=identity_value(owner="agent.plan.approve", slot="approved_at",
                                              inputs=plan.to_dict(), create=_now),
                   updated_at=identity_value(owner="agent.plan.approve", slot="updated_at",
                                             inputs=plan.to_dict(), create=_now))


def _ready_step_index(plan: Plan, operation_ids: list[str]) -> int | None:
    """Select one covering open step, in plan order, after every dependency succeeded."""

    requested = set(operation_ids)
    if not requested:
        return None
    done = {step.step_id for step in plan.steps if step.status == "done"}
    for index, step in enumerate(plan.steps):
        if (step.status in {"pending", "running", "awaiting"}
                and all(dependency in done for dependency in step.depends_on)
                and requested <= set(step.operation_ids)):
            return index
    return None


def scope_for(plan: Plan | None, operation_ids: list[str], *, executed_steps: int = 0) -> dict[str, Any]:
    """What the permission engine needs to know about a request and the approved plan."""

    if plan is None or plan.status != "approved":
        return {"in_plan": False, "allowed_classes": []}
    in_plan = _ready_step_index(plan, operation_ids) is not None
    max_steps = int(plan.budget.get("steps") or 0)
    return {"in_plan": in_plan, "allowed_classes": list(plan.allowed_classes),
            "within_budget": not max_steps or executed_steps < max_steps,
            "plan_id": plan.plan_id, "plan_version": plan.version}


def mark_executed(plan: Plan, operation_ids: list[str], status: str) -> Plan:
    """Mark the same ready covering step that can supply plan authority."""

    steps = list(plan.steps)
    index = _ready_step_index(plan, operation_ids)
    if index is not None:
        steps[index] = replace(steps[index], status="done" if status == "completed" else "failed")
    finished = all(step.status in {"done", "skipped"} for step in steps)
    return replace(plan, steps=tuple(steps), status="completed" if finished and plan.status == "approved" else plan.status,
                   updated_at=identity_value(owner="agent.plan.mark_executed", slot="updated_at",
                                             inputs={"previous": plan.to_dict(), "operation_ids": operation_ids,
                                                     "status": status}, create=_now))


def mark_covered(plan: Plan, operation_ids: list[str], status: str) -> Plan:
    """After a confirmed operation: mark the ready steps it fully covers, nothing more.

    A step is marked only when every operation it lists ran in this one, so a
    step that still has work keeps its status and the plan's authority over that
    work (unlike mark_executed, which serves the plan running its own step).
    """

    ran = set(operation_ids)
    done = {step.step_id for step in plan.steps if step.status == "done"}
    steps = [replace(step, status="done" if status == "completed" else "failed")
             if (step.status in {"pending", "running", "awaiting"} and step.operation_ids
                 and set(step.operation_ids) <= ran and all(item in done for item in step.depends_on))
             else step for step in plan.steps]
    if steps == list(plan.steps):
        return plan
    return replace(plan, steps=tuple(steps),
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

    def current(self, session_id: str) -> Plan | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return Plan.from_dict(json.loads(lines[-1])) if lines else None

    def history(self, session_id: str) -> list[Plan]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        return [Plan.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _append(self, session_id: str, plan: Plan) -> None:
        """Caller owns the plan transaction lock; readers see an old or new file."""
        path = self._path(session_id)
        existing = path.read_bytes() if path.exists() else b""
        if existing and not existing.endswith(b"\n"):
            raise PlanError("incomplete plan history needs reconciliation")
        line = (json.dumps(plan.to_dict(), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
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
        with self._lock, _exclusive_jsonl_lock(self._path(session_id)):
            self._append(session_id, plan)
        return plan

    def update(self, session_id: str, change: Callable[[Plan | None], Plan]) -> Plan:
        """Serialize read/validate/write across instances and worker processes.

        A failed callback cannot grant plan authority. Callbacks may first
        write idempotent intent records; those records alone grant nothing.
        """
        with self._lock, _exclusive_jsonl_lock(self._path(session_id)):
            previous = self.current(session_id)
            updated = change(previous)
            if not isinstance(updated, Plan):
                raise PlanError("plan update must return a Plan")
            if updated != previous:
                self._append(session_id, updated)
            return updated
