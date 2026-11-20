"""Bind a causal target to producer-owned evidence, never an Agent's label."""
import re
import math

TARGET_SCHEMA = {'type': 'object', 'required': ['estimand', 'outcome', 'treatment'],
    'properties': {'estimand': {'enum': ['ATT', 'ATC', 'ATE']},
                   'outcome': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                   'treatment': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
    'additionalProperties': False}

#: Several requested quantities at once ("estimate ATT and ATE and compare them"); each needs its
#: own bound result. A single ``target`` stays valid and means a list of one.
TARGETS_SCHEMA = {'type': 'array', 'minItems': 2, 'maxItems': 6, 'uniqueItems': True, 'items': TARGET_SCHEMA,
                  'description': 'Every requested quantity, when the person asked for more than one.'}


def contract_targets(contract):
    """The targets a completion contract or result names: ``targets``, else ``[target]``."""
    contract = contract or {}
    return list(contract.get('targets') or ([contract['target']] if contract.get('target') else []))


def target_estimands(contract):
    return {target['estimand'] for target in contract_targets(contract)}


REQUESTED_TARGET = re.compile(r'\b(ATT|ATC|ATE)\b|对已处理者的平均处理效应|对未处理者的平均处理效应', re.I)
_COLUMN = r'(?:`[^`\r\n]{1,200}`|[A-Za-z_][A-Za-z0-9_]{0,199})'
_TWO_OUTCOMES = re.compile(
    rf'\b(?P<estimand>ATT|ATC|ATE)\s+for\s+(?:both\s+)?(?P<first>{_COLUMN})\s+and\s+'
    rf'(?P<second>{_COLUMN})(?:\s+(?:using|with)\s+(?:the\s+)?treatment(?:\s+column)?\s+'
    rf'(?P<treatment>{_COLUMN}))?(?=\s*(?:$|[!?;,]|\.(?:\s|$))|\s+and\s+(?:compare|report)\b)',
    re.I,
)


def requested_targets(text):
    return {({'对已处理者的平均处理效应': 'ATT', '对未处理者的平均处理效应': 'ATC'}.get(m[0]) or m[0].upper())
            for m in REQUESTED_TARGET.finditer(text or '')}


def requested_outcomes(text):
    """Bind explicit pairs of outcome columns, preserving their original names."""
    bindings = []
    for match in _TWO_OUTCOMES.finditer(text or ''):
        outcomes = [match[group].strip('`') for group in ('first', 'second')]
        if outcomes[0] == outcomes[1]:
            continue
        treatment = match['treatment']
        bindings.extend({'estimand': match['estimand'].upper(), 'outcome': outcome,
                         'treatment': treatment.strip('`') if treatment is not None else None}
                        for outcome in outcomes)
    return bindings


def requested_targets_unbound(contract, estimands, bindings):
    if estimands and estimands != target_estimands(contract):
        return True
    if not bindings:
        return False
    declared = contract_targets(contract)
    return any(not any(
        target['estimand'] == request['estimand'] and target['outcome'] == request['outcome']
        and (request['treatment'] is None or target['treatment'] == request['treatment'])
        for target in declared
    ) for request in bindings)


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
    if artifact.artifact_type == 'workflow_capability_result':
        result = value.get('result')
        return (value.get('schema_version') == 'workbench.workflow.capability/v1'
                and isinstance(result, dict) and bool(result) and not result.get('error')
                and result.get('status') in {None, 'completed'})
    if artifact.artifact_type == 'p7_analysis':
        result = value.get('result')
        return (value.get('schema_version') == 'workbench.workflow.p7-pack/v1'
                and isinstance(result, dict) and result.get('status') == 'completed'
                and bool(result.get('result')) and not result.get('error'))
    if artifact.artifact_type == 'post_estimation':
        # A margins or Wald result is a computed answer; IV-AR evidence is a diagnostic with its own role.
        result = value.get('result')
        return (value.get('schema_version') == 'workbench.workflow.post-estimation/v1'
                and isinstance(result, dict) and result.get('schema_version') == 'workbench.postestimation.result/v1'
                and not result.get('error'))
    if artifact.artifact_type == 'statistical_test':
        result = value.get('result')
        return (value.get('payload_schema') == 'workbench.statistical_tests.named-family'
                and isinstance(result, dict) and bool(result.get('results')) and not result.get('error'))
    return False


def matches_target(target, artifact, source_sha256):
    # Matching and the treatment-effects family certify an estimand and its
    # variable bindings. No OLS coefficient proves ATT/ATC/ATE.
    # Unsupported targets remain missing; do not relabel an approximation.
    if artifact is None or artifact.artifact_type != 'p7_analysis' or not artifact.payload:
        return False
    payload = artifact.payload
    result = payload.get('result', {})
    if not isinstance(result, dict) or not isinstance(payload.get('source'), dict):
        return False
    estimate = result.get('result', {})
    if result.get('operation_id') == 'treatment_effects.estimate':
        return (result.get('status') == 'completed' and isinstance(estimate, dict)
                and estimate.get('estimand') == target['estimand']
                and type(estimate.get('estimate')) is float and math.isfinite(estimate['estimate'])
                and payload['source'].get('sha256') == source_sha256
                and estimate.get('outcome_column') == target['outcome']
                and estimate.get('treatment_column') == target['treatment'])
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
