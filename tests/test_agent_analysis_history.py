"""Joint analysis undo keeps old evidence and restores a usable branch."""
import asyncio
from pathlib import Path

import pytest

from tests.test_agent_core_restart import setup, Adapter
from tests.test_agent_session_history import conversation
from workbench.agent.chains import ChainStore
from workbench.agent.plans import PlanStore, merge, parse_steps, approve
from workbench.agent.session import JsonlSessionRepository


def fixture(root):
    core, store, repository = setup(root, Adapter())
    seed = repository.append('session-a','custom_message',{
        'name':'workbench_context','audience':'model','content':'Verified source context',
        'metadata':{'run_id':'source'}})
    repository.append('session-a','custom_message',{
        'name':'workbench_agent_focus','audience':'model','content':'Focus: source dataset',
        'metadata':{'focus':{'kind':'dataset','id':'stage:source','run_id':'source','label':'Source'}}})
    chains = ChainStore(repository.root)
    chains.create_root(chain_id='chain-a',run_family_id='family-a',active_head_run_id='source',agent_session_id='session-a')
    (root/'runs/source').mkdir(parents=True)
    (root/'runs/source/original.csv').write_text('y,x\n1,2\n')
    return core,store,repository,chains


def run_analysis(root):
    from workbench.agent.analysis_history import capture_checkpoint
    core,store,repo,chains=fixture(root)
    core.input_checkpoint=lambda command: capture_checkpoint(repo,'session-a',command)
    asyncio.run(core.prompt('Complete an analysis.',budget={'max_steps':2,'timeout_s':10}))
    user=next(e for e in repo.get_branch('session-a') if e.entry_type=='message' and e.payload.get('role')=='user')
    plan=approve(merge(None,question='Later analysis',criteria=['Report uncertainty'],
        steps=parse_steps([{'step_id':'fit','title':'Fit','operation_ids':['test.t_tests']}],{'test.t_tests'}),
        allowed_classes=None,budget={'steps':4}))
    PlanStore(repo.root).save('session-a',plan)
    chains.activate('chain-a',active_head_run_id='later')
    repo.update_metadata('session-a',permission_grants=[{'class':'analyze'}],execution_mode='auto')
    (root/'runs/later').mkdir()
    (root/'runs/later/result.txt').write_text('Saved numerical evidence')
    return repo,chains,user


def test_real_http_turns_record_one_checkpoint_before_each_user_message(conversation):
    _,_,session,root=conversation
    branch=JsonlSessionRepository(root/'workbench').get_branch(session)
    checkpoints=[e for e in branch if e.entry_type=='analysis_checkpoint']
    assert len(checkpoints)==2
    for checkpoint in checkpoints:
        user=next(e for e in branch if e.entry_type=='message' and e.payload.get('role')=='user'
            and e.payload.get('command_id')==checkpoint.payload['command_id'])
        assert branch.index(checkpoint)<branch.index(user)
        assert checkpoint.payload['lineage']['active_head_run_id']=='run-a'


