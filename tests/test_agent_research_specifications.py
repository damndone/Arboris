"""Strict before-results specification evidence through the real operation path."""
import json
from pathlib import Path

import pytest

from tests.test_read_only_analysis import _Fixture, _t_test
from workbench import analysis_ledger
from workbench.agent.plans import PlanStore, merge, PlanStep
from workbench.agent.plan_control import PlanControl
from workbench.artifacts import sha256_file, write_json


def prepared(tmp_path):
    fixture=_Fixture(tmp_path)
    run=fixture.project_root/'runs'/fixture.run_id
    write_json(run/'run_inputs.json',{'upload':{'sha256':sha256_file(run/'data.csv')}})
    draft=merge(None,question='Does mean wage differ by group?',criteria=['Report both estimate and uncertainty.'],
        steps=(PlanStep('tests','Compare groups',('test.t_tests',)),),allowed_classes=None,budget={'steps':8})
    PlanStore(fixture.repository.root).save('chain-session',draft)
    PlanControl(fixture.project_root,fixture.repository,'chain-session').approve(draft.version)
    return fixture


def action_rows(root):
    return [entry for entry in analysis_ledger.read(root) if entry.get('record_id')]


def test_plan_approval_alone_does_not_certify_a_model_but_a_precise_first_request_can(tmp_path):
    fixture=prepared(tmp_path)
    assert not any(entry.get('event_type')=='specification_status' for entry in analysis_ledger.read(fixture.project_root))
    result=fixture.propose([_t_test('primary')])
    assert result['operation']['status']=='completed',result
    proof=fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']
    assert proof['specification_status']=='pre_specified'
    assert proof['question_id']
    [fixed]=[entry for entry in analysis_ledger.read(fixture.project_root) if entry.get('event_type')=='specification_status']
    assert fixed['proposal_revision']==1 and fixed['proposal_fingerprint']==fixture.orchestrator.operation_store.get(result['operation']['record_id']).proposal_fingerprint
    assert fixed['criteria_event_id']
    assert action_rows(fixture.project_root)[0]['specification_status']=='pre_specified'


def test_one_precise_multi_step_request_fixes_all_specifications_before_the_first_result(tmp_path):
    fixture=prepared(tmp_path)
    result=fixture.propose([_t_test('primary'),_t_test('sensitivity')])
    assert result['operation']['status']=='completed',result
    proof=fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']
    assert proof['specification_status']=='pre_specified'
    assert proof['step_ids']==['primary','sensitivity']


def test_new_specification_after_results_is_exploratory_even_under_the_same_approved_plan(tmp_path):
    fixture=prepared(tmp_path)
    fixture.propose([_t_test('first')])
    result=fixture.propose([_t_test('after-reading')])
    assert fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']['specification_status']=='exploratory'
    assert 'prior_result' in fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']['reason']
    assert len(action_rows(fixture.project_root))==2


def test_old_analysis_without_before_results_evidence_stays_explicitly_unverified(tmp_path):
    fixture=_Fixture(tmp_path)
    result=fixture.propose([_t_test('legacy')])
    proof=fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']
    assert proof['specification_status']=='exploratory'
    assert proof['verification']=='unverified'
    assert action_rows(fixture.project_root)[0]['specification_status']=='exploratory'


def test_existing_result_artifacts_prevent_retroactive_prespecification_without_a_ledger_entry(tmp_path):
    from workbench.artifacts import register_artifact
    fixture=prepared(tmp_path)
    run=fixture.project_root/'runs'/fixture.run_id
    write_json(run/'old-model.json',{'coefficients':{'x':{'estimate':0.2}}})
    register_artifact(run,'old-model',run/'old-model.json','model_result','estimation',[])
    result=fixture.propose([_t_test('late-plan')])
    assert fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']['specification_status']=='exploratory'
    assert 'prior_result' in fixture.orchestrator.operation_store.get(result['operation']['record_id']).execution['research_specification']['reason']


