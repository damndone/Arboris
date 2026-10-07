"""Independent FPC public-entry review; fixtures and production stay immutable."""
import ast
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.survey.adapters import build_design_from_artifacts, fpc_summary
from workbench.survey.design import SurveyDesign
from workbench.survey.engine import estimate_with_design
from workbench.survey.errors import SurveyEngineError
from workbench.survey.estimator import EstimatorSpec

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures/survey_fpc_v1811'
BASELINE = '699e378749e8d629aa8230ff6ef7ea7269a4f6bb'


def public_run(tmp_path, source='design', **options):
    project = create_project(tmp_path, 'review').root
    path = FIXTURES / f'{source}.csv' if isinstance(source, str) else source
    outcome = run_workflow(project, [path], mode='auto', model_type='ols', y='y', x=['x1', 'x2'],
        sampling_weight='weight', survey_strata_col='stratum', survey_psu_col='psu', **options)
    root = project / 'runs' / outcome['run_id']
    print(json.dumps({'run_root': str(root), 'options': options, 'status': outcome['status']}))
    return outcome, root


def result(root):
    return read_json(root / 'model_results/ols_1.json'), read_json(root / kernel_relative_path('ols_1'))


@pytest.mark.parametrize('column', [False, 0, [], {}, ['population_fpc']])
def test_workflow_does_not_silently_drop_nonstring_fpc(tmp_path, column):
    with pytest.raises(SurveyEngineError) as caught:
        public_run(tmp_path, survey_fpc_col=column)
    assert caught.value.code == 'SURVEY_FPC_COLUMN_INVALID'
    assert not list(tmp_path.glob('review/runs/*/model_results/ols_1.json'))


@pytest.mark.parametrize('column', [False, 0, [], {}, ['population_fpc']])
def test_adapter_validates_column_even_without_weight(column):
    with pytest.raises(SurveyEngineError) as caught:
        build_design_from_artifacts(pd.read_csv(FIXTURES / 'design.csv'), {'_survey_fpc_col': column})
    assert caught.value.code == 'SURVEY_FPC_COLUMN_INVALID'


@pytest.mark.parametrize('replicate', [None, 'brr', 'jackknife', 'bootstrap', 'provided'])
def test_explicit_method_rejection_precedes_refit_and_capability_validation(replicate):
    design = SurveyDesign(pd.read_csv(FIXTURES / 'design.csv'), weight='weight', strata='stratum',
        psu='psu', fpc='population_fpc')
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('No estimator call is allowed')
    estimator = EstimatorSpec(name='review', refit=forbidden)
    with pytest.raises(SurveyEngineError) as caught:
        estimate_with_design(design, estimator, method='replicate', replicate_type=replicate,
            df_convention='invalid_convention')
    assert caught.value.code == 'SURVEY_FPC_REPLICATE_UNSUPPORTED'
    assert calls == []


@pytest.mark.parametrize('case_name,column', [('population', 'population_fpc'), ('fraction', 'fraction_fpc'),
    ('subpopulation', 'population_fpc'), ('subpopulation', 'fraction_fpc')])
def test_public_covariance_and_full_design_metadata_match_native_domain_reference(tmp_path, case_name, column):
    cases = read_json(FIXTURES / 'oracle_reference.json')['cases']
    case = cases[case_name]
    outcome, root = public_run(tmp_path, case['source'], survey_fpc_col=column,
        **({'survey_subpop': 'subpop == 1'} if case['domain'] else {}))
    assert outcome['status'] == 'completed', read_json(root / 'errors.json')
    packet, kernel = result(root)
    np.testing.assert_allclose(kernel['vcov'], case['covariance'], rtol=1e-9, atol=1e-11)
    assert kernel['param_names'] == ['Intercept', 'x1', 'x2']
    for actual_term, native_term in [('Intercept', '(Intercept)'), ('x1', 'x1'), ('x2', 'x2')]:
        actual = packet['coefficients'][actual_term]
        assert actual['estimate'] == pytest.approx(case['coefficients'][native_term], abs=1e-10)
        assert actual['std_error'] == pytest.approx(case['standard_errors'][native_term], rel=1e-9)
        assert actual['p_value'] == pytest.approx(case['p'][native_term], rel=1e-8)
        assert actual['ci_lower'] == pytest.approx(case['ci_lower'][native_term], abs=1e-9)
        assert actual['ci_upper'] == pytest.approx(case['ci_upper'][native_term], abs=1e-9)
    frame = pd.read_csv(FIXTURES / (case['source'] + '.csv'))
    full_counts = frame.groupby('stratum')['psu'].nunique()
    block = packet['survey_design']['fpc']
    assert packet['survey_design']['n_psu'] == int(full_counts.sum())
    rows = {row['stratum']: row for row in block['strata']}
    assert set(rows) == set(full_counts.index)
    for stratum, count in full_counts.items():
        value = float(frame.loc[frame.stratum == stratum, column].iloc[0])
        fraction = value if value <= 1 else count / value
        assert rows[stratum]['sampled_psus'] == count
        assert rows[stratum]['sampling_fraction'] == fraction
        assert rows[stratum]['variance_factor'] == 1 - fraction
        if value > 1:
            assert rows[stratum]['population_psus'] == value
    if case['domain']:
        domain_counts = frame.loc[frame.subpop == 1].groupby('stratum')['psu'].nunique()
        assert not domain_counts.equals(full_counts), 'Fixture must distinguish full versus domain design'
    from workbench.agent.context_tools import _bounded_survey_design
    assert _bounded_survey_design([packet])['fpc'] == block
    json.dumps(packet, allow_nan=False)
    json.dumps(kernel, allow_nan=False)


