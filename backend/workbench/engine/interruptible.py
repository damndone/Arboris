"""Cancel a long pure computation from outside without waiting for it to finish.

Cancellation is cooperative: a run stops at ``env.checkpoint()``. A single
long call with no checkpoint inside (a 1,000,000-row OLS fit and its result
contract) kept a cancelled run going until the call returned, 5.3 s after
the request. ``run_interruptible`` runs such a call in a worker thread and
checks the run's stop reason while waiting; on a stop the run ends at once
and the worker's eventual result is discarded.

Only for calls that compute and return: nothing they do may persist, since
an abandoned worker can still finish after the run has stopped.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

#: How often a waiting run checks for a stop request (seconds).
POLL_S = 0.1


def run_interruptible(env: Any, call: Callable[[], T], *, drain_on_cancel: bool = False) -> T:
    """Run pure work; opt-in IV and statistics own/drain their cooperative workers.

    The default remains discard-on-cancel for existing callers. An owned caller
    must pass this same env.checkpoint into its computation; no second stop
    source is created here, and no single uninterruptible kernel is bounded.
    """
    checkpoint = getattr(env, "checkpoint", None)
    if getattr(env, "stop_reason", None) is None or checkpoint is None:
        return call()  # nothing could stop this run; no thread needed
    box: dict[str, Any] = {}
    context = contextvars.copy_context()

    def work() -> None:
        try:
            box["value"] = context.run(call)
        except BaseException as exc:  # handed back to the waiting run
            box["error"] = exc

    worker = threading.Thread(target=work, name="workbench-interruptible", daemon=not drain_on_cancel)
    worker.start()
    try:
        while worker.is_alive():
            checkpoint()  # raises RunInterruptionRequested on cancel or timeout
            worker.join(POLL_S)
    except BaseException as owner_error:
        if drain_on_cancel:
            worker.join()  # retain original owner exception after actual drain
            from .context import RunInterruptionRequested

            error = box.get("error")
            expected_cancel = (isinstance(owner_error, RunInterruptionRequested)
                               and isinstance(error, RunInterruptionRequested)
                               and owner_error.reason == error.reason)
            if error is not None and not expected_cancel:
                logging.getLogger(__name__).error(
                    "Owned computation worker failed while draining an owner interruption",
                    exc_info=(type(error), error, error.__traceback__),
                )
        raise
    if "error" in box:
        raise box["error"]
    if drain_on_cancel:
        checkpoint()  # finished pure work cannot bypass cancellation at publish
    return box["value"]
