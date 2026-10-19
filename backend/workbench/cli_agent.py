"""Headless Agent entry using the same turn and permission path as HTTP.

No proposal is confirmed implicitly. An approval request is a nonzero, durable
result for an unattended caller, rather than an instruction to bypass a gate.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import typer
import typer.main

from .cli_commands import CommandError
from .agent.model import OpenAICompatibleModelAdapter


async def run_headless(
    project_root: Path,
    prompt: str,
    *,
    mode: Literal['ask', 'auto'] | None = 'ask',
    execution_policy: Literal['auto_read_only', 'proposal_only'] | None = None,
    session_id: str | None = None,
    focus: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Run one command with durable events; admission remains server-owned."""
    from .http import agent_routes as routes

    body_kwargs: dict[str, Any] = {'question': prompt}
    if mode is not None:
        body_kwargs['execution_mode'] = mode
    if execution_policy is not None:
        body_kwargs['execution_policy'] = execution_policy
    body = routes.AgentTurnRequest(**body_kwargs)
    root = str(project_root)
    if session_id is None:
        session = routes.create_agent_session(
            project_root=root,
            body=routes.AgentSessionCreateRequest(role='chain', focus=focus),
        )
        session_id = str(session['session_id'])
    else:
        routes.get_agent_session(session_id=session_id, project_root=root)
    return await _stream_headless_turn(
        project_root, session_id, mode=body.execution_mode, on_event=on_event,
        start_turn=lambda: routes.run_agent_turn(session_id, root, body),
    )


