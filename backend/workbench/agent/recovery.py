"""Durable two-attempt recovery for a logical tool/operation step.

Failure records belong to the current user command and active session branch.
Changing numerical tuning, labels or call IDs does not reset that step. A new
explicit user command has its own budget; this module never retries an effect.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from ..canonical import sha256_canonical

ATTEMPT_LIMIT = 2


def record_failure(repository, session_id, command_id, provider_step, call, payload):
    output = payload.get('output')
    output = output if isinstance(output, Mapping) else {}
    operation = output.get('operation')
    operation = operation if isinstance(operation, Mapping) else {}
    failed = (payload.get('ok') is False or operation.get('status') == 'failed'
              or output.get('status') in {'failed', 'needs_target_decision'}
              or output.get('executed') is False and (output.get('error') or output.get('denied')))
    if not failed or payload.get('error') in {'agent_aborted', 'agent_timeout', 'tool_runtime_error', 'analysis_recovery_limit'}:
        return None
    arguments = call.get('arguments')
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            arguments = {}
    arguments = arguments if isinstance(arguments, Mapping) else {}
    target = arguments.get('target') or arguments.get('source') or arguments
    target = target if isinstance(target, Mapping) else {}
    changes = arguments.get('changes')
    steps = changes.get('steps', []) if isinstance(changes, Mapping) else []
    steps = steps if isinstance(steps, list) else []
    scope = {'tool_id': call.get('tool_id'), 'operation_id': arguments.get('operation_id'),
        'source': {k: target.get(k) for k in ['run_id', 'artifact_id', 'node_ref']},
        'operations': sorted({s['operation_id'] for s in steps if isinstance(s, Mapping)
                              and isinstance(s.get('operation_id'), str)})}
    scope_hash = sha256_canonical(scope)
    details = payload.get('error_details') or []
    first = details[0] if details and isinstance(details[0], Mapping) else {}
    reason = str(first.get('message') or operation.get('error') or output.get('error')
                 or output.get('reason') or payload.get('error') or output.get('status'))[:300]
    invocation = sha256_canonical([command_id, provider_step, call.get('tool_call_id')])
    repository.append_once(session_id, 'analysis_step_failure', {
        'command_id': command_id, 'scope_sha256': scope_hash, 'tool_id': call.get('tool_id'),
        'reason': reason, 'invocation_sha256': invocation,
    }, key=invocation, stage='analysis_step_failure')
    attempts = sum(e.entry_type == 'analysis_step_failure' and e.payload['command_id'] == command_id
                   and e.payload['scope_sha256'] == scope_hash for e in repository.get_branch(session_id))
    return {'attempts': attempts, 'limit': ATTEMPT_LIMIT, 'exhausted': attempts >= ATTEMPT_LIMIT,
        'reason': reason, 'scope_sha256': scope_hash,
        'guidance': ('Stop automatic retries of this step. Report partial completion, the actual failure, and correction options; wait for the user.'
                     if attempts >= ATTEMPT_LIMIT else
                     'Inspect the actual failure before one remaining corrective attempt. Preserve source and approval requirements; do not tune to obtain significance.')}
