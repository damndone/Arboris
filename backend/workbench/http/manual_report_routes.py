"""Provider-independent manual report draft, revisions, history and export."""
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from filelock import Timeout

from ..agent.workflow import WorkflowExecutionError
from ..api_errors import WorkbenchAPIError
from ..repository.run_repository import _resolve_run_root
from ..services.manual_reports import (
    ManualReportRequest, build_manual_report_draft, export_manual_report,
    list_manual_reports, save_manual_report,
)
from .responses.manual_reports import ManualReportDraft, ManualReportHistory, ManualReportSaved
from .typed_routes import MediaType, TypedAPIRoute

router = APIRouter(route_class=TypedAPIRoute)


def _invoke(function, *args):
    try:
        return function(*args)
    except WorkbenchAPIError:
        raise
    except Timeout as exc:
        raise WorkbenchAPIError(status_code=409, code="MANUAL_REPORT_BUSY", message="Another report write is in progress.") from exc
    except (OSError, ValueError, TypeError, KeyError, WorkflowExecutionError) as exc:
        raise WorkbenchAPIError(status_code=422, code="MANUAL_REPORT_INVALID", message="Report evidence or content could not be validated.") from exc


@router.get("/runs/{run_id}/manual-reports/draft")
def manual_report_draft(run_id: str, project_root: str) -> ManualReportDraft:
    return _invoke(build_manual_report_draft, _resolve_run_root(project_root, run_id))


@router.post("/runs/{run_id}/manual-reports")
def manual_report_save(run_id: str, project_root: str, request: ManualReportRequest) -> ManualReportSaved:
    return _invoke(save_manual_report, _resolve_run_root(project_root, run_id), request)


@router.get("/runs/{run_id}/manual-reports")
def manual_report_history(run_id: str, project_root: str) -> ManualReportHistory:
    return {"reports": _invoke(list_manual_reports, _resolve_run_root(project_root, run_id))}


@router.get("/runs/{run_id}/manual-reports/{report_id}/export")
def manual_report_export(
    run_id: str, report_id: str, project_root: str,
    format: Literal["html", "docx", "tex", "pdf-print"] = "html",
) -> Annotated[Response, MediaType("application/octet-stream")]:
    content, media, filename = _invoke(export_manual_report, _resolve_run_root(project_root, run_id), report_id, format)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
