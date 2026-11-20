"""Native Cox PH diagnostics and completion; all calls are local/offline."""
from __future__ import annotations

import importlib
import json
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from statsmodels.duration.hazard_regression import PHReg


def diagnostic():
    assert importlib.util.find_spec('workbench.engine.packs.survival_analysis.ph_diagnostics') is not None
    return importlib.import_module('workbench.engine.packs.survival_analysis.ph_diagnostics').ph_score_test


@pytest.mark.parametrize('ties', ['breslow', 'efron'])
def test_balanced_small_risk_sets_have_hand_checked_zero_score_and_information(ties):
    result = diagnostic()(np.array([1., 1., 2., 2., 3., 3.]), np.array([1, 1, 1, 1, 0, 0]),
        np.array([[0.], [1.], [0.], [1.], [0.], [1.]]), np.array([0.]), ['x'], ties=ties)
    assert result['status'] == 'computed'
    assert result['global']['statistic'] == pytest.approx(0., abs=1e-14)
    assert result['global']['p_value'] == 1.
    with localcontext() as context:
        context.prec = 50
        information = float(Decimal(2).ln() ** 2 / 4)
    assert result['efficient_information'][0][0] == pytest.approx(information, rel=1e-14)


@pytest.mark.parametrize('case', ['untied_breslow', 'untied_efron', 'tied_breslow', 'tied_efron'])
def test_cox_ph_score_matches_native_survival_cox_zph(case):
    root = Path(__file__).parent / 'fixtures/agent_completion/survival'
    oracle = json.loads((root / 'ph_reference_r.json').read_text())
    info = oracle['cases'][case]
    frame = pd.read_csv(info['source'])
    columns = ['x1', 'x2', 'grp']
    fitted = PHReg(frame.duration, frame[columns], status=frame.event, ties=info['ties']).fit()
    result = diagnostic()(frame.duration.to_numpy(), frame.event.to_numpy(), frame[columns].to_numpy(),
                          fitted.params, columns, ties=info['ties'])
    assert result['status'] == 'computed'
    for key in [*columns, 'global']:
        for quantity in ['statistic', 'p_value']:
            assert result[key][quantity] == pytest.approx(info['tests'][key][quantity], rel=1e-7, abs=1e-9)


def test_delayed_entry_is_explicitly_unverified_and_never_substituted():
    result = diagnostic()(np.array([1., 2., 3.]), np.array([1, 1, 0]), np.array([[0.], [1.], [2.]]),
        np.array([0.]), ['x'], ties='breslow', entry=np.array([0., 0., 1.]))
    assert result['status'] == 'unverified' and result['reason'] == 'delayed_entry_not_validated'


