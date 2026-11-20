"""Scoped claims compare exact public evidence from the real context provider."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from tests.test_agent_context_tools import _load_provider_type, _write_project_run


def api():
    assert importlib.util.find_spec('workbench.agent.statistical_claims') is not None, 'Scoped model claims need an evidence owner'
    return importlib.import_module('workbench.agent.statistical_claims')


def provider(tmp_path):
    root = tmp_path / 'project'
    _write_project_run(root)
    path = root / 'runs/run-a/model_results/ols_1.json'
    value = json.loads(path.read_text())
    value['coefficients']['x1'].update(std_error=0.3, p_value=0.001, ci_lower=0.61, ci_upper=1.79)
    path.write_text(json.dumps(value))
    return _load_provider_type()(root), path


@pytest.mark.parametrize('surface', ['main', 'chain'])
def test_real_product_tools_find_the_wrong_n_without_model_self_certification(tmp_path, surface):
    import asyncio
    from workbench.agent.tools import ToolRegistry
    source, _ = provider(tmp_path)
    definitions = (source.global_tool_definitions(session_id='s') if surface == 'main'
                   else source.tool_definitions(chain_id='c', session_id='s'))
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    call = {'tool_call_id': 'wrong-n', 'tool_id': 'check_model_claims', 'arguments': {
        'run_id': 'run-a', 'model_id': 'ols_1', 'claims': [{'field': 'nobs', 'reported': 101}]}}
    result = asyncio.run(registry.execute(call, session_id='s'))
    assert result.ok and result.output['status'] == 'discrepancies'
    assert result.output['checks'][0]['actual'] == 100
    assert result.output['checks'][0]['evidence_ref']['result_ref'] == 'model_results:ols_1'
    other_session = asyncio.run(registry.execute(call, session_id='other'))
    assert not other_session.ok and other_session.output is None


def test_wrong_n_is_localized_to_exact_model_and_real_evidence(tmp_path):
    source, _ = provider(tmp_path)
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[
        {'field': 'nobs', 'reported': 101, 'text': 'The estimation sample contains n = 101 observations.'},
        {'field': 'estimate', 'term': 'x1', 'reported': 1.2},
    ])
    assert result['status'] == 'discrepancies'
    assert result['counts'] == {'match': 1, 'mismatch': 1, 'unverifiable': 0}
    check = result['checks'][0]
    assert check['reported'] == 101 and check['actual'] == 100 and check['status'] == 'mismatch'
    assert check['scope'] == {'run_id': 'run-a', 'model_id': 'ols_1'}
    assert check['evidence_ref'] == {'run_id': 'run-a', 'model_id': 'ols_1', 'result_ref': 'model_results:ols_1'}
    assert check['text'].startswith('The estimation sample')
    assert 'independent' in ' '.join(result['limitations'])
    assert 'causality' in ' '.join(result['limitations'])


def test_all_explicit_coefficient_fields_use_exact_public_raw_values(tmp_path):
    source, _ = provider(tmp_path)
    expected = {'estimate': 1.2, 'std_error': 0.3, 'p_value': 0.001, 'ci_lower': 0.61, 'ci_upper': 1.79}
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[
        {'field': field, 'term': 'x1', 'reported': value} for field, value in expected.items()
    ])
    assert result['status'] == 'provided_claims_match'
    assert all(item['status'] == 'match' and item['actual'] == expected[item['field']] for item in result['checks'])
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[
        {'field': 'estimate', 'term': 'x1', 'reported': 1.2000000000000002},
    ])
    assert result['status'] == 'discrepancies'
    assert result['checks'][0]['actual'] == 1.2


def test_another_run_or_model_with_the_same_number_cannot_rescue_claim(tmp_path):
    source, path = provider(tmp_path)
    _write_project_run(source.project_root, run_id='run-b')
    other_path = source.project_root / 'runs/run-b/model_results/ols_1.json'
    other = json.loads(other_path.read_text())
    other['nobs'] = 101
    other_path.write_text(json.dumps(other))
    same_run_other_model = json.loads(path.read_text())
    same_run_other_model.update(model_id='other_model', nobs=101)
    (path.parent / 'other_model.json').write_text(json.dumps(same_run_other_model))
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[{'field': 'nobs', 'reported': 101}])
    assert result['status'] == 'discrepancies' and result['checks'][0]['actual'] == 100
    missing = api().check_model_claims(source, run_id='run-a', model_id='not_a_model', claims=[{'field': 'nobs', 'reported': 101}])
    assert missing['status'] == 'unverifiable' and missing['checks'][0]['actual'] is None


@pytest.mark.parametrize('scope', [('run-missing', 'ols_1'), ('run-a', 'missing-model')])
def test_missing_scope_is_unverifiable_instead_of_number_search(tmp_path, scope):
    source, _ = provider(tmp_path)
    result = api().check_model_claims(source, run_id=scope[0], model_id=scope[1], claims=[{'field': 'nobs', 'reported': 100}])
    assert result['status'] == 'unverifiable'
    assert result['checks'][0]['actual'] is None and result['checks'][0]['evidence_ref'] is None


def test_duplicate_selected_model_is_unverifiable_even_when_values_agree(tmp_path):
    source, path = provider(tmp_path)
    (path.parent / 'duplicate.json').write_bytes(path.read_bytes())
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[{'field': 'nobs', 'reported': 100}])
    assert result['status'] == 'unverifiable'
    assert result['checks'][0]['reason'] == 'selected_model_ambiguous'


@pytest.mark.parametrize('claim', [
    {'field': 'estimate', 'term': 'X1', 'reported': 1.2},
    {'field': 'estimate', 'term': 'not_present', 'reported': None},
    {'field': 'nobs', 'reported': None},
])
def test_missing_term_or_reported_value_never_passes(tmp_path, claim):
    source, _ = provider(tmp_path)
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[claim])
    assert result['status'] == 'unverifiable' and result['checks'][0]['status'] == 'unverifiable'


@pytest.mark.parametrize('raw', [None, True, float('nan'), float('inf')])
def test_unavailable_or_invalid_public_actual_value_never_passes(tmp_path, raw):
    source, path = provider(tmp_path)
    value = json.loads(path.read_text())
    value['coefficients']['x1']['std_error'] = raw
    path.write_text(json.dumps(value))
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[{'field': 'std_error', 'term': 'x1', 'reported': 0.3}])
    assert result['status'] == 'unverifiable' and result['checks'][0]['actual'] is None


@pytest.mark.parametrize('claim', [
    {'field': 'nobs', 'reported': True}, {'field': 'nobs', 'reported': 100.0},
    {'field': 'estimate', 'term': 'x1', 'reported': False},
    {'field': 'estimate', 'term': 'x1', 'reported': float('nan')},
    {'field': 'estimate', 'term': 'x1', 'reported': float('inf')},
    {'field': 'estimate', 'reported': 1.2},
    {'field': 'unknown', 'reported': 100},
    {'field': 'nobs', 'reported': 100, 'source': {'run_id': 'run-a', 'model_id': 'ols_1'}},
])
def test_invalid_or_self_reported_source_claim_is_rejected_before_provider(tmp_path, claim):
    module = api()
    class NoProvider:
        def inspect_project_model_coefficients(self, request):
            pytest.fail('invalid claims must fail before source access')
    with pytest.raises(module.StatisticalClaimError):
        module.check_model_claims(NoProvider(), run_id='run-a', model_id='ols_1', claims=[claim])


def test_only_requested_run_and_exact_terms_reach_existing_provider(tmp_path):
    source, _ = provider(tmp_path)
    seen = []
    class Observed:
        def inspect_project_model_coefficients(self, request):
            seen.append(request)
            return source.inspect_project_model_coefficients(request)
    result = api().check_model_claims(Observed(), run_id='run-a', model_id='ols_1', claims=[
        {'field': 'nobs', 'reported': 100},
        {'field': 'estimate', 'term': 'x1', 'reported': 1.2},
        {'field': 'ci_upper', 'term': 'x1', 'reported': 1.79},
    ])
    assert result['status'] == 'provided_claims_match'
    assert len(seen) == 1 and seen[0].run_ids == ('run-a',) and seen[0].terms == ('x1',)


def test_missing_or_wrong_scoped_evidence_ref_is_not_fabricated(tmp_path):
    source, _ = provider(tmp_path)
    class WrongReference:
        def inspect_project_model_coefficients(self, request):
            output = source.inspect_project_model_coefficients(request)
            output['models'][0]['evidence_ref']['run_id'] = 'run-b'
            return output
    result = api().check_model_claims(WrongReference(), run_id='run-a', model_id='ols_1', claims=[{'field': 'nobs', 'reported': 100}])
    assert result['status'] == 'unverifiable'
    assert result['checks'][0]['reason'] == 'evidence_scope_mismatch'


def test_empty_claims_do_not_receive_vacuous_pass(tmp_path):
    source, _ = provider(tmp_path)
    with pytest.raises(api().StatisticalClaimError):
        api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[])


@pytest.mark.parametrize('raw', [None, True, 100.0])
def test_missing_or_noninteger_nobs_is_unverifiable_not_an_independent_n_claim(tmp_path, raw):
    source, path = provider(tmp_path)
    value = json.loads(path.read_text())
    value['nobs'] = raw
    path.write_text(json.dumps(value))
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[{'field': 'nobs', 'reported': 100}])
    assert result['checks'][0]['actual'] is None
    assert result['status'] == 'unverifiable'


def test_missing_reported_and_actual_values_are_not_equal_evidence(tmp_path):
    source, path = provider(tmp_path)
    value = json.loads(path.read_text())
    value['coefficients']['x1']['p_value'] = None
    path.write_text(json.dumps(value))
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[{'field': 'p_value', 'term': 'x1', 'reported': None}])
    assert result['status'] == 'unverifiable'
    assert result['checks'][0]['actual'] is result['checks'][0]['reported'] is None


def test_explicit_missing_term_marker_dominates_even_if_a_value_is_present(tmp_path):
    source, _ = provider(tmp_path)
    class MissingTerm:
        def inspect_project_model_coefficients(self, request):
            output = source.inspect_project_model_coefficients(request)
            output['models'][0]['missing_terms'] = ['x1']
            return output
    result = api().check_model_claims(MissingTerm(), run_id='run-a', model_id='ols_1', claims=[{'field': 'estimate', 'term': 'x1', 'reported': 1.2}])
    assert result['status'] == 'unverifiable'
    assert result['checks'][0]['reason'] == 'term_missing'


def test_mixed_matches_and_missing_evidence_do_not_certify_all_claims(tmp_path):
    source, _ = provider(tmp_path)
    result = api().check_model_claims(source, run_id='run-a', model_id='ols_1', claims=[
        {'field': 'nobs', 'reported': 100}, {'field': 'estimate', 'term': 'missing', 'reported': 1.2},
    ])
    assert result['status'] == 'unverifiable'
    assert result['counts'] == {'match': 1, 'mismatch': 0, 'unverifiable': 1}
