"""Scoped business allocation replays identities, never operation results."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest


def _api():
    return importlib.import_module('workbench.agent.business_identity')


def _value(api, *, owner='probe.owner', slot='id', inputs=None, create=lambda: 'business-id'):
    return api.identity_value(owner=owner, slot=slot, inputs={'request': 'x'} if inputs is None else inputs,
                              create=create)


def _record(root):
    api=_api()
    with api.business_identity_scope(mode='record', root=root, name='business.jsonl'):
        assert _value(api)=='business-id'
    return api


def _forbidden():
    raise AssertionError('Replay must never create a replacement value')


def test_default_calls_only_the_original_factory():
    assert _value(_api(), inputs=object(), create=lambda:'original')=='original'


def test_identity_and_time_roundtrip_without_recording_inputs_or_outputs(tmp_path):
    api=_api()
    with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
        values=[_value(api,slot=slot,inputs={'private_request':'not stored'},create=lambda value=value:value)
                for slot,value in [('id','proposal-abc'),('created_at','2026-10-19T00:00:00+00:00')]]
    raw=(tmp_path/'business.jsonl').read_text()
    assert 'private_request' not in raw and 'not stored' not in raw
    assert all(set(json.loads(line)['payload']) <= {'kind','schema','version','owner','slot','input_sha256','value','count'}
               for line in raw.splitlines())
    with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl') as journal:
        assert [_value(api,slot=slot,inputs={'private_request':'not stored'},create=_forbidden)
                for slot in ['id','created_at']]==values
        assert journal.remaining==0


@pytest.mark.parametrize('change',[{'owner':'other.owner'},{'slot':'other'}, {'inputs':{'request':'changed'}}])
def test_owner_slot_and_request_drift_fail_closed(tmp_path,change):
    api=_record(tmp_path)
    with pytest.raises(api.BusinessIdentityError,match='mismatch'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            _value(api,create=_forbidden,**change)


def test_order_drift_and_unconsumed_records_are_rejected(tmp_path):
    api=_api()
    with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
        _value(api,slot='first');_value(api,slot='second')
    with pytest.raises(api.BusinessIdentityError,match='mismatch'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            _value(api,slot='second',create=_forbidden)
    with pytest.raises(api.BusinessIdentityError,match='unconsumed'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            _value(api,slot='first',create=_forbidden)


@pytest.mark.parametrize('corruption',['truncate','tamper','tail','duplicate'])
def test_corruption_and_missing_completion_are_rejected(tmp_path,corruption):
    api=_record(tmp_path);p=tmp_path/'business.jsonl';raw=p.read_bytes()
    if corruption=='truncate': raw=b'\n'.join(raw.splitlines()[:-1])+b'\n'
    elif corruption=='tamper': raw=raw.replace(b'business-id',b'changed-id')
    elif corruption=='tail': raw=raw[:-1]
    else: raw=raw.replace(b'"index":0',b'"index":0,"index":0',1)
    p.write_bytes(raw)
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'): pass


def test_exclusive_creation_never_overwrites(tmp_path):
    api=_record(tmp_path);before=(tmp_path/'business.jsonl').read_bytes()
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'): pass
    assert (tmp_path/'business.jsonl').read_bytes()==before


@pytest.mark.parametrize('name',['../escape','a/b','.','..'])
def test_journal_name_cannot_escape(tmp_path,name):
    api=_api()
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='record',root=tmp_path,name=name): pass


def test_symlink_and_hardlink_journals_are_rejected(tmp_path):
    api=_record(tmp_path)
    link=tmp_path/'link.jsonl';link.symlink_to(tmp_path/'business.jsonl')
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='replay',root=tmp_path,name=link.name): pass
    hard=tmp_path/'hard.jsonl';hard.hardlink_to(tmp_path/'business.jsonl')
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='replay',root=tmp_path,name=hard.name): pass


def test_scope_propagates_into_tool_task_but_closes_after_exit(tmp_path):
    api=_api()
    async def scenario():
        ready=asyncio.Event()
        async def delayed():
            await ready.wait()
            with pytest.raises(api.BusinessIdentityError,match='closed'):
                _value(api,create=_forbidden)
        with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
            task=asyncio.create_task(delayed())
            assert await asyncio.create_task(asyncio.to_thread(_value,api))=='business-id'
        ready.set();await task
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            assert await asyncio.create_task(asyncio.to_thread(_value,api,create=_forbidden))=='business-id'
    asyncio.run(scenario())


def test_failed_write_cannot_finish_a_replayable_record(tmp_path,monkeypatch):
    api=_api()
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
            monkeypatch.setattr(api.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('failed sync')))
            _value(api)
    monkeypatch.undo()
    with pytest.raises(api.BusinessIdentityError):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'): pass


def test_a_loaded_replay_rejects_journal_mutation_before_allocation(tmp_path):
    api=_record(tmp_path)
    with pytest.raises(api.BusinessIdentityError,match='changed'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            with (tmp_path/'business.jsonl').open('ab') as handle:
                handle.write(b'{}\n')
            _value(api,create=_forbidden)


def test_recording_cannot_follow_a_replaced_directory(tmp_path):
    api=_api();root=tmp_path/'root';root.mkdir()
    with pytest.raises(api.BusinessIdentityError,match='write failed'):
        with api.business_identity_scope(mode='record',root=root,name='business.jsonl'):
            root.rename(tmp_path/'original');root.mkdir()
            _value(api)
    assert not (root/'business.jsonl').exists()


def test_exhausted_replay_never_invokes_a_factory(tmp_path):
    api=_record(tmp_path)
    with pytest.raises(api.BusinessIdentityError,match='exhausted'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            _value(api,create=_forbidden)
            _value(api,create=_forbidden)


def test_parallel_task_scopes_do_not_share_allocations(tmp_path):
    api=_api()
    async def run_one(name):
        with api.business_identity_scope(mode='record',root=tmp_path,name=name):
            await asyncio.sleep(0)
            assert _value(api,create=lambda:name)==name
        with api.business_identity_scope(mode='replay',root=tmp_path,name=name):
            await asyncio.sleep(0)
            assert _value(api,create=_forbidden)==name
    async def scenario():
        await asyncio.gather(run_one('first.jsonl'),run_one('second.jsonl'))
    asyncio.run(scenario())


def _proposal_lifecycle(root, prepared):
    from workbench.agent.proposals import ProposalInvocation,ProposalStore
    store=ProposalStore(root)
    request=dict(session_id='session',chain_id='chain',operation_id='operation.multi_step',
                 target={'run_id':'run-source'},preconditions={'context_fingerprint':'ctx','active_head_run_id':'run-source'},
                 changes={'steps':[]},evidence_refs=['source'],expected_effect=['report'],risks=[],command_id='command')
    if prepared:
        first=store.create_prepared(invocation=ProposalInvocation('invocation',1,'call'),**request)
        assert store.create_prepared(invocation=ProposalInvocation('invocation',1,'call'),**request)==first
    else: first=store.create(**request)
    revised=store.revise(first.proposal_id,base_revision=1,changes={'steps':[],'note':'revised'})
    confirmed=store.confirm(first.proposal_id,revision=2,fingerprint=revised.fingerprint,actor_type='user',
                            current_context_fingerprint='ctx',current_active_head_run_id='run-source')
    return [first.to_dict(),revised.to_dict(),confirmed.to_dict()]


@pytest.mark.parametrize('prepared',[False,True])
def test_proposal_identity_revision_and_confirmation_replay(tmp_path,monkeypatch,prepared):
    api=_api()
    with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
        original=_proposal_lifecycle(tmp_path/'record',prepared)
    from workbench.agent import proposals
    monkeypatch.setattr(proposals,'uuid4',_forbidden);monkeypatch.setattr(proposals,'_now',_forbidden)
    with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
        assert _proposal_lifecycle(tmp_path/'replay',prepared)==original


def _plan_lifecycle():
    from workbench.agent import plans
    p=plans.merge(None,question='Compare groups',criteria=['report saved'],
                  steps=(plans.PlanStep('fit','Fit',('model.genesis',)),),budget={'steps':3},allowed_classes=['derive'])
    approved=plans.approve(p)
    completed=plans.mark_executed(approved,['model.genesis'],'completed')
    return [p.to_dict(),approved.to_dict(),completed.to_dict()]


def test_plan_ids_and_all_business_timestamps_replay(tmp_path,monkeypatch):
    api=_api()
    with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
        original=_plan_lifecycle()
    from workbench.agent import plans
    monkeypatch.setattr(plans,'uuid4',_forbidden);monkeypatch.setattr(plans,'_now',_forbidden)
    with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
        assert _plan_lifecycle()==original


def test_plan_previous_state_is_bound_before_replaying_an_update(tmp_path):
    api=_api()
    from workbench.agent import plans
    p=plans.Plan('fixed',1,'draft','q',(),(),())
    with api.business_identity_scope(mode='record',root=tmp_path,name='business.jsonl'):
        plans.approve(p)
    from dataclasses import replace
    with pytest.raises(api.BusinessIdentityError,match='mismatch'):
        with api.business_identity_scope(mode='replay',root=tmp_path,name='business.jsonl'):
            plans.approve(replace(p,question='changed'))
