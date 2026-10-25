"""Bind a causal target to producer-owned evidence, never an Agent's label."""
import re
import math

TARGET_SCHEMA = {'type': 'object', 'required': ['estimand', 'outcome', 'treatment'],
    'properties': {'estimand': {'enum': ['ATT', 'ATC', 'ATE']},
                   'outcome': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                   'treatment': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
    'additionalProperties': False}

REQUESTED_TARGET = re.compile(r'\b(ATT|ATC|ATE)\b|对已处理者的平均处理效应|对未处理者的平均处理效应', re.I)


def requested_targets(text):
    return {({'对已处理者的平均处理效应': 'ATT', '对未处理者的平均处理效应': 'ATC'}.get(m[0]) or m[0].upper())
            for m in REQUESTED_TARGET.finditer(text or '')}


def computed_result(products, ref, artifact):
    """The artifact reader verifies bytes/lineage; this checks the product kind."""
    if artifact is None or not artifact.payload:
        return False
    value = artifact.payload
    if artifact.artifact_type in {'model_result', 'workflow_result', 'model_result_packet'}:
        return products.model(ref, artifact) is not None
    if artifact.artifact_type == 'statistical_exploration':
        result = value.get('result')
        return (value.get('schema_version') == 'statistical-exploration.v1'
                and isinstance(result, dict) and bool(result) and not value.get('error')
                and not result.get('error') and result.get('status') in {None, 'completed'})
    if artifact.artifact_type == 'p7_analysis':
        result = value.get('result')
        return (value.get('schema_version') == 'workbench.workflow.p7-pack/v1'
                and isinstance(result, dict) and result.get('status') == 'completed'
                and bool(result.get('result')) and not result.get('error'))
    return False


def matches_target(target, artifact, source_sha256):
    # Matching is currently the producer that explicitly certifies an ATT
    # estimand and its variable bindings. No OLS coefficient proves ATT/ATC/ATE.
    # Unsupported targets remain missing; do not relabel an approximation.
    if artifact is None or artifact.artifact_type != 'p7_analysis' or not artifact.payload:
        return False
    payload = artifact.payload
    result = payload.get('result', {})
    if not isinstance(result, dict) or not isinstance(payload.get('source'), dict):
        return False
    estimate = result.get('result', {})
    if not isinstance(estimate, dict) or not isinstance(estimate.get('matching_policy'), dict):
        return False
    bindings = estimate['matching_policy']
    return (target['estimand'] == 'ATT' and result.get('operation_id') == 'matching.att'
            and result.get('status') == 'completed' and estimate.get('estimand') == 'ATT'
            and estimate.get('causal_claim_eligible') is True
            and type(estimate.get('att')) in (int, float) and math.isfinite(estimate['att'])
            and payload['source'].get('sha256') == source_sha256
            and bindings.get('outcome_column') == target['outcome']
            and bindings.get('treatment_column') == target['treatment'])
