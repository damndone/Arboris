"""Reviewer citations are checked by what they point to: a packet key or a path inside one.

Exact-key matching discarded 6 of 10 recorded reviews (paid pass-back round,
panel_fe.specific) because they cited e.g. plan.criteria[2]; one of them was the
finding that exposed the panel time-effects bug.
"""
import json

import pytest

from workbench.agent.research_review import _parse, _supplied

KEYS = ['plan', 'candidate', 'source', 'completion', 'model:0', 'model:1', 'diagnostic:0']


@pytest.mark.parametrize('ref', [
    'plan', 'model:1', 'plan.criteria[2]', 'completion.verified_artifacts[0]',
    'diagnostic:0.summary.diagnostics.panel.absorbed_parameter_rank', 'plan[0]',
])
def test_a_key_or_a_path_inside_it_is_supplied_evidence(ref):
    assert _supplied(ref, KEYS)


@pytest.mark.parametrize('ref', [
    'models', 'models[0]', 'run:20261022_111353_820833_86804463', 'model:2', 'model:10',
    'planned', 'plan_criteria', 'diagnostic:01', 'sourcecode.x', '',
])
def test_anything_the_packet_does_not_hold_is_refused(ref):
    assert not _supplied(ref, KEYS)


def _review(*refs):
    return json.dumps({'verdict': 'issues_found', 'findings': [
        {'severity': 'blocking', 'message': 'Criterion 3 has no supporting fit.', 'evidence_refs': list(refs)}]})


def test_a_review_citing_paths_inside_supplied_evidence_is_accepted():
    result = _parse(_review('plan.criteria[2]', 'diagnostic:0.summary.n_entities'), KEYS)
    assert result['verdict'] == 'issues_found'


def test_one_outside_reference_still_makes_the_review_unverified():
    result = _parse(_review('plan.criteria[2]', 'run:20261022_111353_820833_86804463'), KEYS)
    assert result == {'verdict': 'unverified', 'findings': [],
                      'reason': 'inconsistent_verdict_or_unknown_evidence_reference'}


def test_a_citation_by_the_evidence_own_identity_is_supplied():
    from workbench.agent.research_review import _packet_values

    packet = {'plan': {'plan_id': 'plan_eda232411058'}, 'source': {'sha256': 'a' * 64, 'run_id': '20261022_152633_388180_9d1cbd1c'},
              'completion': {'verified_artifacts': [{'artifact_id': 'survival_cox_1.completion', 'run_id': '20261022_152904_897303_6d53c957'}]}}
    values = _packet_values(packet)
    for ref in ('survival_cox_1.completion', 'plan_eda232411058', 'a' * 64, 'observations.candidate',
                'cleaned_dataset@20261022_152633_388180_9d1cbd1c'.replace('cleaned_dataset', 'survival_cox_1.completion'),
                'plan:plan_eda232411058'):
        assert _supplied(ref, KEYS, values), ref
    for ref in ('cleaned_dataset@20261022_000000_000000_deadbeef', 'run:20261022_111353_820833_86804463', 'models[0]'):
        assert not _supplied(ref, KEYS, values), ref
