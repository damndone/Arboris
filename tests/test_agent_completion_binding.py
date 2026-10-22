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


def test_a_named_report_that_misses_selected_results_is_returned_with_what_it_lacks(products, tmp_path):
    # Free-route no-thinking round (iv_weak): a usable but non-covering named report was kept,
    # 'report:result_sources' stayed missing and the model never learned which results it lacked.
    import shutil
    from tests.test_agent_completion import artifact
    from workbench.reporting import render_html_report

    project, contract, evidence = products
    copy = tmp_path / 'copy'
    shutil.copytree(project, copy)
    main = evidence['models'][0]['run_id']
    artifact(copy, main, 'partial_collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed', 'steps': {
            'primary': {'status': 'completed', 'artifact_ids': [f'{main}:survival_cox_1']}}})
    render_html_report({'title': 'Partial', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
                       copy / 'runs' / main, filename='partial.html', artifact_id='partial_report', inputs=['partial_collection'])
    named = {**evidence, 'report': {'run_id': main, 'artifact_id': 'partial_report'}}
    checked, derived, notes = _check(copy, contract, named)
    [dropped] = [d for d in notes['dropped'] if 'report' in d]
    assert dropped['report']['artifact_id'] == 'partial_report'
    assert evidence['sensitivity'][0] in dropped['does_not_cover']
    # The covering report is bound instead, so the plan completes.
    assert derived['report'] == evidence['report'] and checked['status'] == 'requirements_met', checked['missing']
