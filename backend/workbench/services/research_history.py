"""Result availability on the same original upload, without reading estimates."""
from pathlib import Path
import re

from .pinned_run_directory import PinnedRunError, open_pinned_run_directory
from .server_run_artifacts import read_server_owned_run_artifacts, ServerOwnedArtifactManifestError

_NON_RESULTS = {'raw_data', 'processed_data', 'derived_data', 'dataset', 'dataset_stage', 'metadata', 'dataset_metadata',
                'variable_metadata', 'data_dictionary', 'schema', 'source_data', 'source_provenance'}


def _original_upload(root, run_id):
    try:
        with open_pinned_run_directory(root / 'runs',run_id) as pinned:
            inputs = pinned.read_run_inputs_snapshot().value
    except PinnedRunError:
        return None
    upload = inputs.get('upload')
    sha = upload.get('sha256') if isinstance(upload,dict) else None
    return sha if isinstance(sha,str) and re.fullmatch('[0-9a-f]{64}',sha) is not None else None


def result_history(root, run_id):
    """Conservatively associate all results on one upload across all branches.

    Unknown provenance cannot establish an absence of related results. Merely
    making a result available counts; this is stricter than tracking clicks.
    """
    root = Path(root)
    source = _original_upload(root, run_id)
    prior, verified = [], isinstance(source, str) and re.fullmatch('[0-9a-f]{64}', source) is not None
    runs = root / 'runs'
    if runs.is_symlink():
        return {'source_upload_sha256':source,'verified':False,'prior_results':[]}
    for run in sorted(runs.iterdir()) if runs.exists() else ():
        if run.is_symlink():
            verified = False
            continue
        if not run.is_dir():
            continue
        other_source = _original_upload(root, run.name)
        if other_source is None:
            verified = False
            continue
        if source is not None and other_source is not None and source != other_source:
            continue
        try:
            artifacts = read_server_owned_run_artifacts(root, run.name, required=True)
        except ServerOwnedArtifactManifestError:
            verified = False
            continue
        results = [item for item in artifacts if item['artifact_type'] not in _NON_RESULTS]
        prior.extend({'run_id':run.name, 'artifact_id':item['artifact_id'], 'sha256':item.get('sha256')}
                     for item in results)
        # Native products may already exist before their registration finishes.
        for directory in ('model_results', 'statistical_tests'):
            if (run / directory).is_symlink():
                verified = False
            elif (run / directory).is_dir() and any((run / directory).iterdir()) and not results:
                prior.append({'run_id':run.name,'artifact_id':directory,'sha256':None})
    return {'source_upload_sha256':source,'verified':verified,'prior_results':prior}
