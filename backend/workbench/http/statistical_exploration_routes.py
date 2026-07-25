"""Typed Raw Data statistical-exploration routes."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

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


class StatisticalOlsContextRequest(StatisticalExplorationConfirmRequest):
    outcome_column: str = Field(min_length=1, max_length=200)
    predictor_columns: list[str] = Field(min_length=1, max_length=100)
    # A genesis draft carries no editable_schema, so whatever this endpoint
    # writes is what the run estimates — there is no later screen to change it.
    # "clustered" is absent on purpose: the handoff materializes only the
    # outcome and predictors, so the cluster column would not exist in the
    # input the draft executes against.
    covariance: Literal["robust", "unadjusted"] = "robust"


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
    if "exports" in record:
        response["exports"] = record["exports"]
    return response


@router.post("/statistical-explorations/ols-context")
def create_statistical_ols_context(
    project_root: str,
    body: StatisticalOlsContextRequest,
) -> dict[str, Any]:
    """Create a reviewable OLS Draft from a confirmed exploration context.

    This endpoint materializes only the filtered, complete-case input needed
    by the existing OLS path.  It never dispatches a model run.
    """
    root = _root(project_root)
    spec = _spec(body)
    context, frame, result, fingerprint = _evaluate(root, body, spec, confirm=True)
    if fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="STATISTICAL_EXPLORATION_STALE",
            message="The source data or typed exploration specification changed before OLS handoff.",
            details={"expected": fingerprint, "received": body.preview_fingerprint},
        )
    from ..data_operations import _ensure_registered_artifact, _write_frame_artifact
    from ..lineage.pipeline_drafts import PipelineDraftStore
    from ..lineage.upload_store import store_upload_bytes
    from ..services.draft_materialization import create_genesis_draft
    from ..statistical_exploration import _apply_filters

    columns = [body.outcome_column, *body.predictor_columns]
    if len(set(columns)) != len(columns):
        raise WorkbenchAPIError(
            status_code=422,
            code="STATISTICAL_OLS_CONTEXT_INVALID",
            message="The OLS outcome and predictors must be distinct.",
            details={},
        )
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise WorkbenchAPIError(
            status_code=422,
            code="STATISTICAL_OLS_CONTEXT_INVALID",
            message="The OLS outcome or predictor is not present in the source dataset.",
            details={"missing_columns": missing},
        )
    nonnumeric = [
        column
        for column in columns
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if nonnumeric:
        raise WorkbenchAPIError(
            status_code=422,
            code="STATISTICAL_OLS_CONTEXT_INVALID",
            message="OLS handoff requires numeric outcome and predictor columns.",
            details={"nonnumeric_columns": nonnumeric},
        )
    filtered = _apply_filters(frame, spec.filters).dropna(subset=columns).copy()
    if len(filtered) < 2:
        raise WorkbenchAPIError(
            status_code=422,
            code="STATISTICAL_OLS_CONTEXT_EMPTY",
            message="The confirmed filters leave fewer than two complete OLS rows.",
            details={"analysis_row_count": int(len(filtered))},
        )

    try:
        exploration_record = persist_exploration(
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
        run_root = root / "runs" / body.source_run_id
        filtered_rel = f"derived/statistical_exploration/{fingerprint}/ols_input.csv"
        filtered_path = run_root / filtered_rel
        filtered_artifact_id = f"statistical_ols_input_{fingerprint[:24]}"
        _write_frame_artifact(filtered_path, filtered, "csv")
        _ensure_registered_artifact(
            run_root,
            artifact_id=filtered_artifact_id,
            path=filtered_path,
            artifact_type="derived_data",
            step="statistical_exploration.ols_context",
            inputs=[body.source_artifact_id, exploration_record["artifact_id"]],
        )
        upload_sha = store_upload_bytes(
            root,
            filtered.to_csv(index=False).encode("utf-8"),
            filename=f"{fingerprint[:24]}-ols-input.csv",
        )
        exploration_context = {
            "source_run_id": body.source_run_id,
            "source_node_id": body.source_node_id,
            "source_artifact_id": body.source_artifact_id,
            "source_sha256": context["source_sha256"],
            "exploration_fingerprint": fingerprint,
            "filters": spec.to_dict()["filters"],
            "spec": spec.to_dict(),
            "outcome_column": body.outcome_column,
            "predictor_columns": list(body.predictor_columns),
            # Part of the identity, not decoration: two handoffs that differ
            # only by covariance are different analyses and must not dedupe
            # onto one draft.
            "covariance": body.covariance,
            "analysis_row_count": int(len(filtered)),
            "filtered_artifact_id": filtered_artifact_id,
            "filtered_artifact_path": filtered_rel,
        }
        store = PipelineDraftStore(root)
        for summary in store.list():
            try:
                existing = store.get(summary["draft_id"])
            except Exception:
                continue
            if existing.draft.get("exploration_context") == exploration_context:
                return {
                    "status": "draft_created",
                    "draft": existing.draft,
                    "draft_hash": existing.draft_hash,
                    "exploration": exploration_record,
                }
        draft = create_genesis_draft(
            root,
            upload_sha256=upload_sha,
            filename=f"{fingerprint[:24]}-ols-input.csv",
            sheet_names=(),
            columns=tuple(filtered.columns),
            model_params={
                "model_type": "ols",
                "y": body.outcome_column,
                "x": list(body.predictor_columns),
                "covariance": body.covariance,
            },
            exploration_context=exploration_context,
        )
    except (OSError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="STATISTICAL_OLS_CONTEXT_STALE",
            message="The OLS context could not be bound to the source artifact.",
            details={"reason": str(exc)},
        ) from exc
    return {
        "status": "draft_created",
        "draft": draft.draft,
        "draft_hash": draft.draft_hash,
        "exploration": exploration_record,
    }
