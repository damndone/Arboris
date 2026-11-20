"""A complete review packet must retain the correlation it is asked to judge."""

import pandas as pd
import pytest

from tests.test_agent_completion import artifact
from workbench.agent.plans import Plan
from workbench.agent.research_review import build_context
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.task_requirements import RequirementBinder
from workbench.statistical_exploration import ExplorationSpec, execute_exploration


def test_complete_review_packet_cannot_drop_computed_correlation_pairs(tmp_path):
    computed = execute_exploration(
        pd.DataFrame({'x': [1, 2, 3, 4], 'y': [4, 3, 2, 1]}),
        ExplorationSpec(operation='corr', selected_columns=('x', 'y'), options={}))
    assert computed['pairs'] == [{'a': 'x', 'b': 'y', 'r': -1.0, 'n': 4}]
    source, digest = artifact(tmp_path, 'q', 'data', 'processed_data', {})
    result, _ = artifact(tmp_path, 'q', 'correlation', 'statistical_exploration', {
        'schema_version': 'statistical-exploration.v1', 'result': computed}, ['data'])
    repository = JsonlSessionRepository(tmp_path / 'workbench')
    repository.create_session('session-a', role='chain', chain_id='chain-a')
    question = 'What is the correlation of x with y?'
    repository.append('session-a', 'message', {'role': 'user', 'content': question})
    plan = Plan(plan_id='p', version=1, status='draft', question=question,
        criteria=(), steps=(), allowed_classes=(),
        completion={'scope': 'question', 'playbooks': [],
                    'source': {**source, 'sha256': digest}},
        completion_evidence={'results': [result]},
        task_requirements=RequirementBinder(repository).bind('session-a', None))

    context = build_context(tmp_path, plan, mode='ask',
        candidate='The correlation is positive.', config=None)

    assert context['packet']['completion']['status'] == 'requirements_met'
    summary = context['packet']['results'][0]['summary']['result']
    assert not context['complete_packet'] or summary.get('pairs') == computed['pairs'], (
        'The reviewer receives no computed correlation but the packet claims completeness', summary)


def test_correlation_review_preserves_only_bounded_aggregate_pairs():
    from workbench.agent.research_review import _computed_summary
    computed = execute_exploration(
        pd.DataFrame({'x': [1, 2, 3, 4], 'y': [4, 3, 2, 1]}),
        ExplorationSpec(operation='corr', selected_columns=('x', 'y'), options={}))
    computed['observation_rows'] = [{'private': 'individual observation'}]
    summary, complete = _computed_summary({'result': computed})
    assert complete
    assert summary['result']['pairs'] == computed['pairs']
    assert summary['result']['variables'] == ['x', 'y']
    assert 'observation_rows' not in summary['result']


@pytest.mark.parametrize('change', ['missing', 'extra_field', 'truncated', 'oversized'])
def test_incomplete_correlation_summaries_cannot_claim_complete(change):
    from workbench.agent.research_review import _computed_summary
    frame = pd.DataFrame({f'x{i}': range(4) for i in range(15 if change == 'oversized' else 2)})
    computed = execute_exploration(frame, ExplorationSpec(operation='corr',
        selected_columns=tuple(frame.columns), options={}))
    if change == 'missing':
        computed.pop('pairs')
    elif change == 'extra_field':
        computed['pairs'][0]['private'] = 'individual observation'
    elif change == 'truncated':
        computed['pairs'] = []
    summary, complete = _computed_summary({'result': computed})
    assert not complete
    assert summary['result']['review_evidence_incomplete']
    assert len(summary['result'].get('pairs', [])) <= 100
    assert 'private' not in str(summary)


@pytest.mark.parametrize('operation', ['summarize', 'summarize_detail', 'misstable'])
def test_omitted_production_group_summaries_are_marked_incomplete(operation):
    from workbench.agent.research_review import _computed_summary
    computed = execute_exploration(
        pd.DataFrame({'group': ['a', 'a', 'b', 'b'], 'y': [1, 2, 10, 20]}),
        ExplorationSpec(operation=operation, selected_columns=('y',), options={'group_by': 'group'}))
    assert computed['groups']
    summary, complete = _computed_summary({'result': computed})
    assert not complete
    assert summary['result']['review_evidence_incomplete']
    assert 'groups' not in summary['result']
