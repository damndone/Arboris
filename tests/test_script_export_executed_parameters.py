"""Public exports preserve qualified identities and actual weight semantics."""
import json
from pathlib import Path

import pytest
import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.script_export.builder import build_script_plan
from workbench.script_export.render import resolve_exporter

FIXTURES = Path(__file__).parent / 'fixtures'

@pytest.fixture(scope='module')
def qualified_owners(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp('export-qualified'), 'owners').root
    runs = {}
    for family, y in [('binomial', 'yb'), ('poisson', 'yc'), ('negative_binomial', 'ynb')]:
        options = {'alpha': 1.0} if family == 'negative_binomial' else {}
        outcome = run_workflow(project, [FIXTURES/'postestimation/data.csv'], mode='auto',
            model_type='glm:'+family, y=y, x=['x1','x2','x3'], model_options=options)
        assert outcome['status'] == 'completed', outcome
        runs[family] = outcome['run_id']
    return project, runs

@pytest.mark.parametrize('family', ['binomial', 'poisson', 'negative_binomial'])
def test_qualified_kernel_matches_executed_family_without_relabeling(qualified_owners, family):
    project, runs = qualified_owners
    built = build_script_plan(project, runs[family], 'model:glm_1')
    model = built.plan.steps[-1]
    assert model.operation == 'model.glm:'+family
    assert model.parameters['model_options']['family'] == family
    if family == 'negative_binomial':
        assert model.parameters['model_options']['alpha'] == 1.0
    kernel = read_json(project/'runs'/runs[family]/'model_results/inference_kernels/glm_1.json')
    assert model.expected['coefficients'] == dict(zip(kernel['param_names'], kernel['params']))

@pytest.fixture(scope='module')
def weight_owners(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp('export-weight'), 'owners').root
    frame = pd.read_csv(FIXTURES/'survey_fpc_v1811/design.csv')
    frame['frequency'] = 2
    source = project/'weights.csv'; frame.to_csv(source,index=False)
    runs = {}
    for label, fields in [('sampling', {'sampling_weight':'weight','survey_strata_col':'stratum',
                'survey_psu_col':'psu','survey_fpc_col':'population_fpc'}),
            ('analysis', {'analysis_weight':'weight'}), ('frequency', {'frequency_weight':'frequency'})]:
        outcome = run_workflow(project, [source], mode='auto',
            model_type='ols', y='y', x=['x1','x2'], **fields)
        assert outcome['status'] == 'completed', outcome
        runs[label] = outcome['run_id']
    return project, runs

@pytest.mark.parametrize('kind,column', [('sampling','weight'),('analysis','weight'),('frequency','frequency')])
def test_export_never_drops_a_real_executed_weight(weight_owners,kind,column):
    project, runs = weight_owners
    built = build_script_plan(project,runs[kind],'model:ols_1')
    assert dict(built.plan.steps[-1].parameters['weights']) == {'kind':kind,'column':column}
    if kind == 'sampling':
        model = built.plan.steps[-1]
        assert model.parameters['covariance'] == 'survey_design'
        design = model.parameters['model_options']['survey_design']
        assert design['survey_fpc_col'] == 'population_fpc'
        assert design['sampling_weight'] == 'weight'
        assert design['survey_method'] == 'linearization'
        assert design['survey_df'] == 'design'
        assert design['survey_lonely_psu'] == 'fail'
        # Until the independently reviewed FPC adapter is approved, this must
        # clearly continue from a completed result rather than ignore FPC.
        assert resolve_exporter(model,'r').status in {'snapshot','native_with_equivalence_note'}


def execute_completed_owner(project, run_id, target, language, monkeypatch, *, native=True):
    import hashlib
    from workbench.script_export.render import export_script
    from workbench.script_export.result_snapshot import ResultSnapshotRef
    from test_script_export_data_oracles import fresh_directory, execute
    built = build_script_plan(project,run_id,target)
    directory = fresh_directory()
    files = dict(built.files); references = {}
    if not native:
        for step in built.plan.steps:
            if step.kind in {'model','postestimation'} and resolve_exporter(step,language).status == 'snapshot':
                name, raw = built.result_sidecars[step.step_id]
                files[name] = raw
                references[step.step_id] = ResultSnapshotRef(name,hashlib.sha256(raw).hexdigest())
    for name,raw in files.items():
        (directory/name).write_bytes(raw)
    monkeypatch.setenv('PYTHONPATH',str(Path(__file__).resolve().parents[1]/'backend'))
    exported = export_script(built.plan,language,require_native=native,result_snapshots=references)
    code, output = execute(exported,directory,built.plan)
    assert code == 0, output


@pytest.mark.parametrize('language',['stata','r','python'])
@pytest.mark.parametrize('family',['binomial','poisson'])
def test_actual_qualified_glm_runs_in_each_native_language(qualified_owners,family,language,monkeypatch):
    project,runs=qualified_owners
    execute_completed_owner(project,runs[family],'model:glm_1',language,monkeypatch)


@pytest.mark.parametrize('language',['stata','r','python'])
@pytest.mark.parametrize('kind',['analysis','frequency'])
def test_actual_weighted_ols_runs_in_each_native_language(weight_owners,kind,language,monkeypatch):
    project,runs=weight_owners
    execute_completed_owner(project,runs[kind],'model:ols_1',language,monkeypatch)
