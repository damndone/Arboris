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


def test_focused_answer_review_receives_the_actual_computed_evidence(tmp_path):
    from tests.test_agent_completion import artifact
    from workbench.agent.plans import Plan
    from workbench.agent.research_review import build_context
    from workbench.llm.config import LLMConfig

    source, digest = artifact(tmp_path, 'q', 'data', 'processed_data', {})
    result, _ = artifact(tmp_path, 'q', 'summary', 'statistical_exploration', {
        'schema_version': 'statistical-exploration.v1', 'result': {'operation': 'tabulate',
            'weighted_count': 10, 'variables': {'category': {'distinct': 1}},
            'rows': [{'variable': 'category', 'value': 'red', 'count': 10}],
            'observation_rows': [{'private': 'value'}]}}, ['data'])
    plan = Plan(plan_id='p', version=1, status='draft', question='Classify this variable.', criteria=(),
                steps=(), allowed_classes=(), completion={'scope': 'question', 'playbooks': [],
                    'source': {**source, 'sha256': digest}}, completion_evidence={'results': [result]})
    context = build_context(tmp_path, plan, mode='ask', candidate='It is categorical.',
                            config=LLMConfig(base_url='http://127.0.0.1', api_key='test', model='offline'))
    assert context['complete_packet']
    assert 'result:0' in context['evidence_keys']
    assert context['packet']['results'][0]['summary']['result']['weighted_count'] == 10
    assert 'private' not in json.dumps(context['packet'])


@pytest.mark.parametrize('categories,complete', [(2, True), (201, False)])
def test_tabulate_review_contains_bounded_aggregate_counts_and_reports_truncation(tmp_path, categories, complete):
    import pandas as pd
    from tests.test_agent_completion import artifact
    from workbench.agent.plans import Plan
    from workbench.agent.research_review import build_context
    from workbench.statistical_exploration import ExplorationSpec, execute_exploration
    source, digest = artifact(tmp_path, 'q', 'data', 'processed_data', {})
    frame = pd.DataFrame({'category': [f'c{i}' for i in range(categories)], 'n': range(1, categories + 1)})
    computed = execute_exploration(frame, ExplorationSpec(operation='tabulate',
        selected_columns=('category',), options={'frequency_weight': 'n'}))
    ref, _ = artifact(tmp_path, 'q', 'summary', 'statistical_exploration', {
        'schema_version': 'statistical-exploration.v1', 'result': computed}, ['data'])
    plan = Plan(plan_id='p', version=1, status='draft', question='What proportion belong to each category?',
        criteria=(), steps=(), allowed_classes=(), completion={'scope': 'question', 'playbooks': [],
        'source': {**source, 'sha256': digest}}, completion_evidence={'results': [ref]})
    context = build_context(tmp_path, plan, mode='ask', candidate='The first category is rare.', config=None)
    assert context['complete_packet'] is complete
    rows = context['packet']['results'][0]['summary']['result']['rows']
    assert len(rows) <= 100
    assert rows[0]['count'] == computed['rows'][0]['count']
    assert rows[0]['percent'] == computed['rows'][0]['percent']
    assert rows[0]['value'] == computed['rows'][0]['value']


def test_frequency_review_rejects_observation_rows_and_oversize_packets():
    from workbench.agent.research_review import _computed_summary
    summary, complete = _computed_summary({'result': {'operation': 'tabulate',
        'variables': {'category': {'distinct': 1}},
        'rows': [{'variable': 'category', 'value': 'red', 'count': 1, 'private': 'individual record'}]}})
    assert not complete and summary['result']['rows'] == []
    assert 'individual record' not in json.dumps(summary)


@pytest.mark.parametrize('columns,invalid,complete', [(30, False, True), (64, False, True), (65, False, False), (3, True, False)])
def test_native_prediction_review_keeps_full_bounded_scalar_coefficients(columns, invalid, complete):
    from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result
    from workbench.agent.research_review import _computed_summary

    coefficients = {f'x{i}': i / 64 for i in range(columns)}
    if invalid:
        coefficients['x0'] = True
    result = {
        'operation_id': 'prediction.native_logistic', 'coefficients': coefficients,
        'n_rows': 200, 'assumptions': ['held-out scores'],
        'metrics': {'log_loss': 0.45, 'roc_auc': 0.7},
        'split': {'train_rows': 150, 'test_rows': 50},
        'native_build': {'build_identity_sha256': 'a' * 64}, 'prevalence_baseline': {'log_loss': 0.66},
    }
    payload = {'schema_version': 'workbench.workflow.capability/v1', 'result': result,
               'local_detail': {'private_fixture': ['private value']}}
    ordinary, _ = _public_operation_artifact_result('workflow_capability_result', payload)
    summary, valid = _computed_summary(payload)
    assert len(ordinary['coefficients']) <= 12
    assert valid is complete and 'private value' not in json.dumps(summary)
    if complete:
        assert summary['result']['coefficients'] == coefficients


