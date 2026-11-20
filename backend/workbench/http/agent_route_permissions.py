"""agent route permissions: extracted HTTP responsibility."""
from __future__ import annotations
from typing import Any

from ..agent.permission_config import project_permission_rules as _project_permission_rules


def _session_grants(repository: Any, session_id: str):
    """This conversation's "don't ask again" answers, kept in the session metadata."""
    from ..agent.permissions import GRANTABLE, Grants, PermissionClass, Rule

    entries = set()
    for item in (repository.get_metadata(session_id).get("permission_grants") or []):
        try:
            cls = PermissionClass(str(item.get("class")))
        except (ValueError, AttributeError):
            continue
        if cls in GRANTABLE:
            entries.add(Rule(cls, item.get("operation_id") or None))
    return Grants(frozenset(entries))


def _session_grant_class(repository, registry, proposal, metadata):
    from ..agent import permissions

    if metadata.get("execution_mode") == "auto":
        return None
    request = permissions.request_for_proposal(repository, registry, proposal)
    cls = request.permission_class
    if cls not in permissions.GRANTABLE:
        return None
    rules = permissions.with_execution_policy(_project_permission_rules(repository.root.parent),
                                              metadata.get("execution_policy", "proposal_only"))
    grant = permissions.Grants(frozenset({permissions.Rule(cls)}))
    decision = permissions.decide(permissions.Mode.ASK, request, rules, grant)
    return cls.value if decision.authority == "session_grant" else None


def _grant_for_session(repository: Any, session_id: str, grant_class: str) -> None:
    repository.add_permission_grant(session_id, grant_class)

