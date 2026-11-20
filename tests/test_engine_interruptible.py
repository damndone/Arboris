"""A long pure call stops waiting on cancel; otherwise it behaves like a direct call."""

import contextvars
import threading
import time

import pytest

from workbench.engine.context import RunEnv
from workbench.engine.interruptible import run_interruptible
from workbench.engine.context import RunInterruptionRequested


def _env(stop):
    return RunEnv(run_root=None, run_id="r", recorder=None, stop_reason=stop)


def test_cancel_ends_the_wait_promptly():
    release = threading.Event()
    stops = {"reason": None}
    def slow():
        release.wait(10)
        return "late"
    threading.Timer(0.2, lambda: stops.update(reason="cancelled")).start()
    started = time.perf_counter()
    with pytest.raises(RunInterruptionRequested):
        run_interruptible(_env(lambda: stops["reason"]), slow)
    assert time.perf_counter() - started < 1.0
    release.set()


def test_result_errors_and_context_pass_through():
    marker = contextvars.ContextVar("marker", default=None)
    marker.set("seen")
    assert run_interruptible(_env(lambda: None), lambda: marker.get()) == "seen"
    with pytest.raises(ZeroDivisionError):
        run_interruptible(_env(lambda: None), lambda: 1 / 0)
    # Without a stop source there is no thread at all.
    assert run_interruptible(RunEnv(run_root=None, run_id="r", recorder=None),
                             lambda: threading.current_thread()) is threading.current_thread()
