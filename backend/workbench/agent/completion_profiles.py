"""Native companion bindings and family-specific delivery requirements."""
from __future__ import annotations

from ..canonical import sha256_canonical

NATIVE_COMPANIONS = {'survival_cox'}


def companion_model(products, ref, artifact, model):
    if model.get('model_type') not in NATIVE_COMPANIONS:
        return model
    companion = products.load({'run_id': ref['run_id'], 'artifact_id': model['model_id'] + '.completion'})
    if companion is None or companion.artifact_type != 'analysis_completion_evidence':
        return None
    value = companion.payload or {}
    if (value.get('contract') != 'analysis-completion.evidence.v1' or value.get('status') != 'complete'
            or value.get('model_payload_sha256') != sha256_canonical(artifact.payload)
            or value.get('model_id') != model['model_id'] or value.get('model_type') != model['model_type']
            or value.get('nobs') != model['nobs']):
        return None
    source = value.get('source')
    if not isinstance(source, dict):
        return None
    registered = products.load({'run_id': ref['run_id'], 'artifact_id': source.get('artifact_id')})
    if registered is None or registered.sha256 != source.get('sha256'):
        return None
    positions = value.get('retained_positions')
    if (not isinstance(positions, list) or len(positions) != model['nobs']
            or any(type(p) is not int or p < 0 or p >= source['row_count'] for p in positions)
            or positions != sorted(set(positions))
            or sha256_canonical(positions) != value.get('analysis_sample_fingerprint')):
        return None
    if any(item not in companion.inputs for item in [model['model_id'], source['artifact_id']]):
        return None
    for artifact_id in value.get('diagnostic_artifact_ids', []):
        if products.load({'run_id': ref['run_id'], 'artifact_id': artifact_id}) is None:
            return None
    return {**model, 'point_estimation_fingerprint': value['point_estimation_fingerprint'],
            'analysis_sample_fingerprint': value['analysis_sample_fingerprint']}


def native_diagnostics(family, values):
    if family == 'survival':
        for value in values:
            ph = (value.get('diagnostics') or {}).get('proportional_hazards') or {}
            if (value.get('contract') == 'analysis-completion.evidence.v1'
                    and ph.get('status') == 'computed' and ph.get('method') == 'cox_log_time_interaction_score_v1'
                    and ph.get('transform') == 'log' and ph.get('ties') in {'breslow', 'efron'}
                    and type((ph.get('global') or {}).get('p_value')) in {float, int}
                    and 0 <= ph['global']['p_value'] <= 1):
                return True
    return False


def native_findings(family, values):
    if family == 'survival':
        for value in values:
            ph = (value.get('diagnostics') or {}).get('proportional_hazards') or {}
            if ph.get('status') == 'unverified':
                return ['survival:diagnostics:' + ph['reason']]
            if ph.get('status') == 'computed' and (ph.get('global') or {}).get('p_value', 1) < .05:
                return ['survival:diagnostics:ph_rejected_requires_model_revision']
    return []
