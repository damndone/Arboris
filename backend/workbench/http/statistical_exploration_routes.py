"""Typed Raw Data statistical-exploration routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..api_errors import WorkbenchAPIError
from ..data_operations import DataColumnCastValidationError
from ..statistical_exploration import (
    ExplorationSpec,
    FilterSpec,
    StatisticalExplorationValidationError,
    exploration_fingerprint,
    execute_exploration,
    persist_exploration,
    resolve_statistical_source,
)


router = APIRouter()


class StatisticalFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=200)
    operator: Literal["eq", "neq", "lt", "lte", "gt", "gte", "in", "not_in"]
    value: Any


class StatisticalExplorationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    operation: Literal[
        "summarize",
        "summarize_detail",
        "misstable",
        "corr",
        "derive_boolean",
        "scatter",
    ]
    selected_columns: list[str] = Field(default_factory=list, max_length=200)
    filters: list[StatisticalFilterRequest] = Field(default_factory=list, max_length=200)
    options: dict[str, Any] = Field(default_factory=dict)
    derived_definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class StatisticalExplorationConfirmRequest(StatisticalExplorationRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)


def _root(project_root: str):
    from pathlib import Path

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _spec(body: StatisticalExplorationRequest) -> ExplorationSpec:
    try:
        return ExplorationSpec(
            operation=body.operation,
            selected_columns=tuple(body.selected_columns),
            filters=tuple(
                FilterSpec(
                    column=item.column,
                    operator=item.operator,
                    value=item.value,
                )
                for item in body.filters
            ),
            options=body.options,
            derived_definitions=tuple(body.derived_definitions),
        )
    except (StatisticalExplorationValidationError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="STATISTICAL_EXPLORATION_INVALID",
            message="The typed statistical exploration specification is invalid.",
            details={"reason": str(exc)},
        ) from exc


def _evaluate(
    root,
    body: StatisticalExplorationRequest,
    spec: ExplorationSpec,
    *,
    confirm: bool = False,
):
    try:
        context, frame = resolve_statistical_source(
            root,
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
        )
        result = execute_exploration(frame, spec)
    except (DataColumnCastValidationError, StatisticalExplorationValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="STATISTICAL_EXPLORATION_STALE" if confirm else "STATISTICAL_EXPLORATION_INVALID",
            message=(
                "The source data changed before confirmation."
                if confirm
                else "The typed statistical exploration could not be evaluated."
            ),
            details={"reason": str(exc)},
        ) from exc
    fingerprint = exploration_fingerprint(context["source_sha256"], spec)
    return context, frame, result, fingerprint


@router.post("/statistical-explorations/preview")
def preview_statistical_exploration(
    project_root: str,
    body: StatisticalExplorationRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _spec(body)
    context, frame, result, fingerprint = _evaluate(root, body, spec)
    return {
        "spec": spec.to_dict(),
        "preview": {
            "status": "ready",
            "fingerprint": fingerprint,
            "source_sha256": context["source_sha256"],
            "source_artifact_id": context["source_artifact_id"],
            "result": result,
        },
    }


@router.post("/statistical-explorations/confirm")
def confirm_statistical_exploration(
    project_root: str,
    body: StatisticalExplorationConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _spec(body)
    context, frame, result, fingerprint = _evaluate(root, body, spec, confirm=True)
    if fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="STATISTICAL_EXPLORATION_STALE",
            message="The source data or typed exploration specification changed before confirmation.",
            details={"expected": fingerprint, "received": body.preview_fingerprint},
        )
    try:
        record = persist_exploration(
            root,
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            source_sha256=context["source_sha256"],
            spec=spec,
            result=result,
            fingerprint=fingerprint,
            source_frame=frame,
        )
    except (StatisticalExplorationValidationError, OSError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="STATISTICAL_EXPLORATION_STALE",
            message="The exploration artifact could not be durably bound to the source.",
            details={"reason": str(exc)},
        ) from exc
    response: dict[str, Any] = {"status": "completed", "exploration": record, "result": result}
    if "derived" in record:
        response["derived"] = record["derived"]
    if "plot" in record:
        response["plot"] = record["plot"]
    return response
