"""Who may run what without asking: the Agent's permission engine.

The person chooses an execution mode -- ``ask`` (every step) or ``auto``
(within an approved plan) -- and may add project rules and per-conversation
grants. ``decide`` turns that, plus the operation's declared permission class,
into allow / ask / deny. It reads declarations and settings only, never model
text: "read-only" is an impact classification, not permission to skip a review
the person asked for (v1.9.0 retrospective #30).

The safety floor holds in every mode and under every rule: leaving the
Workbench (export, egress, code, external tools), registered high-risk
operations and anything that changes source data always ask. Rules and grants
can tighten it, never loosen it. Precedence, as in Claude Code: deny rules,
then the floor, then ask rules, then allow rules and grants, then the mode's
default table.

Design: ``docs/superpowers/specs/2026-10-18-v1.9.1-agent-autonomy-design.md`` §3.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from ..analysis_ledger import step_category


class Mode(str, Enum):
    ASK = "ask"
    AUTO = "auto"


class PermissionClass(str, Enum):
    READ = "read"
    ANALYZE = "analyze"
    DERIVE = "derive"
    MODIFY = "modify"
    EXTERNAL = "external"
    HIGH = "high"


class Outcome(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


#: Ledger categories (``analysis_ledger.step_category``) by permission class.
_CATEGORY_CLASS = {
    "descriptive": PermissionClass.ANALYZE,
    "inferential": PermissionClass.ANALYZE,
    "model": PermissionClass.DERIVE,
    "data_change": PermissionClass.DERIVE,
    "report": PermissionClass.DERIVE,
    "metadata_change": PermissionClass.MODIFY,
    "export": PermissionClass.EXTERNAL,
    "deletion": PermissionClass.HIGH,
}
#: Operations whose impact their ledger category does not describe.
_OVERRIDES = {
    "code.execute": PermissionClass.EXTERNAL,
    "graph.fork": PermissionClass.DERIVE,
}
#: Classes a per-conversation "don't ask again" may cover.
GRANTABLE = frozenset({PermissionClass.ANALYZE, PermissionClass.DERIVE, PermissionClass.MODIFY})


def permission_class(operation_id: str, *, risk_level: str | None = None) -> PermissionClass:
    """The permission class of a workflow step or registered operation.

    Unknown operations fail closed to ``modify`` (asks in every mode) rather
    than to an allowing class.
    """
    if risk_level == "high":
        return PermissionClass.HIGH
    if operation_id in _OVERRIDES:
        return _OVERRIDES[operation_id]
    return _CATEGORY_CLASS.get(step_category(operation_id), PermissionClass.MODIFY)


def strictest(classes: Iterable[PermissionClass]) -> PermissionClass:
    """The class of a multi-step request: its most restrictive step."""
    order = list(PermissionClass)
    values = list(classes)
    return max(values, key=order.index) if values else PermissionClass.READ


@dataclass(frozen=True)
class Rule:
    """One project rule: a class, optionally narrowed to one operation id."""

    permission_class: PermissionClass
    operation_id: str | None = None

    def matches(self, request: "Request") -> bool:
        return self.permission_class == request.permission_class and (
            self.operation_id is None or self.operation_id == request.operation_id
        )


@dataclass(frozen=True)
class Rules:
    allow: tuple[Rule, ...] = ()
    ask: tuple[Rule, ...] = ()
    deny: tuple[Rule, ...] = ()


@dataclass(frozen=True)
class Request:
    operation_id: str
    permission_class: PermissionClass
    #: The step changes a source dataset (not a derived one on a branch).
    touches_source: bool = False
    #: Auto mode: the step belongs to the approved plan ...
    in_plan: bool = False
    #: ... whose allowed classes cover it ...
    class_allowed_by_plan: bool = False
    #: ... and the plan names this exact object (needed for ``modify``).
    named_in_plan: bool = False
    #: The plan's (Auto) or the conversation's (Ask) budget still covers it.
    within_budget: bool = True


@dataclass(frozen=True)
class Grants:
    """Per-conversation "don't ask again" answers."""

    entries: frozenset[Rule] = field(default_factory=frozenset)

    def covers(self, request: Request) -> bool:
        return request.permission_class in GRANTABLE and not request.touches_source and any(
            rule.matches(request) for rule in self.entries
        )


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str
    #: The safety floor decided it; nothing the person configured could change it.
    floor: bool = False
    #: Who allowed it, for the ledger: the mode's default ("default"), a project
    #: rule ("project_rule"), a conversation grant ("session_grant") or the
    #: approved plan ("approved_plan").
    authority: str = "default"


def on_floor(request: Request) -> bool:
    return request.permission_class in {PermissionClass.EXTERNAL, PermissionClass.HIGH} or request.touches_source


def decide(mode: Mode, request: Request, rules: Rules = Rules(), grants: Grants = Grants()) -> Decision:
    if any(rule.matches(request) for rule in rules.deny):
        return Decision(Outcome.DENY, "a project rule denies this operation")
    if on_floor(request):
        what = ("changes source data" if request.touches_source
                else "leaves the Workbench" if request.permission_class == PermissionClass.EXTERNAL
                else "is registered as high risk")
        return Decision(Outcome.ASK, f"this operation {what}, which always needs your approval", floor=True)
    if any(rule.matches(request) for rule in rules.ask):
        return Decision(Outcome.ASK, "a project rule asks before this operation")
    if any(rule.matches(request) for rule in rules.allow):
        return Decision(Outcome.ALLOW, "a project rule allows this operation", authority="project_rule")
    if grants.covers(request):
        return Decision(Outcome.ALLOW, "you allowed this kind of operation for this conversation",
                        authority="session_grant")
    return _default(mode, request)


def _default(mode: Mode, request: Request) -> Decision:
    cls = request.permission_class
    if cls == PermissionClass.READ:
        return Decision(Outcome.ALLOW, "reading results changes nothing")
    if mode == Mode.ASK:
        if cls == PermissionClass.ANALYZE:
            if request.within_budget:
                return Decision(Outcome.ALLOW, "read-only analysis changes no data or model")
            return Decision(Outcome.ASK, "this conversation's budget of inferential steps is spent")
        return Decision(Outcome.ASK, "every step that changes something is confirmed in Ask every step")
    # Auto within plan.
    if not request.in_plan:
        return Decision(Outcome.ASK, "this step is not in the approved plan")
    if not request.within_budget:
        return Decision(Outcome.ASK, "the approved plan's budget is spent")
    if cls in {PermissionClass.ANALYZE, PermissionClass.DERIVE}:
        if request.class_allowed_by_plan:
            return Decision(Outcome.ALLOW, "the approved plan covers this step", authority="approved_plan")
        return Decision(Outcome.ASK, "the approved plan does not allow this kind of step")
    if cls == PermissionClass.MODIFY and request.named_in_plan and request.class_allowed_by_plan:
        return Decision(Outcome.ALLOW, "the approved plan names this change", authority="approved_plan")
    return Decision(Outcome.ASK, "changes to existing objects are confirmed unless the plan names them")


__all__ = [
    "Decision", "GRANTABLE", "Grants", "Mode", "Outcome", "PermissionClass", "Request", "Rule", "Rules",
    "decide", "on_floor", "permission_class", "rules_from_payload", "strictest",
]


def rules_from_payload(payload: object) -> Rules:
    """Project rules from ``<project>/workbench/agent-permissions.json``.

    Shape: ``{"allow": [{"class": "derive", "operation_id": "model.genesis"}], "ask": [...], "deny": [...]}``.
    Anything malformed is ignored rather than guessed; the floor holds regardless.
    """

    def entries(name: str) -> tuple[Rule, ...]:
        items = payload.get(name) if isinstance(payload, dict) else None
        out = []
        for item in items if isinstance(items, list) else ():
            try:
                cls = PermissionClass(str(item.get("class")))
            except (ValueError, AttributeError):
                continue
            operation_id = item.get("operation_id")
            out.append(Rule(cls, str(operation_id) if isinstance(operation_id, str) and operation_id else None))
        return tuple(out)

    return Rules(allow=entries("allow"), ask=entries("ask"), deny=entries("deny"))
