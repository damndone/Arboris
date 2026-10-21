"""Explicit native-IV AR computation on a verified completed model's input.

The original fit is reconstructed to recover its exact estimator-owned design;
no coefficient result, original diagnostic, or default workflow is rewritten.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from ..canonical import sha256_canonical
from ..checks.context import build_context
from ..checks.iv_checks import first_stage_strength, FIRST_STAGE_STRENGTH
from ..engine.iv_diagnostics import iv_point_definition
from ..econometrics.runner import run_iv_2sls
from ..postestimation.comparison_data import _bound_bytes
from ..postestimation.core import PostestimationRefusal
from .completion_products import read_analysis_frame, sample_metadata
from .pinned_run_directory import open_pinned_run_directory


def _refuse(message):
    raise PostestimationRefusal('IV_AR_BINDING_UNVERIFIED', message)


def compute_ar(run_root, model_id, expected_source, target_frame):
    """Return a supplement bound to the original result, sample and design."""
    if model_id != 'iv_2sls_1':
        _refuse('AR is offered here only for a completed native iv_2sls model.')
    primary_raw = _bound_bytes(run_root, run_root/'model_results'/f'{model_id}.json')
    completion_raw = _bound_bytes(run_root, run_root/'model_results'/f'{model_id}.completion.json')
    primary, completion = json.loads(primary_raw), json.loads(completion_raw)
    if (primary.get('model_type') != 'iv_2sls' or primary.get('model_id') != model_id
            or completion.get('contract') != 'analysis-completion.evidence.v2'
            or completion.get('status') != 'complete'
            or completion.get('model_payload_sha256') != sha256_canonical(primary)):
        _refuse('The native IV result and completion evidence are not bound.')
    with open_pinned_run_directory(run_root.parent, run_root.name) as pinned:
        inputs = pinned.read_run_inputs_snapshot().value
        source = completion['source']
        record = pinned.lmm_source_record(artifact_id=source['artifact_id'], sha256=source['sha256'])
        if record is None or record['sha256'] != source['sha256']:
            _refuse('The original IV analysis data is unavailable or changed.')
        if expected_source['sha256'] == source['sha256']:
            # The workflow already loaded and bound these exact source bytes.
            frame = target_frame
        else:
            # A model branch can materialize different derived columns/data.
            # Read that original analysis input once for AR, not as a duplicate
            # copy of the target merely to validate it.
            selected = pinned.read_lmm_analysis_source(artifact_id=source['artifact_id'], sha256=source['sha256'])
            if selected is None:
                _refuse('The original IV analysis input cannot be opened with its registered binding.')
            frame = read_analysis_frame(*selected)
    original = {'run_id': run_root.name, 'artifact_id': source['artifact_id'], 'sha256': source['sha256']}
    target = {key: expected_source[key] for key in original}
    parent = inputs.get('dataset_source') or {}
    parent_binding = {'run_id': parent.get('source_run_id'), 'artifact_id': parent.get('source_artifact_id'),
                      'sha256': parent.get('source_sha256')}
    if target not in (original, parent_binding):
        _refuse('The workflow target is not the fixed IV analysis source.')
    # Require a terminal owner; a completed operation receipt alone is not a fit.
    if json.loads((run_root/'run_manifest.json').read_text()).get('status') != 'completed':
        _refuse('The original IV owner run has not completed.')
    summary = json.loads(_bound_bytes(run_root, run_root/'diagnostic_summary.json'))
    identity = summary['model_identity']
    form = inputs['form']
    from ..cleaning import normalize_column_name
    endog = [normalize_column_name(v) for v in json.loads(form['iv_endog'])]
    instruments = [normalize_column_name(v) for v in json.loads(form['iv_instruments'])]
    covariance = completion['diagnostics']['iv']['weak_instruments']['covariance']
    _, fitted = run_iv_2sls(frame, y=identity['y_variable'], exog=identity['x_variables'],
        endog=endog, instruments=instruments, model_id=model_id, covariance=covariance)
    point = sha256_canonical(iv_point_definition(fitted.model))
    sample = sample_metadata(np.flatnonzero(fitted.model.notnull), len(frame))
    if (point != completion['point_estimation_fingerprint']
            or sample != completion['sample'] or fitted.nobs != primary['nobs']):
        _refuse('Reconstructed IV inputs do not match the original design and retained rows.')
    context = build_context(model_id=model_id, model_type='iv_2sls', fitted=fitted,
                            kernel=None, nobs=primary['nobs'])
    outcome = first_stage_strength(context, FIRST_STAGE_STRENGTH, compute_ar=True)
    return {'contract': 'iv-ar.evidence.v1', 'model_id': model_id, 'model_run_id': run_root.name,
        'model_sha256': hashlib.sha256(primary_raw).hexdigest(),
        'completion_sha256': hashlib.sha256(completion_raw).hexdigest(),
        'point_estimation_fingerprint': point, 'analysis_sample_fingerprint': sample['positions_sha256'],
        'covariance': covariance, 'confidence_level': .95,
        'anderson_rubin_95': outcome.evidence['anderson_rubin_95'],
        'scientific_validity': 'not_certified'}
