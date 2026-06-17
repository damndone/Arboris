"""honest-DID (Rambachan-Roth) ΔRM sensitivity engine.

Faithful Python port of R ``HonestDiD 0.2.8``. The committed R oracles under
``tests/fixtures/honest_did/`` are the element-wise source of truth.
"""
from __future__ import annotations

import numpy as np


class HonestDiDError(ValueError):
    """HONEST_*-prefixed failure; degrades the honest_did block, never fails the run."""


def create_arm_constraints(
    *,
    num_pre: int,
    num_post: int,
    mbar: float,
    s: int,
    max_positive: bool = True,
    drop_zero: bool = True,
) -> np.ndarray:
    """ΔRM(Mbar) per-``(s, sign)`` constraint matrix ``A``.

    Faithful port of R ``HonestDiD:::.create_A_RM``. ``arm_constraints.json`` is
    the oracle. The full ΔRM set is the UNION over ``s in -(num_pre-1)..0`` and
    ``max_positive in {True, False}``; this builds ONE polyhedron of that union.

    Index conversion (R 1-based -> Python 0-based):
      * ``Atilde``: n x (n+1), n = num_pre + num_post. Row ``i`` (0..n-1) gets
        ``[-1, 1]`` at columns ``[i, i+1]``.
      * ``v_max_dif``: R writes columns ``(num_pre+s):(num_pre+1+s)`` (1-based).
        0-based those two columns are ``num_pre + s - 1`` and ``num_pre + s``.
      * ``drop_zero``: delete 1-based column ``num_pre+1`` = 0-based column
        ``num_pre`` (the normalized event-time -1 reference period).
    """
    n = num_pre + num_post

    # Atilde: first differences, row i has [-1, 1] at cols [i, i+1].
    Atilde = np.zeros((n, n + 1))
    for i in range(n):
        Atilde[i, i] = -1.0
        Atilde[i, i + 1] = 1.0

    # v_max_dif: [-1, 1] at 0-based columns (num_pre + s - 1) and (num_pre + s).
    v_max_dif = np.zeros((1, n + 1))
    c0 = num_pre + s - 1
    v_max_dif[0, c0] = -1.0
    v_max_dif[0, c0 + 1] = 1.0
    if not max_positive:
        v_max_dif = -v_max_dif

    # repmat v over pre periods, Mbar*v over post periods, stacked vertically.
    A_UB = np.vstack(
        [np.tile(v_max_dif, (num_pre, 1)), np.tile(mbar * v_max_dif, (num_post, 1))]
    )

    A = np.vstack([Atilde - A_UB, -Atilde - A_UB])

    # Drop all-zero rows (squared L2 norm <= 1e-10), preserving R's row order.
    zerorows = np.einsum("ij,ij->i", A, A) <= 1e-10
    A = A[~zerorows, :]

    if drop_zero:
        A = np.delete(A, num_pre, axis=1)

    return A
