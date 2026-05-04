from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional


class EventManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[dict]] = {}
        self._subscribers: dict[str, set[queue.Queue]] = {}
        self._sequence: dict[str, int] = {}
        self._active_runs: set[str] = set()
        self._reserved_slots = 0
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    # --- slot lifecycle ---

    def try_acquire_slot(self) -> bool:
        with self._lock:
            if self._reserved_slots >= self._max_workers:
                return False
            self._reserved_slots += 1
            return True

    def mark_active(self, run_id: str) -> None:
        with self._lock:
            self._active_runs.add(run_id)

    def release_slot(self, run_id: str | None) -> None:
        with self._lock:
            if self._reserved_slots > 0:
                self._reserved_slots -= 1
            if run_id is not None:
                self._active_runs.discard(run_id)

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._active_runs

    @property
    def executor(self) -> ThreadPoolExecutor:
        return self._executor

    # --- event subscriptions ---

    def register_run(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._history:
                self._history[run_id] = []
                self._subscribers[run_id] = set()
                self._sequence[run_id] = 0

    def subscribe(self, run_id: str) -> tuple[queue.Queue, list[dict]]:
        with self._lock:
            q: queue.Queue = queue.Queue()
            self._subscribers.setdefault(run_id, set()).add(q)
            snapshot = list(self._history.get(run_id, []))
            return q, snapshot

    def unsubscribe(self, run_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(run_id)
            if subs is not None:
                subs.discard(subscriber)

    # --- event emission ---

    def emit(self, run_id: str, fields: dict) -> None:
        with self._lock:
            seq = self._sequence.get(run_id, 0)
            self._sequence[run_id] = seq + 1

            event = dict(fields)
            event.setdefault("run_id", run_id)
            event.setdefault("sequence", seq)
            event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            event.setdefault("step", None)
            event.setdefault("message", "")
            event.setdefault("status", None)

            self._history.setdefault(run_id, []).append(event)

            for sub in list(self._subscribers.get(run_id, set())):
                sub.put(event)

    def emit_terminal(self, run_id: str, status: str, message: str) -> None:
        self.emit(
            run_id,
            {
                "event": f"workflow_{status}",
                "step": None,
                "message": message,
                "status": status,
            },
        )
        with self._lock:
            for sub in list(self._subscribers.get(run_id, set())):
                sub.put(None)
        self.schedule_cleanup(run_id, delay=60)

    def schedule_cleanup(self, run_id: str, delay: int = 60) -> None:
        def _cleanup() -> None:
            import time
            time.sleep(delay)
            with self._lock:
                self._history.pop(run_id, None)
                self._subscribers.pop(run_id, None)
                self._sequence.pop(run_id, None)

        t = threading.Thread(target=_cleanup, daemon=True)
        t.start()


    def _reset_for_testing(self) -> None:
        with self._lock:
            self._history.clear()
            self._subscribers.clear()
            self._sequence.clear()
            self._active_runs.clear()
            self._reserved_slots = 0


_event_manager: Optional[EventManager] = None


def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager(max_workers=1)
    return _event_manager