def test_joint_undo_restores_conversation_head_plan_and_grants_without_deleting_evidence(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis, require_active_session
    repo,chains,user=run_analysis(tmp_path)
    result=rewind_analysis(repo,'session-a',user.entry_id)
    restored=result['session_id']
    assert restored!='session-a'
    metadata=repo.get_metadata(restored)
    assert chains.resolve_active_head(metadata['chain_id'])=='source'
    assert result['lineage']['run_id']=='source'
    assert result['lineage']['focus']['id']=='stage:source'
    assert not any(e.payload.get('content')=='Complete an analysis.' for e in repo.get_branch(restored))
    assert PlanStore(repo.root).current(restored) is None
    assert not metadata.get('permission_grants')
    assert (tmp_path/'runs/source/original.csv').read_text()=='y,x\n1,2\n'
    assert (tmp_path/'runs/later/result.txt').read_text()=='Saved numerical evidence'
    assert user in repo.get_branch('session-a')
    with pytest.raises(ValueError,match='restored branch'):
        require_active_session(repo,'session-a')
    require_active_session(repo,restored)
    assert rewind_analysis(repo,'session-a',user.entry_id)==result


def test_process_loss_during_restore_reuses_the_same_branch_and_requires_repair(tmp_path,monkeypatch):
    from workbench.agent.analysis_history import rewind_analysis, require_active_session
    repo,chains,user=run_analysis(tmp_path)
    original=repo.update_status
    def lose_ready(session,status):
        if session!='session-a' and status=='idle':
            raise OSError('process lost after branch creation')
        return original(session,status)
    monkeypatch.setattr(repo,'update_status',lose_ready)
    with pytest.raises(OSError,match='process lost'):
        rewind_analysis(repo,'session-a',user.entry_id)
    with pytest.raises(ValueError,match='restored branch'):
        require_active_session(repo,'session-a')
    fresh=JsonlSessionRepository(repo.root)
    result=rewind_analysis(fresh,'session-a',user.entry_id)
    assert fresh.get_metadata(result['session_id'])['status']=='idle'
    assert len(fresh.list_metadata())==2
    assert (tmp_path/'runs/later/result.txt').exists()


def test_undo_refuses_an_owned_live_turn_and_does_not_create_a_branch(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis
    from workbench.agent.turn_store import TurnStore
    repo,_,user=run_analysis(tmp_path)
    with TurnStore(tmp_path).execution_guard('session-a'):
        with pytest.raises(ValueError,match='execut'):
            rewind_analysis(repo,'session-a',user.entry_id)
    assert len(repo.list_metadata())==1


def test_an_old_turn_with_unverifiable_lineage_is_not_presented_as_joint_undo(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis
    _,_,repo,_=fixture(tmp_path)
    user=repo.append('session-a','message',{'role':'user','content':'Old unrecorded analysis','command_id':'old'})
    repo.append('session-a','message',{'role':'assistant','content':'Old result','command_id':'old'})
    with pytest.raises(ValueError,match='checkpoint'):
        rewind_analysis(repo,'session-a',user.entry_id)
    assert len(repo.list_metadata())==1


def test_restored_plan_keeps_intent_but_requires_fresh_approval(tmp_path):
    from workbench.agent.analysis_history import capture_checkpoint, rewind_analysis
    from workbench.agent.plan_control import PlanControl
    core,_,repo,_=fixture(tmp_path)
    prior=approve(merge(None,question='Original question',criteria=['Uncertainty'],
        steps=parse_steps([{'step_id':'fit','title':'Fit','operation_ids':['test.t_tests']}],{'test.t_tests'}),
        allowed_classes=None,budget={'steps':4}))
    PlanStore(repo.root).save('session-a',prior)
    core.input_checkpoint=lambda command: capture_checkpoint(repo,'session-a',command)
    asyncio.run(core.prompt('Run it.',budget={'max_steps':2,'timeout_s':10}))
    user=next(e for e in repo.get_branch('session-a') if e.entry_type=='message' and e.payload.get('role')=='user')
    result=rewind_analysis(repo,'session-a',user.entry_id)
    restored=PlanStore(repo.root).current(result['session_id'])
    assert restored.question==prior.question
    assert restored.status=='draft' and restored.approved_at is None and restored.approved_version is None
    assert PlanControl(tmp_path,repo,'session-a').view()['plan'] is not None
    with pytest.raises(ValueError,match='restored branch'):
        PlanControl(tmp_path,repo,'session-a').approve(prior.version)


def test_first_command_on_an_empty_session_also_has_a_restorable_checkpoint(tmp_path):
    from workbench.agent.analysis_history import capture_checkpoint, rewind_analysis
    core,_,repo=setup(tmp_path,Adapter())
    core.input_checkpoint=lambda command: capture_checkpoint(repo,'session-a',command)
    asyncio.run(core.prompt('First analysis.',budget={'max_steps':2,'timeout_s':10}))
    user=next(e for e in repo.get_branch('session-a') if e.entry_type=='message' and e.payload.get('role')=='user')
    result=rewind_analysis(repo,'session-a',user.entry_id)
    assert not any(e.entry_type=='message' for e in repo.get_branch(result['session_id']))


def test_undo_cancels_the_waiting_turn_and_retires_pending_cards(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis
    from workbench.agent.proposals import ProposalStore
    from workbench.agent.turn_store import TurnStore
    repo,_,user=run_analysis(tmp_path)
    proposals=ProposalStore(repo.root)
    proposal=proposals.create(operation_id='model.rerun',operation_version='v1',session_id='session-a',chain_id='chain-a',
        command_id='waiting',target={'run_id':'later','node_ref':'model:ols'},preconditions={},changes={},
        evidence_refs=[],expected_effect=[],risks=[])
    turns=TurnStore(tmp_path)
    turn=turns.create('session-a',user.entry_id,budget={'max_steps':2,'timeout_s':10})
    turn=turns.claim(turn.turn_id,expected_version=turn.version,owner='test',lease_seconds=60)
    turn=turns.transition(turn.turn_id,'running',expected_version=turn.version,owner=turn.lease_owner,fence=turn.lease_epoch)
    turns.transition(turn.turn_id,'awaiting_approval',expected_version=turn.version,owner=turn.lease_owner,fence=turn.lease_epoch)
    result=rewind_analysis(repo,'session-a',user.entry_id)
    assert proposals.latest_status(proposal.proposal_id)=='declined'
    assert turns.get(turn.turn_id).status=='cancelled'
    assert proposals.latest_revisions_for_session(result['session_id'])==[]


def test_undo_does_not_overwrite_a_parent_that_has_newer_independent_work(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis
    from workbench.agent.session import EntryRef
    repo,_,user=run_analysis(tmp_path)
    branch=repo.get_branch('session-a')
    reply=branch[-1]
    repo.create_session('child',chain_id='chain-a',role='chain',
        inherited_parent_ref=EntryRef(reply.session_id,reply.entry_id))
    repo.append('session-a','message',{'role':'user','content':'Newer independent work'})
    with pytest.raises(ValueError,match='parent conversation changed'):
        rewind_analysis(repo,'child',user.entry_id)
    assert len(repo.list_metadata())==2
    assert repo.get_metadata('session-a')['status']=='idle'


def test_undo_holds_the_same_domain_lease_as_operation_execution(tmp_path):
    from workbench.agent.analysis_history import rewind_analysis
    from workbench.agent.execution import ChainExecutionLease, OperationClaimConflict
    repo,_,user=run_analysis(tmp_path)
    lease=ChainExecutionLease(repo.root,chain_id='chain-a',active_head_run_id='later',execution_key='live')
    lease.acquire()
    try:
        with pytest.raises(OperationClaimConflict):
            rewind_analysis(repo,'session-a',user.entry_id)
    finally:
        lease.release()
    assert len(repo.list_metadata())==1


def test_an_already_registered_core_cannot_reopen_the_retired_session(tmp_path):
    from workbench.agent.analysis_history import capture_checkpoint, rewind_analysis, require_active_session
    core,_,repo,_=fixture(tmp_path)
    core.input_checkpoint=lambda command:capture_checkpoint(repo,'session-a',command)
    core.command_check=lambda:require_active_session(repo,'session-a')
    asyncio.run(core.prompt('Original.',budget={'max_steps':2,'timeout_s':10}))
    user=next(e for e in repo.get_branch('session-a') if e.entry_type=='message' and e.payload.get('role')=='user')
    rewind_analysis(repo,'session-a',user.entry_id)
    for operation in (lambda:core.prompt('New.'),core.continue_):
        with pytest.raises(ValueError,match='restored branch'):
            asyncio.run(operation())
        assert repo.get_metadata('session-a')['status']=='rewound'
