"""Execution-owned cooperative checks for exact AR arithmetic.

This leaf owns no operation, permission, thread or native-library lifecycle.
Context variables propagate through the existing asyncio.to_thread boundary.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_CHECK = ContextVar('exact_ar_cancel_check', default=None)


def current_check():
    return _CHECK.get()


def check_cancellation():
    check = _CHECK.get()
    if check is not None:
        check()


@contextmanager
def cancellation_scope(check_cancel):
    if not callable(check_cancel):
        raise TypeError('AR cancellation check must be callable')
    previous = _CHECK.get()
    if previous is None:
        check = check_cancel
    else:
        def check():
            previous()
            check_cancel()
    token = _CHECK.set(check)
    try:
        yield
    finally:
        _CHECK.reset(token)
