"""The completion gate binds what follows from verified products; the Agent keeps the choices.

Each case is a failure from the paid v1.9.1 Ask round (candidate-small-20261021),
on real native Cox fits: two distinct specifications and a report covering them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_agent_completion_survival import build_native_products
from workbench.agent.completion import derive_evidence, evaluate

FAMILIES = Path(__file__).parent / 'fixtures/v186_families/families.csv'


@pytest.fixture(scope='module')
def products(tmp_path_factory):
    return build_native_products(tmp_path_factory.mktemp('binding'), FAMILIES)


def _check(project, contract, evidence):
    derived, notes = derive_evidence(project, contract, evidence)
    return evaluate(project, contract, derived), derived, notes


def test_correct_evidence_is_kept_as_given(products):
    project, contract, evidence = products
    checked, derived, notes = _check(project, contract, evidence)
    assert checked['status'] == 'requirements_met', checked['missing']
    assert derived['models'] == evidence['models'] and derived['report'] == evidence['report']
    assert notes['dropped'] == []


def test_naming_the_primary_is_enough(products):
    project, contract, evidence = products
    checked, derived, notes = _check(project, contract, {'models': evidence['models']})
    assert checked['status'] == 'requirements_met', checked['missing']
    assert {'diagnostics', 'sensitivity', 'report'} <= set(notes['bound_by_workbench'])


def test_several_distinct_fits_stay_the_agents_choice(products):
    project, contract, _ = products
    checked, derived, notes = _check(project, contract, None)
    assert 'survival:model:survival_cox' in checked['missing']
    assert len(notes['primary_candidates']['survival']) == 2
    assert all(c['terms'] for c in notes['primary_candidates']['survival'])


def test_invented_ids_and_a_report_collection_are_dropped_and_named(products):
    project, contract, evidence = products
    main = evidence['models'][0]['run_id']
    given = {'models': [{'run_id': main, 'artifact_id': f'{main}:cleaned_dataset'}, *evidence['models']],
             'report': {'run_id': main, 'artifact_id': 'collection'}}
    checked, derived, notes = _check(project, contract, given)
    assert checked['status'] == 'requirements_met', checked['missing']
    assert {'models': {'run_id': main, 'artifact_id': f'{main}:cleaned_dataset'}} in notes['dropped']
    assert {'report': {'run_id': main, 'artifact_id': 'collection'}} in notes['dropped']
    assert derived['report'] == evidence['report']


def test_several_named_fits_mean_first_primary_then_alternatives(products):
    project, contract, evidence = products
    both = [*evidence['models'], *evidence['sensitivity']]
    checked, derived, _ = _check(project, contract, {'models': both})
    assert checked['status'] == 'requirements_met', checked['missing']
    assert derived['models'] == evidence['models'] and derived['sensitivity'] == evidence['sensitivity']


def test_reruns_of_one_specification_are_not_a_choice_and_give_no_comparison(tmp_path):
    project, contract, _ = build_native_products(tmp_path, FAMILIES, specifications=[['x1', 'grp'], ['x1', 'grp']])
    checked, derived, notes = _check(project, contract, None)
    assert 'survival:primary' in notes['bound_by_workbench'] and not notes['primary_candidates']
    assert checked['missing'] == ['survival:sensitivity:distinct_point_estimation']


def test_without_a_covering_report_the_exact_compose_step_is_given(products, tmp_path):
    import shutil
    project, contract, evidence = products
    copy = tmp_path / 'copy'
    shutil.copytree(project, copy)
    main = evidence['models'][0]['run_id']
    index = copy / 'runs' / main / 'artifacts_index.json'
    import json
    value = json.loads(index.read_text())
    value['artifacts'] = [a for a in value['artifacts'] if a['artifact_type'] != 'report']
    index.write_text(json.dumps(value))
    checked, derived, notes = _check(copy, contract, {'models': evidence['models']})
    assert 'report:registered_nonempty' in checked['missing']
    refs = notes['compose_report']['spec']['result_refs']
    assert notes['compose_report']['operation_id'] == 'report.compose'
    assert {'role': 'primary', **evidence['models'][0]} in refs
    assert {r['role'] for r in refs} == {'primary', 'diagnostic', 'sensitivity'}
