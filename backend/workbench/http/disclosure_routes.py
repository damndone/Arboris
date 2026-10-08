"""The analysis path behind a report, and whether exports include it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .. import analysis_disclosure
from ..analysis_ledger import record_ui_action
from ..api_errors import WorkbenchAPIError
from .responses.disclosure import AnalysisDisclosure
from .responses.disclosure import DisclosureSettings as DisclosureSettingsView
from .typed_routes import TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


def _root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(status_code=404, code="PROJECT_NOT_FOUND", message="Workbench project was not found.")
    return root


@router.get("/runs/{run_id}/analysis-disclosure")
def analysis_disclosure_endpoint(run_id: str, project_root: str) -> AnalysisDisclosure:
    root = _root(project_root)
    if not (root / "runs" / run_id).is_dir():
        raise WorkbenchAPIError(status_code=404, code="RUN_NOT_FOUND", message=f"run {run_id} was not found")
    value = analysis_disclosure.disclosure(root, run_id)
    value["markdown"] = analysis_disclosure.markdown(value, detail=value["settings"]["detail"])
    return value


class DisclosureSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_in_exports: bool
    detail: Literal["summary", "full"]


@router.put("/projects/report-disclosure")
def report_disclosure_settings_endpoint(project_root: str, settings: DisclosureSettings) -> DisclosureSettingsView:
    root = _root(project_root)
    value = analysis_disclosure.write_settings(
        root, include_in_exports=settings.include_in_exports, detail=settings.detail
    )
    # Turning the disclosure off is itself part of the path.
    record_ui_action(
        root, source="PUT /projects/report-disclosure", steps=["report.disclosure_setting"],
        summary=f"include_in_exports={settings.include_in_exports} detail={settings.detail}",
    )
    return value
