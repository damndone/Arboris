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

from .clustering import (
    CLUSTERING_ALGORITHMS,
    CLUSTERING_LINKAGES,
    CLUSTERING_METRICS,
    CLUSTERING_SELECTIONS,
    CLUSTERING_STANDARDIZATIONS,
    fit_clustering,
)
from .correspondence import (
    MAX_CA_CATEGORIES,
    MAX_CA_DIMENSIONS,
    MCA_MISSING_POLICIES,
    fit_correspondence,
    fit_mca,
)
from .discriminant import (
    DISCRIMINANT_EVALUATIONS,
    DISCRIMINANT_METHODS,
    DISCRIMINANT_PRIOR_POLICIES,
    fit_discriminant,
)
from .efa import EFA_EXTRACTIONS, EFA_ROTATIONS, fit_efa
from .manova import MANOVA_MAX_RETAINED_POSITIONS, MANOVA_STATISTICS, fit_manova
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
    "MANOVA_MAX_RETAINED_POSITIONS",
    "MANOVA_STATISTICS",
    "fit_manova",
    "CLUSTERING_ALGORITHMS",
    "CLUSTERING_LINKAGES",
    "CLUSTERING_METRICS",
    "CLUSTERING_SELECTIONS",
    "CLUSTERING_STANDARDIZATIONS",
    "fit_clustering",
    "MAX_CA_CATEGORIES",
    "MAX_CA_DIMENSIONS",
    "MCA_MISSING_POLICIES",
    "fit_correspondence",
    "fit_mca",
    "DISCRIMINANT_EVALUATIONS",
    "DISCRIMINANT_METHODS",
    "DISCRIMINANT_PRIOR_POLICIES",
    "fit_discriminant",
]