async def continue_headless(
    project_root: Path,
    session_id: str,
    *,
    mode: Literal['ask', 'auto'] | None = 'ask',
    execution_policy: Literal['auto_read_only', 'proposal_only'] | None = None,
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Continue an existing conversation without approving any pending action."""
    from .http import agent_routes as routes

    root = str(project_root)
    routes.get_agent_session(session_id=session_id, project_root=root)
    body_kwargs: dict[str, Any] = {}
    if mode is not None:
        body_kwargs['execution_mode'] = mode
    if execution_policy is not None:
        body_kwargs['execution_policy'] = execution_policy
    body = routes.AgentContinueRequest(**body_kwargs)
    return await _stream_headless_turn(
        project_root, session_id, mode=body.execution_mode, on_event=on_event,
        start_turn=lambda: routes.continue_agent_turn(session_id, root, body),
    )


async def resume_headless(
    project_root: Path,
    session_id: str,
    turn_id: str,
    *,
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Resume the recorded command with its original execution mode and budget."""
    from .http import agent_routes as routes

    root = str(project_root)
    state = routes.get_agent_turn_state(session_id, root)
    record = next((item for item in state['turns'] if item['turn_id'] == turn_id), None)
    if record is None:
        raise CommandError('AGENT_TURN_NOT_FOUND: Agent turn was not found')
    mode = record['execution_mode']
    if mode not in {'ask', 'auto'}:
        raise CommandError('invalid saved Agent execution mode')
    body = routes.AgentResumeRequest(turn_id=turn_id)
    return await _stream_headless_turn(
        project_root, session_id, mode=mode, on_event=on_event,
        start_turn=lambda: routes.resume_agent_turn(session_id, root, body),
    )


async def _stream_headless_turn(
    project_root: Path,
    session_id: str,
    *,
    mode: Literal['ask', 'auto'],
    on_event: Callable[[dict[str, Any]], None],
    start_turn: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Use one event, cancellation and result boundary for run and continue."""
    from .http import agent_routes as routes

    root = str(project_root)
    # Replay the session from its start, including creation and earlier turns;
    # consumers deduplicate by (session_id, seq), exactly as the UI does.
    after_seq = 0

    def drain() -> None:
        nonlocal after_seq
        result = routes.get_agent_events(session_id, root, after_seq=after_seq)
        for event in result['events']:
            on_event(event)
            after_seq = int(event['seq'])

    drain()
    task = asyncio.create_task(start_turn())
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.1)
            drain()
        result = await task
        drain()
    except BaseException:
        # A broken output stream or Ctrl-C must not leave an unattended model
        # task running without its event consumer. Capture the exact descendant:
        # a rejected request must never abort another caller's session turn.
        owned = routes.turn_registry.owned_task_for(task)

        async def stop_and_drain() -> None:
            if owned is not None and not owned.done():
                try:
                    await routes.abort_agent_turn(session_id, root)
                except Exception:
                    pass
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if owned is not None:
                await asyncio.gather(owned, return_exceptions=True)

        cleanup = asyncio.create_task(stop_and_drain())
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Repeated Ctrl-C must not close the event loop while an
                # operation is still binding its effect and releasing leases.
                continue
        cleanup.result()
        # Do not retry the failed output sink or replace its original exception.
        raise
    proposals = routes.get_agent_proposals(session_id, root)['proposals']
    pending = [item for item in proposals if item.get('status') == 'pending']
    plan = routes.get_agent_plan(session_id, root)['plan']
    status = result.get('status')
    if pending:
        status = 'awaiting_approval'
    elif mode == 'auto' and plan and plan['status'] in {'draft', 'needs_approval'}:
        status = 'awaiting_plan_approval'
    return {
        'type': 'agent_result',
        'session_id': session_id,
        'status': status,
        'assistant': result['assistant'],
        'pending_proposals': pending,
        'plan': plan,
    }


_SAFE_CONFIG_FIELDS = (
    'base_url', 'model', 'timeout_s', 'provider_id', 'provider_name', 'source',
    'context_window_tokens', 'supports_1m', 'supports_vision',
)


def _journal_directory(project_root: Path, record: Path | None, replay: Path | None) -> Path | None:
    if record is not None and replay is not None:
        raise CommandError('--record-journal and --replay-journal are mutually exclusive')
    path = record if record is not None else replay
    if path is None:
        return None
    if not path.is_absolute() or '..' in path.parts or not path.is_dir():
        raise CommandError('journal directory must be absolute and already exist')
    if path.resolve() != path:
        raise CommandError('journal directory must not contain symlinks')
    if path == project_root or project_root in path.parents:
        raise CommandError('journal directory must be outside the project fixture')
    return path


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _fixture_sha256(project_root: Path) -> str:
    """Bind every initial path and file byte; never omit runtime/contract fields."""
    import hashlib
    import stat

    entries = []
    for path in sorted(project_root.rglob('*')):
        observed = path.lstat()
        relative = str(path.relative_to(project_root))
        if stat.S_ISDIR(observed.st_mode):
            entries.append({'path': relative, 'kind': 'directory'})
        elif stat.S_ISREG(observed.st_mode):
            with path.open('rb') as handle:
                before = os.fstat(handle.fileno())
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
                after = os.fstat(handle.fileno())
            signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if signature(before) != signature(observed) or signature(after) != signature(before):
                raise CommandError('project fixture changed while hashing')
            entries.append({'path': relative, 'kind': 'file', 'sha256': digest})
        else:
            raise CommandError('project fixture must contain only regular files and directories')
    return hashlib.sha256(_json_bytes(entries)).hexdigest()


def _safe_config(config) -> dict[str, Any]:
    from urllib.parse import urlsplit

    value = {field: getattr(config, field) for field in _SAFE_CONFIG_FIELDS}
    if (any(type(value[field]) is not str for field in (
            'base_url', 'model', 'provider_id', 'provider_name', 'source'))
            or type(value['timeout_s']) not in {int, float} or value['timeout_s'] <= 0
            or type(value['supports_1m']) is not bool or type(value['supports_vision']) is not bool
            or value['context_window_tokens'] is not None and (
                type(value['context_window_tokens']) is not int or value['context_window_tokens'] <= 0)):
        raise CommandError('journal runtime config has invalid safe fields')
    parsed = urlsplit(value['base_url'])
    if (parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or not value['model'].strip()):
        raise CommandError('journal config requires a credential-free base URL and model')
    _json_bytes(value)
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CommandError('duplicate journal runtime field')
        value[key] = item
    return value


def _read_runtime(journal) -> dict[str, Any]:
    value = json.loads(journal.read_runtime(), object_pairs_hook=_unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(CommandError('nonfinite journal value')))
    fields = {'schema', 'input', 'fixture_sha256', 'config', 'complete', 'model_sha256', 'business_sha256'}
    if (type(value) is not dict or set(value) != fields
            or value['schema'] != 'workbench.headless-journal.v1' or value['complete'] is not True
            or type(value['input']) is not dict or type(value['config']) is not dict
            or set(value['config']) != set(_SAFE_CONFIG_FIELDS)):
        raise CommandError('journal runtime is incomplete or unsupported')
    for field in ('fixture_sha256', 'model_sha256', 'business_sha256'):
        digest = value[field]
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise CommandError('journal runtime has an invalid digest')
    return value


async def _journaled_turn(
    start_turn: Callable[[], Awaitable[dict[str, Any]]], *, project_root: Path,
    request: dict[str, Any], journal: Path | None, replay: bool,
) -> dict[str, Any]:
    if journal is None:
        return await start_turn()
    from .agent.business_identity import business_identity_scope
    from .agent.headless_journal import open_headless_journal
    from .agent.model_replay import RecordingAdapter, ReplayAdapter
    from .agent.runtime_adapter import headless_runtime_scope
    from .llm.config import LLMConfig

    with open_headless_journal(journal) as storage:
        fixture = _fixture_sha256(project_root)
        if replay:
            manifest = _read_runtime(storage)
            if _json_bytes(manifest['input']) != _json_bytes(request):
                raise CommandError('journal command input does not match the recorded input')
            if manifest['fixture_sha256'] != fixture:
                raise CommandError('project fixture does not match the recorded pre-turn state')
            for name in ('model', 'business'):
                if storage.sha256(f'{name}.jsonl') != manifest[f'{name}_sha256']:
                    raise CommandError(f'{name} journal digest does not match runtime manifest')
            config = LLMConfig(api_key='', **manifest['config'])
            _safe_config(config)
            adapter = ReplayAdapter(root=journal, name='model.jsonl')
            adapter.assert_complete()
            with business_identity_scope(mode='replay', root=journal, name='business.jsonl'):
                with headless_runtime_scope(adapter_factory=lambda _: adapter, config=config, offline=True):
                    result = await start_turn()
                    adapter.assert_consumed()
            return result

        manifest = {'schema': 'workbench.headless-journal.v1', 'input': request,
                    'fixture_sha256': fixture, 'config': None, 'complete': False,
                    'model_sha256': None, 'business_sha256': None}
        # Exclusive creation keeps an interrupted attempt visible and never overwrites evidence.
        with storage.create_runtime(_json_bytes(manifest) + b'\n') as writer:
            def save() -> None:
                writer.save(_json_bytes(manifest) + b'\n')

            def factory(config):
                manifest['config'] = _safe_config(config)
                save()
                return RecordingAdapter(OpenAICompatibleModelAdapter(config), root=journal, name='model.jsonl')

            with business_identity_scope(mode='record', root=journal, name='business.jsonl'):
                with headless_runtime_scope(adapter_factory=factory):
                    result = await start_turn()
            ReplayAdapter(root=journal, name='model.jsonl').assert_complete()
            for name in ('model', 'business'):
                manifest[f'{name}_sha256'] = storage.sha256(f'{name}.jsonl')
            manifest['complete'] = True
            save()
        return result


def build_agent_group(json_value: Callable, fail: Callable) -> Any:
    group = typer.Typer(name='agent')

    @group.callback()
    def agent() -> None:
        """Run the research Agent without a browser; stream durable JSON events."""

    def invoke_turn(build_turn: Callable, events_jsonl: Path | None) -> None:
        handle = None
        try:
            start_turn = build_turn()
            if events_jsonl is not None:
                fd = os.open(events_jsonl.expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                handle = os.fdopen(fd, 'w', encoding='utf-8')

            def emit(event: dict[str, Any]) -> None:
                line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                if handle is not None:
                    handle.write(line + '\n')
                    handle.flush()
                typer.echo(line)

            result = asyncio.run(start_turn(emit))
            typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        except (CommandError, OSError, ValueError) as exc:
            fail(exc if isinstance(exc, CommandError) else CommandError(str(exc)))
            return
        except Exception as exc:
            from .api_errors import WorkbenchAPIError
            if isinstance(exc, WorkbenchAPIError):
                fail(CommandError(f'{exc.code}: {exc.message}'))
                return
            raise
        finally:
            if handle is not None:
                handle.close()
        if result['status'] in {'awaiting_approval', 'awaiting_plan_approval'}:
            raise typer.Exit(3)
        if result['status'] in {'failed', 'cancelled', 'interrupted', 'blocked'}:
            raise typer.Exit(1)

    @group.command('run')
    def run(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        prompt: str = typer.Option(..., '--prompt'),
        mode: str = typer.Option('ask', '--mode', help='ask or auto; approval gates remain enforced.'),
        session: str | None = typer.Option(None, '--session', help='Continue this existing conversation with a new prompt.'),
        focus: str | None = typer.Option(None, '--focus', help='Focus JSON, inline or @file, as accepted by the Agent API.'),
        events_jsonl: Path | None = typer.Option(None, '--events-jsonl', help='Create a new local event evidence file; never overwrite.'),
        record_journal: Path | None = typer.Option(None, '--record-journal', help='Record this actual provider call and business identities in a new journal.'),
        replay_journal: Path | None = typer.Option(None, '--replay-journal', help='Strict local replay; requires an existing session and exact pre-turn fixture at the same path.'),
    ) -> None:
        """Run one prompt. Exit 3 means explicit approval is required; no card is auto-approved."""
        def build_turn():
            if mode not in {'ask', 'auto'}:
                raise CommandError('--mode must be ask or auto')
            if not prompt.strip():
                raise CommandError('--prompt must not be blank')
            focus_value = json_value(focus, '--focus')
            if focus_value is not None and not isinstance(focus_value, dict):
                raise CommandError('--focus must be a JSON object')
            if session is not None and focus_value is not None:
                raise CommandError('--focus applies to a new session; use the existing session focus when resuming')
            root = project.resolve()
            journal = _journal_directory(root, record_journal, replay_journal)
            request = {'command': 'run', 'project_root': str(root), 'prompt': prompt.strip(),
                       'session_id': session, 'mode': mode, 'focus': focus_value}
            return lambda emit: _journaled_turn(
                lambda: run_headless(root, prompt.strip(), mode=mode,
                    session_id=session, focus=focus_value, on_event=emit),
                project_root=root, request=request, journal=journal, replay=replay_journal is not None,
            )

        invoke_turn(build_turn, events_jsonl)

    @group.command('continue')
    def continue_command(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        session: str = typer.Option(..., '--session', help='Existing conversation to continue.'),
        mode: str = typer.Option('ask', '--mode', help='ask or auto; approval gates remain enforced.'),
        events_jsonl: Path | None = typer.Option(None, '--events-jsonl', help='Create a new local event evidence file; never overwrite.'),
        record_journal: Path | None = typer.Option(None, '--record-journal', help='Record this actual provider call and business identities in a new journal.'),
        replay_journal: Path | None = typer.Option(None, '--replay-journal', help='Strict local replay; requires an existing session and exact pre-turn fixture at the same path.'),
    ) -> None:
        """Continue after an explicit approval or result. Exit 3 still means approval is required."""
        def build_turn():
            if mode not in {'ask', 'auto'}:
                raise CommandError('--mode must be ask or auto')
            root = project.resolve()
            journal = _journal_directory(root, record_journal, replay_journal)
            request = {'command': 'continue', 'project_root': str(root), 'session_id': session, 'mode': mode}
            return lambda emit: _journaled_turn(
                lambda: continue_headless(root, session, mode=mode, on_event=emit),
                project_root=root, request=request, journal=journal, replay=replay_journal is not None,
            )

        invoke_turn(build_turn, events_jsonl)

    @group.command('resume')
    def resume_command(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        session: str = typer.Option(..., '--session'),
        turn: str = typer.Option(..., '--turn', help='Exact interrupted command to resume.'),
        events_jsonl: Path | None = typer.Option(None, '--events-jsonl'),
    ) -> None:
        """Resume one durable command; unknown tool receipts remain interrupted."""
        invoke_turn(lambda: lambda emit: resume_headless(
            project.resolve(), session, turn, on_event=emit,
        ), events_jsonl)

    @group.command('turn-state')
    def turn_state(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        session: str = typer.Option(..., '--session'),
    ) -> None:
        """Read durable command state without loading a model or running tools."""
        try:
            from .http import agent_routes as routes

            result = routes.get_agent_turn_state(session, str(project.resolve()))
            typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        except (CommandError, OSError, ValueError) as exc:
            fail(exc if isinstance(exc, CommandError) else CommandError(str(exc)))
        except Exception as exc:
            from .api_errors import WorkbenchAPIError
            if isinstance(exc, WorkbenchAPIError):
                fail(CommandError(f'{exc.code}: {exc.message}'))
                return
            raise

    @group.command('plan-approve')
    def plan_approve(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        session: str = typer.Option(..., '--session', help='Conversation containing the plan.'),
        version: int = typer.Option(..., '--version', help='Exact plan version reviewed by the person.'),
    ) -> None:
        """Explicitly approve one plan version without running the Agent."""
        try:
            from .http import agent_routes as routes

            result = routes.approve_agent_plan(
                session, str(project.resolve()), routes.AgentPlanApproveRequest(version=version),
            )
            typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        except (CommandError, OSError, ValueError) as exc:
            fail(exc if isinstance(exc, CommandError) else CommandError(str(exc)))
            return
        except Exception as exc:
            from .api_errors import WorkbenchAPIError
            if isinstance(exc, WorkbenchAPIError):
                fail(CommandError(f'{exc.code}: {exc.message}'))
                return
            raise

    return typer.main.get_command(group)
