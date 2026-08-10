"""Declaration-only combiner dispatch.

The shared foundation records how replicates were produced.  Statistical
combination remains a named strategy so Rubin, distributional, permutation,
and survey mathematics cannot accidentally be conflated.
"""

from __future__ import annotations

from dataclasses import dataclass

from workbench.contracts.model.replicate_combine import COMBINER_IDS

from .errors import ReplicateCombineError


@dataclass(frozen=True)
class CombinerDescriptor:
    combiner_id: str


def dispatch_combiner(combiner_id: str) -> CombinerDescriptor:
    if type(combiner_id) is not str or combiner_id not in COMBINER_IDS:
        raise ReplicateCombineError("REPLICATE_UNKNOWN_COMBINER", "combiner_id is not declared")
    return CombinerDescriptor(combiner_id=combiner_id)


__all__ = ["CombinerDescriptor", "dispatch_combiner"]
