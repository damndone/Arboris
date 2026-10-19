"""agent route permissions: extracted HTTP responsibility."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from ..api_errors import WorkbenchAPIError

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


def _grant_for_session(repository: Any, session_id: str, orchestrator: Any, proposal: Any) -> None:
    """Remember "don't ask again" for this proposal's class, if it is grantable."""
    from ..agent.permissions import GRANTABLE

    request = orchestrator._permission_request(proposal, within_budget=True)
    if request.permission_class not in GRANTABLE or request.touches_source:
        return
    grants = list(repository.get_metadata(session_id).get("permission_grants") or [])
    entry = {"class": request.permission_class.value}
    if entry not in grants:
        repository.update_metadata(session_id, permission_grants=[*grants, entry])

