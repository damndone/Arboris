"""One receipt pipeline for serial tools and independent read-only batches."""
from __future__ import annotations

import asyncio
import json

from .recovery import record_failure
from .tools import ToolRegistry, ToolResult
from .turn_journal import invocation_id

READ_CONCURRENCY = 4


def can_parallelize(core, calls):
    return isinstance(core.tool_runtime, ToolRegistry) and core.tool_runtime.parallel_read_batch(calls)


def _start(core, call):
    core.events.emit(core.session_id, 'tool_execution_start', {
        'tool_call_id':str(call.get('tool_call_id','')), 'tool_id':str(call.get('tool_id','')),
    }, command_id=core._active_command_id)


def _cancelled(core, call):
    return ToolResult(tool_call_id=str(call.get('tool_call_id','')), tool_id=str(call.get('tool_id','')),
        ok=False, error='agent_timeout' if core._timeout_requested else 'agent_aborted')


async def _invoke(core, call, tool_context):
    call_id = str(call.get('tool_call_id',''))
    try:
        return await core.tool_runtime.execute(call, session_id=core.session_id, metadata={
            **(tool_context or {}), 'command_id':core._active_command_id, 'provider_step':core._steps_used,
            'tool_call_id':call_id, 'invocation_id':invocation_id(core.session_id,core._active_command_id,core._steps_used,call_id)})
    except asyncio.CancelledError:
        if core._timeout_requested or core._abort_requested:
            return _cancelled(core,call)
        raise
    except Exception:
        return ToolResult(tool_call_id=call_id,tool_id=str(call.get('tool_id','')),ok=False,error='tool_runtime_error')


def _publish(core, call, result, recovered=None):
    if recovered is not None:
        payload = recovered
        if result.ok:
            core._answered_tool_calls[core._tool_call_fingerprint(call)] = result.tool_id
    else:
        payload = result.to_payload()
        fingerprint = core._tool_call_fingerprint(call)
        if result.ok and fingerprint in core._answered_tool_calls:
            payload = {**payload,'already_answered_this_turn':True,'guidance':
                'This exact inspection was already answered in this turn; its evidence is unchanged. '
                'Stop inspecting and either submit a proposal or answer the user.'}
            core.events.emit(core.session_id,'loop_guard',{'tool_id':result.tool_id,'reason':'repeated_inspection_replayed'},
                command_id=core._active_command_id)
        elif result.ok:
            core._answered_tool_calls[fingerprint] = result.tool_id
        payload = core._annotate_step_budget(payload)
    recovery = payload.get('bounded_recovery') if recovered is not None else None
    if recovery is None:
        recovery = record_failure(core.repository,core.session_id,core._active_command_id,core._steps_used,call,payload)
    if recovery is not None:
        if recovered is None:
            payload = {**payload,'bounded_recovery':recovery}
        core._last_tool_failure = recovery['reason']
    if core.turn_journal:
        entry = core.turn_journal.result_message(core,call,payload)
    else:
        entry = core.repository.append(core.session_id,'message',{'role':'tool','tool_call_id':result.tool_call_id,
            'name':result.tool_id,'command_id':core._active_command_id,
            'content':json.dumps(payload,ensure_ascii=False,sort_keys=True)})
    core.events.emit(core.session_id,'tool_execution_end',{'tool_call_id':result.tool_call_id,'tool_id':result.tool_id,
        'ok':result.ok,'entry_id':entry.entry_id,'error':result.error},command_id=core._active_command_id)
    return result, recovery


def _from_receipt(call,payload):
    return ToolResult(tool_call_id=str(call.get('tool_call_id','')),tool_id=str(call.get('tool_id','')),
        ok=payload['ok'],output=payload.get('output'),error=payload.get('error'),error_details=payload.get('error_details'))


async def run_single(core,call,*,tool_context,skip=False):
    _start(core,call)
    original = core.turn_journal.original_receipt(core,call) if core.turn_journal else None
    if original is not None:
        return _publish(core,call,_from_receipt(call,original),original)
    if skip:
        result = ToolResult(tool_call_id=str(call.get('tool_call_id','')),tool_id=str(call.get('tool_id','')),
                            ok=False,error='analysis_recovery_limit',output={'executed':False})
    else:
        if core.turn_journal:
            core.turn_journal.before_tool(core,call)
        task = asyncio.create_task(_invoke(core,call,tool_context))
        core._active_tool_task = task
        try:
            result = await task
        finally:
            if core._active_tool_task is task:
                core._active_tool_task = None
    return _publish(core,call,result)


async def run_reads(core,calls,*,tool_context):
    """Admit all intents first; settle every outcome before returning control."""
    originals = {}
    for call in calls:
        _start(core,call)
        original = core.turn_journal.original_receipt(core,call) if core.turn_journal else None
        originals[call['tool_call_id']] = original
        if original is None and core.turn_journal:
            core.turn_journal.before_tool(core,call)
    semaphore = asyncio.Semaphore(READ_CONCURRENCY)
    async def invoke(call):
        async with semaphore:
            return await _invoke(core,call,tool_context)
    fresh = [call for call in calls if originals[call['tool_call_id']] is None]
    tasks = [asyncio.create_task(invoke(call)) for call in fresh]
    try:
        results = await asyncio.gather(*tasks,return_exceptions=True)
    except asyncio.CancelledError:
        if not (core._abort_requested or core._timeout_requested):
            raise
        results = await asyncio.gather(*tasks,return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    produced = {}
    for call, result in zip(fresh,results,strict=True):
        if isinstance(result,asyncio.CancelledError) and (core._abort_requested or core._timeout_requested):
            result = _cancelled(core,call)
        elif isinstance(result,BaseException):
            raise result
        produced[call['tool_call_id']] = result
    # Model-visible results keep request order. This is also the ordinary
    # receipt/repair pipeline; parallel reads create no second receipt owner.
    return {call['tool_call_id']:_publish(core,call,
        _from_receipt(call,originals[call['tool_call_id']]) if originals[call['tool_call_id']] is not None
        else produced[call['tool_call_id']], originals[call['tool_call_id']]) for call in calls}
