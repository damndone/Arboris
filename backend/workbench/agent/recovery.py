"""Durable two-attempt recovery for a logical tool/operation step.

Failure records belong to the current user command and active session branch.
Changing numerical tuning, labels or call IDs does not reset that step. A new
explicit user command has its own budget; this module never retries an effect.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping

from ..canonical import sha256_canonical

ATTEMPT_LIMIT = 2


def prepare_completion_recovery(core, payload, entry):
    """Persist one bounded correction; restart reuses it and the original budget."""
    result = payload.get('completion_check') or {}
    if (payload.get('stop_reason') != 'stop' or payload.get('tool_calls')
            or result.get('status') != 'partial' or result.get('recovery_action') != 'inspect_and_repair'
            or not core._has_step_left()):
        return False
    question = getattr(core, '_user_text', None)
    if question:
        # A partial plan can outlive its command. A coefficient question or
        # a stop request must not silently resume that plan's full analysis.
        if re.search(r'停止|暂停|取消|\b(?:stop|pause|cancel)\b', question, re.I):
            return False
        original = result.get('recovery_question_sha256')
        explicit = re.fullmatch(r'\s*(?:请)?(?:继续|完成)(?:(?:原|全部|完整)?(?:分析|研究))?(?:和报告)?[。！!]?\s*'
                                r'|\s*(?:please\s+)?(?:continue|complete|finish)(?:\s+the)?\s+(?:analysis|research)[.!]?\s*',
                                question, re.I)
        # A request to finish this analysis, in any wording (the harness's
        # "请继续，把这项分析做完……" failed the exact match above, so three
        # nudges in the paid fix2 round ended with the bare partial note).
        # A narrowed request ("继续，但只告诉我系数") does not match.
        finish = re.search(r'(?:继续|做完|完成|接着做).{0,12}(?:分析|研究)|(?:分析|研究).{0,8}(?:做完|完成)'
                           r'|\b(?:continue|finish|complete)\b.{0,24}\b(?:analysis|analyses|research)\b',
                           question, re.I)
        if original and sha256_canonical(question) != original and not explicit and not finish:
            return False
    previous = [e for e in core.repository.get_branch(core.session_id)
                if e.entry_type == 'custom_message' and e.payload.get('message_type') == 'completion_recovery'
                and e.payload.get('command_id') == core._active_command_id]
    if any(e.payload.get('candidate_entry_id') == entry.entry_id for e in previous):
        return True
    if len(previous) >= ATTEMPT_LIMIT:
        return False
    content = ('The delivery gate still reports partial completion. Continue this same analysis within '
        'the ORIGINAL remaining command budget, plan, source, permissions and approval rules. '
        'Call inspect_analysis_completion to obtain exact verified artifact bindings and repair_steps. '
        'Bind exactly one primary model chosen by the fixed research question/specification; other '
        'predeclared fits belong in sensitivity. Do not select by significance, guess artifact IDs, '
        'refit merely to repair a reference, or weaken completion. If AR has not been requested for '
        'the fixed native IV fit, propose iv.ar_confidence explicitly through the shared operation path. '
        'Use an actual report that covers all selected models, diagnostics, sensitivity and new AR '
        'evidence, composing one through the existing operation path if needed. Stop for approval, '
        'a scientific/method limitation, or an unresolved selection that needs the user; state the '
        'precise remaining gap instead of claiming completion.\nMissing: '
        + json.dumps(result.get('missing', [])[:32], ensure_ascii=False)
        + _next_step(result))[:6000]
    core.repository.append_once(core.session_id, 'custom_message', {
        'message_type': 'completion_recovery', 'audience': 'model', 'model_role': 'user',
        'name': 'workbench_completion_recovery', 'content': content,
        'command_id': core._active_command_id, 'candidate_entry_id': entry.entry_id,
        'attempt': len(previous)+1, 'limit': ATTEMPT_LIMIT,
    }, key=core._active_command_id, stage='completion_recovery:' + entry.entry_id)
    return True


def _next_step(result):
    """The gate's concrete next action, so the repair is a proposal, not a guess."""
    lines = []
    if result.get('next_step'):
        lines.append('Next step: ' + str(result['next_step']))
    if result.get('compose_report'):
        lines.append('compose_report: ' + json.dumps(result['compose_report'], ensure_ascii=False))
    if result.get('sensitivity_options'):
        lines.append('sensitivity_options: ' + json.dumps(result['sensitivity_options'], ensure_ascii=False))
    if result.get('primary_candidates'):
        lines.append('primary_candidates: ' + json.dumps(result['primary_candidates'], ensure_ascii=False))
    return ('\n' + '\n'.join(lines)) if lines else ''


async def continue_completion_recovery(core, payload, entry, *, request_id, context_fingerprint, tool_context):
    command = core._active_command_id
    core.events.emit(core.session_id, 'message_end', {'entry_id': entry.entry_id,
        'content': payload['content'], 'stop_reason': 'revised', 'error': None}, command_id=command)
    core.events.emit(core.session_id, 'turn_end', {'stop_reason': 'completion_recovery'}, command_id=command)
    core.events.emit(core.session_id, 'save_point', {'entry_id': entry.entry_id,
        'context_fingerprint': context_fingerprint}, command_id=command)
    core._active_request_id = None
    core._active_message_started = False
    core._active_turn_started = False
    if core.turn_journal:
        core.turn_journal.save(core, 'ready')
    return await core._run_turn(None, append_user=False, tool_context=tool_context)


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
