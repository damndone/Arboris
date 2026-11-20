"""Isolated, opt-in tau-b adapter around the existing C++ integer-count pilot.

This is a Python adapter, not a new native kernel or a product replacement.
Only native binary64 contiguous 1D buffers, n<=1M, no NaN, and SciPy 1.18.0
are admitted. No conversion, row list, or second observation copy is made here.
The C++ entry point snapshots 16*n row bytes while holding the GIL, releases the
input buffers, and releases the GIL during sort/Fenwick (~4*n extra bytes).
Inputs must not be concurrently written during evaluate (including any explicit
SciPy path, which uses the original caller buffers after counting). This adapter
does not provide worker isolation, run cancellation, an RSS bound, or measured
speedup. std::sort has no cancellation-latency bound; signals are checked only
after native counting. ABI/platform changes require rebuilding the extension.

Native inference is restricted to untied asymptotic tau-b with n>=3. Ties are
excluded because exact integer tie sums can differ from SciPy's intermediate
floating sums. Small/near-perfect auto cases and requested exact p-values stay
with the original public SciPy implementation. They raise CandidateNotApplicable
by default; fallback='scipy' explicitly opts into that path and records why.
Buffer/option/version errors never trigger a fallback. The public SciPy result
and warnings are preserved on the explicitly requested fallback path.

Candidate integration requires an explicit import of evaluate, handling the
engine/reason fields, and separate numerical/cancellation/resource acceptance.
No Workbench module imports this adapter. It never changes diagnostics/defaults.

The untied arithmetic order is adapted from SciPy 1.18.0:
scipy/stats/_stats_py.py::_kendalltau, _get_pvalue, _SimpleNormal.
Source: https://github.com/scipy/scipy/blob/v1.18.0/scipy/stats/_stats_py.py
BSD-3-Clause attribution and conditions are in SCIPY_LICENSE.txt alongside this
file. No private SciPy API is imported or called.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy
from scipy import special, stats

import _kendall_counts


class CandidateNotApplicable(ValueError):
    """Input is outside the independently restricted native-inference boundary."""


@dataclass(frozen=True)
class CandidateResult:
    statistic: float
    pvalue: float
    engine: str
    reason: str | None


def evaluate(x, y, *, method='auto', alternative='two-sided', fallback='raise'):
    """Return tau-b/p plus explicit execution provenance, without coercing inputs.

Use fallback='scipy' only when the caller intentionally accepts the original
public implementation for ties, small samples or exact p-values. Result fields
statistic/pvalue preserve binary64 values; this is not a drop-in SciPy result
object (it does not offer tuple unpacking, axis/keepdims or a correlation alias).
"""
    if scipy.__version__ != '1.18.0':
        raise RuntimeError('candidate arithmetic is reviewed only for SciPy 1.18.0')
    if method not in ('auto', 'asymptotic', 'exact'):
        raise ValueError("method must be 'auto', 'asymptotic', or 'exact'")
    if alternative not in ('less', 'greater', 'two-sided'):
        raise ValueError("alternative must be 'less', 'greater', or 'two-sided'")
    if fallback not in ('raise', 'scipy'):
        raise ValueError("fallback must be 'raise' or 'scipy'")

    counts = _kendall_counts.count(x, y)
    n, discordant = counts['n'], counts['discordant']
    total = n * (n - 1) // 2
    reason = None
    if n < 3:
        reason = 'sample-too-small'
    elif counts['x_tie_pairs'] or counts['y_tie_pairs']:
        reason = 'ties'
    elif method == 'exact' or (method == 'auto' and
                               (n <= 33 or min(discordant, total - discordant) <= 1)):
        reason = 'exact-method'
    if reason is not None:
        if fallback == 'raise':
            raise CandidateNotApplicable(reason + "; explicitly select fallback='scipy' if intended")
        original = stats.kendalltau(x, y, variant='b', method=method,
                                    alternative=alternative, nan_policy='raise')
        return CandidateResult(original.statistic, original.pvalue, 'scipy-public', reason)

    score = total - 2 * discordant
    # Retain SciPy's two divisions; score/total can change the last bit.
    tau = score / np.sqrt(total) / np.sqrt(total)
    tau = np.minimum(1., max(-1., tau))
    m = n * (n - 1.)
    variance = m * (2 * n + 5) / 18
    z = score / np.sqrt(variance)
    if alternative == 'less':
        pvalue = special.ndtr(z)
    elif alternative == 'greater':
        pvalue = special.ndtr(-z)
    else:
        pvalue = 2 * special.ndtr(-np.abs(z))
    return CandidateResult(tau[()], pvalue[()], 'native-counts', None)
