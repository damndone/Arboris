"""The C++ Breslow sweep against statsmodels PHReg, bit for bit."""
import numpy as np
import pytest
from statsmodels.duration.hazard_regression import PHReg

from workbench.native_cox import FastPHReg, _native

pytestmark = pytest.mark.skipif(_native() is None, reason="native/cox_breslow/build.py has not been run")


def data(seed, n, p, rounded, delayed):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, p))
    time = rng.exponential(np.exp(-x[:, 0] * .4)) + .01
    if rounded:
        time = np.round(time, rounded) + .01
    status = (rng.random(n) < .7).astype(int)
    if not status.any():
        status[0] = 1
    entry = time * rng.uniform(0, .8, n) if delayed else None
    return time, x, status, entry


CASES = [(n, p, rounded, delayed) for n in (40, 700, 9000) for p in (1, 2, 5) for rounded in (0, 1) for delayed in (False, True)]


@pytest.mark.parametrize("n,p,rounded,delayed", CASES)
def test_every_evaluation_and_the_fit_match_bit_for_bit(n, p, rounded, delayed):
    time, x, status, entry = data(n + p, n, p, rounded, delayed)
    reference = PHReg(time, x, status=status, entry=entry, ties="breslow")
    fast = FastPHReg(time, x, status=status, entry=entry, ties="breslow")
    for params in (np.zeros(p), np.full(p, .3), np.arange(p) * .1 - .2):
        assert fast.loglike(params) == reference.loglike(params)
        assert np.array_equal(fast.score(params), reference.score(params))
        assert np.array_equal(fast.hessian(params), reference.hessian(params))
    a, b = reference.fit(), fast.fit()
    assert np.array_equal(a.params, b.params) and np.array_equal(a.bse, b.bse) and a.llf == b.llf


def test_efron_stays_on_the_reference():
    time, x, status, _ = data(3, 300, 2, 1, False)
    a, b = PHReg(time, x, status=status, ties="efron").fit(), FastPHReg(time, x, status=status, ties="efron").fit()
    assert np.array_equal(a.params, b.params)


def test_a_malformed_buffer_is_refused():
    native = _native()
    empty, off = np.empty(0, dtype=np.int32), np.zeros(2, dtype=np.int64)
    values = np.ones(2)
    with pytest.raises(ValueError):
        native.loglike(values, values, np.ones(3), 2, empty, off, empty, off, empty, off)
    with pytest.raises(ValueError):
        native.gradient(values, values, np.ones(4), 2, np.array([5], dtype=np.int32), np.array([0, 1], dtype=np.int64), empty, off, empty, off)


def test_an_extension_that_disagrees_stands_aside():
    from workbench.native_cox import _agrees_with_reference

    class Wrong:
        def __getattr__(self, name):
            return getattr(_native(), name)

        def loglike(self, *arguments):
            return _native().loglike(*arguments) + 1e-9

    assert _agrees_with_reference(_native())
    assert not _agrees_with_reference(Wrong())
