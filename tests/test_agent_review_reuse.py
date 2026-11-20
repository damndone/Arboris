"""A blocking review of unchanged verified evidence is handed back, not asked again, in a later command.

Recorded Auto task (panel_fe.specific, 2026-10-22): one unchanged manifest, twelve
reviews (about 95k reasoning tokens) because every nudge started a new command
and each command reviewed twice. Within one command the revision and its recheck
remain (tests/test_agent_isolated_reviewer.py).
"""
import asyncio
import json

from tests.test_agent_core_restart import setup
from tests.test_agent_isolated_reviewer import wire
from workbench.agent.model import ModelStreamEvent

BLOCKING = {'verdict': 'issues_found', 'findings': [{'severity': 'blocking',
            'message': 'Plan criterion 2 has no supporting fit.', 'evidence_refs': ['plan']}]}
WARNING = {'verdict': 'issues_found', 'findings': [{'severity': 'warning',
           'message': 'Report the clustering choice.', 'evidence_refs': ['plan']}]}


class Adapter:
    """Main turns claim completion; reviewer requests (no tools, the reviewer prompt) get ``verdict``."""

    def __init__(self, verdict=BLOCKING):
        self.verdict = verdict
        self.main = 0
        self.reviews = 0

    async def stream(self, request):
        if request.messages and str(request.messages[0].get('content', '')).startswith('You are Arboris research reviewer'):
            self.reviews += 1
            yield ModelStreamEvent.text_delta(request.request_id, json.dumps(self.verdict))
        else:
            self.main += 1
            yield ModelStreamEvent.text_delta(request.request_id, f'分析完成：第 {self.main} 次总结。')
        yield ModelStreamEvent.done(request.request_id)


def _results(repo):
    return [e.payload for e in repo.get_branch('session-a') if e.entry_type == 'research_review_result']


def _nudge(core):
    return core.prompt('请继续，把这项分析做完。', budget={'max_steps': 10, 'timeout_s': 30})


def test_a_later_command_reuses_the_blocking_review_of_unchanged_evidence(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        assert adapter.reviews == 2  # review, revision, recheck: unchanged
        first = _results(repo)[-1]
        for _ in range(2):
            answer = await _nudge(core)
            assert '部分完成' in answer and 'Plan criterion 2 has no supporting fit.' in answer
        assert adapter.reviews == 2  # two nudges, no further reviewer call (a third reviews afresh)
        reused = _results(repo)[-2:]
        assert all(r['reused_from_review_id'] == first['review_id'] for r in reused)
        assert all(r['reuse_reason'] == 'verified_evidence_unchanged' for r in reused)
        assert all(r['findings'] == first['findings'] for r in reused)
        # No intent was written for a reuse, so nothing waits on a provider reply.
        assert len([e for e in repo.get_branch('session-a') if e.entry_type == 'research_review_intent']) == 2
    asyncio.run(scenario())


def test_a_reused_verdict_gets_no_further_revision_turn(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        before = adapter.main
        await _nudge(core)
        assert adapter.main == before + 1  # the nudge's answer only; no revision of an already-returned finding
    asyncio.run(scenario())


def test_changed_evidence_is_reviewed_again(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        manifest = {'sha': 'evidence-sha-2'}
        core.completion_check = lambda: {'status': 'requirements_met', 'missing': [], 'verified_manifest_sha256': manifest['sha']}
        original = core.research_review_context
        core.research_review_context = lambda candidate: {**original(candidate), 'manifest_sha256': manifest['sha']}
        await _nudge(core)
        assert adapter.reviews == 4
    asyncio.run(scenario())


def test_a_warning_only_review_is_not_reused(tmp_path):
    async def scenario():
        adapter = Adapter(verdict=WARNING)
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        before = adapter.reviews
        await _nudge(core)
        assert adapter.reviews == before + 1
    asyncio.run(scenario())


def test_an_explicit_review_request_asks_the_reviewer_again(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core, mode='ask')
        await core.prompt('/review', budget={'max_steps': 2, 'timeout_s': 30})
        assert adapter.reviews == 1
        await core.prompt('/review', budget={'max_steps': 2, 'timeout_s': 30})
        assert adapter.reviews == 2
    asyncio.run(scenario())


def test_another_reviewer_model_reviews_again(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        core.model_name = 'model-a'
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        core.model_name = 'model-b'
        await _nudge(core)
        assert adapter.reviews == 4
    asyncio.run(scenario())


def test_a_reviewer_side_failure_keeps_a_met_completion_but_a_partial_one_stays_partial():
    from workbench.agent.research_review import _publication

    payload = {'content': '分析完成：结论如下。', 'completion_check': {'status': 'requirements_met'}}
    base = {'candidate_entry_id': 'e', 'findings': [], 'verdict': 'unverified'}
    kept = _publication(payload, {**base, 'reason': 'inconsistent_verdict_or_unknown_evidence_reference',
                                  'completion_check': {'status': 'requirements_met'}},
                        language='zh', mode='auto', review_count=1, remaining=None)
    assert '分析完成' in kept['content'] and '隔离复核不可用' in kept['content']
    assert kept['research_review']['review_unavailable'] is True
    for reason, check in (('evidence_changed_during_review', 'requirements_met'),
                          ('delivery_requirements_still_partial', 'requirements_met'),
                          ('invalid_reviewer_response', 'partial')):
        demoted = _publication({**payload, 'completion_check': {'status': check}},
                               {**base, 'reason': reason, 'completion_check': {'status': check}},
                               language='zh', mode='auto', review_count=1, remaining=None)
        assert '部分完成' in demoted['content'] and '分析完成' not in demoted['content'], reason


def test_a_verified_blocking_finding_still_blocks():
    from workbench.agent.research_review import _publication

    payload = {'content': '分析完成：结论如下。', 'completion_check': {'status': 'requirements_met'}}
    result = {'candidate_entry_id': 'e', 'verdict': 'issues_found', 'completion_check': {'status': 'requirements_met'},
              'findings': [{'severity': 'blocking', 'message': 'Criterion 2 unmet.', 'evidence_refs': ['plan']}]}
    published = _publication(payload, result, language='zh', mode='auto', review_count=2, remaining=None)
    assert '部分完成' in published['content'] and '分析完成' not in published['content']


WORDING = {'verdict': 'issues_found', 'findings': [{'severity': 'blocking',
           'message': 'The candidate says the test is absent; it is present.', 'evidence_refs': ['candidate', 'plan']}]}


def test_a_blocking_finding_about_the_answer_is_reviewed_again_for_a_new_answer(tmp_path):
    async def scenario():
        adapter = Adapter(verdict=WORDING)
        core, _, _ = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        before = adapter.reviews
        await _nudge(core)
        assert adapter.reviews > before  # the new answer is reviewed, not handed the old verdict
    asyncio.run(scenario())


def test_after_two_reuses_in_a_row_the_next_answer_is_reviewed_afresh(tmp_path):
    async def scenario():
        adapter = Adapter()
        core, _, repo = setup(tmp_path, adapter)
        wire(core)
        await core.prompt('完成分析', budget={'max_steps': 10, 'timeout_s': 30})
        first = adapter.reviews
        await _nudge(core); await _nudge(core)
        assert adapter.reviews == first  # two reuses
        await _nudge(core)
        assert adapter.reviews > first  # then a fresh review
    asyncio.run(scenario())