def build_native_products(root, source, outcome='duration', specifications=None):
    from workbench.projects import create_project
    from workbench.orchestrator import run_workflow
    from workbench.reporting import render_html_report
    from tests.test_agent_completion import artifact
    project = create_project(root, 'cox')
    runs = []
    for columns in specifications or [['x1', 'x2', 'grp'], ['x1', 'grp']]:
        result = run_workflow(project.root, [source], mode='auto', model_type='survival_cox',
                              y=outcome, x=columns, model_options={'event_column': 'event', 'ties': 'breslow'})
        assert result['status'] == 'completed', result
        runs.append(result['run_id'])
    main, alternate = runs
    source_path = project.root / 'runs' / main / 'processed/cleaned_dataset.parquet'
    import hashlib
    contract = {'playbooks': ['survival'], 'source': {'run_id': main, 'artifact_id': 'cleaned_dataset',
                                                   'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()}}
    evidence = {'models': [{'run_id': main, 'artifact_id': 'survival_cox_1'}],
        'diagnostics': [{'run_id': main, 'artifact_id': 'survival_cox_1.completion'}],
        'sensitivity': [{'run_id': alternate, 'artifact_id': 'survival_cox_1'}],
        'report': {'run_id': main, 'artifact_id': 'report'}}
    artifact(project.root, main, 'collection', 'report_collection', {
        'schema_version': 'workflow-report-collection.v1', 'status': 'completed', 'steps': {
        'primary': {'status': 'completed', 'artifact_ids': [f'{main}:survival_cox_1', f'{main}:survival_cox_1.completion',
                                                         f'{alternate}:survival_cox_1']}}})
    render_html_report({'title': 'Cox analysis', 'facts': [], 'claims': [], 'warnings': [], 'descriptive_stats': []},
        project.root / 'runs' / main, artifact_id='report', inputs=['collection'])
    return project.root, contract, evidence


@pytest.fixture(scope='module')
def native_products(tmp_path_factory):
    return build_native_products(tmp_path_factory.mktemp('completion-cox'),
        Path(__file__).parent / 'fixtures/v186_families/families.csv')


def test_native_cox_completion_uses_actual_ph_test_and_changed_fitted_specification(native_products):
    from workbench.agent.completion import evaluate
    project, contract, evidence = native_products
    checked = evaluate(project, contract, evidence)
    assert checked['status'] == 'requirements_met', checked['missing']
    assert checked['scientific_validity'] == 'not_certified'
    repeated = {**evidence, 'sensitivity': evidence['models']}
    assert 'survival:sensitivity:distinct_point_estimation' in evaluate(project, contract, repeated)['missing']
    missing = {**evidence, 'diagnostics': []}
    assert any(m.startswith('survival:diagnostics:') for m in evaluate(project, contract, missing)['missing'])


def test_rejected_ph_and_unverified_entry_remain_explicit_completion_gaps():
    from workbench.agent.completion_profiles import native_findings
    rejected = {'diagnostics': {'proportional_hazards': {'status': 'computed', 'global': {'p_value': .001}}}}
    assert native_findings('survival', [rejected]) == ['survival:diagnostics:ph_rejected_requires_model_revision']
    unsupported = {'diagnostics': {'proportional_hazards': {'status': 'unverified', 'reason': 'delayed_entry_not_validated'}}}
    assert native_findings('survival', [unsupported]) == ['survival:diagnostics:delayed_entry_not_validated']


def test_companion_cannot_be_reused_after_primary_result_changes(native_products, tmp_path):
    import hashlib
    import shutil
    from workbench.agent.completion import evaluate
    project, contract, evidence = native_products
    copy = tmp_path / 'copy'
    shutil.copytree(project, copy)
    run = copy / 'runs' / contract['source']['run_id']
    path = run / 'model_results/survival_cox_1.json'
    value = json.loads(path.read_text())
    value['coefficients']['x1']['estimate'] += 1
    path.write_text(json.dumps(value))
    index_path = run / 'artifacts_index.json'
    index = json.loads(index_path.read_text())
    next(a for a in index['artifacts'] if a['artifact_id'] == 'survival_cox_1')['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    checked = evaluate(copy, contract, evidence)
    assert checked['status'] == 'partial' and 'survival:model:survival_cox' in checked['missing']


@pytest.mark.parametrize('case', ['untied_breslow', 'untied_efron', 'tied_breslow', 'tied_efron'])
def test_native_cox_coefficients_and_uncertainty_match_stata(case):
    root = Path(__file__).parent / 'fixtures/agent_completion/survival'
    reference = pd.read_csv(root / 'cox_reference_stata.csv')
    info = json.loads((root / 'ph_reference_r.json').read_text())['cases'][case]
    frame = pd.read_csv(info['source'])
    names = ['x1', 'x2', 'grp']
    fit = PHReg(frame.duration, frame[names], status=frame.event, ties=info['ties']).fit()
    selected = reference[reference['case'] == case]
    assert list(selected['term']) == names
    np.testing.assert_allclose(fit.params, selected['estimate'], rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(fit.bse, selected['std_error'], rtol=1e-7, atol=1e-9)


def test_m0_survival_failure_can_be_followed_by_real_native_cox_analysis_offline(tmp_path):
    from workbench.agent.completion import evaluate
    source = next((Path(__file__).parent / 'fixtures/agent_completion/survival.goal.r1/project/runs').glob('*/raw_snapshot/survival.csv'))
    project, contract, evidence = build_native_products(tmp_path, source, outcome='months',
                                                      specifications=[['drug', 'age'], ['drug']])
    checked = evaluate(project, contract, evidence)
    # Keep an assumption failure if the actual data show one; never manufacture
    # a scientific pass to satisfy a completion target.
    assert not any(':model:' in m or ':sensitivity:' in m or m.startswith('report:') for m in checked['missing'])
    assert checked['missing'] in [[], ['survival:diagnostics:ph_rejected_requires_model_revision']]
    run = project / 'runs' / evidence['models'][0]['run_id']
    native = json.loads((run / 'model_results/survival_cox_1.completion.json').read_text())
    assert native['diagnostics']['proportional_hazards']['status'] == 'computed'
    assert native['nobs'] == 600


def test_seeded_ph_size_and_nonph_power_with_frozen_monte_carlo_budget():
    # Fixed before execution: 200 null replicates, 60 alternatives, n=400,
    # alpha=.05; null MCSE at nominal size .0154. No failed fit is discarded.
    rng = np.random.default_rng(20261020)
    rejected = [0, 0]
    replicates = [200, 60]
    for alternative, count in enumerate(replicates):
        for _ in range(count):
            n = 400
            group = rng.integers(0, 2, n)
            latent = -np.log(rng.uniform(size=n))
            if alternative:
                treated = np.where(latent <= 1.8, latent / 3, .6 + (latent - 1.8) / .1)
                death = np.where(group == 1, treated, latent)
            else:
                death = latent / np.exp(.4 * group)
            censor = rng.uniform(.5, 5, n)
            time, event = np.minimum(death, censor), (death <= censor).astype(int)
            design = group[:, None].astype(float)
            fitted = PHReg(time, design, status=event, ties='breslow').fit()
            result = diagnostic()(time, event, design, fitted.params, ['group'], ties='breslow')
            assert result['status'] == 'computed'
            rejected[alternative] += result['global']['p_value'] < .05
    assert .005 <= rejected[0] / replicates[0] <= .11, rejected
    assert rejected[1] / replicates[1] >= .8, rejected


def test_cox_oracle_inputs_versions_commands_and_outputs_are_content_bound():
    import hashlib
    root = Path(__file__).parent / 'fixtures/agent_completion/survival'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, digest in manifest['repository_files'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
    assert manifest['ph_oracle'] == 'R survival::cox.zph(transform=log, terms=FALSE)'
    assert manifest['tolerance'] == {'rtol': 1e-7, 'atol': 1e-9}
