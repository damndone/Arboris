"""The estimator side of the composition.

An estimator is described by the capabilities it declares, not by which family
it belongs to.  That is the whole point: the engine must be able to drive an
estimator it has never heard of -- including one written in the sandbox -- so it
can only ask "what can you do", never "who are you".

    refit        REQUIRED. A deterministic re-fit under arbitrary weights.
                 Unlocks the replicate-weight channel, which needs nothing else
                 because it simply re-runs the estimator per replicate.
    influence    optional. Unlocks Taylor linearization.
    consumes_design  optional. Lets the estimator see the design structure.

Adding a capability must never require editing the design layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RefitFn = Callable[[pd.DataFrame, np.ndarray], Mapping[str, float]]
InfluenceFn = Callable[[pd.DataFrame, np.ndarray], Mapping[str, np.ndarray]]

CAPABILITY_DETERMINISTIC_REFIT = "deterministic_refit"
CAPABILITY_INFLUENCE_FUNCTION = "influence_function"
CAPABILITY_CONSUMES_DESIGN = "consumes_design"


@dataclass(frozen=True)
class EstimatorSpec:
    name: str
    refit: RefitFn
    influence: InfluenceFn | None = None
    consumes_design: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("EstimatorSpec requires a name")
        if not callable(self.refit):
            raise ValueError("EstimatorSpec.refit must be callable")

    @property
    def capabilities(self) -> frozenset[str]:
        caps = {CAPABILITY_DETERMINISTIC_REFIT}
        if self.influence is not None:
            caps.add(CAPABILITY_INFLUENCE_FUNCTION)
        if self.consumes_design:
            caps.add(CAPABILITY_CONSUMES_DESIGN)
        return frozenset(caps)


#: What each variance channel requires.  Support is derived by set inclusion, so
#: a new channel is one entry here and a new estimator is one declaration -- there
#: is deliberately no family axis in this table.
VARIANCE_METHOD_REQUIREMENTS: dict[str, frozenset[str]] = {
    "replicate": frozenset({CAPABILITY_DETERMINISTIC_REFIT}),
    "linearization": frozenset({CAPABILITY_DETERMINISTIC_REFIT, CAPABILITY_INFLUENCE_FUNCTION}),
}


def missing_capabilities(spec: EstimatorSpec, method: str) -> list[str]:
    required = VARIANCE_METHOD_REQUIREMENTS.get(method)
    if required is None:
        raise KeyError(method)
    return sorted(required - spec.capabilities)