def test_replaying_a_frozen_decision_after_results_does_not_reclassify_or_duplicate_it(tmp_path):
    from workbench.research_specifications import freeze_operation
    fixture=prepared(tmp_path)
    result=fixture.propose([_t_test('primary')])
    record=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    original=list(analysis_ledger.read(fixture.project_root))
    assert freeze_operation(fixture.project_root,record,fixture.orchestrator.plan_store.current('chain-session'),
        first_dispatch=False)==record.execution['research_specification']
    assert analysis_ledger.read(fixture.project_root)==original


def test_a_restart_without_a_preexecution_snapshot_cannot_backfill_a_positive_label(tmp_path):
    from workbench.research_specifications import freeze_operation
    fixture=prepared(tmp_path)
    result=fixture.propose([_t_test('primary')])
    record=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    from dataclasses import replace
    legacy=replace(record,record_id='old-unrecorded-operation')
    proof=freeze_operation(fixture.project_root,legacy,fixture.orchestrator.plan_store.current('chain-session'),first_dispatch=False)
    assert proof['specification_status']=='exploratory' and proof['verification']=='unverified'


def test_report_exports_separate_prespecified_and_exploratory_analyses_with_evidence_refs(tmp_path):
    from openpyxl import load_workbook
    fixture=prepared(tmp_path)
    fixture.propose([_t_test('primary')])
    result=fixture.propose([_t_test('exploratory'),{
        'step_id':'report','operation_id':'report.compose','depends_on':['exploratory'],'spec':{}}])
    assert result['requires_confirmation'] is True
    from tests.test_read_only_analysis import FINGERPRINT
    import asyncio
    proposal=result['proposal']
    record=fixture.orchestrator.confirm_proposal(proposal['proposal_id'],revision=proposal['revision'],
        fingerprint=proposal['fingerprint'],actor_type='user',current_context_fingerprint=FINGERPRINT,
        current_active_head_run_id=fixture.run_id)
    record=asyncio.run(fixture.orchestrator.execute_confirmed_operation(record.record_id,
        project_root=fixture.project_root,current_context_fingerprint=FINGERPRINT,current_active_head_run_id=fixture.run_id))
    assert record.status=='completed',record.to_dict()
    run=fixture.project_root/'runs'/fixture.run_id
    workflow=record.execution['workflow_id']
    html=(run/'reports'/f'{workflow}.html').read_text()
    assert 'Pre-specified analyses' in html and 'Exploratory analyses' in html
    assert 'Source rows: 60' in html
    assert 'fixed_before_related_results' in html and 'prior_result_on_same_original_data' in html
    assert b'Pre-specified analyses' in (run/'reports'/f'{workflow}.pdf').read_bytes()
    workbook=load_workbook(run/'exports'/f'{workflow}.xlsx',read_only=True,data_only=True)
    assert {'pre_specified','exploratory'} <= set(workbook.sheetnames)
    assert 'primary' in str(list(workbook['pre_specified'].values))
    assert 'exploratory' in str(list(workbook['exploratory'].values))
    workbook.close()
    disclosure=__import__('workbench.analysis_disclosure',fromlist=['disclosure'])
    text=disclosure.markdown(disclosure.disclosure(fixture.project_root,fixture.run_id),detail='full')
    assert 'Pre-specified analyses' in text and 'Exploratory analyses' in text


def test_changing_the_question_does_not_create_a_fresh_prespecification_history(tmp_path):
    fixture=prepared(tmp_path)
    control=PlanControl(fixture.project_root,fixture.repository,'chain-session')
    current=fixture.orchestrator.plan_store.current('chain-session')
    revised=control.revise(current.version,{'question':'A different question about these data'})['plan']
    control.approve(revised['version'])
    result=fixture.propose([_t_test('changed-question')])
    record=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    assert record.execution['research_specification']['reason']=='question_changed'
    assert record.execution['research_specification']['specification_status']=='exploratory'