@pytest.mark.parametrize('receipt_state', ['missing', 'wrong_winner', 'wrong_split', 'valid'])
def test_ridge_selection_review_requires_reproducible_validation_evidence(receipt_state):
    from workbench.agent.research_review import _computed_summary

    result = {
        'operation_id': 'prediction.native_ridge_selection', 'n_rows': 10, 'assumptions': ['held-out scores'],
        'alpha': 6, 'coefficients': {'x': 1.0}, 'split': {'train_rows': 8, 'test_rows': 2},
        'metrics': {'rmse': .5}, 'mean_baseline': {'rmse': 1.5}, 'native_build': {'build_identity_sha256': 'a' * 64},
    }
    if receipt_state != 'missing':
        result['selection'] = {
            'criterion': 'validation_rmse', 'tie_break': 'largest_alpha',
            'fit_rows': 6, 'validation_rows': 3 if receipt_state == 'wrong_split' else 2, 'refit_rows': 8,
            'selected_alpha': 1 if receipt_state == 'wrong_winner' else 6, 'selected_validation_rmse': 0.0,
            'candidates': [{'alpha': 1, 'validation_rmse': .7}, {'alpha': 6, 'validation_rmse': 0.0}],
        }
    summary, complete = _computed_summary({'schema_version': 'workbench.workflow.capability/v1', 'result': result})
    assert complete is (receipt_state == 'valid')
    if complete:
        assert summary['result']['selection'] == result['selection']


def test_oversize_review_context_is_marked_incomplete(tmp_path, monkeypatch):
    from tests.test_agent_completion import artifact
    from workbench.agent.plans import Plan
    from workbench.agent import research_review
    source, digest = artifact(tmp_path, 'q', 'data', 'processed_data', {})
    plan = Plan(plan_id='p', version=1, status='draft', question='Describe this variable.', criteria=(),
        steps=(), allowed_classes=(), completion={'scope': 'question', 'playbooks': [],
        'source': {**source, 'sha256': digest}})
    monkeypatch.setattr(research_review, 'MAX_PACKET_BYTES', 10)
    context = research_review.build_context(tmp_path, plan, mode='ask', candidate='A descriptive answer.', config=None)
    assert not context['complete_packet']


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
        # The reviewer's own failure: the met completion stands, marked review unavailable (2026-10-22).
        assert '隔离复核不可用' in answer and '分析完成' in answer
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
        assert '隔离复核不可用' in answer and '分析完成' in answer
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
        assert '隔离复核不可用' in await resumed.resume(turn.turn_id)
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


def test_task_requirement_change_during_review_invalidates_verdict_with_same_artifacts(tmp_path):
    version = {'changed': False}
    class ChangingAdapter(Adapter):
        async def stream(self, request):
            async for event in super().stream(request):
                yield event
            if len(self.requests) == 2:
                version['changed'] = True
    async def scenario():
        adapter = ChangingAdapter()
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        original = core.research_review_context
        core.research_review_context = lambda candidate: {**original(candidate), 'task_requirements_sha256': 'task-a'}
        core.completion_check = lambda: {'status': 'partial' if version['changed'] else 'requirements_met',
            'missing': ['target:requested_estimand_unbound'] if version['changed'] else [],
            'verified_manifest_sha256': 'evidence-sha',
            'task_requirements_sha256': 'task-b' if version['changed'] else 'task-a'}
        await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        review = next(e.payload for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result')
        assert review['verdict'] == 'unverified'
        assert review['reason'] == 'evidence_changed_during_review'
    asyncio.run(scenario())


def test_plan_criteria_change_during_review_invalidates_verdict_with_same_artifacts(tmp_path):
    version = {'changed': False}
    class ChangingAdapter(Adapter):
        async def stream(self, request):
            async for event in super().stream(request):
                yield event
            if len(self.requests) == 2:
                version['changed'] = True
    async def scenario():
        core, _, repo = setup(tmp_path, ChangingAdapter())
        wire(core)
        original = core.research_review_context
        core.research_review_context = lambda candidate: {**original(candidate), 'review_plan_basis_sha256': 'plan-a'}
        core.completion_check = lambda: {'status': 'requirements_met', 'missing': [],
            'verified_manifest_sha256': 'evidence-sha',
            'review_plan_basis_sha256': 'plan-b' if version['changed'] else 'plan-a'}
        await core.prompt('完成分析', budget={'max_steps': 3, 'timeout_s': 30})
        review = next(e.payload for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result')
        assert review['verdict'] == 'unverified'
        assert review['reason'] == 'evidence_changed_during_review'
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
