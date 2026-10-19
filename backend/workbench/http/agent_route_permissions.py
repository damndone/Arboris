"""agent route permissions: extracted HTTP responsibility."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from ..api_errors import WorkbenchAPIError

def _project_permission_rules(root: Path):
    """Read complete project rules; an invalid store must not discard denies."""
    from ..agent.permissions import Rules, rules_from_payload

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate permission key")
            result[key] = value
        return result

    path = root / "workbench" / "agent-permissions.json"
    try:
        document = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if not path.is_symlink():
            return Rules()
        raise WorkbenchAPIError(
            status_code=503, code="AGENT_PERMISSION_RULES_INVALID",
            message="The project permission rules cannot be read; repair the permission file before continuing.",
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise WorkbenchAPIError(
            status_code=503, code="AGENT_PERMISSION_RULES_INVALID",
            message="The project permission rules cannot be read; repair the permission file before continuing.",
        ) from exc
    try:
        return rules_from_payload(json.loads(document, object_pairs_hook=unique_keys))
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="AGENT_PERMISSION_RULES_INVALID",
            message="The project permission rules are invalid; repair the permission file before continuing.",
        ) from exc


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

