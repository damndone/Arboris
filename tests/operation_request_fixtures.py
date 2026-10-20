"""Typed proposal setup for existing lifecycle and execution tests."""
from workbench.agent.operation_requests import OperationRequest


def admit_proposal(orchestrator, *, chain_id, command_id=None, proposal_id=None, session_id=None, **arguments):
    return orchestrator.admit_operation_request(
        OperationRequest.from_arguments(arguments), chain_id=chain_id, command_id=command_id,
        proposal_id=proposal_id, session_id=session_id,
    ).proposal
