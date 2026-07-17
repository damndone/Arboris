from __future__ import annotations

from pathlib import Path
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional



def _read_history(path: Path) -> list[dict]:
    # Import lazily: importing ``workbench.agent.storage`` executes the agent
    # package exports, some of which import services that depend on events.
    # Keeping this edge lazy avoids a package-initialization cycle when this
    # low-level event module is imported on its own.
    from .agent.storage import read_jsonl

    return read_jsonl(path)


def _append_history(path: Path, event: dict) -> None:
    from .agent.storage import append_jsonl_atomic

    append_jsonl_atomic(path, event)


class EventManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[dict]] = {}
        self._subscribers: dict[str, set[queue.Queue]] = {}
        self._sequence: dict[str, int] = {}
        self._history_paths: dict[str, Path] = {}
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

    def register_run(self, run_id: str, history_path: Path | None = None) -> None:
        with self._lock:
            if history_path is not None:
                self._history_paths[run_id] = history_path
            if run_id not in self._history:
                history = []
                path = self._history_paths.get(run_id)
                if path is not None:
                    history = _read_history(path)
                self._history[run_id] = history
                self._subscribers[run_id] = set()
                self._sequence[run_id] = max(
                    (int(event.get("sequence", index)) for index, event in enumerate(history)),
                    default=-1,
                ) + 1

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
            history_path = self._history_paths.get(run_id)
            if history_path is not None:
                _append_history(history_path, event)

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
                self._history_paths.pop(run_id, None)

        t = threading.Thread(target=_cleanup, daemon=True)
        t.start()


    def _reset_for_testing(self) -> None:
        with self._lock:
            self._history.clear()
            self._subscribers.clear()
            self._sequence.clear()
            self._history_paths.clear()
            self._active_runs.clear()
            self._reserved_slots = 0


_event_manager: Optional[EventManager] = None


def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager(max_workers=1)
    return _event_manager
