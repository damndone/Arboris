"""Time inside a turn that the caller declares is not the Agent's.

An evaluation harness that holds provider requests back to stay under a route's rate
declares how long it has held them, and a turn's wall budget leaves that time out.
With nothing declared, nothing is left out and the budget is plain elapsed time.
"""
from __future__ import annotations

from collections.abc import Callable

_source: Callable[[], float] | None = None


def exclude_waits(source: Callable[[], float] | None) -> Callable[[], float] | None:
    """Declare a running total of held seconds (or None to stop); returns the previous source."""
    global _source
    previous, _source = _source, source
    return previous


def excluded_s() -> float:
    return 0.0 if _source is None else float(_source())
