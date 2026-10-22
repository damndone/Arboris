"""Strict request models for the Notebook routes."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotebookCreateRequest(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    created_by: str = Field(min_length=1, max_length=200)
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    analysis_contract: dict[str, Any] = Field(default_factory=dict)
    user_focus: dict[str, Any] = Field(default_factory=dict)
    available_capabilities: list[str] = Field(default_factory=list, max_length=100)


class DatasetProjectionRequest(_StrictModel):
    upload_sha256: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    sheet_names: list[str] = Field(default_factory=list, max_length=100)


class NotebookProjectionRequest(_StrictModel):
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    dataset: DatasetProjectionRequest | None = None
    created_by: str = Field(min_length=1, max_length=200)
    title: str = Field(default="Analysis Notebook", min_length=1, max_length=300)


class RunDatasetNotebookProjectionRequest(_StrictModel):
    """Request a new dataset-rooted Notebook from a run's verified upload."""

    from_run_id: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    title: str = Field(default="Analysis Notebook", min_length=1, max_length=300)


class NotebookFocusRequest(_StrictModel):
    """User-authored intent and interaction mode; both are freshness dependencies."""

    goal: str | None = Field(default=None, min_length=1, max_length=4_000)
    interaction_mode: Literal["plan", "action"] | None = None


class ExpectedArtifactRequest(_StrictModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    artifact_type: str = Field(min_length=1, max_length=200)
    required: bool = True
    count: int = Field(default=1, ge=0)
    step: str | None = Field(default=None, min_length=1, max_length=200)


class OptionDraftRequest(_StrictModel):
    rank: int = Field(ge=1, le=3)
    rationale: str = Field(min_length=1, max_length=4_000)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    proposal: dict[str, Any]
    expected_artifacts: list[ExpectedArtifactRequest] = Field(
        default_factory=list, max_length=50
    )
    option_id: str | None = Field(default=None, min_length=1, max_length=200)
    capability_id: str | None = Field(default=None, min_length=1, max_length=200)


class ProposeOptionsRequest(_StrictModel):
    drafts: list[OptionDraftRequest] = Field(default_factory=list, max_length=3)
    count: int | None = Field(default=None, ge=1, le=3)
    attempt_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )


class RevalidateOptionRequest(OptionDraftRequest):
    pass


class ConfirmOptionRequest(_StrictModel):
    option_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=200)
    proposal_revision: int = Field(ge=1)


class DecisionRequest(_StrictModel):
    decision: Literal[
        "selected",
        "deferred",
        "rejected",
        "edited",
        "requested_more_options",
        "requested_explanation",
    ]
    actor: str = Field(min_length=1, max_length=200)
    edited_fields: list[str] | None = Field(default=None, max_length=50)
    note_ref: str | None = Field(default=None, max_length=500)


class ExecuteOptionRequest(_StrictModel):
    execution_status: str | None = Field(default=None, min_length=1, max_length=100)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    produced_artifacts: list[dict[str, Any]] | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=200)
