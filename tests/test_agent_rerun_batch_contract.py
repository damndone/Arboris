"""Same-source Ask confirmations create siblings without advancing their source."""

import asyncio

from tests.operation_request_fixtures import admit_proposal
from tests.test_agent_proposal_operations import make_orchestrator, proposal_kwargs
from workbench.agent.chains import ChainStore, RerunExecutionResult


def test_same_source_reruns_complete_serially_with_original_approvals_and_no_replay(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    chains = ChainStore(orchestrator.repository.root)
    chains.create_root(chain_id='chain-a', run_family_id='family',
        active_head_run_id='run-1', agent_session_id='chain-session')
    proposals = [admit_proposal(orchestrator, **{
        **proposal_kwargs(),
        'changes': {'covariance': {'old': 'nonrobust', 'new': covariance}},
    }) for covariance in ['HC1', 'HC3']]
    requests = []

    async def executor(request):
        requests.append(request)
        return RerunExecutionResult(target_run_id=f'child-{request.proposal_id}',
            outputs={'status': 'completed'})

    completed = []
    for proposal in proposals:
        record = orchestrator.confirm_proposal(proposal.proposal_id,
            revision=proposal.revision, fingerprint=proposal.fingerprint, actor_type='user',
            current_context_fingerprint='ctx-1', current_active_head_run_id='run-1')
        assert (record.proposal_id, record.proposal_revision, record.proposal_fingerprint) == (
            proposal.proposal_id, proposal.revision, proposal.fingerprint)
        arguments = {'project_root': tmp_path, 'current_context_fingerprint': 'ctx-1',
            'current_active_head_run_id': 'run-1', 'rerun_executor': executor}
        result = asyncio.run(orchestrator.execute_confirmed_operation(record.record_id, **arguments))
        assert result.status == 'completed'
        assert chains.resolve_active_head('chain-a') == 'run-1'
        assert chains.resolve_active_head(result.execution['child_chain_id']) == result.outputs['target_run_id']
        # A transport retry of a terminal operation must not execute again.
        assert asyncio.run(orchestrator.execute_confirmed_operation(record.record_id, **arguments)) == result
        completed.append(result)

    assert len({result.record_id for result in completed}) == 2
    assert len({result.execution['child_chain_id'] for result in completed}) == 2
    assert len({result.outputs['target_run_id'] for result in completed}) == 2
    assert len(requests) == 2
    assert [request.proposal_id for request in requests] == [proposal.proposal_id for proposal in proposals]
    assert [request.changes for request in requests] == [proposal.changes for proposal in proposals]
    assert all(request.source_chain_id == 'chain-a' and request.source_run_id == 'run-1'
               and request.active_head_run_id == 'run-1' for request in requests)
