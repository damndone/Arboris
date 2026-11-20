"""Stata-style omission of OLS terms the analysis rows cannot identify.

statsmodels fits a rank-deficient design with the pseudo-inverse and still
prints a number for every term: a constant column gets 0.00 with standard
error 0, and of x and 2x each gets a share of one effect. Neither number is an
estimate. Stata instead omits the term that adds nothing to the terms before
it and fits the rest; this module finds those terms.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: A column whose part not explained by the columns before it is below this
#: share of its length adds nothing to them.
_DEPENDENT_SHARE = 1e-9


def dependent_columns(model: Any) -> list[int] | None:
    """Design columns that are exact combinations of the columns before them.

    Read left to right like Stata: of x and 2x, 2x is the one that adds nothing.
    Empty for a full-rank design, which reads only the rank statsmodels already
    computed. None when the rank deficit cannot be pinned to particular columns.
    """
    exog = np.asarray(model.wexog, dtype=float)
    columns = exog.shape[1]
    if model.rank is None:
        model.df_model  # statsmodels computes the rank on first read
    deficit = columns - int(model.rank)
    if deficit <= 0:
        return []
    norms = np.linalg.norm(exog, axis=0)
    diagonal = np.zeros(columns)
    upper = np.abs(np.diag(np.linalg.qr(exog, mode="r")))
    diagonal[: upper.shape[0]] = upper
    added = np.divide(diagonal, norms, out=np.zeros(columns), where=norms > 0)
    dependent = [index for index in range(columns) if added[index] < _DEPENDENT_SHARE]
    if len(dependent) != deficit:
        return None
    kept = [index for index in range(columns) if index not in set(dependent)]
    if np.linalg.matrix_rank(exog[:, kept]) != len(kept):
        return None
    return dependent


def whole_terms(model: Any, dependent: list[int]) -> list[str]:
    """Formula terms every one of whose design columns adds nothing."""
    design_info = getattr(model.data, "design_info", None)
    slices = getattr(design_info, "term_name_slices", None) or {}
    dropped = set(dependent)
    return [
        term
        for term, span in slices.items()
        if term != "Intercept" and span.stop > span.start and set(range(span.start, span.stop)) <= dropped
    ]


def unidentified_columns(model: Any) -> list[int]:
    """Design columns whose coefficient the rows cannot pin down.

    A coefficient is identified when no combination of columns that sums to
    zero on the rows involves its column; of a set of category levels that
    other terms determine, every level in the set is unidentified, not only
    the one Stata would omit.
    """
    exog = np.asarray(model.wexog, dtype=float)
    if model.rank is None:
        model.df_model  # statsmodels computes the rank on first read
    deficit = exog.shape[1] - int(model.rank)
    if deficit <= 0:
        return []
    # The k x k cross-product keeps this small however many rows there are;
    # its eigenvectors with the smallest eigenvalues span those combinations.
    _, vectors = np.linalg.eigh(exog.T @ exog)
    loadings = np.linalg.norm(vectors[:, :deficit], axis=1)
    return [index for index in range(exog.shape[1]) if loadings[index] > _DEPENDENT_SHARE ** 0.5]
