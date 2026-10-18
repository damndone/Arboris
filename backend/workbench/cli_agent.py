"""Headless Agent entry using the same turn and permission path as HTTP.

No proposal is confirmed implicitly. An approval request is a nonzero, durable
result for an unattended caller, rather than an instruction to bypass a gate.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable, Literal

import typer
import typer.main

from .cli_commands import CommandError


async def run_headless(
    project_root: Path,
    prompt: str,
    *,
    mode: Literal['ask', 'auto'] = 'ask',
    session_id: str | None = None,
    focus: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Run one command with durable events; admission remains server-owned."""
    from .http import agent_routes as routes

    body = routes.AgentTurnRequest(question=prompt, execution_mode=mode)
    root = str(project_root)
    if session_id is None:
        session = routes.create_agent_session(
            project_root=root,
            body=routes.AgentSessionCreateRequest(role='chain', focus=focus),
        )
        session_id = str(session['session_id'])
    else:
        routes.get_agent_session(session_id=session_id, project_root=root)
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
    task = asyncio.create_task(routes.run_agent_turn(session_id, root, body))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.1)
            drain()
        result = await task
    except BaseException:
        # A broken output stream or Ctrl-C must not leave an unattended model
        # task running without its event consumer. Existing abort semantics apply.
        try:
            await routes.abort_agent_turn(session_id, root)
        except Exception:
            pass
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    finally:
        drain()
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


def build_agent_group(json_value: Callable, fail: Callable) -> Any:
    group = typer.Typer(name='agent')

    @group.callback()
    def agent() -> None:
        """Run the research Agent without a browser; stream durable JSON events."""

    @group.command('run')
    def run(
        project: Path = typer.Option(..., '--project', exists=True, file_okay=False),
        prompt: str = typer.Option(..., '--prompt'),
        mode: str = typer.Option('ask', '--mode', help='ask or auto; approval gates remain enforced.'),
        session: str | None = typer.Option(None, '--session', help='Continue this existing conversation with a new prompt.'),
        focus: str | None = typer.Option(None, '--focus', help='Focus JSON, inline or @file, as accepted by the Agent API.'),
        events_jsonl: Path | None = typer.Option(None, '--events-jsonl', help='Create a new local event evidence file; never overwrite.'),
    ) -> None:
        """Run one prompt. Exit 3 means explicit approval is required; no card is auto-approved."""
        handle = None
        try:
            if mode not in {'ask', 'auto'}:
                raise CommandError('--mode must be ask or auto')
            if not prompt.strip():
                raise CommandError('--prompt must not be blank')
            focus_value = json_value(focus, '--focus')
            if focus_value is not None and not isinstance(focus_value, dict):
                raise CommandError('--focus must be a JSON object')
            if session is not None and focus_value is not None:
                raise CommandError('--focus applies to a new session; use the existing session focus when resuming')
            if events_jsonl is not None:
                fd = os.open(events_jsonl.expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                handle = os.fdopen(fd, 'w', encoding='utf-8')

            def emit(event: dict[str, Any]) -> None:
                line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                if handle is not None:
                    handle.write(line + '\n')
                    handle.flush()
                typer.echo(line)

            result = asyncio.run(run_headless(
                project.resolve(), prompt.strip(), mode=mode,
                session_id=session, focus=focus_value, on_event=emit,
            ))
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
        if result['status'] in {'failed', 'cancelled', 'interrupted'}:
            raise typer.Exit(1)

    return typer.main.get_command(group)
