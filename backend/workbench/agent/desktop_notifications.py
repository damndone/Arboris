"""Opt-in, same-Mac notices after a durable turn ends; never resume a model.

A session attempt is committed before OS dispatch. After an interruption its
outcome can be unknown; it is retained for inspection, never automatically
resent. An OS command accepting a notice is not proof of visible delivery.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import subprocess
import sys

from .plans import PlanStore
from .proposals import ProposalStore
from .turn_store import TERMINAL

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
NOTICES = {
    'approval_required': 'A step needs your approval. Open Workbench to review it.',
    'turn_ended': 'The Agent turn has ended. Open Workbench to review its status.',
}
SCRIPT = ('on run argv\n'
          'display notification (item 1 of argv) with title "Arboris Agent"\n'
          'end run')


def supported():
    return sys.platform == 'darwin' and Path('/usr/bin/osascript').is_file()


def send_on_mac(kind):
    if not supported():
        raise OSError('local macOS notifications unavailable')
    result = subprocess.run(['/usr/bin/osascript', '-e', SCRIPT, '--', NOTICES[kind]],
        timeout=2, capture_output=True, check=False)
    if result.returncode != 0:
        raise OSError('macOS notification command refused the request')


def _kind(repository, record):
    proposals = ProposalStore(repository.root, create=False)
    if record.status == 'completed' and any(proposals.latest_status(p.proposal_id) == 'pending'
            for p in proposals.latest_revisions_for_session(record.session_id)):
        return 'approval_required'
    plan = PlanStore(repository.root).current(record.session_id)
    if (record.status == 'completed' and record.execution_mode == 'auto' and plan is not None
            and plan.status in {'draft', 'needs_approval'} and plan.approved_version != plan.version):
        return 'approval_required'
    return 'turn_ended'


async def _dispatch(repository, record, kind):
    result = {'turn_id': record.turn_id, 'command_id': record.command_id, 'kind': kind,
              'automatic_retry': False}
    if repository.get_metadata(record.session_id).get('desktop_notifications') is not True:
        result['status'] = 'disabled'
    else:
        try:
            await asyncio.to_thread(send_on_mac, kind)
            result['status'] = 'submitted'  # macOS visibility/permission is not certified.
        except (OSError, TimeoutError, subprocess.SubprocessError) as error:
            result.update(status='failed', error_type=type(error).__name__)
    repository.append_once(record.session_id, 'desktop_notification_result', result,
        key=record.turn_id, stage='desktop_notification_result')


def schedule_notification(repository, record):
    """Called only after TurnJournal's terminal transition, while its owner holds the guard."""
    if record.status not in TERMINAL:
        return None
    if repository.get_metadata(record.session_id).get('desktop_notifications') is not True:
        return None
    if repository.count_on_branch(record.session_id, entry_type='desktop_notification_attempt', key=record.turn_id):
        return None
    kind = _kind(repository, record)
    repository.append_once(record.session_id, 'desktop_notification_attempt', {
        'turn_id': record.turn_id, 'command_id': record.command_id, 'kind': kind,
        'status': 'unknown', 'automatic_retry': False,
    }, key=record.turn_id, stage='desktop_notification_attempt')
    task = asyncio.create_task(_dispatch(repository, record, kind))
    _tasks.add(task)
    def finished(value):
        _tasks.discard(value)
        if not value.cancelled() and value.exception() is not None:
            logger.error('Desktop notification outcome could not be recorded; inspect the retained attempt.',
                         exc_info=value.exception())
    task.add_done_callback(finished)
    return task
