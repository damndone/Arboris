"""Local script export requests accept owner identities, never supplied numbers."""
from typing import Literal
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..analysis_ledger import record_ui_action
from ..api_errors import WorkbenchAPIError
from ..egress import EgressPolicyError
from ..script_export.plan import ScriptExportRefusal
from ..services.script_export import export_analysis_script, list_script_export_targets

router = APIRouter()


class ScriptExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    target: str = Field(min_length=1, max_length=300)
    language: Literal['stata', 'r', 'python']
    require_native: bool = False


@router.get('/runs/{run_id}/script-export/targets')
def script_export_targets_endpoint(run_id: str, project_root: str, model_target: str):
    try:
        return list_script_export_targets(Path(project_root), run_id, model_target)
    except ScriptExportRefusal as exc:
        raise WorkbenchAPIError(422, exc.code, str(exc), {'steps': list(exc.steps)}) from exc


@router.post('/runs/{run_id}/script-export')
def script_export_endpoint(run_id: str, project_root: str, request: ScriptExportRequest):
    try:
        result = export_analysis_script(Path(project_root), run_id, request.target, request.language, require_native=request.require_native)
    except EgressPolicyError as exc:
        raise WorkbenchAPIError(403, 'SCRIPT_EXPORT_EGRESS_DENIED', str(exc)) from exc
    except ScriptExportRefusal as exc:
        raise WorkbenchAPIError(422, exc.code, str(exc), {'steps': list(exc.steps)}) from exc
    # The same record the Agent's export leaves, so the ledger shows every export.
    record_ui_action(Path(project_root), source='POST /runs/{run_id}/script-export', steps=['export.analysis_script'],
        run_id=run_id, node_id=request.target, summary='Local ' + result['language'] + ' script export')
    return result
