"""Create immutable local script bundles from completed server-owned paths."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from ..script_export.storage import publish_script_bundle
import zipfile

from ..egress import authorize_local_artifact_export
from ..script_export.builder import build_script_plan
from ..script_export.plan import ScriptExportRefusal
from ..script_export.render import export_script, resolve_exporter
from ..script_export.result_snapshot import ResultSnapshotRef
from ..postestimation.comparison_data import _bound_bytes
from ..services.server_run_artifacts import read_server_owned_run_artifacts


def list_script_export_targets(project_root, run_id, model_target):
    """List identities for a verified model, without returning numeric content."""
    built = build_script_plan(project_root, run_id, model_target)
    if not model_target.startswith('model:') or built.plan.steps[-1].kind != 'model':
        raise ScriptExportRefusal('INVALID_EXPORT_INPUT', 'Analysis paths require a model target')
    model_id = model_target.removeprefix('model:')
    root = Path(project_root).resolve() / 'runs' / run_id
    labels = {'wald':'Wald test', 'lincom':'linear combination', 'nlcom':'nonlinear combination',
              'lr':'likelihood-ratio test', 'margins':'marginal effects'}
    targets = [{'target':model_target, 'label':'Model only'}]
    for record in read_server_owned_run_artifacts(Path(project_root), run_id, required=True):
        if record['artifact_type'] != 'post_estimation':
            continue
        payload = json.loads(_bound_bytes(root, root / record['path']))
        source = payload.get('source', {})
        if (payload.get('schema_version') != 'workbench.workflow.post-estimation/v1'
                or source.get('model_run_id') != run_id or source.get('model_artifact_id') != model_id):
            continue
        operation = payload.get('result', {}).get('operation')
        if operation in labels:
            targets.append({'target':'artifact:'+record['artifact_id'], 'label':'Model and '+labels[operation]})
    return {'targets': targets}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _prepare(project_root, run_id, target, language, require_native):
    built = build_script_plan(project_root, run_id, target)
    completed = set(); references = {}; files = dict(built.files)
    for step in built.plan.steps:
        declaration = resolve_exporter(step, language)
        uses_result = declaration.status == 'snapshot' or (step.kind == 'postestimation' and any(key in completed for key in step.parameters['models']))
        if uses_result and step.kind in {'model', 'postestimation'}:
            completed.add(step.step_id)
            name, raw = built.result_sidecars[step.step_id]
            references[step.step_id] = ResultSnapshotRef(name, hashlib.sha256(raw).hexdigest())
            files[name] = raw
    exported = export_script(built.plan, language, require_native=require_native, result_snapshots=references)
    files[exported.filename] = exported.text.encode()
    files['plan.json'] = _json(built.plan.to_dict())
    coverage = [{'step_id': item.step_id, 'operation': item.operation, 'status': item.status, 'note': item.note} for item in exported.coverage]
    summary = {'run_id': run_id, 'target': target, 'language': language, 'fully_native': exported.fully_native,
        'coverage': coverage, 'required_packages': list(exported.required_packages), 'lineage_hash': built.plan.lineage_hash}
    files['manifest.json'] = _json({**summary, 'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}})
    columns = sorted(set(built.source_columns) | {column for step in built.plan.steps if step.snapshot for column in step.snapshot.columns})
    return files, summary, columns


def export_analysis_script(project_root: Path | str, run_id: str, target: str, language: str, *, require_native: bool = False):
    """Only local artifacts are returned; no script or data enters tool output."""
    if language not in {'stata', 'r', 'python'} or type(require_native) is not bool:
        raise ScriptExportRefusal('INVALID_EXPORT_INPUT', 'Invalid language or native requirement')
    project = Path(project_root).resolve()
    files, summary, columns = _prepare(project, run_id, target, language, require_native)
    authorize_local_artifact_export(project, columns=columns, content_classes=('schema', 'metadata', 'model_result', 'rows'))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw)
    raw = stream.getvalue(); digest = hashlib.sha256(raw).hexdigest()
    artifact_id = 'script_export_' + language + '_' + digest[:24]
    publish_script_bundle(project, run_id, artifact_id, raw, digest)
    return {**summary, 'artifact_id': artifact_id, 'filename': 'analysis-' + language + '.zip', 'sha256': digest,
        'download_url': f'/runs/{run_id}/artifacts/{artifact_id}?' + urlencode({'project_root': str(project)}), 'bytes': len(raw)}
