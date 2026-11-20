"""Consecutive registered read-only calls overlap; anything else is a barrier; receipts stay durable."""
import asyncio
import json
import threading

from tests.test_agent_core_restart import setup
from workbench.agent.model import ModelStreamEvent
from workbench.agent.tools import ToolDefinition, ToolRegistry


class Adapter:
    def __init__(self, names=('read_a', 'read_b'), *, answer_only=False, arguments=None):
        self.requests, self.names, self.answer_only = [], names, answer_only
        self.arguments = arguments or [{} for _ in names]
    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1 and not self.answer_only:
            for i,name in enumerate(self.names):
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    'tool_call_id':f'call-{i}', 'tool_id':name, 'arguments':self.arguments[i]})
            yield ModelStreamEvent.done(request.request_id, 'tool_calls')
        else:
            yield ModelStreamEvent.text_delta(request.request_id, 'Evidence read.')
            yield ModelStreamEvent.done(request.request_id)


def registry(handlers):
    owner = ToolRegistry()
    for name, handler, effect in handlers:
        owner.register(ToolDefinition(tool_id=name, version='v1', input_schema={'type':'object'},
            side_effect=effect, handler=handler, max_output_budget=2000))
    return owner


def test_independent_async_reads_overlap_and_publish_original_receipts_in_call_order(tmp_path):
    async def scenario():
        started = set()
        ready = asyncio.Event()
        async def read(name, args, context):
            started.add(name)
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), .3)
            return {'read':name}
        from functools import partial
        runtime = registry([(name, partial(read,name), 'none') for name in ['read_a','read_b']])
        core, store, repo = setup(tmp_path, Adapter(), runtime=runtime)
        answer = await core.prompt('Read evidence.', budget={'max_steps':3,'timeout_s':5})
        assert answer == 'Evidence read.'
        messages = [e.payload for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert all(json.loads(m['content'])['ok'] for m in messages)
        assert [m['name'] for m in messages] == ['read_a','read_b']
        assert not store.list_active()
    asyncio.run(scenario())


def test_synchronous_read_handlers_run_in_parallel_without_blocking_the_event_loop(tmp_path):
    gate = threading.Barrier(2, timeout=.5)
    def read(args, context):
        gate.wait()
        return {'read':True}
    async def scenario():
        runtime = registry([(name, read, 'none') for name in ['read_a','read_b']])
        core, _, repo = setup(tmp_path, Adapter(), runtime=runtime)
        await core.prompt('Read evidence.', budget={'max_steps':3,'timeout_s':5})
        messages = [e.payload for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert all(json.loads(m['content'])['ok'] for m in messages)
    asyncio.run(scenario())


def test_mixed_reads_and_effects_keep_serial_order(tmp_path):
    state, seen = {'value':0}, []
    def read(args, context):
        seen.append(state['value'])
        return {'value':state['value']}
    def change(args, context):
        state['value'] += 1
        return {'changed':True}
    async def scenario():
        runtime = registry([('read_a',read,'none'),('change',change,'proposal'),('read_b',read,'none')])
        core, _, _ = setup(tmp_path, Adapter(('read_a','change','read_b')), runtime=runtime)
        await core.prompt('Run the requested sequence.', budget={'max_steps':3,'timeout_s':5})
        assert seen == [0,1]
    asyncio.run(scenario())


def test_abort_parallel_reads_settles_all_intents_without_another_model_call(tmp_path):
    async def scenario():
        entered = set()
        ready = asyncio.Event()
        async def read(name, args, context):
            entered.add(name)
            if len(entered) == 2:
                ready.set()
            await asyncio.Event().wait()
        from functools import partial
        runtime = registry([(name,partial(read,name),'none') for name in ['read_a','read_b']])
        adapter = Adapter()
        core, store, repo = setup(tmp_path,adapter,runtime=runtime)
        task = asyncio.create_task(core.prompt('Read.',budget={'max_steps':3,'timeout_s':5}))
        await asyncio.wait_for(ready.wait(), .5)
        await core.abort()
        await task
        assert len(adapter.requests) == 1
        messages = [e.payload for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert len(messages) == 2
        assert all(json.loads(m['content'])['error'] == 'agent_aborted' for m in messages)
        assert repo.get_metadata('session-a')['status'] == 'cancelled'
        assert not store.list_active()
    asyncio.run(scenario())


def test_restart_repairs_all_parallel_read_receipts_without_rereading(tmp_path, monkeypatch):
    import pytest
    from functools import partial
    from tests.test_agent_core_restart import ProcessLost
    counts = {'read_a':0,'read_b':0}
    def read(name, args, context):
        counts[name] += 1
        return {'read':name,'original_count':counts[name]}
    async def scenario():
        runtime = registry([(name,partial(read,name),'none') for name in counts])
        core, store, repo = setup(tmp_path,Adapter(),runtime=runtime)
        original = repo.append_once
        def lose_second_message(*args, **kwargs):
            if kwargs.get('stage') == 'tool_result' and args[2].get('tool_call_id') == 'call-1':
                raise ProcessLost()
            return original(*args,**kwargs)
        monkeypatch.setattr(repo,'append_once',lose_second_message)
        with pytest.raises(ProcessLost):
            await core.prompt('Read.',budget={'max_steps':3,'timeout_s':5})
        [turn] = store.list_active()
        assert counts == {'read_a':1,'read_b':1}
        fresh_adapter = Adapter(answer_only=True)
        resumed, fresh, repository = setup(tmp_path,fresh_adapter,runtime=runtime,create=False)
        assert await resumed.resume(turn.turn_id) == 'Evidence read.'
        assert counts == {'read_a':1,'read_b':1}
        messages = [e.payload for e in repository.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert len(messages) == 2 and all(json.loads(m['content'])['output']['original_count'] == 1 for m in messages)
    asyncio.run(scenario())


def _overlapping_read(started, expected):
    """A read that finishes only once ``expected`` reads are in flight together."""
    ready = asyncio.Event()
    async def read(args, context):
        started.append(args.get('which'))
        if len(started) >= expected:
            ready.set()
        await asyncio.wait_for(ready.wait(), .3)
        return {'read':args.get('which')}
    return read


def test_the_same_read_tool_twice_overlaps_and_keeps_request_order(tmp_path):
    async def scenario():
        started = []
        runtime = registry([('inspect', _overlapping_read(started, 2), 'none')])
        adapter = Adapter(('inspect','inspect'), arguments=[{'which':'first'},{'which':'second'}])
        core, store, repo = setup(tmp_path, adapter, runtime=runtime)
        assert await core.prompt('Read both.', budget={'max_steps':3,'timeout_s':5}) == 'Evidence read.'
        messages = [e.payload for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert [json.loads(m['content'])['output']['read'] for m in messages] == ['first','second']
        assert len(adapter.requests) == 2 and not store.list_active()
    asyncio.run(scenario())


def test_reads_before_an_effect_overlap_and_the_effect_stays_a_barrier(tmp_path):
    state, after = {'value':0}, []
    def change(args, context):
        state['value'] += 1
        return {'changed':True}
    def read_after(args, context):
        after.append(state['value'])
        return {'value':state['value']}
    async def scenario():
        overlapping = _overlapping_read([], 2)
        runtime = registry([('read_a',overlapping,'none'),('read_b',overlapping,'none'),
                            ('change',change,'proposal'),('read_c',read_after,'none')])
        adapter = Adapter(('read_a','read_b','change','read_c'))
        core, _, repo = setup(tmp_path, adapter, runtime=runtime)
        await core.prompt('Run the requested sequence.', budget={'max_steps':3,'timeout_s':5})
        messages = [e.payload for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert [m['name'] for m in messages] == ['read_a','read_b','change','read_c']
        assert all(json.loads(m['content'])['ok'] for m in messages)
        assert after == [1]
    asyncio.run(scenario())


def test_partition_groups_only_consecutive_reads():
    from types import SimpleNamespace
    from workbench.agent.tool_batches import partition
    runtime = registry([('r',lambda a,c:{},'none'),('w',lambda a,c:{},'proposal')])
    core = SimpleNamespace(tool_runtime=runtime)
    calls = [{'tool_call_id':str(i),'tool_id':name} for i,name in enumerate(['r','r','w','r','w','w','r','r','r'])]
    assert [[c['tool_id'] for c in group] for group in partition(core, calls)] == [
        ['r','r'],['w'],['r'],['w'],['w'],['r','r','r']]
