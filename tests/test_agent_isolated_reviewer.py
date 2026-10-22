"""The research reviewer gets a bounded evidence packet and no execution tools."""
import asyncio
import json
import pytest

from tests.test_agent_core_restart import setup
from workbench.agent.model import ModelStreamEvent


class Adapter:
    def __init__(self, verdict='no_issues_found', *, tool=False):
        self.requests = []
        self.verdict = verdict
        self.tool = tool

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.text_delta(request.request_id, '分析完成：已核验原生结果。')
        else:
            if self.tool:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    'tool_call_id': 'escape', 'tool_id': 'run_operation', 'arguments': {}})
                yield ModelStreamEvent.done(request.request_id, 'tool_calls')
                return
            findings = [] if self.verdict == 'no_issues_found' else [{'severity': 'blocking',
                'message': 'The candidate makes an unsupported causal claim.', 'evidence_refs': ['candidate', 'plan']}]
            yield ModelStreamEvent.text_delta(request.request_id, json.dumps({'verdict': self.verdict, 'findings': findings}))
        yield ModelStreamEvent.done(request.request_id)


def wire(core, *, mode='auto'):
    core.research_review_mode = lambda: mode
    from workbench.agent.research_review import restore_phase
    core.phase_restorer = lambda checkpoint: restore_phase(core, checkpoint)
    core.completion_check = lambda: {'status': 'requirements_met', 'missing': [], 'verified_manifest_sha256': 'evidence-sha'}
    core.research_review_context = lambda candidate: {'mode': mode, 'packet': {
        'plan': {'question': 'Describe the association', 'criteria': ['no causal claims']},
        'source': {'sha256': 'source-sha'}, 'candidate': candidate, 'models': [], 'diagnostics': [],
        'completion': core.completion_check()}, 'evidence_keys': ['plan','source','candidate'],
        'manifest_sha256': 'evidence-sha', 'complete_packet': True, 'egress_allowed': True}