def test_unrelated_known_uploads_do_not_prevent_a_first_precise_specification(tmp_path):
    from workbench.artifacts import register_artifact
    fixture=prepared(tmp_path)
    other=fixture.project_root/'runs'/'unrelated'
    other.mkdir()
    write_json(other/'run_inputs.json',{'upload':{'sha256':'f'*64}})
    write_json(other/'model.json',{'unrelated':True})
    write_json(other/'artifacts_index.json',{'schema_version':1,'artifacts':[]})
    register_artifact(other,'model',other/'model.json','model_result','estimation',[])
    result=fixture.propose([_t_test('primary')])
    record=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    assert record.execution['research_specification']['specification_status']=='pre_specified'


def test_undo_and_fresh_approval_do_not_erase_result_history(tmp_path):
    from dataclasses import replace
    from workbench.agent.analysis_history import capture_checkpoint,rewind_analysis
    from workbench.research_specifications import freeze_operation
    fixture=prepared(tmp_path)
    repo=fixture.repository
    repo.append('chain-session','message',{'role':'assistant','content':'Ready.'})
    capture_checkpoint(repo,'chain-session','analysis-command')
    user=repo.append('chain-session','message',{'role':'user','content':'Analyze.','command_id':'analysis-command'})
    result=fixture.propose([_t_test('primary')])
    original=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    restored=rewind_analysis(repo,'chain-session',user.entry_id)['session_id']
    plan=PlanStore(repo.root).current(restored)
    PlanControl(fixture.project_root,repo,restored).approve(plan.version)
    record=replace(original,record_id='new-after-undo',agent_session_id=restored)
    proof=freeze_operation(fixture.project_root,record,PlanStore(repo.root).current(restored),first_dispatch=True)
    assert proof['specification_status']=='exploratory'
    assert 'prior_result' in proof['reason']
    assert len(action_rows(fixture.project_root))==1


@pytest.mark.parametrize('link_kind',['run_directory','run_inputs'])
def test_result_history_does_not_follow_project_links_to_external_metadata(tmp_path,link_kind):
    from workbench.services.research_history import result_history
    fixture=prepared(tmp_path)
    source=fixture.project_root/'runs'/fixture.run_id
    outside=tmp_path/'external'
    outside.mkdir()
    write_json(outside/'run_inputs.json',json.loads((source/'run_inputs.json').read_text()))
    write_json(outside/'model.json',{'outside_marker':'must not be inspected'})
    write_json(outside/'artifacts_index.json',{'schema_version':1,'artifacts':[]})
    from workbench.artifacts import register_artifact
    register_artifact(outside,'outside-model',outside/'model.json','model_result','estimation',[])
    branch=fixture.project_root/'runs'/'escape'
    if link_kind=='run_directory':
        branch.symlink_to(outside,target_is_directory=True)
    else:
        branch.mkdir()
        (branch/'run_inputs.json').symlink_to(outside/'run_inputs.json')
        write_json(branch/'artifacts_index.json',{'schema_version':1,'artifacts':[]})
    history=result_history(fixture.project_root,fixture.run_id)
    assert history['verified'] is False
    assert not any(row.get('artifact_id')=='outside-model' for row in history['prior_results'])


@pytest.mark.parametrize('artifact_type',['processed_data','derived_data'])
def test_a_data_stage_without_estimates_is_not_itself_a_related_result(tmp_path,artifact_type):
    fixture=prepared(tmp_path)
    path=fixture.project_root/'runs'/fixture.run_id/'artifacts_index.json'
    index=json.loads(path.read_text())
    index['artifacts'][0]['artifact_type']=artifact_type
    write_json(path,index)
    result=fixture.propose([_t_test('primary')])
    record=fixture.orchestrator.operation_store.get(result['operation']['record_id'])
    assert record.execution['research_specification']['specification_status']=='pre_specified'
