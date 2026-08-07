"""Replicate weight construction — the general variance channel.

This is what makes the engine work for estimators Taylor linearization cannot
touch: it never needs an influence function, because it simply re-runs the whole
estimator under each set of weights.  Quantile regression, panel fixed effects,
DID and anything an agent writes in the sandbox all reach a design-based variance
through here.

It is also not optional in practice.  NHANES, CPS and similar surveys publish
replicate weights and name them as the recommended variance method, so a system
without this channel cannot follow the publisher's own instructions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.linalg import hadamard

from .design import SurveyDesign
from .errors import SurveyEngineError


def build_replicates(
    design: SurveyDesign, replicate_type: str | None
) -> tuple[np.ndarray, list[float]]:
    """Return (n_obs x n_replicates) weights and the per-replicate scale factors."""
    kind = replicate_type or design.replicate_type
    if kind is None:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_TYPE_REQUIRED",
            "the replicate channel needs a replicate_type",
        )
    if kind == "provided":
        return _provided(design)
    if kind == "jackknife":
        return _jackknife(design)
    if kind == "brr":
        return _brr(design)
    if kind == "bootstrap":
        return _bootstrap(design)
    raise SurveyEngineError("SURVEY_REPLICATE_TYPE_INVALID", kind)


def _psu_index(design: SurveyDesign) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    strata = design._stratum_key.to_numpy()
    psu = design._psu_key.to_numpy()
    groups: dict[str, list[int]] = {}
    for stratum in pd.unique(strata):
        groups[str(stratum)] = list(pd.unique(psu[strata == stratum]))
    return strata, psu, groups


def _provided(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    columns = design.replicate_weight_columns
    missing = [c for c in columns if c not in design.frame.columns]
    if missing:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_MISSING", f"missing columns: {', '.join(missing)}"
        )
    weights = design.frame[columns].to_numpy(dtype=float)
    # Published replicate weights are combined weights (the sampling weight is
    # already folded in), which is the NHANES/CPS convention.
    scales = [1.0 / weights.shape[1]] * weights.shape[1]
    return weights, scales


def _jackknife(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    """Stratified delete-one-PSU jackknife (R's JKn).

    Dropping PSU i in stratum h reweights the remaining PSUs of that stratum by
    n_h/(n_h-1); the replicate carries scale (n_h-1)/n_h.
    """
    strata, psu, groups = _psu_index(design)
    base = design.weights
    columns: list[np.ndarray] = []
    scales: list[float] = []

    for stratum, psu_ids in groups.items():
        n_h = len(psu_ids)
        if n_h < 2:
            raise SurveyEngineError(
                "SURVEY_LONELY_PSU",
                f"stratum {stratum!r} has a single PSU; the jackknife needs at least two",
                strata=[stratum],
            )
        in_stratum = strata == stratum
        for dropped in psu_ids:
            w = base.copy()
            w[in_stratum] *= n_h / (n_h - 1)
            w[psu == dropped] = 0.0
            columns.append(w)
            scales.append((n_h - 1) / n_h)

    return np.column_stack(columns), scales


def _brr(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    """Balanced repeated replication over a Hadamard design.

    Requires exactly two PSUs per stratum -- that is the definition, not a
    limitation we chose, and a design that does not satisfy it must be told so
    rather than quietly handed a different method.
    """
    strata, psu, groups = _psu_index(design)
    bad = {h: len(ids) for h, ids in groups.items() if len(ids) != 2}
    if bad:
        raise SurveyEngineError(
            "SURVEY_BRR_REQUIRES_TWO_PSU_PER_STRATUM",
            f"strata with other than two PSUs: {sorted(bad)}",
            strata=sorted(bad),
        )

    stratum_names = sorted(groups)
    n_strata = len(stratum_names)

    # BRR is NOT uniquely defined: the estimate depends on which balanced set of
    # half-samples is used.  Measured on the committed fixture, R returns
    # 1.62518598 from its 12-replicate matrix and 1.70845732 from a 20-replicate
    # one, and a 16-replicate Sylvester matrix gives a third value -- all valid.
    # So the balanced set is part of the specification, not an implementation
    # detail, and a BRR standard error reported without naming its set is
    # under-specified.  Callers may supply one; otherwise a Sylvester matrix is
    # built and recorded on the result.
    if design.hadamard_matrix is not None:
        matrix = np.asarray(design.hadamard_matrix, dtype=int)
        if matrix.shape[0] < n_strata + 1 or matrix.shape[1] < n_strata + 1:
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_TOO_SMALL",
                f"a {matrix.shape} matrix cannot balance {n_strata} strata",
            )
        order = matrix.shape[0]
        # R emits 0/1; convert to the +/-1 half-sample selector, dropping the
        # leading all-ones column.
        selector = np.where(matrix[:, 1 : n_strata + 1] > 0, 1, -1)
    else:
        order = 1
        while order < n_strata + 1:
            order *= 2
        selector = hadamard(order)[:, 1 : n_strata + 1]

    base = design.weights
    columns: list[np.ndarray] = []
    for row in selector:
        w = base.copy()
        for sign, stratum in zip(row, stratum_names, strict=True):
            first, second = groups[stratum]
            keep, drop = (first, second) if sign > 0 else (second, first)
            w[psu == keep] *= 2.0
            w[psu == drop] = 0.0
        columns.append(w)

    scales = [1.0 / order] * order
    return np.column_stack(columns), scales


def _bootstrap(design: SurveyDesign, replicates: int = 500, seed: int = 20260805) -> tuple[np.ndarray, list[float]]:
    """Rao-Wu rescaling bootstrap: resample PSUs within strata with replacement."""
    strata, psu, groups = _psu_index(design)
    rng = np.random.default_rng(seed)
    base = design.weights
    columns: list[np.ndarray] = []

    for _ in range(replicates):
        w = np.zeros_like(base)
        for stratum, psu_ids in groups.items():
            n_h = len(psu_ids)
            drawn = rng.choice(n_h, size=n_h - 1, replace=True)
            counts = np.bincount(drawn, minlength=n_h)
            factor = 1.0 + np.sqrt(n_h / (n_h - 1)) * (counts * n_h / (n_h - 1) - 1.0)
            for pid, f in zip(psu_ids, factor, strict=True):
                rows = psu == pid
                w[rows] = base[rows] * f
        columns.append(w)

    scales = [1.0 / replicates] * replicates
    return np.column_stack(columns), scales
