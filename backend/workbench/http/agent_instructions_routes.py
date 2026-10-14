"""Read, edit and draft the instructions the Agent reads (agent/instructions.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..agent import instructions
from ..api_errors import WorkbenchAPIError
from .agent_routes import _project_root
from .responses.agent import AgentInstructions, AgentInstructionsDraft
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


def _view(root) -> AgentInstructions:
    return {
        "layers": [layer.to_dict() for layer in instructions.layers(root)],
        "limit_bytes": instructions.MAX_BYTES,
        "templates": {kind: instructions.template(kind) for kind in ("personal", "project")},
    }


@router.get("/agent/instructions")
def get_agent_instructions(project_root: str) -> AgentInstructions:
    """The built-in guide, the person's and the project's instructions.

    A new conversation reads them as they are when it starts.
    """
    return _view(_project_root(project_root))


class AgentInstructionsSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["personal", "project"]
    content: str = Field(max_length=instructions.MAX_BYTES)


@router.put("/agent/instructions")
def save_agent_instructions(project_root: str, body: AgentInstructionsSave) -> AgentInstructions:
    """Write the personal or the project AGENTS.md."""
    root = _project_root(project_root)
    try:
        instructions.save(body.kind, root, body.content)
    except ValueError as exc:
        raise WorkbenchAPIError(status_code=422, code="AGENT_INSTRUCTIONS_INVALID", message=str(exc), details={}) from exc
    except OSError as exc:
        raise WorkbenchAPIError(status_code=500, code="AGENT_INSTRUCTIONS_UNWRITABLE",
                                message="The instructions file could not be written.",
                                details={"kind": body.kind, "reason": type(exc).__name__}) from exc
    return _view(root)


@router.get("/agent/instructions/draft")
def draft_agent_instructions(project_root: str) -> AgentInstructionsDraft:
    """The project template filled with this project's datasets and models; not saved."""
    return {"content": instructions.draft(_project_root(project_root))}
