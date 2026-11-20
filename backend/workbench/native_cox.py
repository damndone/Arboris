"""Cox Breslow fits with the failure-time sweep in C++ (native/cox_breslow).

The linear predictor, its maximum and exp stay in NumPy; only the Python loop over
failure times moves, in the same order of operations, so every result equals
statsmodels PHReg bit for bit (tests/test_native_cox.py). Only an absent extension
selects the reference; a broken one fails. Strata and offsets use the reference. Those bits
depend on how this build of NumPy sums, so the extension proves itself once on tied data and
stands aside if NumPy disagrees.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import logging
from pathlib import Path
import sysconfig

import numpy as np
from statsmodels.duration.hazard_regression import PHReg

_LOG = logging.getLogger(__name__)
_EXTENSION = "_cox_breslow" + sysconfig.get_config_var("EXT_SUFFIX")


@lru_cache(maxsize=1)
def _native():
    path = Path(__file__).resolve().parents[2] / "local/native-cox-breslow" / _EXTENSION
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_cox_breslow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.ABI_VERSION != 1:
        raise RuntimeError("native Cox ABI mismatch; rebuild with native/cox_breslow/build.py")
    if not _agrees_with_reference(module):
        _LOG.warning("native Cox sweep differs from this NumPy's PHReg; using the reference")
        return None
    return module


def _agrees_with_reference(module) -> bool:
    rng = np.random.default_rng(20261101)
    size, columns = 400, 3
    exog = rng.normal(size=(size, columns))
    time = np.round(rng.exponential(1.0, size), 1) + .1
    status = (rng.random(size) < .7).astype(int)
    reference = PHReg(time, exog, status=status, ties="breslow")
    surv, params = reference.surv, np.array([.3, -.2, .1])
    data = np.ascontiguousarray(surv.exog_s[0], dtype=np.float64)
    linpred = np.dot(surv.exog_s[0], params)
    linpred -= linpred.max()
    arguments = (linpred, np.exp(linpred), data, columns,
                 *_flat(surv.ufailt_ix[0]), *_flat(surv.risk_enter[0]), *_flat(surv.risk_exit[0]))
    return (module.loglike(*arguments) == reference.breslow_loglike(params)
            and np.array_equal(np.frombuffer(module.gradient(*arguments)), reference.breslow_gradient(params))
            and np.array_equal(-np.frombuffer(module.hessian(*arguments)).reshape(columns, columns),
                               reference.breslow_hessian(params)))


def _flat(lists):
    offsets = np.zeros(len(lists) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([len(item) for item in lists], dtype=np.int64)
    rows = np.concatenate(lists).astype(np.int32) if len(lists) else np.empty(0, dtype=np.int32)
    return rows, offsets


class FastPHReg(PHReg):
    """PHReg whose Breslow likelihood, score and Hessian sweep in C++."""

    def _sweep(self, name, params):
        surv = self.surv
        native = _native()
        if native is None or surv.nstrat != 1 or surv.offset_s is not None:
            return None
        if getattr(self, "_flat_times", None) is None:
            self._flat_times = (np.ascontiguousarray(surv.exog_s[0], dtype=np.float64),
                                *_flat(surv.ufailt_ix[0]), *_flat(surv.risk_enter[0]), *_flat(surv.risk_exit[0]))
        exog, fail, fail_off, enter, enter_off, leave, leave_off = self._flat_times
        linpred = np.dot(surv.exog_s[0], params)
        linpred -= linpred.max()
        e_linpred = np.exp(linpred)
        return getattr(native, name)(linpred, e_linpred, exog, exog.shape[1], fail, fail_off, enter, enter_off, leave, leave_off)

    def breslow_loglike(self, params):
        result = self._sweep("loglike", params)
        return super().breslow_loglike(params) if result is None else result

    def breslow_gradient(self, params):
        result = self._sweep("gradient", params)
        return super().breslow_gradient(params) if result is None else np.frombuffer(result).copy()

    def breslow_hessian(self, params):
        result = self._sweep("hessian", params)
        if result is None:
            return super().breslow_hessian(params)
        size = len(params)
        return -np.frombuffer(result).reshape(size, size)