@pytest.mark.parametrize('source', ['design', 'subpop'])
def test_no_fpc_public_packet_and_kernel_exactly_match_699_function(tmp_path, monkeypatch, source):
    from workbench.engine.stages import estimation
    options = {'survey_subpop': 'subpop == 1'} if source == 'subpop' else {}
    current_outcome, current_root = public_run(tmp_path / 'current', source, **options)
    assert current_outcome['status'] == 'completed'
    code = subprocess.check_output(['git', 'show', BASELINE + ':backend/workbench/engine/stages/estimation.py'],
        cwd=ROOT, text=True)
    tree = ast.parse(code)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name == '_apply_survey_design_variance')
    namespace = dict(estimation.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '699_estimation.py', 'exec'), namespace)
    monkeypatch.setattr(estimation, '_apply_survey_design_variance', namespace['_apply_survey_design_variance'])
    old_outcome, old_root = public_run(tmp_path / 'baseline', source, **options)
    assert old_outcome['status'] == 'completed'
    actual_packet, actual_kernel = result(current_root)
    old_packet, old_kernel = result(old_root)
    assert actual_packet == old_packet
    assert actual_kernel == old_kernel
    assert 'fpc' not in actual_packet['survey_design']


def test_census_public_kernel_and_agent_coefficients_do_not_invent_inference(tmp_path):
    from workbench.agent.context_tools import _bounded_persisted_model_facts
    frame = pd.read_csv(FIXTURES / 'design.csv')
    frame['review_census'] = 1.0
    source = tmp_path / 'census.csv'; frame.to_csv(source, index=False)
    outcome, root = public_run(tmp_path / 'projects', source, survey_fpc_col='review_census')
    assert outcome['status'] == 'completed'
    packet, kernel = result(root)
    assert np.count_nonzero(np.asarray(kernel['vcov'])) == 0
    projected = _bounded_persisted_model_facts([packet], root)[0]
    for row in projected['coefficients']:
        assert row['std_error'] == 0 and row['p_value'] is None
        assert row['ci_lower'] == row['estimate'] == row['ci_upper']
    assert any(warning.get('code') == 'SURVEY_ZERO_VARIANCE_INFERENCE_UNAVAILABLE'
        for warning in packet['warnings'] if isinstance(warning, dict))
    for asset in [packet, kernel, projected, read_json(root / 'errors.json')]:
        json.dumps(asset, allow_nan=False)
    print(json.dumps({'census_public_warnings': packet['warnings'], 'shared_issues': read_json(root / 'errors.json')}))


def test_domain_absent_strata_metadata_keeps_full_population_structure():
    frame = pd.read_csv(FIXTURES / 'subpop.csv')
    frame['review_domain'] = frame['stratum'] == frame.stratum.iloc[0]
    design = SurveyDesign(frame, weight='weight', strata='stratum', psu='psu', fpc='population_fpc',
        subpop='review_domain == True')
    summary = fpc_summary(design)
    assert len(summary['strata']) == frame.stratum.nunique()
    assert sum(row['sampled_psus'] for row in summary['strata']) == design.n_psu
    assert all(row['variance_factor'] == 1-row['sampled_psus']/row['population_psus']
        for row in summary['strata'])
