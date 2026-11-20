"""Exact, scoped checks of supplied claims against public model evidence.

This owner reads only the existing coefficient inspector. It neither searches
for a matching number elsewhere nor recomputes a statistical result. Quoted
text is retained as data; it supplies no source facts and is never parsed.
"""
from __future__ import annotations

import math
from typing import Any, Protocol

from .context_tools_support.requests import InspectProjectModelCoefficientsRequest

MAX_CLAIMS = 64
MAX_TERMS = 16
_FIELDS = frozenset({'nobs', 'estimate', 'std_error', 'p_value', 'ci_lower', 'ci_upper'})
_LIMITATIONS = (
    'Only the explicitly provided claims are compared with exact public raw values from the selected run/model.',
    'A matching nobs does not establish independent units or the number of independent experimental samples.',
    'This check does not establish causality or methodological suitability.',
    'Unprovided report text, omitted claims and arbitrary manuscript wording have not been verified.',
    'No statistical result is recomputed; missing or ambiguous public evidence is unverifiable.',
)


class StatisticalClaimError(ValueError):
    code = 'MODEL_CLAIMS_INVALID'


class ModelClaimProvider(Protocol):
    def inspect_project_model_coefficients(self, request: InspectProjectModelCoefficientsRequest) -> dict[str, Any]: ...


def _number(value: Any) -> bool:
    return type(value) is int or type(value) is float and math.isfinite(value)


def _text(value: Any, limit: int) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= limit


def _claims(values: Any) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    if type(values) not in {list, tuple} or not 1 <= len(values) <= MAX_CLAIMS:
        raise StatisticalClaimError(f'claims must contain 1 to {MAX_CLAIMS} explicit field claims')
    claims = []
    terms = []
    for value in values:
        if (type(value) is not dict or not {'field', 'reported'} <= set(value)
                or set(value) - {'field', 'reported', 'term', 'text'}):
            raise StatisticalClaimError('each claim needs field/reported; source facts cannot be self-reported')
        field = value['field']
        if type(field) is not str or field not in _FIELDS:
            raise StatisticalClaimError('unsupported model claim field')
        if field == 'nobs':
            if 'term' in value:
                raise StatisticalClaimError('nobs is a model claim and must not name a coefficient term')
        else:
            term = value.get('term')
            if not _text(term, 300):
                raise StatisticalClaimError('coefficient claims require an exact bounded term')
            if term not in terms:
                terms.append(term)
        reported = value['reported']
        if reported is not None and (not _number(reported) or field == 'nobs' and type(reported) is not int):
            raise StatisticalClaimError('reported values must be finite numbers; nobs must be an exact integer, not bool')
        if 'text' in value and not _text(value['text'], 2000):
            raise StatisticalClaimError('optional quoted text must be a nonblank string of at most 2000 characters')
        claims.append(dict(value))
    if len(terms) > MAX_TERMS:
        raise StatisticalClaimError(f'at most {MAX_TERMS} exact coefficient terms may be checked')
    return claims, tuple(terms)


def _selected(output: Any, run_id: str, model_id: str):
    if not isinstance(output, dict) or not isinstance(output.get('models'), list):
        return None, None, 'invalid_public_projection'
    matches = [model for model in output['models'] if isinstance(model, dict)
               and model.get('run_id') == run_id and model.get('model_id') == model_id]
    if not matches:
        return None, None, 'selected_model_not_found'
    if len(matches) != 1:
        return None, None, 'selected_model_ambiguous'
    model = matches[0]
    reference = model.get('evidence_ref')
    if not isinstance(reference, dict) or not _text(reference.get('result_ref'), 500):
        return None, None, 'evidence_reference_missing'
    reference = dict(reference)
    if reference.get('run_id') != run_id or reference.get('model_id') != model_id:
        return None, reference, 'evidence_scope_mismatch'
    return model, reference, None


def _actual(model: dict[str, Any], claim: dict[str, Any]):
    field = claim['field']
    if field == 'nobs':
        value = model.get('nobs')
        if type(value) is not int or value < 0:
            return None, 'actual_value_unavailable'
        return value, None
    term = claim['term']
    missing = model.get('missing_terms')
    if not isinstance(missing, list) or any(type(item) is not str for item in missing):
        return None, 'term_availability_unverifiable'
    if term in missing:
        return None, 'term_missing'
    coefficients = model.get('coefficients')
    if not isinstance(coefficients, list):
        return None, 'coefficient_evidence_unavailable'
    matches = [item for item in coefficients if isinstance(item, dict) and item.get('term') == term]
    if not matches:
        return None, 'term_missing'
    if len(matches) != 1:
        return None, 'term_ambiguous'
    value = matches[0].get(field)
    if not _number(value):
        return None, 'actual_value_unavailable'
    return value, None


def check_model_claims(provider: ModelClaimProvider, *, run_id: str, model_id: str,
                       claims: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Check supplied fields in exactly one public run/model projection.

    Input is a nonempty list of {field, reported, term? , text?}. Coefficient
    fields require the exact persisted term. None is missing evidence, never
    equality. No tolerance or formatting-based numerical matching is applied.
    """
    if not _text(run_id, 200) or not _text(model_id, 200):
        raise StatisticalClaimError('run_id and model_id must be explicit nonblank identifiers')
    normalized, terms = _claims(claims)
    scope = {'run_id': run_id, 'model_id': model_id}
    provider_error = None
    try:
        output = provider.inspect_project_model_coefficients(
            InspectProjectModelCoefficientsRequest(run_ids=(run_id,), terms=terms),
        )
    except Exception as error:
        model, reference, issue = None, None, 'provider_evidence_unavailable'
        provider_error = {'type': type(error).__name__, 'message': str(error)[:500]}
    else:
        model, reference, issue = _selected(output, run_id, model_id)
    checks = []
    counts = {'match': 0, 'mismatch': 0, 'unverifiable': 0}
    for claim in normalized:
        actual, reason = (None, issue) if issue is not None else _actual(model, claim)
        if reason is None and claim['reported'] is None:
            reason = 'reported_value_missing'
        status = 'unverifiable' if reason is not None else 'match' if claim['reported'] == actual else 'mismatch'
        counts[status] += 1
        checks.append({**claim, 'actual': actual, 'status': status, 'reason': reason,
                       'scope': dict(scope), 'evidence_ref': dict(reference) if reference is not None else None})
    aggregate = ('discrepancies' if counts['mismatch'] else 'unverifiable' if counts['unverifiable']
                 else 'provided_claims_match')
    result = {'schema': 'workbench.model-claims.v1', 'scope': scope, 'status': aggregate,
              'comparison': 'exact_public_raw_values', 'checks': checks, 'counts': counts,
              'limitations': list(_LIMITATIONS)}
    if provider_error is not None:
        result['provider_error'] = provider_error
    return result
