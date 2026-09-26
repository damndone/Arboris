"""A project's data-sharing policy and the record of what was sent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..api_errors import WorkbenchAPIError
from ..egress import (
    CONTENT_CLASSES,
    LOCAL_DEFAULT_ALLOW,
    REMOTE_DEFAULT_ALLOW,
    SENSITIVITY_LEVELS,
    EgressPolicy,
    EgressPolicyError,
    load_policy,
    parse_policy,
    provider_locality,
    read_audit,
    save_policy,
)
from ..llm.config import load_llm_config

router = APIRouter()


def _root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _policy(root: Path) -> EgressPolicy:
    try:
        return load_policy(root)
    except EgressPolicyError as exc:
        raise WorkbenchAPIError(status_code=422, code="EGRESS_POLICY_INVALID", message=str(exc)) from exc


def _view(root: Path, policy: EgressPolicy) -> dict[str, Any]:
    config = load_llm_config()
    locality = provider_locality(config.base_url) if config.base_url else None
    active = None
    if locality is not None:
        active = {
            "provider_id": config.provider_id,
            "provider_name": config.provider_name,
            "locality": locality,
            "allowed_classes": sorted(
                policy.allowed_classes(provider_id=config.provider_id, locality=locality),
                key=CONTENT_CLASSES.index,
            ),
        }
    return {
        "project_root": str(root),
        "policy": policy.to_dict(),
        "policy_source": policy.source,
        "content_classes": list(CONTENT_CLASSES),
        "sensitivity_levels": list(SENSITIVITY_LEVELS),
        "defaults": {
            "remote": sorted(REMOTE_DEFAULT_ALLOW, key=CONTENT_CLASSES.index),
            "local": sorted(LOCAL_DEFAULT_ALLOW, key=CONTENT_CLASSES.index),
        },
        "active_provider": active,
    }


@router.get("/projects/egress")
def egress_policy_endpoint(project_root: str) -> dict[str, Any]:
    root = _root(project_root)
    return _view(root, _policy(root))


@router.put("/projects/egress/policy")
def replace_egress_policy_endpoint(project_root: str, document: dict[str, Any]) -> dict[str, Any]:
    root = _root(project_root)
    try:
        policy = parse_policy(document)
    except EgressPolicyError as exc:
        raise WorkbenchAPIError(status_code=422, code="EGRESS_POLICY_INVALID", message=str(exc)) from exc
    save_policy(root, policy)
    return _view(root, _policy(root))


class ColumnSensitivityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null removes the explicit level: the column falls back to the suggestion.
    columns: dict[str, Literal["public", "internal", "sensitive", "restricted"] | None] = Field(min_length=1)


@router.patch("/projects/egress/columns")
def patch_column_sensitivity_endpoint(project_root: str, patch: ColumnSensitivityPatch) -> dict[str, Any]:
    root = _root(project_root)
    policy = _policy(root)
    columns = dict(policy.columns)
    for column, level in patch.columns.items():
        if level is None:
            columns.pop(column, None)
        else:
            columns[column] = level
    save_policy(root, EgressPolicy(providers=policy.providers, columns=columns))
    return _view(root, _policy(root))


@router.get("/projects/egress/audit")
def egress_audit_endpoint(project_root: str, limit: int = 50) -> dict[str, Any]:
    root = _root(project_root)
    if not 1 <= limit <= 500:
        raise WorkbenchAPIError(status_code=422, code="EGRESS_AUDIT_LIMIT", message="limit must be between 1 and 500")
    return {"project_root": str(root), "records": read_audit(root, limit=limit)}
