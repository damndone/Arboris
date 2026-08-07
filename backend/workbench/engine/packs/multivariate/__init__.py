"""Standalone multivariate statistical kernels.

The package is intentionally not registered with the Workbench model or Agent
registries in this first slice.  Its public functions are pure-ish adapters
over explicit data frames and option policies, ready for a later capability
adapter without changing the numerical kernels.
"""

from workbench.contracts.model.multivariate import (
    MULTIVARIATE_CONTRACT_VERSION,
    MULTIVARIATE_OPERATION_IDS,
)

from .efa import EFA_EXTRACTIONS, EFA_ROTATIONS, fit_efa
from .pca import PCA_COMPONENT_SELECTIONS, PCA_MATRICES, fit_pca
from .reliability import cronbach_alpha

__all__ = [
    "cronbach_alpha",
    "fit_efa",
    "fit_pca",
    "MULTIVARIATE_CONTRACT_VERSION",
    "MULTIVARIATE_OPERATION_IDS",
    "PCA_COMPONENT_SELECTIONS",
    "PCA_MATRICES",
    "EFA_EXTRACTIONS",
    "EFA_ROTATIONS",
]
