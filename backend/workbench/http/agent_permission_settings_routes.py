"""Typed project permission settings for the local Settings page."""

from typing import Annotated, NotRequired

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, with_config
from typing_extensions import TypedDict

from ..agent.permission_config import (
    permission_rules_document,
    read_project_permission_settings,
    save_project_permission_settings,
)
from ..agent.permissions import PermissionClass, Rules
from ..api_errors import WorkbenchAPIError
from .agent_route_context import _project_root
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

ProjectAgentPermissionRule = with_config(ConfigDict(extra="forbid"))(
    TypedDict("ProjectAgentPermissionRule", {
        "class": PermissionClass,
        "operation_id": NotRequired[Annotated[str, Field(min_length=1)]],
    })
)


@with_config(ConfigDict(extra="forbid"))
class ProjectAgentPermissionRules(TypedDict):
    allow: list[ProjectAgentPermissionRule]
    ask: list[ProjectAgentPermissionRule]
    deny: list[ProjectAgentPermissionRule]


class ProjectAgentPermissionsView(TypedDict):
    revision: str
    rules: ProjectAgentPermissionRules


class ProjectAgentPermissionsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: str = Field(pattern="^(missing|[a-f0-9]{64})$")
    rules: ProjectAgentPermissionRules


def _view(rules: Rules, revision: str) -> ProjectAgentPermissionsView:
    return {"revision": revision, "rules": permission_rules_document(rules)}


@router.get("/projects/agent-permissions")
def get_project_agent_permissions(project_root: str) -> ProjectAgentPermissionsView:
    return _view(*read_project_permission_settings(_project_root(project_root)))


@router.put("/projects/agent-permissions")
def save_project_agent_permissions(
    project_root: str, body: ProjectAgentPermissionsUpdate
) -> ProjectAgentPermissionsView:
    try:
        saved = save_project_permission_settings(
            _project_root(project_root),
            expected_revision=body.expected_revision,
            payload=body.model_dump(mode="json")["rules"],
        )
    except ValueError as exc:
        raise WorkbenchAPIError(status_code=422, code="AGENT_PERMISSION_RULES_INVALID", message=str(exc)) from exc
    return _view(*saved)
