"""Narrow cross-estimator event-study contract.

EventStudyBundle is the seam consumed by sup-t band inference (and, later, any
estimator that produces a dynamic event study directly — dCDH today; CS/SA could
promote their internal dynamic IF onto this seam in the future). ``event_times`` is
the SOLE primary axis; ``labels`` is a derived display-only field, never a second key.

Deliberately NOT placed in ``cs_attgt.py`` so it does not read as a Callaway-Sant'Anna
appendage — this is estimator-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class EventStudyBundle:
    estimates: np.ndarray        # (L,) aligned to event_times
    influence_func: np.ndarray   # (N, L) entity rows, mean-zero columns, N-scaled
    event_times: np.ndarray      # (L,) SOLE primary axis; <0 = placebo, >=0 = effect
    cluster_ids: np.ndarray      # (n_clusters,) descriptive
    n_switchers: np.ndarray      # (L,) per-event-time switcher count
    aux: dict = field(default_factory=dict)         # {"n_total": N, "row_cluster": (N,)}
    diagnostics: dict = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        """Derived display-only field. Never a second key — event_times is the axis."""
        return ["placebo" if e < 0 else "effect" for e in self.event_times]
