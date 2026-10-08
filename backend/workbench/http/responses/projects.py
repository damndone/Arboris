"""Projects and standalone uploads."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from .common import RunLabels


class ProjectCreated(TypedDict):
    project_root: str


class UploadStored(TypedDict):
    sha256: str
    filename: str


class StatisticalUploadPreview(TypedDict):
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    labels: RunLabels
