"""Persisted isolated reviews are reproducible report evidence, not authority."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.test_agent_completion_time_series import products, series
from tests.test_agent_core_restart import setup
from workbench.agent.completion import evaluate
from workbench.agent.model import ModelStreamEvent
from workbench.agent.plans import Plan
from workbench.agent.research_review import build_context, restore_phase
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor


@pytest.fixture
def reviewed(tmp_path, request):
    project, contract, evidence = products(tmp_path, series())
    if getattr(request, 'param', None) == 'cross_run':
        import shutil
        from workbench.artifacts import read_json, write_json, register_artifact
        original = project / 'runs' / contract['source']['run_id']
        source = project / 'runs/source-only'
        source.mkdir()
        shutil.copy2(original / 'data.csv', source / 'data.csv')
        graph = read_json(original / 'graph.json')
        graph['run_id'] = source.name
        write_json(source / 'graph.json', graph)
        write_json(source / 'artifacts_index.json', {'schema_version':1, 'artifacts':[]})
        register_artifact(source, 'source_data', source / 'data.csv', 'raw_data', 'ingestion', [])
        contract = {**contract, 'source':{**contract['source'], 'run_id':source.name}}
    plan = Plan(plan_id='p', version=1, status='approved', question='Forecast the observed series',
        criteria=('Disclose limitations',), steps=(), allowed_classes=(),
        completion=contract, completion_evidence=evidence)
    class Adapter:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            yield ModelStreamEvent.text_delta(request.request_id, json.dumps({
                'verdict': 'issues_found', 'findings': [{'severity': 'warning',
                    'message': '保留限制：Do not infer <causality> from this forecast.',
                    'evidence_refs': ['plan', 'candidate']}]}))
            yield ModelStreamEvent.done(request.request_id)
    adapter = Adapter()
    core, _, repo = setup(project, adapter)
    repo.append('session-a', 'message', {'role':'assistant', 'content':'Analysis complete.', 'stop_reason':'stop'})
    core.research_review_mode = lambda: 'ask'
    core.completion_check = lambda: evaluate(project, contract, evidence)
    core.research_review_context = lambda candidate: build_context(project, plan, mode='ask', candidate=candidate,
        config=SimpleNamespace(provider_id='offline', base_url='http://127.0.0.1', data_location='remote'))
    core.phase_restorer = lambda checkpoint: restore_phase(core, checkpoint)
    asyncio.run(core.prompt('/review', budget={'max_steps':1, 'timeout_s':30}))
    [result] = [entry.payload for entry in repo.get_branch('session-a') if entry.entry_type == 'research_review_result']
    assert result['verdict'] == 'issues_found'
    return project, contract, evidence, repo, adapter, result


def compose(reviewed, *, workflow='review-report', target=None):
    project, contract, _, _, _, result = reviewed
    draft = compile_workflow(workflow_id=workflow, target={**(target or contract['source']), 'node_ref':'stage:source'},
        preconditions={'context_fingerprint':'report-source'}, steps=[{
            'step_id':'report', 'operation_id':'report.compose', 'spec':{
                'research_review': {'session_id':'session-a', 'review_id':result['review_id']}}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    run = project / 'runs' / draft.target['run_id']
    return state, run


def test_common_report_path_exports_original_review_without_a_model_or_changing_old_report(reviewed):
    project, contract, _, repo, adapter, result = reviewed
    run = project / 'runs' / contract['source']['run_id']
    original_report = (run / 'reports/report.html').read_bytes()
    state, run = compose(reviewed)
    assert state.status == 'completed', state.to_dict()
    collection = json.loads((run / 'artifacts/statistical_exploration/review-report.json').read_text())
    review = collection['research_review']
    assert review['result'] == result
    assert review['evidence_status'] == 'unchanged'
    assert review['independent_numerical_oracle'] is False
    assert review['session_id'] == 'session-a'
    assert review['packet_sha256'] == result['packet_sha256']
    html = (run / 'reports/review-report.html').read_text()
    assert 'Isolated research review' in html and '保留限制' in html
    assert '&lt;causality&gt;' in html and '<causality>' not in html
    pdf = (run / 'reports/review-report.pdf').read_bytes()
    assert b'Isolated research review' in pdf and b'/FontFile2' in pdf
    from openpyxl import load_workbook
    book = load_workbook(run / 'exports/review-report.xlsx', data_only=True)
    values = list(book['research_review'].values)
    assert any(result['review_id'] in row for row in values)
    assert any('保留限制' in str(value) for row in values for value in row)
    assert (run / 'reports/report.html').read_bytes() == original_report
    assert adapter.calls == 1
    before = (run / 'artifacts/statistical_exploration/review-report.json').read_bytes()
    repeated, _ = compose(reviewed)
    assert repeated.status == 'completed'
    assert before == (run / 'artifacts/statistical_exploration/review-report.json').read_bytes()
    assert adapter.calls == 1


def test_changed_evidence_keeps_the_original_verdict_but_marks_it_historical(reviewed):
    project, contract, evidence, _, adapter, result = reviewed
    run = project / 'runs' / contract['source']['run_id']
    # An actual old report changes after review; its original review is retained,
    # but no longer certifies the current evidence packet.
    with (run / 'reports/report.html').open('a') as handle:
        handle.write('\nChanged after review.')
    state, run = compose(reviewed)
    assert state.status == 'completed', state.to_dict()
    review = json.loads((run / 'artifacts/statistical_exploration/review-report.json').read_text())['research_review']
    assert review['evidence_status'] == 'changed_or_unavailable'
    assert review['result'] == result
    assert review['result']['verdict'] == 'issues_found'
    assert 'changed_or_unavailable' in (run / 'reports/review-report.html').read_text()
    assert adapter.calls == 1


def test_wrong_source_review_refuses_the_report_instead_of_attaching_unrelated_opinions(reviewed):
    from workbench.artifacts import register_artifact
    project, contract, _, _, _, _ = reviewed
    run = project / 'runs' / contract['source']['run_id']
    other = run / 'other.csv'
    other.write_text('time,y\n1,99\n2,98\n')
    register_artifact(run, 'other', other, 'raw_data', 'ingestion', [])
    from workbench.artifacts import read_json, write_json
    graph = read_json(run / 'graph.json')
    graph['nodes']['stage:source']['payload_ref'] = 'other.csv'
    write_json(run / 'graph.json', graph)
    state, _ = compose(reviewed, target={**contract['source'], 'artifact_id':'other'})
    assert state.status == 'failed'
    assert 'source' in state.steps['report'].error.lower()
    assert not (run / 'reports/review-report.html').exists()


@pytest.mark.parametrize('reviewed', ['cross_run'], indirect=True)
def test_review_report_preserves_verified_result_ancestry_across_runs(reviewed):
    project, contract, evidence, _, _, _ = reviewed
    state, run = compose(reviewed)
    assert state.status == 'completed', state.to_dict()
    assert run.name != evidence['models'][0]['run_id']
    check = evaluate(project, contract, {**evidence,
        'report':{'run_id':run.name, 'artifact_id':'workflow_report_review-report_html'}})
    assert check['status'] == 'requirements_met', check['missing']
