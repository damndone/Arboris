"""Project permission rules shared by manual and Agent entry points."""
from pathlib import Path
import json
from typing import Any
from ..api_errors import WorkbenchAPIError

def project_permission_rules(root: Path):
    """Read complete project rules; an invalid store must not discard denies."""
    from .permissions import Rules, rules_from_payload

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

