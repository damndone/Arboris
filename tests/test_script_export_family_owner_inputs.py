"""Completed public owners retain native estimation input semantics."""
from pathlib import Path

import pytest

from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.script_export.builder import build_script_plan
from test_script_export_executed_parameters import execute_completed_owner


@pytest.fixture(scope='module')
def completed_owners(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp('export-family-inputs'), 'public').root
    fixtures = Path(__file__).parent/'fixtures/admission'
    configurations = {
        'iv_2sls': dict(y='y',x=['x1'],iv_endog=['xe'],iv_instruments=['z'],covariance='robust'),
        'panel_ols': dict(y='y',x=['x1','x2'],entity_col='g',time_col='time'),
    }
    runs = {}
    for family, parameters in configurations.items():
        result = run_workflow(project,[fixtures/family/'data.csv'],mode='auto',model_type=family,**parameters)
        assert result['status'] == 'completed', result
        runs[family] = result['run_id']
    return project,runs


def test_iv_preserves_actual_instrument_and_response_roles(completed_owners):
    project,runs = completed_owners
    model = build_script_plan(project,runs['iv_2sls'],'model:iv_2sls_1').plan.steps[-1]
    assert model.parameters['covariance'] == 'robust'
    assert model.parameters['x'] == ('x1',)
    assert model.parameters['model_options']['endog'] == ('xe',)
    assert model.parameters['model_options']['instruments'] == ('z',)


def test_panel_uses_executed_cluster_and_reference_distribution(completed_owners):
    project,runs = completed_owners
    model = build_script_plan(project,runs['panel_ols'],'model:panel_ols_1').plan.steps[-1]
    assert model.parameters['covariance'] == 'clustered'
    assert model.parameters['cluster'] == 'g'
    assert model.parameters['entity'] == 'g'
    assert model.parameters['time'] == 'time'


@pytest.mark.parametrize('family,distribution,df',[('iv_2sls','z',None),('panel_ols','t',49)])
def test_public_expected_includes_final_statistics_and_reference(completed_owners,family,distribution,df):
    project,runs = completed_owners
    model = build_script_plan(project,runs[family],'model:'+family+'_1').plan.steps[-1]
    assert set(model.expected['statistics']) == set(model.expected['coefficients'])
    for term, statistic in model.expected['statistics'].items():
        assert statistic['distribution'] == distribution
        assert statistic['df'] == df
        assert statistic['value'] == model.expected['coefficients'][term]/model.expected['std_errors'][term]
        assert 0 <= statistic['p_value'] <= 1


@pytest.mark.parametrize('family',['iv_2sls','panel_ols'])
@pytest.mark.parametrize('language',['stata','r','python'])
def test_completed_family_owner_native_self_checks(completed_owners,family,language,monkeypatch):
    project,runs = completed_owners
    execute_completed_owner(project,runs[family],'model:'+family+'_1',language,monkeypatch)
