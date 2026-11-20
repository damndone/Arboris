"""Cox score test for coefficient interactions with centered log(event time).

The information includes the original coefficients as nuisance parameters.
Per-column and global tests use chi-square reference distributions. This is
not a normality test or a certificate that PH holds after non-rejection.
The tested surface is unweighted, unstratified, right-censored Cox with
Breslow/Efron ties; delayed entry remains explicitly unverified.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import chi2

from workbench import native_kernels


def ph_score_test(time, event, design, beta, names, *, ties, entry=None):
    if entry is not None:
        return {'status': 'unverified', 'reason': 'delayed_entry_not_validated'}
    x = np.asarray(design, dtype=float)
    x = x - x.mean(axis=0)
    time, event = np.asarray(time), np.asarray(event, dtype=bool)
    p = x.shape[1]
    center = np.mean(np.log(time[event]))
    eta = x @ beta
    weights = np.exp(eta - eta.max())
    order = np.argsort(-time, kind='stable')
    sorted_time = time[order]
    breaks = np.r_[0, np.flatnonzero(sorted_time[1:] != sorted_time[:-1]) + 1, len(time)]
    score = np.zeros(p)
    information = np.zeros((2 * p, 2 * p))
    s0, s1, s2 = 0., np.zeros(p), np.zeros((p, p))
    swept = None
    if len(breaks) == len(time) + 1:
        swept = native_kernels.ph_sweep(x, weights, np.log(time) - center, order.astype(np.int64), event)
    if swept is not None:
        score, information = swept
    for start, stop in zip(breaks[:-1], breaks[1:]) if swept is None else ():
        rows = order[start:stop]
        xr, wr = x[rows], weights[rows]
        s0 += wr.sum()
        s1 += xr.T @ wr
        s2 += xr.T @ (xr * wr[:, None])
        deaths = rows[event[rows]]
        d = len(deaths)
        if d == 0:
            continue
        g = float(np.log(time[deaths[0]]) - center)
        xd, wd = x[deaths], weights[deaths]
        e0, e1, e2 = wd.sum(), xd.T @ wd, xd.T @ (xd * wd[:, None])
        score += g * xd.sum(axis=0)
        for count in range(d):
            fraction = count / d if ties == 'efron' else 0.
            denom = s0 - fraction * e0
            mean = (s1 - fraction * e1) / denom
            variance = (s2 - fraction * e2) / denom - np.outer(mean, mean)
            score -= g * mean
            information[:p, :p] += variance
            information[:p, p:] += g * variance
            information[p:, :p] += g * variance
            information[p:, p:] += g * g * variance
    try:
        efficient = information[p:, p:] - information[p:, :p] @ np.linalg.solve(
            information[:p, :p], information[:p, p:])
        if not np.isfinite(efficient).all() or np.linalg.eigvalsh(efficient).min() <= 0:
            raise np.linalg.LinAlgError('Nonpositive efficient information')
        statistic = float(score @ np.linalg.solve(efficient, score))
    except np.linalg.LinAlgError:
        return {'status': 'unavailable', 'reason': 'singular_time_interaction_information'}
    def test(statistic, df):
        return {'statistic': float(statistic), 'df': df, 'p_value': float(chi2.sf(statistic, df))}
    return {'status': 'computed', 'method': 'cox_log_time_interaction_score_v1',
            'transform': 'log', 'ties': ties, 'n_events': int(event.sum()),
            'independent_unit': 'subject; one right-censored record per subject',
            'score': score.tolist(), 'efficient_information': efficient.tolist(),
            'global': test(statistic, p),
            **{name: test(score[j] ** 2 / efficient[j, j], 1) for j, name in enumerate(names)},
            'limitations': ['Non-rejection does not establish proportional hazards or a causal effect.']}