def test_auto_completion_runs_one_isolated_tool_free_review_in_the_same_budget(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, store, repo = setup(tmp_path, adapter)
        wire(core)
        repo.append('session-a', 'message', {'role': 'user', 'content': 'PRIVATE PRIOR CONVERSATION'})
        answer = await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        assert len(adapter.requests) == 2
        review = adapter.requests[-1]
        assert not review.tools and review.response_schema
        assert 'PRIVATE PRIOR CONVERSATION' not in json.dumps(review.messages)
        assert '隔离复核' in answer
        receipts = [e for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result']
        assert len(receipts) == 1
        assert receipts[0].payload['verdict'] == 'no_issues_found'
        assert repo.get_metadata('session-a')['status'] == 'idle'
    asyncio.run(scenario())


def test_ask_mode_does_not_add_an_unrequested_review_call(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core, mode='ask')
        await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        assert len(adapter.requests) == 1
    asyncio.run(scenario())


def test_reviewer_cannot_invoke_a_tool_or_grant_execution_permission(tmp_path):
    async def scenario():
        adapter = Adapter(tool=True)
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        answer = await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        assert len(adapter.requests) == 2
        assert '部分完成' in answer
        assert not any(e.entry_type == 'tool_intent' for e in repo.get_branch('session-a'))
    asyncio.run(scenario())


def test_ask_review_command_makes_only_the_requested_review_call(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core, mode='ask')
        await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        before = len(adapter.requests)
        answer = await core.prompt('/review', budget={'max_steps': 1, 'timeout_s': 30})
        assert len(adapter.requests) == before+1
        assert '隔离复核' in answer
        assert adapter.requests[-1].tools == []
    asyncio.run(scenario())


def test_review_respects_remaining_command_budget(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        answer = await core.prompt('完成分析', budget={'max_steps': 1, 'timeout_s': 30})
        assert len(adapter.requests) == 1
        assert '部分完成' in answer
    asyncio.run(scenario())


def test_restart_republishes_original_review_without_another_provider_call(tmp_path, monkeypatch):
    import pytest
    from tests.test_agent_core_restart import ProcessLost
    async def scenario():
        adapter = Adapter()
        core, store, repo = setup(tmp_path, adapter)
        wire(core)
        original = repo.append_once
        def lose_publication(*args, **kwargs):
            if kwargs.get('stage') == 'research_review_publication':
                raise ProcessLost()
            return original(*args, **kwargs)
        monkeypatch.setattr(repo, 'append_once', lose_publication)
        with pytest.raises(ProcessLost):
            await core.prompt('完成分析', budget={'max_steps': 2, 'timeout_s': 30})
        assert len(adapter.requests) == 2
        [turn] = store.list_active()
        fresh_adapter = Adapter()
        resumed, fresh, repository = setup(tmp_path, fresh_adapter, create=False)
        wire(resumed)
        assert '隔离复核' in await resumed.resume(turn.turn_id)
        assert fresh_adapter.requests == []
        assert fresh.get(turn.turn_id).steps_used == 2
        assert len([e for e in repository.get_branch('session-a') if e.entry_type == 'research_review_result']) == 1
    asyncio.run(scenario())


def test_unfinished_review_is_not_automatically_reissued_after_restart(tmp_path):
    import pytest
    from tests.test_agent_core_restart import ProcessLost
    class LostAdapter(Adapter):
        async def stream(self, request):
            if len(self.requests) == 1:
                self.requests.append(request)
                raise ProcessLost()
            async for event in super().stream(request):
                yield event
    async def scenario():
        adapter = LostAdapter()
        core, store, _ = setup(tmp_path, adapter)
        wire(core)
        with pytest.raises(ProcessLost):
            await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        [turn] = store.list_active()
        fresh_adapter = Adapter()
        resumed, _, _ = setup(tmp_path, fresh_adapter, create=False)
        wire(resumed)
        assert '部分完成' in await resumed.resume(turn.turn_id)
        assert fresh_adapter.requests == []
    asyncio.run(scenario())


def test_auto_uses_critique_to_revise_once_then_rechecks_without_sharing_primary_history(tmp_path):
    class CorrectingAdapter:
        def __init__(self):
            self.requests = []
        async def stream(self, request):
            self.requests.append(request)
            n = len(self.requests)
            if n == 1:
                text = '分析完成：这是一个因果效应。'
            elif n == 2:
                text = json.dumps({'verdict':'issues_found','findings':[{'severity':'blocking',
                    'message':'The candidate claims causality without identification evidence.', 'evidence_refs':['candidate','plan']}]})
            elif n == 3:
                text = '已修正为相关性解释，因果识别尚未建立。'
            else:
                text = json.dumps({'verdict':'no_issues_found','findings':[]})
            yield ModelStreamEvent.text_delta(request.request_id, text)
            yield ModelStreamEvent.done(request.request_id)
    async def scenario():
        adapter = CorrectingAdapter()
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        answer = await core.prompt('完成分析', budget={'max_steps': 6, 'timeout_s': 30})
        assert len(adapter.requests) == 4
        assert '相关性解释' in answer
        assert 'no causal claims' in json.dumps(adapter.requests[-1].messages)
        assert not adapter.requests[1].tools and not adapter.requests[3].tools
        assert len([e for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result']) == 2
    asyncio.run(scenario())


def test_two_blocking_reviews_stop_the_same_command_without_a_third_review(tmp_path):
    async def scenario():
        adapter = Adapter(verdict='issues_found')
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        answer = await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        assert len(adapter.requests) == 4
        assert '部分完成' in answer
        assert len([e for e in repo.get_branch('session-a') if e.entry_type == 'research_review_intent']) == 2
    asyncio.run(scenario())


def test_evidence_change_during_review_never_reuses_a_positive_verdict(tmp_path):
    version = {"changed":False}
    class ChangingAdapter(Adapter):
        async def stream(self, request):
            async for event in super().stream(request):
                yield event
            if len(self.requests) == 2:
                version["changed"] = True
    async def scenario():
        adapter = ChangingAdapter()
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        core.completion_check = lambda: {'status':'partial' if version['changed'] else 'requirements_met',
            'missing':['source:changed_or_unavailable'] if version['changed'] else [],
            'verified_manifest_sha256':'changed' if version['changed'] else 'evidence-sha'}
        answer = await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        assert '部分完成' in answer
        review = next(e.payload for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result')
        assert review['verdict'] == 'unverified' and review['reason'] == 'evidence_changed_during_review'
        assert review['prior_verdict'] == 'no_issues_found' and 'no_issues_found' in review['raw_response']
    asyncio.run(scenario())


def test_unknown_reviewer_citations_are_unverified_not_granted_authority(tmp_path):
    from workbench.agent.research_review import _parse
    result = _parse(json.dumps({'verdict':'issues_found','findings':[{'severity':'blocking',
        'message':'Unsupported evidence', 'evidence_refs':['invented-source']}]}), ['source'])
    assert result['verdict'] == 'unverified'


@pytest.mark.parametrize("data_location, permitted", [("local", True), ("remote", False)])
def test_production_review_packet_contains_verified_primary_and_sensitivity_without_rows(tmp_path, data_location, permitted):
    from types import SimpleNamespace
    from workbench.agent.plans import Plan
    from workbench.agent.research_review import build_context
    from workbench.egress import EgressPolicy, REMOTE_DEFAULT_ALLOW, save_policy
    from tests.test_agent_completion_time_series import products, series
    project, contract, evidence = products(tmp_path, series())
    save_policy(project, EgressPolicy(providers={"local": REMOTE_DEFAULT_ALLOW, "remote": frozenset({"schema"})}))
    plan = Plan(plan_id='p', version=1, status='approved', question='Forecast the series', criteria=(), steps=(),
        allowed_classes=(), budget={'steps':6}, completion=contract, completion_evidence=evidence)
    context = build_context(project, plan, mode='auto', candidate='Analysis complete.',
        config=SimpleNamespace(provider_id='offline', base_url='http://127.0.0.1', data_location=data_location))
    assert context['complete_packet'] is True and context['egress_allowed'] is permitted
    assert [m['role'] for m in context['packet']['models']] == ['models', 'sensitivity']
    assert context['packet']['source'] == contract['source']
    encoded = json.dumps(context['packet'])
    assert '"residuals"' not in encoded and '"ordered_positions"' not in encoded and '"innovations"' not in encoded
    assert 'ar.L1' in encoded and 'std_error' in encoded


def test_reviewer_uses_core_phase_and_never_calls_an_adapter_itself():
    import inspect
    from workbench.agent import research_review
    source = inspect.getsource(research_review)
    assert 'adapter.stream' not in source
    assert 'observe_provider(' not in source


def test_restart_during_pure_review_transition_reuses_original_provider_events(tmp_path, monkeypatch):
    import pytest
    from tests.test_agent_core_restart import ProcessLost
    async def scenario():
        adapter = Adapter()
        core, store, repo = setup(tmp_path, adapter)
        wire(core)
        original = core.turn_journal.save
        def lose_transition(core, stage, **details):
            if stage == 'phase_applied':
                raise ProcessLost()
            return original(core, stage, **details)
        monkeypatch.setattr(core.turn_journal, 'save', lose_transition)
        with pytest.raises(ProcessLost):
            await core.prompt('完成分析', budget={'max_steps':2,'timeout_s':30})
        [turn] = store.list_active()
        fresh_adapter = Adapter()
        resumed, fresh, repository = setup(tmp_path, fresh_adapter, create=False)
        wire(resumed)
        assert '隔离复核' in await resumed.resume(turn.turn_id)
        assert fresh_adapter.requests == []
        assert fresh.get(turn.turn_id).steps_used == 2
    asyncio.run(scenario())
