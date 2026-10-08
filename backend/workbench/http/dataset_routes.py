"""Data view: browse a run's dataset nodes and edit variable metadata."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..analysis_ledger import record_ui_action
from ..api_errors import WorkbenchAPIError
from ..data_operations import DataColumnCastValidationError
from ..services.dataset_view import dataset_page, dataset_variables, list_dataset_nodes
from ..services.rerun_service import (
    RerunService,
    RerunServiceError,
    RerunSubmissionRequest,
    editable_rerun_nodes,
)
from .responses.datasets import DatasetNodes, DatasetPage, DatasetVariables, MetadataRerunSubmitted
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)

_METADATA_FIELDS = frozenset(
    {"variable_labels", "value_labels", "measurement_level", "user_missing_values"}
)


def _unavailable(exc: Exception, run_id: str, node_id: str | None = None) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=422,
        code="DATASET_UNAVAILABLE",
        message=str(exc),
        details={"run_id": run_id, "node_id": node_id},
    )


@router.get("/runs/{run_id}/datasets")
def list_datasets_endpoint(run_id: str, project_root: str) -> DatasetNodes:
    try:
        return {"run_id": run_id, "datasets": list_dataset_nodes(project_root, run_id)}
    except (FileNotFoundError, ValueError) as exc:
        raise _unavailable(exc, run_id) from exc


@router.get("/runs/{run_id}/datasets/rows")
def dataset_rows_endpoint(
    run_id: str,
    project_root: str,
    node_id: str,
    offset: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    descending: bool = False,
) -> DatasetPage:
    try:
        return dataset_page(
            project_root, run_id, node_id,
            offset=offset, limit=limit, sort_by=sort_by, descending=descending,
        )
    except (DataColumnCastValidationError, FileNotFoundError, ValueError) as exc:
        raise _unavailable(exc, run_id, node_id) from exc


@router.get("/runs/{run_id}/datasets/variables")
def dataset_variables_endpoint(run_id: str, project_root: str, node_id: str) -> DatasetVariables:
    try:
        return dataset_variables(project_root, run_id, node_id)
    except (DataColumnCastValidationError, FileNotFoundError, ValueError) as exc:
        raise _unavailable(exc, run_id, node_id) from exc


class MetadataEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: dict[str, dict[str, Any] | None] = Field(min_length=1)


@router.post("/runs/{run_id}/metadata")
def edit_metadata_endpoint(
    run_id: str, project_root: str, request: MetadataEditRequest
) -> MetadataRerunSubmitted:
    """Record a variable-metadata edit as a new run in the lineage.

    Only the named fields and columns change; everything else declared is kept
    (a value of null removes a column's declaration). Missing-code edits change
    the estimation sample, so the run is re-estimated, not just relabelled.
    """

    unknown = sorted(set(request.labels) - _METADATA_FIELDS)
    if unknown:
        raise WorkbenchAPIError(
            status_code=422,
            code="METADATA_EDIT_INVALID",
            message="Unknown metadata field(s): " + ", ".join(unknown),
            details={"fields": unknown},
        )
    try:
        nodes = editable_rerun_nodes(project_root, run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _unavailable(exc, run_id) from exc
    if not nodes:
        raise WorkbenchAPIError(
            status_code=409,
            code="METADATA_EDIT_NO_EDITABLE_NODE",
            message="This run has no editable stage to record a metadata edit from.",
            details={"run_id": run_id},
        )
    try:
        submission = RerunService(project_root).submit(
            RerunSubmissionRequest(
                source_run_id=run_id,
                from_node=nodes[0],
                op_overrides={"labels": request.labels},
                rerun_reason="metadata_edit",
                metadata_edit=True,
            )
        )
    except RerunServiceError as exc:
        raise WorkbenchAPIError(
            status_code=409 if exc.code == "slot_busy" else 422,
            code=f"METADATA_EDIT_{exc.code.upper()}",
            message=str(exc),
            details={"run_id": run_id},
        ) from exc
    record_ui_action(
        project_root, source="POST /runs/{run_id}/metadata", steps=["metadata.edit"],
        run_id=run_id, produced_run_id=submission.run_id,
        summary=json.dumps(request.labels, ensure_ascii=False, sort_keys=True, default=str)[:500],
    )
    return {"source_run_id": run_id, "run_id": submission.run_id, "status": submission.status}
