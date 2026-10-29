"""Explicit task overlap with one cross-process NVIDIA HTTP request at a time."""
import asyncio
import os
from pathlib import Path
import time
from uuid import uuid4

from filelock import FileLock, Timeout

from .budget import BudgetStop, NVIDIA_BASE_URL, NVIDIA_MODEL, NVIDIA_PROVIDER_ID, RoundBudget


class NvidiaSerialCoordinator:
    """Keep the original single reservation/ticket rules across task processes.

    The HTTP lease survives the approved retry waits. A separate state lock lets
    queued senders observe stop without waiting for the HTTP lease. A dead
    owner's active state is evidence of an unknown request, never a free slot.
    """

    _change = RoundBudget._change

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + '.lock')
        self.http_lock = FileLock(str(self.path) + '.http.lock', thread_local=False)
        self.owner = uuid4().hex
        self.held = False
        self.wait_s = 0.0
        with self._change() as state:
            expected = {'schema': 'nvidia-shared-serial/v1', 'provider_id': NVIDIA_PROVIDER_ID,
                'base_url': NVIDIA_BASE_URL, 'model': NVIDIA_MODEL, 'min_start_interval_s': 2,
                'max_http_inflight': 1}
            if any(state.get(key) != value for key, value in expected.items()):
                raise ValueError('NVIDIA shared serial coordinator configuration changed')

    @property
    def state(self):
        if self.path.exists():
            import json
            return json.loads(self.path.read_text())
        return {'schema': 'nvidia-shared-serial/v1', 'provider_id': NVIDIA_PROVIDER_ID,
            'base_url': NVIDIA_BASE_URL, 'model': NVIDIA_MODEL, 'min_start_interval_s': 2,
            'max_http_inflight': 1, 'last_start': None, 'starts': [], 'active': None,
            'stopped': False, 'reason': None}

    @property
    def stopped(self):
        return self.state['stopped']

    def stop(self, reason):
        with self._change() as state:
            if not state['stopped']:
                state.update(stopped=True, reason=reason)

    async def acquire(self, abort_event=None):
        if self.held:
            if self.stopped:
                raise BudgetStop(self.state['reason'])
            return
        queued = time.monotonic()
        try:
            while True:
                state = self.state
                if state['stopped']:
                    raise BudgetStop(state['reason'])
                if abort_event is not None and abort_event.is_set():
                    self.stop('NVIDIA queued request cancelled before send; no further request authorized')
                    raise BudgetStop(self.state['reason'])
                try:
                    self.http_lock.acquire(timeout=0)
                except Timeout:
                    await asyncio.sleep(0.1)
                    continue
                refused = None
                with self._change() as state:
                    if state['stopped']:
                        refused = state['reason']
                    elif state['active'] is not None:
                        refused = 'NVIDIA orphaned serial request; unknown usage cannot be reclaimed'
                        state.update(stopped=True, reason=refused)
                    else:
                        state['active'] = {'owner': self.owner, 'pid': os.getpid(),
                            'acquired_at': time.time(), 'reservation': None}
                if refused:
                    self.http_lock.release()
                    raise BudgetStop(refused)
                self.held = True
                return
        finally:
            self.wait_s += max(0.0, time.monotonic() - queued)

    def record_start(self, *, reservation, round_ledger, request_sha256):
        if not self.held:
            self.stop('NVIDIA request has no shared serial HTTP lease')
            raise BudgetStop(self.state['reason'])
        # The HTTP lease excludes other starts. Release the state lock while
        # sleeping so another process can publish stop during the rate wait.
        while True:
            refused, delay = None, 0
            with self._change() as state:
                if state['stopped']:
                    refused = state['reason']
                elif not state['active'] or state['active']['owner'] != self.owner:
                    refused = 'NVIDIA shared serial HTTP lease owner changed'
                    state.update(stopped=True, reason=refused)
                else:
                    if state['last_start'] is not None:
                        delay = max(0, state['last_start'] + 2 - time.time())
                    if not delay:
                        entry = {'at': time.time(), 'owner': self.owner,
                            'reservation': reservation, 'round_ledger': str(round_ledger),
                            'request_sha256': request_sha256}
                        state['starts'].append(entry)
                        state['last_start'] = entry['at']
                        state['active'].update(entry)
            if refused:
                raise BudgetStop(refused)
            if not delay:
                return
            time.sleep(delay)

    def release(self, *, preserve_unknown=False):
        if not self.held:
            return
        try:
            with self._change() as state:
                active = state['active']
                if active and active['owner'] == self.owner:
                    if preserve_unknown:
                        active['outcome'] = 'unknown; retained'
                        if not state['stopped']:
                            state.update(stopped=True, reason='NVIDIA serial request ended with unknown usage')
                    else:
                        state['active'] = None
                else:
                    state.update(stopped=True, reason='NVIDIA shared serial HTTP lease owner changed on release')
        finally:
            self.held = False
            self.http_lock.release()
